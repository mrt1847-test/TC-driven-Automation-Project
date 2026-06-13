from __future__ import annotations

import asyncio
import json
from datetime import datetime as real_datetime
from pathlib import Path

from sqlmodel import SQLModel, Session, create_engine, select

import worker.core.database as database
from worker.models.db import ArtifactAsset, CasePromptOverride, Project, ProjectPromptContext, TestCase as DbTestCase
from worker.models.db import WebwrightRun
from worker.models.db import WebwrightRunStatus
from worker.routers import webwright_runs
from worker.services import webwright_adapter


class _Profile:
    execution_mode = "native"
    webwright_python = "python"
    base_config = "base.yaml"
    model_config = "model_openai.yaml"
    model_name = None
    webwright_shell = None
    webwright_step_limit = None
    webwright_run_timeout_seconds = 1

    def __init__(self, root: Path, output_root: Path) -> None:
        self.webwright_root = str(root)
        self.webwright_output_root = str(output_root)

    def subprocess_env(self) -> dict[str, str]:
        return {}


class _FakeProcess:
    pid = 1234

    def __init__(self, *, keep_stdout_open: bool = False) -> None:
        self.returncode: int | None = None
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stdout.feed_data(b"Running task\n")
        if not keep_stdout_open:
            self.stdout.feed_eof()
        self.stderr.feed_eof()

    async def wait(self) -> int:
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def kill(self) -> None:
        self.returncode = -1

    def terminate(self) -> None:
        self.returncode = -15


class _LongRunningFakeProcess:
    pid = 5678

    def __init__(self) -> None:
        self.returncode: int | None = None
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stdout.feed_data(b"Started long Webwright task\n")
        self.terminated = False
        self.killed = False
        self._done = asyncio.Event()

    async def wait(self) -> int:
        await self._done.wait()
        return self.returncode if self.returncode is not None else 0

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15
        self.stdout.feed_eof()
        self.stderr.feed_eof()
        self._done.set()

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9
        self.stdout.feed_eof()
        self.stderr.feed_eof()
        self._done.set()


def _session_with_case(tmp_path: Path) -> tuple[Session, DbTestCase]:
    engine = create_engine(f"sqlite:///{tmp_path / 'studio.db'}", echo=False)
    SQLModel.metadata.create_all(engine)
    session = Session(engine)
    project = Project(
        id="proj_test",
        name="Test Project",
        root_path=str(tmp_path / "project"),
        generated_project_path=str(tmp_path / "project" / "generated"),
    )
    case = DbTestCase(
        id="tc_test",
        project_id="proj_test",
        source_type="excel",
        source_case_id="CASE-1",
        title="Test case",
        steps_json="[]",
        automation_key="case_1",
        start_url="https://example.com",
    )
    session.add(project)
    session.add(case)
    session.commit()
    session.refresh(case)
    return session, case


class _Clock:
    current_second = 0

    @classmethod
    def now(cls, tz=None):
        cls.current_second += 1
        return real_datetime(2026, 6, 12, 0, 0, cls.current_second, tzinfo=tz)

    @classmethod
    def utcnow(cls):
        return real_datetime(2026, 6, 12, 0, 0, max(cls.current_second, 1))


def test_cancel_stops_active_webwright_process_and_retry_creates_fresh_run(monkeypatch, tmp_path: Path) -> None:
    session, case = _session_with_case(tmp_path)
    profile = _Profile(tmp_path, tmp_path / "runs")
    messages: list[str] = []
    processes: list[_LongRunningFakeProcess | _FakeProcess] = []

    async def fake_create_subprocess_exec(*args, **kwargs):
        output_root = Path(args[args.index("-o") + 1])
        if not processes:
            process = _LongRunningFakeProcess()
            processes.append(process)
            return process

        (output_root / "final_script.py").write_text("print('retry ok')\n", encoding="utf-8")
        process = _FakeProcess()
        processes.append(process)
        return process

    async def capture_publish(_job_id: str, message: str) -> None:
        messages.append(message)

    monkeypatch.setattr(webwright_adapter, "resolve_runtime", lambda: profile)
    monkeypatch.setattr(webwright_adapter, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(webwright_adapter.log_streams, "publish", capture_publish)
    monkeypatch.setattr(webwright_adapter, "PIPE_DRAIN_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(webwright_adapter, "PROCESS_STOP_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(webwright_adapter, "datetime", _Clock)

    async def run_and_cancel() -> WebwrightRun:
        task = asyncio.create_task(
            webwright_adapter.run_webwright_for_case(
                session,
                "proj_test",
                case,
                "model_openai.yaml",
                "job_cancel",
            )
        )
        while not processes:
            await asyncio.sleep(0)

        run = session.exec(select(WebwrightRun).where(WebwrightRun.test_case_id == case.id)).one()
        cancelled = False
        for _ in range(50):
            cancelled = await webwright_adapter.cancel_webwright_run(run.id or "", "job_cancel")
            if cancelled:
                break
            await asyncio.sleep(0)
        assert cancelled
        return await task

    cancelled_run = asyncio.run(run_and_cancel())

    first_process = processes[0]
    assert isinstance(first_process, _LongRunningFakeProcess)
    assert first_process.terminated
    assert not first_process.killed
    assert cancelled_run.status == WebwrightRunStatus.cancelled.value
    session.refresh(case)
    assert case.status == "cancelled"

    output_root = Path(cancelled_run.output_path or "")
    stdout_text = (output_root / "stdout.log").read_text(encoding="utf-8")
    stderr_text = (output_root / "stderr.log").read_text(encoding="utf-8")
    metadata = json.loads((output_root / "metadata.json").read_text(encoding="utf-8"))
    assert "Started long Webwright task" in stdout_text
    assert "[cancelled]" in stdout_text
    assert "[cancelled]" in stderr_text
    assert metadata["status"] == WebwrightRunStatus.cancelled.value

    assets = session.exec(
        select(ArtifactAsset).where(ArtifactAsset.source_id == cancelled_run.id)
    ).all()
    assert {asset.artifact_type for asset in assets} >= {"log", "metadata"}
    assert any("log stream marked cancelled" in message for message in messages)

    retry_run = asyncio.run(
        webwright_adapter.run_webwright_for_case(
            session,
            "proj_test",
            case,
            "model_openai.yaml",
            "job_retry",
        )
    )

    assert retry_run.id != cancelled_run.id
    assert retry_run.status == WebwrightRunStatus.completed.value
    assert Path(retry_run.final_script_path or "").read_text(encoding="utf-8") == "print('retry ok')\n"
    session.refresh(case)
    assert case.status == "webwright_completed"
    session.close()


def test_cancel_endpoint_marks_case_and_delegates_to_process_registry(
    monkeypatch,
    client,
    project_id: str,
) -> None:
    with Session(database.engine) as session:
        case = DbTestCase(
            id="tc_cancel_api",
            project_id=project_id,
            source_type="excel",
            source_case_id="CASE-CANCEL",
            title="Cancel API case",
            steps_json="[]",
            automation_key="cancel_api",
            status="webwright_running",
        )
        run = WebwrightRun(
            id="ww_cancel_api",
            project_id=project_id,
            test_case_id=case.id,
            automation_key=case.automation_key,
            status=WebwrightRunStatus.running.value,
        )
        session.add(case)
        session.add(run)
        session.commit()

    cancelled_run_ids: list[str] = []

    async def fake_cancel_webwright_run(run_id: str, job_id: str | None = None) -> bool:
        cancelled_run_ids.append(run_id)
        return True

    monkeypatch.setattr(webwright_runs, "cancel_webwright_run", fake_cancel_webwright_run)

    response = client.post(f"/projects/{project_id}/webwright-runs/ww_cancel_api/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == WebwrightRunStatus.cancelled.value
    assert cancelled_run_ids == ["ww_cancel_api"]
    with Session(database.engine) as session:
        refreshed_case = session.get(DbTestCase, "tc_cancel_api")
        assert refreshed_case is not None
        assert refreshed_case.status == "cancelled"


def test_webwright_run_finishes_when_output_pipe_stays_open(monkeypatch, tmp_path: Path) -> None:
    session, case = _session_with_case(tmp_path)
    profile = _Profile(tmp_path, tmp_path / "runs")
    messages: list[str] = []
    captured_env: dict[str, str] = {}
    captured_prompt: list[str] = []

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured_env.update(kwargs["env"])
        captured_prompt.append(args[args.index("-t") + 1])
        output_root = Path(args[args.index("-o") + 1])
        (output_root / "final_script.py").write_text("print('ok')\n", encoding="utf-8")
        return _FakeProcess(keep_stdout_open=True)

    async def capture_publish(_job_id: str, message: str) -> None:
        messages.append(message)

    monkeypatch.setattr(webwright_adapter, "resolve_runtime", lambda: profile)
    monkeypatch.setattr(webwright_adapter, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(webwright_adapter.log_streams, "publish", capture_publish)
    monkeypatch.setattr(webwright_adapter, "index_webwright_run_artifacts", lambda *_args: None)
    monkeypatch.setattr(webwright_adapter, "PIPE_DRAIN_TIMEOUT_SECONDS", 0.01)

    run = asyncio.run(
        webwright_adapter.run_webwright_for_case(session, "proj_test", case, "model_openai.yaml", "job_test")
    )

    assert run.status == WebwrightRunStatus.completed.value
    assert run.ended_at is not None
    assert captured_env["PYTHONUNBUFFERED"] == "1"
    assert captured_prompt
    assert "Additional Prompt Context" not in captured_prompt[0]
    assert "Running task" in (Path(run.output_path) / "stdout.log").read_text(encoding="utf-8")
    assert any("Output pipes remained open" in message for message in messages)
    session.close()


def test_webwright_run_includes_batch_and_case_prompt_context(monkeypatch, tmp_path: Path) -> None:
    session, case = _session_with_case(tmp_path)
    session.add(
        ProjectPromptContext(
            project_id="proj_test",
            batch_prompt="Use the signed-in admin workspace.",
        )
    )
    session.add(
        CasePromptOverride(
            project_id="proj_test",
            case_id="tc_test",
            automation_key="case_1",
            prompt_override="Open the billing tab before asserting totals.",
        )
    )
    session.commit()
    profile = _Profile(tmp_path, tmp_path / "runs")
    captured_prompt: list[str] = []

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured_prompt.append(args[args.index("-t") + 1])
        output_root = Path(args[args.index("-o") + 1])
        (output_root / "final_script.py").write_text("print('ok')\n", encoding="utf-8")
        return _FakeProcess()

    async def capture_publish(_job_id: str, _message: str) -> None:
        return None

    monkeypatch.setattr(webwright_adapter, "resolve_runtime", lambda: profile)
    monkeypatch.setattr(webwright_adapter, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(webwright_adapter.log_streams, "publish", capture_publish)
    monkeypatch.setattr(webwright_adapter, "index_webwright_run_artifacts", lambda *_args: None)

    run = asyncio.run(
        webwright_adapter.run_webwright_for_case(session, "proj_test", case, "model_openai.yaml", "job_test")
    )

    assert run.status == WebwrightRunStatus.completed.value
    assert captured_prompt
    prompt = captured_prompt[0]
    assert "Automation Key:\ncase_1" in prompt
    assert "Additional Prompt Context" in prompt
    assert "Batch Shared Prompt:\nUse the signed-in admin workspace." in prompt
    assert "Per-Case Prompt Override:\nOpen the billing tab before asserting totals." in prompt
    session.close()


def test_webwright_run_records_unexpected_spawn_error(monkeypatch, tmp_path: Path) -> None:
    session, case = _session_with_case(tmp_path)
    profile = _Profile(tmp_path, tmp_path / "runs")
    messages: list[str] = []

    async def fail_create_subprocess_exec(*_args, **_kwargs):
        raise RuntimeError("spawn failed")

    async def capture_publish(_job_id: str, message: str) -> None:
        messages.append(message)

    monkeypatch.setattr(webwright_adapter, "resolve_runtime", lambda: profile)
    monkeypatch.setattr(webwright_adapter, "create_subprocess_exec", fail_create_subprocess_exec)
    monkeypatch.setattr(webwright_adapter.log_streams, "publish", capture_publish)
    monkeypatch.setattr(webwright_adapter, "index_webwright_run_artifacts", lambda *_args: None)

    run = asyncio.run(
        webwright_adapter.run_webwright_for_case(session, "proj_test", case, "model_openai.yaml", "job_test")
    )

    assert run.status == WebwrightRunStatus.failed.value
    assert run.ended_at is not None
    assert "RuntimeError: spawn failed" in (Path(run.output_path) / "stderr.log").read_text(encoding="utf-8")
    assert any("RuntimeError: spawn failed" in message for message in messages)
    session.close()
