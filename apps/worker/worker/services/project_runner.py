from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import RLock

from sqlmodel import Session, select

from worker.core.config import mask_secret_data, mask_secrets, new_id
from worker.core.log_stream import log_streams
from worker.models.db import ExecutionResult, ExecutionRun, Project
from worker.models.schemas import ExecutionRequest
from worker.core.runtime import resolve_runtime
from worker.core.subprocess_compat import create_subprocess_exec
from worker.services.artifact_indexing import index_execution_failure_artifacts
from worker.services.generated_runtime import ensure_generated_runtime

RUNNER_ENTRYPOINT = (
    "import sys; "
    "sys.path.insert(0, sys.argv.pop(1)); "
    "from runner.cli import main; "
    "raise SystemExit(main())"
)
PROCESS_STOP_TIMEOUT_SECONDS = 10


@dataclass
class ActiveExecutionRun:
    execution_id: str
    job_id: str
    process: object
    generated_path: Path
    run_id: str
    stdout_path: Path
    stderr_path: Path
    result_path: Path
    cancel_requested: bool = False


_active_executions: dict[str, ActiveExecutionRun] = {}
_active_job_executions: dict[str, set[str]] = {}
_active_executions_lock = RLock()


def _register_active_execution(active_execution: ActiveExecutionRun) -> None:
    with _active_executions_lock:
        _active_executions[active_execution.execution_id] = active_execution
        _active_job_executions.setdefault(active_execution.job_id, set()).add(active_execution.execution_id)


def _mark_active_execution_cancel_requested(execution_id: str) -> ActiveExecutionRun | None:
    with _active_executions_lock:
        active_execution = _active_executions.get(execution_id)
        if active_execution is None:
            return None
        active_execution.cancel_requested = True
        return active_execution


def _active_execution_cancel_requested(execution_id: str | None) -> bool:
    if not execution_id:
        return False
    with _active_executions_lock:
        active_execution = _active_executions.get(execution_id)
        return bool(active_execution and active_execution.cancel_requested)


def _unregister_active_execution(execution_id: str | None) -> None:
    if not execution_id:
        return
    with _active_executions_lock:
        active_execution = _active_executions.pop(execution_id, None)
        if active_execution is None:
            return
        job_executions = _active_job_executions.get(active_execution.job_id)
        if job_executions is not None:
            job_executions.discard(execution_id)
            if not job_executions:
                _active_job_executions.pop(active_execution.job_id, None)


def _append_log(path: Path, text: str) -> None:
    if not text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


async def _terminate_process(process: object, timeout: float | None = None) -> str:
    timeout = PROCESS_STOP_TIMEOUT_SECONDS if timeout is None else timeout
    if getattr(process, "returncode", None) is not None:
        return "already_exited"

    graceful_sent = False
    terminate = getattr(process, "terminate", None)
    if callable(terminate):
        try:
            terminate()
            graceful_sent = True
        except ProcessLookupError:
            return "already_exited"
    else:
        kill = getattr(process, "kill", None)
        if callable(kill):
            try:
                kill()
            except ProcessLookupError:
                return "already_exited"

    wait = getattr(process, "wait", None)
    if not callable(wait):
        return "terminated" if graceful_sent else "killed"

    try:
        await asyncio.wait_for(wait(), timeout=timeout)
    except asyncio.TimeoutError:
        if getattr(process, "returncode", None) is None:
            kill = getattr(process, "kill", None)
            if callable(kill):
                try:
                    kill()
                except ProcessLookupError:
                    return "already_exited"
        try:
            await asyncio.wait_for(wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return "kill_timeout"
        return "killed"

    return "terminated" if graceful_sent else "killed"


async def _append_cancellation_diagnostic(active_execution: ActiveExecutionRun, message: str) -> None:
    diagnostic = mask_secrets(message)
    line = diagnostic + "\n"
    _append_log(active_execution.stdout_path, line)
    _append_log(active_execution.stderr_path, line)
    await log_streams.publish(active_execution.job_id, diagnostic)


async def cancel_execution_run(execution_id: str, job_id: str | None = None) -> bool:
    active_execution = _mark_active_execution_cancel_requested(execution_id)
    if active_execution is None:
        if job_id:
            await log_streams.publish(job_id, f"[runner] Cancellation requested for inactive execution {execution_id}")
        return False

    if job_id:
        active_execution.job_id = job_id
    await _append_cancellation_diagnostic(
        active_execution,
        f"[cancelled] Execution cancellation requested for run {execution_id}",
    )
    stop_result = await _terminate_process(active_execution.process)
    await _append_cancellation_diagnostic(
        active_execution,
        f"[cancelled] runner.cli process stop result for run {execution_id}: {stop_result}; log stream marked cancelled",
    )
    return True


async def run_project(session: Session, project: Project, request: ExecutionRequest, job_id: str) -> ExecutionRun:
    generated_path = Path(project.generated_project_path or (Path(project.root_path) / "generated"))
    run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    exec_run = ExecutionRun(
        id=new_id("exec"),
        project_id=project.id,
        run_id=run_id,
        env=request.env,
        browser=request.browser,
        headed=request.headed,
        status="running",
        started_at=datetime.utcnow(),
    )
    session.add(exec_run)
    session.commit()
    session.refresh(exec_run)

    bootstrap = ensure_generated_runtime(
        generated_path,
        install=True,
        session=session,
        project_id=project.id,
        browser=request.browser,
    )
    if _refresh_cancelled_state(session, exec_run):
        await _finish_cancelled_execution(session, exec_run, generated_path, run_id, job_id)
        return exec_run
    if not bootstrap.get("ok"):
        await _finish_bootstrap_failure(session, exec_run, generated_path, run_id, job_id, bootstrap, request.automation_key)
        return exec_run

    profile = resolve_runtime()

    cmd = [
        profile.python, "-c", RUNNER_ENTRYPOINT, str(generated_path), "run",
        "--env", request.env,
        "--browser", request.browser,
        "--run-id", run_id,
    ]
    if request.headed:
        cmd.append("--headed")
    if request.target_type == "case" and request.automation_key:
        cmd.extend(["--case-key", request.automation_key])
    elif request.target_type == "selected" and request.case_ids:
        for key in request.case_ids:
            cmd.extend(["--case-key", key])
    else:
        cmd.append("--all")

    runner_env = profile.subprocess_env({"TC_HEADLESS": "false" if request.headed else "true"})
    return await _run_runner_command(session, exec_run, generated_path, run_id, job_id, cmd, runner_env)


async def rerun_failed(session: Session, project: Project, execution_id: str, job_id: str) -> ExecutionRun:
    prev = session.get(ExecutionRun, execution_id)
    if not prev:
        raise ValueError("Execution not found")
    generated_path = Path(project.generated_project_path or (Path(project.root_path) / "generated"))
    run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    exec_run = ExecutionRun(
        id=new_id("exec"),
        project_id=project.id,
        run_id=run_id,
        env=prev.env,
        browser=prev.browser,
        headed=prev.headed,
        status="running",
        started_at=datetime.utcnow(),
    )
    session.add(exec_run)
    session.commit()
    session.refresh(exec_run)

    bootstrap = ensure_generated_runtime(
        generated_path,
        install=True,
        session=session,
        project_id=project.id,
        browser=prev.browser,
    )
    if _refresh_cancelled_state(session, exec_run):
        await _finish_cancelled_execution(session, exec_run, generated_path, run_id, job_id)
        return exec_run
    if not bootstrap.get("ok"):
        await _finish_bootstrap_failure(session, exec_run, generated_path, run_id, job_id, bootstrap)
        return exec_run

    profile = resolve_runtime()
    cmd = [
        profile.python, "-c", RUNNER_ENTRYPOINT, str(generated_path),
        "rerun-failed", "--from-run-id", prev.run_id, "--run-id", run_id,
    ]
    runner_env = profile.subprocess_env()
    return await _run_runner_command(session, exec_run, generated_path, run_id, job_id, cmd, runner_env)


async def _run_runner_command(
    session: Session,
    exec_run: ExecutionRun,
    generated_path: Path,
    run_id: str,
    job_id: str,
    cmd: list[str],
    runner_env: dict[str, str],
) -> ExecutionRun:
    await log_streams.publish(job_id, f"[runner] {' '.join(cmd)}")

    process = await create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(generated_path),
        env=runner_env,
    )
    result_path = generated_path / "artifacts" / "runs" / run_id / "results.json"
    artifact_dir = result_path.parent
    active_execution = ActiveExecutionRun(
        execution_id=exec_run.id or "",
        job_id=job_id,
        process=process,
        generated_path=generated_path,
        run_id=run_id,
        stdout_path=artifact_dir / "stdout.log",
        stderr_path=artifact_dir / "stderr.log",
        result_path=result_path,
    )
    _register_active_execution(active_execution)
    try:
        if _refresh_cancelled_state(session, exec_run):
            _mark_active_execution_cancel_requested(exec_run.id or "")
            await cancel_execution_run(exec_run.id or "", job_id)

        stdout, stderr = await process.communicate()
        stdout_text = mask_secrets(stdout.decode("utf-8", errors="replace"), runner_env)
        stderr_text = mask_secrets(stderr.decode("utf-8", errors="replace"), runner_env)
        if stdout_text:
            await log_streams.publish(job_id, stdout_text)
        if stderr_text:
            await log_streams.publish(job_id, stderr_text)

        if _refresh_cancelled_state(session, exec_run):
            await _finish_cancelled_execution(
                session,
                exec_run,
                generated_path,
                run_id,
                job_id,
                stdout_text=stdout_text,
                stderr_text=stderr_text,
                return_code=getattr(process, "returncode", None),
            )
            return exec_run

        _write_runner_logs(generated_path, run_id, stdout_text, stderr_text)
        exec_run.status = _execution_status(getattr(process, "returncode", None), result_path)
        exec_run.ended_at = datetime.utcnow()
        exec_run.result_path = str(result_path) if result_path.exists() else None
        session.add(exec_run)
        if result_path.exists():
            _persist_results(session, exec_run, result_path)
        session.commit()
        session.refresh(exec_run)
        index_execution_failure_artifacts(session, exec_run)
        return exec_run
    finally:
        _unregister_active_execution(exec_run.id)


def _refresh_cancelled_state(session: Session, exec_run: ExecutionRun) -> bool:
    try:
        session.refresh(exec_run)
    except Exception:
        pass
    return exec_run.status == "cancelled" or _active_execution_cancel_requested(exec_run.id)


async def _finish_cancelled_execution(
    session: Session,
    exec_run: ExecutionRun,
    generated_path: Path,
    run_id: str,
    job_id: str,
    *,
    stdout_text: str = "",
    stderr_text: str = "",
    return_code: int | None = None,
) -> None:
    message = "[cancelled] Execution run cancelled; harvesting available artifacts."
    stdout_text = _append_line(stdout_text, message)
    stderr_text = _append_line(stderr_text, message)
    _write_runner_logs(generated_path, run_id, stdout_text, stderr_text)
    result_path = _write_cancelled_results(generated_path, run_id, exec_run, return_code)

    existing_results = session.exec(
        select(ExecutionResult).where(ExecutionResult.execution_run_id == exec_run.id)
    ).all()
    for result in existing_results:
        session.delete(result)

    exec_run.status = "cancelled"
    exec_run.ended_at = datetime.utcnow()
    exec_run.result_path = str(result_path)
    session.add(exec_run)
    session.commit()
    session.refresh(exec_run)
    await log_streams.publish(job_id, message)
    index_execution_failure_artifacts(session, exec_run)


async def _finish_bootstrap_failure(
    session: Session,
    exec_run: ExecutionRun,
    generated_path: Path,
    run_id: str,
    job_id: str,
    bootstrap: dict,
    automation_key: str | None = None,
) -> None:
    safe_bootstrap = mask_secret_data(bootstrap)
    message = mask_secrets(safe_bootstrap.get("message") or "generated runtime bootstrap failed")
    stdout_text = _bootstrap_log(safe_bootstrap)
    stderr_text = f"[bootstrap] {message}\n"
    _write_runner_logs(generated_path, run_id, stdout_text, stderr_text)
    result_path = _write_bootstrap_results(generated_path, run_id, exec_run, message, safe_bootstrap, automation_key)

    await log_streams.publish(job_id, stderr_text)
    if stdout_text:
        await log_streams.publish(job_id, stdout_text)

    exec_run.status = "failed"
    exec_run.ended_at = datetime.utcnow()
    exec_run.result_path = str(result_path)
    session.add(exec_run)
    _persist_results(session, exec_run, result_path)
    session.commit()
    session.refresh(exec_run)
    index_execution_failure_artifacts(session, exec_run)


def _bootstrap_log(bootstrap: dict) -> str:
    lines = ["[bootstrap] generated runtime check failed before runner.cli execution"]
    message = bootstrap.get("message")
    if message:
        lines.append(f"message: {message}")
    checks = bootstrap.get("checks")
    if checks:
        lines.append(f"checks: {json.dumps(checks, ensure_ascii=False, sort_keys=True)}")
    for key in ["pip", "pipError", "playwright", "playwrightError"]:
        value = bootstrap.get(key)
        if value:
            lines.append(f"[{key}]")
            lines.append(str(value).strip())
    browser = bootstrap.get("playwrightBrowser")
    if browser:
        lines.append(f"playwrightBrowser: {json.dumps(browser, ensure_ascii=False, sort_keys=True)}")
    return "\n".join(lines).rstrip() + "\n"


def _write_bootstrap_results(
    generated_path: Path,
    run_id: str,
    exec_run: ExecutionRun,
    message: str,
    bootstrap: dict,
    automation_key: str | None,
) -> Path:
    artifact_dir = generated_path / "artifacts" / "runs" / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    cases = []
    if automation_key:
        cases.append({
            "automationKey": automation_key,
            "sourceType": None,
            "sourceCaseId": None,
            "title": automation_key,
            "status": "failed",
            "durationMs": 0,
            "error": message,
            "artifacts": {
                "screenshot": None,
                "trace": None,
                "video": None,
            },
        })
    result_path = artifact_dir / "results.json"
    payload = {
        "runId": run_id,
        "projectName": generated_path.name,
        "env": exec_run.env,
        "browser": exec_run.browser,
        "startedAt": exec_run.started_at.isoformat() if exec_run.started_at else None,
        "endedAt": datetime.utcnow().isoformat(),
        "summary": {
            "total": len(cases),
            "passed": 0,
            "failed": len(cases),
            "skipped": 0,
        },
        "bootstrap": bootstrap,
        "cases": cases,
    }
    result_path.write_text(json.dumps(mask_secret_data(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    return result_path


def _write_cancelled_results(
    generated_path: Path,
    run_id: str,
    exec_run: ExecutionRun,
    return_code: int | None,
) -> Path:
    artifact_dir = generated_path / "artifacts" / "runs" / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    result_path = artifact_dir / "results.json"
    payload = {
        "runId": run_id,
        "projectName": generated_path.name,
        "env": exec_run.env,
        "browser": exec_run.browser,
        "startedAt": exec_run.started_at.isoformat() if exec_run.started_at else None,
        "endedAt": datetime.utcnow().isoformat(),
        "status": "cancelled",
        "summary": {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
        },
        "cancellation": {
            "reason": "user_cancelled",
            "returnCode": return_code,
        },
        "cases": [],
    }
    result_path.write_text(json.dumps(mask_secret_data(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    return result_path


def _append_line(text: str, line: str) -> str:
    if not text:
        return line + "\n"
    return text + ("" if text.endswith("\n") else "\n") + line + "\n"


def _write_runner_logs(generated_path: Path, run_id: str, stdout_text: str, stderr_text: str) -> None:
    artifact_dir = generated_path / "artifacts" / "runs" / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    for name, fallback_name, text in [
        ("stdout.log", "worker_stdout.log", stdout_text),
        ("stderr.log", "worker_stderr.log", stderr_text),
    ]:
        primary = artifact_dir / name
        target = artifact_dir / fallback_name if primary.exists() else primary
        target.write_text(text, encoding="utf-8")


def _execution_status(returncode: int | None, result_path: Path) -> str:
    if returncode != 0 or not result_path.exists():
        return "failed"
    try:
        data = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "failed"
    return "failed" if (data.get("summary") or {}).get("failed", 0) else "completed"


def _persist_results(session: Session, exec_run: ExecutionRun, result_path: Path) -> None:
    data = json.loads(result_path.read_text(encoding="utf-8"))
    for case in data.get("cases", []):
        session.add(ExecutionResult(
            id=new_id("er"),
            execution_run_id=exec_run.id,
            automation_key=case.get("automationKey", ""),
            source_type=case.get("sourceType"),
            source_case_id=case.get("sourceCaseId"),
            title=case.get("title"),
            status=case.get("status", "unknown"),
            duration_ms=case.get("durationMs"),
            error=mask_secrets(case.get("error")) if case.get("error") else None,
            screenshot_path=(case.get("artifacts") or {}).get("screenshot"),
            trace_path=(case.get("artifacts") or {}).get("trace"),
        ))
