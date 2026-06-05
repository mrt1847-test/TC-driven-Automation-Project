from __future__ import annotations

import asyncio
from pathlib import Path

from sqlmodel import SQLModel, Session, create_engine

from worker.models.db import CasePromptOverride, Project, ProjectPromptContext, TestCase as DbTestCase
from worker.models.db import WebwrightRunStatus
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
        self.returncode = 0
        return 0

    def kill(self) -> None:
        self.returncode = -1


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
