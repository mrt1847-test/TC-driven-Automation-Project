from __future__ import annotations

import asyncio
import json
from datetime import datetime as real_datetime
from pathlib import Path

from sqlmodel import SQLModel, Session, create_engine, select

import worker.core.database as database
from worker.models.db import ArtifactAsset, ExecutionResult, ExecutionRun, Project
from worker.models.schemas import ExecutionRequest
from worker.routers import executions
from worker.services import project_runner


class _Profile:
    python = "python"

    def subprocess_env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        return extra or {}


class _Clock:
    current_second = 0

    @classmethod
    def utcnow(cls):
        cls.current_second += 1
        return real_datetime(2026, 6, 12, 0, 0, cls.current_second)


class _SameSecondClock:
    @classmethod
    def utcnow(cls):
        return real_datetime(2026, 6, 12, 0, 0, 0)


class _LongRunningRunnerProcess:
    pid = 9876

    def __init__(self, stdout: bytes = b"runner started\n", stderr: bytes = b"") -> None:
        self.returncode: int | None = None
        self.stdout = stdout
        self.stderr = stderr
        self.terminated = False
        self.killed = False
        self._done = asyncio.Event()

    async def communicate(self) -> tuple[bytes, bytes]:
        await self._done.wait()
        return self.stdout, self.stderr

    async def wait(self) -> int:
        await self._done.wait()
        return self.returncode if self.returncode is not None else 0

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15
        self._done.set()

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9
        self._done.set()


class _CompletedRunnerProcess:
    pid = 9877

    def __init__(self, stdout: bytes = b"runner completed\n", stderr: bytes = b"") -> None:
        self.returncode: int | None = 0
        self.stdout = stdout
        self.stderr = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        return self.stdout, self.stderr

    async def wait(self) -> int:
        return self.returncode if self.returncode is not None else 0

    def terminate(self) -> None:
        self.returncode = -15

    def kill(self) -> None:
        self.returncode = -9


class _BlockingRunnerProcess:
    pid = 9878

    def __init__(self, label: str) -> None:
        self.returncode: int | None = 0
        self.stdout = f"{label} stdout\n".encode("utf-8")
        self.stderr = f"{label} stderr\n".encode("utf-8")
        self._done = asyncio.Event()

    async def communicate(self) -> tuple[bytes, bytes]:
        await self._done.wait()
        return self.stdout, self.stderr

    async def wait(self) -> int:
        await self._done.wait()
        return self.returncode if self.returncode is not None else 0

    def terminate(self) -> None:
        self.returncode = -15
        self._done.set()

    def kill(self) -> None:
        self.returncode = -9
        self._done.set()

    def finish(self) -> None:
        self._done.set()


def _session_with_project(tmp_path: Path) -> tuple[Session, Project]:
    engine = create_engine(f"sqlite:///{tmp_path / 'studio.db'}", echo=False)
    SQLModel.metadata.create_all(engine)
    session = Session(engine)
    generated = tmp_path / "generated"
    generated.mkdir()
    project = Project(
        id="proj_runner_cancel",
        name="Runner Cancel Project",
        root_path=str(tmp_path),
        generated_project_path=str(generated),
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    return session, project


def _write_results(generated_path: Path, run_id: str, *, status: str = "passed") -> Path:
    run_dir = generated_path / "artifacts" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    result_path = run_dir / "results.json"
    failed = 1 if status == "failed" else 0
    payload = {
        "runId": run_id,
        "summary": {"total": 1, "passed": 0 if failed else 1, "failed": failed, "skipped": 0},
        "cases": [
            {
                "automationKey": "runner_cancel_case",
                "sourceType": "excel",
                "sourceCaseId": "RUN-CANCEL",
                "title": "Runner cancel case",
                "status": status,
                "durationMs": 1,
                "error": "stale result should not persist" if failed else None,
                "artifacts": {"screenshot": None, "trace": None, "video": None},
            }
        ],
    }
    result_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return result_path


def _patch_runner(monkeypatch, processes: list[object]) -> None:
    monkeypatch.setattr(project_runner, "ensure_generated_runtime", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(project_runner, "resolve_runtime", lambda: _Profile())
    monkeypatch.setattr(project_runner, "datetime", _Clock)
    monkeypatch.setattr(project_runner, "PROCESS_STOP_TIMEOUT_SECONDS", 0.05)

    async def capture_publish(_job_id: str, _message: str) -> None:
        return None

    async def fake_create_subprocess_exec(*args, **kwargs):
        generated_path = Path(args[3])
        run_id = args[args.index("--run-id") + 1]
        if not processes:
            _write_results(generated_path, run_id, status="failed")
            process = _LongRunningRunnerProcess()
            processes.append(process)
            return process

        _write_results(generated_path, run_id, status="passed")
        process = _CompletedRunnerProcess()
        processes.append(process)
        return process

    monkeypatch.setattr(project_runner, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(project_runner.log_streams, "publish", capture_publish)


def test_parallel_same_second_executions_use_unique_run_dirs_logs_and_rows(
    monkeypatch,
    tmp_path: Path,
) -> None:
    session, project = _session_with_project(tmp_path)
    processes: list[_BlockingRunnerProcess] = []
    published: list[tuple[str, str]] = []
    request = ExecutionRequest(
        env="stg",
        browser="chromium",
        headed=False,
        target_type="case",
        automation_key="runner_cancel_case",
        result_target="local",
    )

    monkeypatch.setattr(project_runner, "ensure_generated_runtime", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(project_runner, "resolve_runtime", lambda: _Profile())
    monkeypatch.setattr(project_runner, "datetime", _SameSecondClock)

    async def capture_publish(job_id: str, message: str) -> None:
        published.append((job_id, message))

    async def fake_create_subprocess_exec(*args, **kwargs):
        generated_path = Path(args[3])
        run_id = args[args.index("--run-id") + 1]
        label = f"parallel {len(processes) + 1}"
        _write_results(generated_path, run_id, status="passed")
        process = _BlockingRunnerProcess(label)
        processes.append(process)
        return process

    monkeypatch.setattr(project_runner, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(project_runner.log_streams, "publish", capture_publish)

    async def run_parallel() -> tuple[ExecutionRun, ExecutionRun]:
        first_task = asyncio.create_task(project_runner.run_project(session, project, request, "job_parallel_a"))
        while len(processes) < 1:
            await asyncio.sleep(0)
        second_task = asyncio.create_task(project_runner.run_project(session, project, request, "job_parallel_b"))
        while len(processes) < 2:
            await asyncio.sleep(0)
        for process in processes:
            process.finish()
        first_run, second_run = await asyncio.gather(first_task, second_task)
        return first_run, second_run

    first, second = asyncio.run(run_parallel())

    assert first.id != second.id
    assert first.run_id != second.run_id
    assert first.run_id.startswith("run_20260612_000000_exec_")
    assert second.run_id.startswith("run_20260612_000000_exec_")
    assert first.result_path is not None
    assert second.result_path is not None
    first_dir = Path(first.result_path).parent
    second_dir = Path(second.result_path).parent
    assert first_dir != second_dir
    assert first_dir.name == first.run_id
    assert second_dir.name == second.run_id
    assert json.loads(Path(first.result_path).read_text(encoding="utf-8"))["runId"] == first.run_id
    assert json.loads(Path(second.result_path).read_text(encoding="utf-8"))["runId"] == second.run_id
    assert "parallel 1 stdout" in (first_dir / "stdout.log").read_text(encoding="utf-8")
    assert "parallel 2 stdout" in (second_dir / "stdout.log").read_text(encoding="utf-8")
    first_results = session.exec(select(ExecutionResult).where(ExecutionResult.execution_run_id == first.id)).all()
    second_results = session.exec(select(ExecutionResult).where(ExecutionResult.execution_run_id == second.id)).all()
    assert len(first_results) == 1
    assert len(second_results) == 1
    assert first_results[0].id != second_results[0].id
    assert {job_id for job_id, _message in published} >= {"job_parallel_a", "job_parallel_b"}
    session.close()


def test_execution_cancel_stops_process_harvests_artifacts_and_rerun_uses_fresh_dir(
    monkeypatch,
    tmp_path: Path,
) -> None:
    session, project = _session_with_project(tmp_path)
    processes: list[object] = []
    _patch_runner(monkeypatch, processes)
    request = ExecutionRequest(
        env="stg",
        browser="chromium",
        headed=False,
        target_type="case",
        automation_key="runner_cancel_case",
        result_target="local",
    )

    async def run_and_cancel() -> ExecutionRun:
        task = asyncio.create_task(project_runner.run_project(session, project, request, "job_exec_cancel"))
        while not processes:
            await asyncio.sleep(0)

        execution = session.exec(select(ExecutionRun).where(ExecutionRun.project_id == project.id)).one()
        cancelled = False
        for _ in range(50):
            cancelled = await project_runner.cancel_execution_run(execution.id or "", "job_exec_cancel")
            if cancelled:
                break
            await asyncio.sleep(0)
        assert cancelled
        return await task

    cancelled_run = asyncio.run(run_and_cancel())

    first_process = processes[0]
    assert isinstance(first_process, _LongRunningRunnerProcess)
    assert first_process.terminated
    assert not first_process.killed
    assert cancelled_run.status == "cancelled"
    assert cancelled_run.result_path is not None

    cancelled_result_path = Path(cancelled_run.result_path)
    cancelled_payload = json.loads(cancelled_result_path.read_text(encoding="utf-8"))
    assert cancelled_payload["status"] == "cancelled"
    assert cancelled_payload["cases"] == []
    assert cancelled_payload["cancellation"]["returnCode"] == -15

    run_dir = cancelled_result_path.parent
    all_logs = "\n".join(path.read_text(encoding="utf-8") for path in run_dir.glob("*.log"))
    assert "runner started" in all_logs
    assert "[cancelled]" in all_logs

    stale_results = session.exec(
        select(ExecutionResult).where(ExecutionResult.execution_run_id == cancelled_run.id)
    ).all()
    assert stale_results == []
    assets = session.exec(select(ArtifactAsset).where(ArtifactAsset.source_id == cancelled_run.id)).all()
    assert {asset.artifact_type for asset in assets} >= {"metadata", "log"}

    rerun = asyncio.run(project_runner.rerun_failed(session, project, cancelled_run.id or "", "job_rerun_success"))
    assert rerun.id != cancelled_run.id
    assert rerun.run_id != cancelled_run.run_id
    assert rerun.result_path is not None
    assert Path(rerun.result_path).parent != run_dir
    assert rerun.status == "completed"
    rerun_results = session.exec(select(ExecutionResult).where(ExecutionResult.execution_run_id == rerun.id)).all()
    assert len(rerun_results) == 1
    assert rerun_results[0].status == "passed"
    session.close()


def test_rerun_failed_cancel_uses_execution_registry(monkeypatch, tmp_path: Path) -> None:
    session, project = _session_with_project(tmp_path)
    prev = ExecutionRun(
        id="exec_prev_failed",
        project_id=project.id,
        run_id="prev_failed",
        env="stg",
        browser="chromium",
        headed=False,
        status="failed",
        result_path=str(tmp_path / "generated" / "artifacts" / "runs" / "prev_failed" / "results.json"),
    )
    session.add(prev)
    session.commit()
    processes: list[object] = []
    _patch_runner(monkeypatch, processes)

    async def rerun_and_cancel() -> ExecutionRun:
        task = asyncio.create_task(project_runner.rerun_failed(session, project, prev.id or "", "job_rerun_cancel"))
        while not processes:
            await asyncio.sleep(0)

        rerun = session.exec(
            select(ExecutionRun)
            .where(ExecutionRun.project_id == project.id)
            .where(ExecutionRun.id != prev.id)
        ).one()
        cancelled = await project_runner.cancel_execution_run(rerun.id or "", "job_rerun_cancel")
        assert cancelled
        return await task

    cancelled_rerun = asyncio.run(rerun_and_cancel())

    process = processes[0]
    assert isinstance(process, _LongRunningRunnerProcess)
    assert process.terminated
    assert cancelled_rerun.status == "cancelled"
    assert cancelled_rerun.result_path is not None
    payload = json.loads(Path(cancelled_rerun.result_path).read_text(encoding="utf-8"))
    assert payload["cases"] == []
    results = session.exec(
        select(ExecutionResult).where(ExecutionResult.execution_run_id == cancelled_rerun.id)
    ).all()
    assert results == []
    session.close()


def test_execution_cancel_endpoint_delegates_to_process_registry(monkeypatch, client, project_id: str) -> None:
    with Session(database.engine) as session:
        run = ExecutionRun(
            id="exec_cancel_api",
            project_id=project_id,
            run_id="api_cancel",
            env="stg",
            browser="chromium",
            headed=False,
            status="running",
        )
        session.add(run)
        session.commit()

    cancelled_execution_ids: list[str] = []

    async def fake_cancel_execution_run(execution_id: str, job_id: str | None = None) -> bool:
        cancelled_execution_ids.append(execution_id)
        return True

    monkeypatch.setattr(executions, "cancel_execution_run", fake_cancel_execution_run)

    response = client.post(f"/projects/{project_id}/executions/exec_cancel_api/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert cancelled_execution_ids == ["exec_cancel_api"]


def test_execution_queue_and_rerun_return_unique_job_ids(monkeypatch, client, project_id: str) -> None:
    async def noop_run_execution(*_args, **_kwargs) -> None:
        return None

    async def noop_rerun_failed_execution(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(executions, "_run_execution", noop_run_execution)
    monkeypatch.setattr(executions, "_rerun_failed_execution", noop_rerun_failed_execution)

    payload = {
        "env": "stg",
        "browser": "chromium",
        "headed": False,
        "target_type": "all",
        "result_target": "local",
    }
    first = client.post(f"/projects/{project_id}/executions", json=payload)
    second = client.post(f"/projects/{project_id}/executions", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    first_job = first.json()["jobId"]
    second_job = second.json()["jobId"]
    assert first_job.startswith("execjob_")
    assert second_job.startswith("execjob_")
    assert first_job != second_job

    with Session(database.engine) as session:
        run = ExecutionRun(
            id="exec_rerun_job_unique",
            project_id=project_id,
            run_id="run_rerun_job_unique",
            env="stg",
            browser="chromium",
            headed=False,
            status="failed",
        )
        session.add(run)
        session.commit()

    rerun_first = client.post(f"/projects/{project_id}/executions/exec_rerun_job_unique/rerun-failed")
    rerun_second = client.post(f"/projects/{project_id}/executions/exec_rerun_job_unique/rerun-failed")

    assert rerun_first.status_code == 200
    assert rerun_second.status_code == 200
    rerun_first_job = rerun_first.json()["jobId"]
    rerun_second_job = rerun_second.json()["jobId"]
    assert rerun_first_job.startswith("rerunjob_")
    assert rerun_second_job.startswith("rerunjob_")
    assert rerun_first_job != rerun_second_job
