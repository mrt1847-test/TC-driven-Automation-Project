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
from worker.services.artifact_indexing import index_execution_failure_artifacts


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

    cmd = [
        "python", "-m", "runner.cli", "run",
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
    exec_run.status = "completed" if process.returncode == 0 else "failed"
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
    cmd = ["python", "-m", "runner.cli", "rerun-failed", "--from-run-id", prev.run_id, "--run-id", run_id]
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

    process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=str(generated_path))
    stdout, stderr = await process.communicate()
    stdout_text = stdout.decode("utf-8", errors="replace")
    stderr_text = stderr.decode("utf-8", errors="replace")
    _write_runner_logs(generated_path, run_id, stdout_text, stderr_text)
    if stdout_text:
        await log_streams.publish(job_id, stdout_text)
    if stderr_text:
        await log_streams.publish(job_id, stderr_text)

    result_path = generated_path / "artifacts" / "runs" / run_id / "results.json"
    exec_run.status = "completed" if process.returncode == 0 else "failed"
    exec_run.ended_at = datetime.utcnow()
    exec_run.result_path = str(result_path) if result_path.exists() else None
    session.add(exec_run)
    if result_path.exists():
        _persist_results(session, exec_run, result_path)
    session.commit()
    session.refresh(exec_run)
    index_execution_failure_artifacts(session, exec_run)
    return exec_run


def _write_runner_logs(generated_path: Path, run_id: str, stdout_text: str, stderr_text: str) -> None:
    artifact_dir = generated_path / "artifacts" / "runs" / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "stdout.log").write_text(stdout_text, encoding="utf-8")
    (artifact_dir / "stderr.log").write_text(stderr_text, encoding="utf-8")


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
