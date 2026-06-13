from __future__ import annotations

import asyncio
import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from worker.core.config import mask_secrets, new_id
from worker.core.runtime import resolve_runtime
from worker.core.subprocess_compat import create_subprocess_exec
from worker.core.log_stream import log_streams
from worker.services.prompt_payloads import build_webwright_prompt_payload_components, record_webwright_prompt_payload
from worker.models.db import Project, TestCase, WebwrightRun, WebwrightRunStatus
from worker.services.artifact_indexing import index_webwright_run_artifacts
from sqlmodel import Session


ERROR_PATTERNS = {
    "api_access_forbidden": r"403|forbidden",
    "api_key_invalid": r"401|unauthorized",
    "api_key_missing": r"api.?key|authentication",
    "bash_missing": r"/bin/bash|winerror 2",
    "browser_missing": r"browser.*not.*install|executable.*doesn't exist",
    "timeout": r"timeout|timed out",
    "url_unreachable": r"net::ERR|ECONNREFUSED|404",
    "script_generation_failed": r"final_script|generation failed",
}

MOCK_START_URL = "data:text/html,%3Ca%20href%3D%22%23done%22%3EMore%20information%3C%2Fa%3E"
HEARTBEAT_INTERVAL_SECONDS = 15
PIPE_DRAIN_TIMEOUT_SECONDS = 2
PROCESS_STOP_TIMEOUT_SECONDS = 10
CANCELLED_CASE_STATUS = "cancelled"


@dataclass
class ActiveWebwrightRun:
    run_id: str
    job_id: str
    process: Any
    stdout_path: Path
    stderr_path: Path
    stream_tasks: list[asyncio.Task[Any]]
    heartbeat_task: asyncio.Task[Any] | None = None
    cancel_requested: bool = False


_active_runs: dict[str, ActiveWebwrightRun] = {}
_active_job_runs: dict[str, set[str]] = {}
_active_runs_lock = RLock()


def classify_error(stderr: str) -> str:
    text = stderr.lower()
    for name, pattern in ERROR_PATTERNS.items():
        if re.search(pattern, text, re.IGNORECASE):
            return name
    return "unknown"


def _resolve_output_root() -> Path:
    profile = resolve_runtime()
    root = profile.webwright_output_root or str(Path.home() / "webwright-runs")
    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _find_webwright_artifact(output_root: Path, file_name: str) -> Path | None:
    direct = output_root / file_name
    if direct.exists():
        return direct

    top_level_nested = [path for path in output_root.glob(f"*/{file_name}") if path.is_file()]
    if top_level_nested:
        return max(top_level_nested, key=lambda path: path.stat().st_mtime)

    nested = [path for path in output_root.rglob(file_name) if path.is_file()]
    if nested:
        return max(nested, key=lambda path: path.stat().st_mtime)
    return None


def _relative_artifact(output_root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.resolve().relative_to(output_root.resolve()))
    except ValueError:
        return str(path)


def _append_log(path: Path, text: str) -> None:
    if not text:
        return
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def _register_active_run(active_run: ActiveWebwrightRun) -> None:
    with _active_runs_lock:
        _active_runs[active_run.run_id] = active_run
        _active_job_runs.setdefault(active_run.job_id, set()).add(active_run.run_id)


def _update_active_run_tasks(
    run_id: str,
    stream_tasks: list[asyncio.Task[Any]],
    heartbeat_task: asyncio.Task[Any] | None,
) -> None:
    with _active_runs_lock:
        active_run = _active_runs.get(run_id)
        if active_run is None:
            return
        active_run.stream_tasks = stream_tasks
        active_run.heartbeat_task = heartbeat_task


def _mark_active_run_cancel_requested(run_id: str) -> ActiveWebwrightRun | None:
    with _active_runs_lock:
        active_run = _active_runs.get(run_id)
        if active_run is None:
            return None
        active_run.cancel_requested = True
        return active_run


def _active_run_cancel_requested(run_id: str | None) -> bool:
    if not run_id:
        return False
    with _active_runs_lock:
        active_run = _active_runs.get(run_id)
        return bool(active_run and active_run.cancel_requested)


def _unregister_active_run(run_id: str | None) -> None:
    if not run_id:
        return
    with _active_runs_lock:
        active_run = _active_runs.pop(run_id, None)
        if active_run is None:
            return
        job_runs = _active_job_runs.get(active_run.job_id)
        if job_runs is not None:
            job_runs.discard(run_id)
            if not job_runs:
                _active_job_runs.pop(active_run.job_id, None)


async def _stream_pipe(
    stream: asyncio.StreamReader,
    job_id: str,
    log_path: Path,
    chunks: list[str],
) -> None:
    with log_path.open("a", encoding="utf-8") as handle:
        while True:
            line = await stream.readline()
            if not line:
                return
            text = mask_secrets(line.decode("utf-8", errors="replace"))
            chunks.append(text)
            handle.write(text)
            handle.flush()
            message = text.rstrip("\r\n")
            if message:
                await log_streams.publish(job_id, message)


async def _publish_heartbeat(
    process: Any,
    job_id: str,
    automation_key: str,
) -> None:
    elapsed = 0
    while process.returncode is None:
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
        elapsed += HEARTBEAT_INTERVAL_SECONDS
        if process.returncode is None:
            await log_streams.publish(job_id, f"[webwright] {automation_key} still running ({elapsed}s elapsed)")


async def _terminate_process(process: Any, timeout: float | None = None) -> str:
    timeout = PROCESS_STOP_TIMEOUT_SECONDS if timeout is None else timeout
    if process.returncode is not None:
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
        try:
            process.kill()
        except ProcessLookupError:
            return "already_exited"

    try:
        await asyncio.wait_for(process.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                return "already_exited"
        try:
            await asyncio.wait_for(process.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return "kill_timeout"
        return "killed"

    return "terminated" if graceful_sent else "killed"


async def _stop_process(process: Any) -> None:
    await _terminate_process(process)


async def _finish_background_tasks(tasks: list[asyncio.Task[Any]], timeout: float) -> bool:
    if not tasks:
        return True
    _, pending = await asyncio.wait(tasks, timeout=timeout)
    for task in pending:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    return not pending


async def _append_cancellation_diagnostic(
    *,
    job_id: str,
    stdout_path: Path,
    stderr_path: Path,
    message: str,
) -> None:
    diagnostic = mask_secrets(message)
    line = diagnostic + "\n"
    _append_log(stdout_path, line)
    _append_log(stderr_path, line)
    await log_streams.publish(job_id, diagnostic)


async def cancel_webwright_run(run_id: str, job_id: str | None = None) -> bool:
    active_run = _mark_active_run_cancel_requested(run_id)
    if active_run is None:
        if job_id:
            await log_streams.publish(job_id, f"[webwright] Cancellation requested for inactive run {run_id}")
        return False

    stream_job_id = job_id or active_run.job_id
    await _append_cancellation_diagnostic(
        job_id=stream_job_id,
        stdout_path=active_run.stdout_path,
        stderr_path=active_run.stderr_path,
        message=f"[cancelled] Webwright cancellation requested for run {run_id}",
    )
    stop_result = await _terminate_process(active_run.process)

    if active_run.heartbeat_task is not None:
        active_run.heartbeat_task.cancel()
    await _finish_background_tasks(
        [
            *active_run.stream_tasks,
            *([active_run.heartbeat_task] if active_run.heartbeat_task is not None else []),
        ],
        PIPE_DRAIN_TIMEOUT_SECONDS,
    )
    await _append_cancellation_diagnostic(
        job_id=stream_job_id,
        stdout_path=active_run.stdout_path,
        stderr_path=active_run.stderr_path,
        message=f"[cancelled] Webwright process stop result for run {run_id}: {stop_result}; log stream marked cancelled",
    )
    return True


def _refresh_cancelled_state(session: Session, run: WebwrightRun, case: TestCase) -> bool:
    try:
        session.refresh(run)
    except Exception:
        pass
    try:
        session.refresh(case)
    except Exception:
        pass
    return (
        run.status == WebwrightRunStatus.cancelled.value
        or case.status == CANCELLED_CASE_STATUS
        or _active_run_cancel_requested(run.id)
    )


def _mark_run_cancelled(run: WebwrightRun, case: TestCase) -> None:
    run.status = WebwrightRunStatus.cancelled.value
    run.error_message = "cancelled"
    case.status = CANCELLED_CASE_STATUS


async def run_webwright_for_case(
    session: Session,
    project_id: str,
    case: TestCase,
    model_config: str,
    job_id: str,
    *,
    preset_id: str | None = None,
    environment: str = "stg",
    start_url_override: str | None = None,
) -> WebwrightRun:
    profile = resolve_runtime()
    project = session.get(Project, project_id)
    if not project:
        raise ValueError("Project not found")
    prompt_components = build_webwright_prompt_payload_components(
        session,
        project,
        case,
        preset_id=preset_id,
        environment=environment,
        start_url_override=start_url_override,
    )
    start_url = prompt_components["startUrl"]
    prompt = prompt_components["prompt"]

    run_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_root = _resolve_output_root() / case.automation_key / f"run_{run_ts}"
    output_root.mkdir(parents=True, exist_ok=True)

    run = WebwrightRun(
        id=new_id("ww"),
        project_id=project_id,
        test_case_id=case.id,
        automation_key=case.automation_key,
        status=WebwrightRunStatus.running.value,
        output_path=str(output_root),
        started_at=datetime.utcnow(),
    )
    session.add(run)
    case.status = "webwright_running"
    session.add(case)
    session.commit()
    session.refresh(run)

    execution_mode = profile.execution_mode
    webwright_root = profile.webwright_root
    python_path = profile.webwright_python
    base_config = profile.base_config
    model_cfg = profile.model_config or model_config
    config_args = [base_config, model_cfg]
    if profile.model_name:
        config_args.append(f"model.model_name={profile.model_name}")
    if profile.webwright_shell:
        config_args.append(f"environment.shell={profile.webwright_shell}")
    if profile.webwright_step_limit:
        config_args.append(f"agent.step_limit={profile.webwright_step_limit}")
    subprocess_env = profile.subprocess_env()
    subprocess_env.setdefault("PYTHONUNBUFFERED", "1")
    record_webwright_prompt_payload(
        session,
        project=project,
        case=case,
        run=run,
        components=prompt_components,
        model_config=model_cfg,
    )

    cmd = [
        python_path, "-m", "webwright.run.cli",
    ]
    for config_arg in config_args:
        cmd.extend(["-c", config_arg])
    cmd.extend([
        "-t", prompt,
        "--start-url", start_url,
        "--task-id", case.automation_key,
        "-o", str(output_root),
    ])

    await log_streams.publish(job_id, f"[webwright] Starting run for {case.automation_key}")

    stdout_path = output_root / "stdout.log"
    stderr_path = output_root / "stderr.log"
    stdout_path.write_text("", encoding="utf-8")
    stderr_path.write_text("", encoding="utf-8")
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    process: Any = None
    stream_tasks: list[asyncio.Task[Any]] = []
    heartbeat_task: asyncio.Task[Any] | None = None
    timed_out = False
    return_code: int | None = None

    try:
        if execution_mode == "wsl":
            inner = " ".join([f"'{c}'" if " " in c else c for c in cmd])
            shell_cmd = ["wsl.exe", "bash", "-lc", f"cd {webwright_root} && source .venv/bin/activate && {inner}"]
            process = await create_subprocess_exec(
                *shell_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=webwright_root or None,
                env=subprocess_env,
            )
        else:
            process = await create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=webwright_root or None,
                env=subprocess_env,
            )

        _register_active_run(
            ActiveWebwrightRun(
                run_id=run.id or "",
                job_id=job_id,
                process=process,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                stream_tasks=[],
            )
        )
        await log_streams.publish(
            job_id,
            f"[webwright] Process started for {case.automation_key} (pid={process.pid}, timeout={profile.webwright_run_timeout_seconds}s)",
        )
        assert process.stdout is not None
        assert process.stderr is not None
        stream_tasks = [
            asyncio.create_task(_stream_pipe(process.stdout, job_id, stdout_path, stdout_chunks)),
            asyncio.create_task(_stream_pipe(process.stderr, job_id, stderr_path, stderr_chunks)),
        ]
        heartbeat_task = asyncio.create_task(_publish_heartbeat(process, job_id, case.automation_key))
        _update_active_run_tasks(run.id or "", stream_tasks, heartbeat_task)

        if _refresh_cancelled_state(session, run, case):
            _mark_active_run_cancel_requested(run.id or "")
            await cancel_webwright_run(run.id or "", job_id)

        try:
            return_code = await asyncio.wait_for(
                process.wait(),
                timeout=profile.webwright_run_timeout_seconds,
            )
        except asyncio.TimeoutError:
            timed_out = True
            await _stop_process(process)
            return_code = process.returncode
        finally:
            if heartbeat_task:
                heartbeat_task.cancel()
                await asyncio.gather(heartbeat_task, return_exceptions=True)

        pipes_closed = await _finish_background_tasks(stream_tasks, PIPE_DRAIN_TIMEOUT_SECONDS)
        stderr_text = "".join(stderr_chunks)
        if not pipes_closed:
            pipe_message = "[webwright] Output pipes remained open after process exit; continuing with captured output."
            stderr_text += ("\n" if stderr_text and not stderr_text.endswith("\n") else "") + pipe_message + "\n"
            _append_log(stderr_path, pipe_message + "\n")
            await log_streams.publish(job_id, pipe_message)
        if timed_out:
            timeout_message = f"[timeout] Webwright exceeded {profile.webwright_run_timeout_seconds}s; harvesting available artifacts."
            stderr_text += ("\n" if stderr_text and not stderr_text.endswith("\n") else "") + timeout_message + "\n"
            _append_log(stderr_path, timeout_message + "\n")
            await log_streams.publish(job_id, timeout_message)
        elif return_code not in {None, 0}:
            exit_message = f"[webwright] Process exited with code {return_code} for {case.automation_key}."
            stderr_text += ("\n" if stderr_text and not stderr_text.endswith("\n") else "") + exit_message + "\n"
            _append_log(stderr_path, exit_message + "\n")
            await log_streams.publish(job_id, exit_message)
        else:
            await log_streams.publish(job_id, f"[webwright] Process finished for {case.automation_key}")

        final_script = _find_webwright_artifact(output_root, "final_script.py")
        trajectory = _find_webwright_artifact(output_root, "trajectory.json")

        if _refresh_cancelled_state(session, run, case):
            cancellation_message = "[cancelled] Webwright run cancelled; harvesting available artifacts."
            stderr_text += ("\n" if stderr_text and not stderr_text.endswith("\n") else "") + cancellation_message + "\n"
            await _append_cancellation_diagnostic(
                job_id=job_id,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                message=cancellation_message,
            )
            _mark_run_cancelled(run, case)
            run.final_script_path = str(final_script) if final_script else None
            run.trajectory_path = str(trajectory) if trajectory else None
        elif not final_script:
            run.status = WebwrightRunStatus.failed.value
            if not stderr_text:
                missing_artifact_message = "[error] Webwright exited without final_script.py or diagnostic output."
                stderr_text = missing_artifact_message + "\n"
                _append_log(stderr_path, stderr_text)
                await log_streams.publish(job_id, missing_artifact_message)
            run.error_message = "timeout" if timed_out else classify_error(stderr_text)
            case.status = "webwright_failed"
        else:
            run.status = WebwrightRunStatus.completed.value
            run.final_script_path = str(final_script)
            run.trajectory_path = str(trajectory) if trajectory else None
            case.status = "webwright_completed"

        metadata = {
            "runId": output_root.name,
            "automationKey": case.automation_key,
            "caseId": case.source_case_id,
            "sourceType": case.source_type,
            "startUrl": start_url,
            "status": run.status,
            "startedAt": run.started_at.isoformat() if run.started_at else None,
            "endedAt": datetime.utcnow().isoformat(),
            "artifacts": {
                "finalScript": _relative_artifact(output_root, final_script),
                "trajectory": _relative_artifact(output_root, trajectory),
                "stdout": "stdout.log",
                "stderr": "stderr.log",
            },
            "timedOut": timed_out,
            "returnCode": return_code,
        }
        (output_root / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    except FileNotFoundError as exc:
        if process is not None:
            await _stop_process(process)
        if heartbeat_task is not None:
            heartbeat_task.cancel()
        await _finish_background_tasks(
            [*stream_tasks, *([heartbeat_task] if heartbeat_task is not None else [])],
            PIPE_DRAIN_TIMEOUT_SECONDS,
        )
        error_message = f"[error] {exc}"
        _append_log(stderr_path, error_message + "\n")
        await log_streams.publish(job_id, error_message)
        if _refresh_cancelled_state(session, run, case):
            _mark_run_cancelled(run, case)
        else:
            run.status = WebwrightRunStatus.failed.value
            run.error_message = "webwright_not_found"
            case.status = "webwright_failed"
    except Exception as exc:
        if process is not None:
            await _stop_process(process)
        if heartbeat_task is not None:
            heartbeat_task.cancel()
        await _finish_background_tasks(
            [*stream_tasks, *([heartbeat_task] if heartbeat_task is not None else [])],
            PIPE_DRAIN_TIMEOUT_SECONDS,
        )
        error_message = mask_secrets(f"[error] {type(exc).__name__}: {exc}")
        _append_log(stderr_path, error_message + "\n")
        await log_streams.publish(job_id, error_message)
        if _refresh_cancelled_state(session, run, case):
            _mark_run_cancelled(run, case)
        else:
            run.status = WebwrightRunStatus.failed.value
            run.error_message = classify_error(error_message)
            case.status = "webwright_failed"

    _unregister_active_run(run.id)
    run.ended_at = datetime.utcnow()
    session.add(run)
    session.add(case)
    session.commit()
    session.refresh(run)
    index_webwright_run_artifacts(session, run)
    return run


async def create_mock_run(
    session: Session,
    project_id: str,
    case: TestCase,
    job_id: str,
    *,
    model_config: str = "model_openai.yaml",
    preset_id: str | None = None,
    environment: str = "stg",
    start_url_override: str | None = None,
) -> WebwrightRun:
    """Create a mock Webwright run when CLI is unavailable (dev/demo)."""
    project = session.get(Project, project_id)
    prompt_components = (
        build_webwright_prompt_payload_components(
            session,
            project,
            case,
            preset_id=preset_id,
            environment=environment,
            start_url_override=start_url_override or MOCK_START_URL,
        )
        if project
        else None
    )
    run_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_root = _resolve_output_root() / case.automation_key / f"run_{run_ts}"
    output_root.mkdir(parents=True, exist_ok=True)

    script = f'''from playwright.sync_api import sync_playwright, expect

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto({json.dumps(MOCK_START_URL)})
        page.get_by_role("link", name="More information").click()
        expect(page).to_have_url({json.dumps(MOCK_START_URL)})
        browser.close()

if __name__ == "__main__":
    run()
'''
    (output_root / "final_script.py").write_text(script, encoding="utf-8")
    (output_root / "trajectory.json").write_text("[]", encoding="utf-8")
    (output_root / "stdout.log").write_text("[mock] generated sample script\n", encoding="utf-8")
    (output_root / "stderr.log").write_text("", encoding="utf-8")

    run = WebwrightRun(
        id=new_id("ww"),
        project_id=project_id,
        test_case_id=case.id,
        automation_key=case.automation_key,
        status=WebwrightRunStatus.completed.value,
        output_path=str(output_root),
        final_script_path=str(output_root / "final_script.py"),
        trajectory_path=str(output_root / "trajectory.json"),
        started_at=datetime.utcnow(),
        ended_at=datetime.utcnow(),
    )
    metadata = {
        "runId": output_root.name,
        "automationKey": case.automation_key,
        "caseId": case.source_case_id,
        "sourceType": case.source_type,
        "startUrl": MOCK_START_URL,
        "status": run.status,
        "startedAt": run.started_at.isoformat() if run.started_at else None,
        "endedAt": run.ended_at.isoformat() if run.ended_at else None,
        "artifacts": {
            "finalScript": "final_script.py",
            "trajectory": "trajectory.json",
            "stdout": "stdout.log",
            "stderr": "stderr.log",
        },
    }
    (output_root / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    case.status = "webwright_completed"
    session.add(run)
    session.add(case)
    session.commit()
    session.refresh(run)
    if project and prompt_components:
        record_webwright_prompt_payload(
            session,
            project=project,
            case=case,
            run=run,
            components=prompt_components,
            model_config=model_config,
        )
    index_webwright_run_artifacts(session, run)
    await log_streams.publish(job_id, f"[mock] Created sample Webwright run for {case.automation_key}")
    return run
