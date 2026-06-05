from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

from sqlmodel import Session

from worker.core.config import new_id
from worker.core.log_stream import log_streams
from worker.models.db import ExecutionResult, ExecutionRun, Project
from worker.models.schemas import ExecutionRequest
from worker.core.runtime import resolve_runtime
from worker.services.artifact_indexing import index_execution_failure_artifacts
from worker.services.generated_runtime import ensure_generated_runtime

RUNNER_ENTRYPOINT = (
    "import sys; "
    "sys.path.insert(0, sys.argv.pop(1)); "
    "from runner.cli import main; "
    "raise SystemExit(main())"
)


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

    await log_streams.publish(job_id, f"[runner] {' '.join(cmd)}")

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(generated_path),
        env=profile.subprocess_env({"TC_HEADLESS": "false" if request.headed else "true"}),
    )
    stdout, stderr = await process.communicate()
    stdout_text = stdout.decode("utf-8", errors="replace")
    stderr_text = stderr.decode("utf-8", errors="replace")
    _write_runner_logs(generated_path, run_id, stdout_text, stderr_text)
    if stdout_text:
        await log_streams.publish(job_id, stdout_text)
    if stderr_text:
        await log_streams.publish(job_id, stderr_text)

    result_path = generated_path / "artifacts" / "runs" / run_id / "results.json"
    exec_run.status = _execution_status(process.returncode, result_path)
    exec_run.ended_at = datetime.utcnow()
    exec_run.result_path = str(result_path) if result_path.exists() else None
    session.add(exec_run)

    if result_path.exists():
        _persist_results(session, exec_run, result_path)

    session.commit()
    session.refresh(exec_run)
    index_execution_failure_artifacts(session, exec_run)
    return exec_run


async def rerun_failed(session: Session, project: Project, execution_id: str, job_id: str) -> ExecutionRun:
    prev = session.get(ExecutionRun, execution_id)
    if not prev:
        raise ValueError("Execution not found")
    generated_path = Path(project.generated_project_path or (Path(project.root_path) / "generated"))
    run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    bootstrap = ensure_generated_runtime(
        generated_path,
        install=True,
        session=session,
        project_id=project.id,
        browser=prev.browser,
    )
    if not bootstrap.get("ok"):
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
        await _finish_bootstrap_failure(session, exec_run, generated_path, run_id, job_id, bootstrap)
        return exec_run

    profile = resolve_runtime()
    cmd = [
        profile.python, "-c", RUNNER_ENTRYPOINT, str(generated_path),
        "rerun-failed", "--from-run-id", prev.run_id, "--run-id", run_id,
    ]
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

    await log_streams.publish(job_id, f"[runner] {' '.join(cmd)}")

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(generated_path),
        env=profile.subprocess_env(),
    )
    stdout, stderr = await process.communicate()
    stdout_text = stdout.decode("utf-8", errors="replace")
    stderr_text = stderr.decode("utf-8", errors="replace")
    _write_runner_logs(generated_path, run_id, stdout_text, stderr_text)
    if stdout_text:
        await log_streams.publish(job_id, stdout_text)
    if stderr_text:
        await log_streams.publish(job_id, stderr_text)

    result_path = generated_path / "artifacts" / "runs" / run_id / "results.json"
    exec_run.status = _execution_status(process.returncode, result_path)
    exec_run.ended_at = datetime.utcnow()
    exec_run.result_path = str(result_path) if result_path.exists() else None
    session.add(exec_run)
    if result_path.exists():
        _persist_results(session, exec_run, result_path)
    session.commit()
    session.refresh(exec_run)
    index_execution_failure_artifacts(session, exec_run)
    return exec_run


async def _finish_bootstrap_failure(
    session: Session,
    exec_run: ExecutionRun,
    generated_path: Path,
    run_id: str,
    job_id: str,
    bootstrap: dict,
    automation_key: str | None = None,
) -> None:
    message = bootstrap.get("message") or "generated runtime bootstrap failed"
    stdout_text = _bootstrap_log(bootstrap)
    stderr_text = f"[bootstrap] {message}\n"
    _write_runner_logs(generated_path, run_id, stdout_text, stderr_text)
    result_path = _write_bootstrap_results(generated_path, run_id, exec_run, message, bootstrap, automation_key)

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
    result_path.write_text(json.dumps({
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
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return result_path


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
            error=case.get("error"),
            screenshot_path=(case.get("artifacts") or {}).get("screenshot"),
            trace_path=(case.get("artifacts") or {}).get("trace"),
        ))
