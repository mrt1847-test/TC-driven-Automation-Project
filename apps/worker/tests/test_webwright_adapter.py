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


class _SameSecondClock:
    @classmethod
    def now(cls, tz=None):
        return real_datetime(2026, 6, 12, 0, 0, 0, tzinfo=tz)

    @classmethod
    def utcnow(cls):
        return real_datetime(2026, 6, 12, 0, 0, 0)


def test_wsl_command_builder_passes_unsafe_values_as_positional_argv(tmp_path: Path) -> None:
    prompt = "Prompt with spaces; $(touch hacked) 'single' \"double\" & 한글"
    webwright_root = "/mnt/c/QA/Webwright Root (한글) & 'quoted'"
    output_root = tmp_path / "output dir (한글) & shell"
    cli_args = webwright_adapter._build_webwright_cli_args(
        python_path="python",
        config_args=[
            "base config.yaml",
            "model_openai.yaml",
            "model.model_name=gpt-5-mini; echo bad",
            "environment.shell=/mnt/c/Program Files/Git/bin/bash.exe && bad",
            "agent.step_limit=30",
        ],
        prompt=prompt,
        start_url="https://example.test/path?q=one&name='two'",
        automation_key="case key $(bad) & 한글",
        output_root=output_root,
    )

    wsl_args = webwright_adapter._build_wsl_webwright_args(webwright_root, cli_args)

    assert wsl_args[:4] == ["wsl.exe", "bash", "-lc", webwright_adapter.WSL_WEBWRIGHT_SCRIPT]
    assert wsl_args[4] == "tc-studio-webwright"
    assert wsl_args[5] == webwright_root
    assert wsl_args[6:] == cli_args
    assert webwright_root not in webwright_adapter.WSL_WEBWRIGHT_SCRIPT
    assert prompt not in webwright_adapter.WSL_WEBWRIGHT_SCRIPT
    assert str(output_root) not in webwright_adapter.WSL_WEBWRIGHT_SCRIPT
    assert "$(touch hacked)" not in webwright_adapter.WSL_WEBWRIGHT_SCRIPT
    assert "echo bad" not in webwright_adapter.WSL_WEBWRIGHT_SCRIPT


def test_wsl_webwright_run_uses_argv_safe_wrapper(monkeypatch, tmp_path: Path) -> None:
    session, case = _session_with_case(tmp_path)
    profile = _Profile(tmp_path / "Webwright Root (한글) & shell", tmp_path / "runs dir (한글) & shell")
    profile.execution_mode = "wsl"
    profile.webwright_root = "/mnt/c/QA/Webwright Root (한글) & 'quoted'"
    profile.base_config = "base config.yaml"
    profile.model_config = "model openai.yaml"
    profile.model_name = "gpt-5-mini; echo bad"
    profile.webwright_shell = "/mnt/c/Program Files/Git/bin/bash.exe && bad"
    profile.webwright_step_limit = 37
    captured_args: list[str] = []
    captured_kwargs: dict[str, object] = {}
    start_url = "https://example.test/path?q=one&name='two'&lang=한글"

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured_args.extend(str(arg) for arg in args)
        captured_kwargs.update(kwargs)
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
        webwright_adapter.run_webwright_for_case(
            session,
            "proj_test",
            case,
            "ignored model.yaml",
            "job_wsl",
            start_url_override=start_url,
        )
    )

    assert run.status == WebwrightRunStatus.completed.value
    assert captured_args[:4] == ["wsl.exe", "bash", "-lc", webwright_adapter.WSL_WEBWRIGHT_SCRIPT]
    assert captured_args[5] == profile.webwright_root
    assert captured_kwargs["cwd"] is None
    assert captured_args[captured_args.index("--start-url") + 1] == start_url
    assert captured_args[captured_args.index("--task-id") + 1] == case.automation_key
    assert captured_args[captured_args.index("-o") + 1] == run.output_path
    config_values = [
        captured_args[index + 1]
        for index, value in enumerate(captured_args)
        if value == "-c"
    ]
    assert config_values == [
        "base config.yaml",
        "model openai.yaml",
        "model.model_name=gpt-5-mini; echo bad",
        "environment.shell=/mnt/c/Program Files/Git/bin/bash.exe && bad",
        "agent.step_limit=37",
    ]
    assert profile.webwright_root not in webwright_adapter.WSL_WEBWRIGHT_SCRIPT
    assert start_url not in webwright_adapter.WSL_WEBWRIGHT_SCRIPT
    assert "echo bad" not in webwright_adapter.WSL_WEBWRIGHT_SCRIPT
    session.close()


def test_webwright_same_second_runs_use_unique_output_roots_and_metadata(monkeypatch, tmp_path: Path) -> None:
    session, case = _session_with_case(tmp_path)
    profile = _Profile(tmp_path, tmp_path / "runs")
    output_roots: list[Path] = []

    async def fake_create_subprocess_exec(*args, **kwargs):
        output_root = Path(args[args.index("-o") + 1])
        output_roots.append(output_root)
        (output_root / "final_script.py").write_text(f"print('run {len(output_roots)}')\n", encoding="utf-8")
        return _FakeProcess()

    async def capture_publish(_job_id: str, _message: str) -> None:
        return None

    monkeypatch.setattr(webwright_adapter, "resolve_runtime", lambda: profile)
    monkeypatch.setattr(webwright_adapter, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(webwright_adapter.log_streams, "publish", capture_publish)
    monkeypatch.setattr(webwright_adapter, "index_webwright_run_artifacts", lambda *_args: None)
    monkeypatch.setattr(webwright_adapter, "datetime", _SameSecondClock)

    first = asyncio.run(
        webwright_adapter.run_webwright_for_case(session, "proj_test", case, "model_openai.yaml", "job_same_second_a")
    )
    second = asyncio.run(
        webwright_adapter.run_webwright_for_case(session, "proj_test", case, "model_openai.yaml", "job_same_second_b")
    )

    assert first.id != second.id
    assert first.output_path != second.output_path
    assert output_roots == [Path(first.output_path or ""), Path(second.output_path or "")]
    assert output_roots[0].parent == output_roots[1].parent
    assert output_roots[0].name.startswith("run_20260612_000000_ww_")
    assert output_roots[1].name.startswith("run_20260612_000000_ww_")
    first_metadata = json.loads((output_roots[0] / "metadata.json").read_text(encoding="utf-8"))
    second_metadata = json.loads((output_roots[1] / "metadata.json").read_text(encoding="utf-8"))
    assert first_metadata["runId"] == output_roots[0].name
    assert second_metadata["runId"] == output_roots[1].name
    assert first_metadata["runId"] != second_metadata["runId"]
    assert "Running task" in (output_roots[0] / "stdout.log").read_text(encoding="utf-8")
    assert "Running task" in (output_roots[1] / "stdout.log").read_text(encoding="utf-8")
    runs = session.exec(select(WebwrightRun).where(WebwrightRun.test_case_id == case.id)).all()
    assert {run.id for run in runs} == {first.id, second.id}
    assert {run.output_path for run in runs} == {first.output_path, second.output_path}
    session.close()


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


def test_webwright_queue_and_retry_return_unique_job_ids(monkeypatch, client, project_id: str) -> None:
    async def noop_process_runs(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(webwright_runs, "_process_runs", noop_process_runs)

    first = client.post(f"/projects/{project_id}/webwright-runs", json={"caseIds": ["tc_same_second"]})
    second = client.post(f"/projects/{project_id}/webwright-runs", json={"caseIds": ["tc_same_second"]})

    assert first.status_code == 200
    assert second.status_code == 200
    first_job = first.json()["jobId"]
    second_job = second.json()["jobId"]
    assert first_job.startswith("wwjob_")
    assert second_job.startswith("wwjob_")
    assert first_job != second_job

    with Session(database.engine) as session:
        case = DbTestCase(
            id="tc_retry_job_unique",
            project_id=project_id,
            source_type="excel",
            source_case_id="CASE-RETRY-JOB",
            title="Retry job uniqueness",
            steps_json="[]",
            automation_key="retry_job_unique",
        )
        run = WebwrightRun(
            id="ww_retry_job_unique",
            project_id=project_id,
            test_case_id=case.id,
            automation_key=case.automation_key,
            status=WebwrightRunStatus.failed.value,
        )
        session.add(case)
        session.add(run)
        session.commit()

    retry_first = client.post(f"/projects/{project_id}/webwright-runs/ww_retry_job_unique/retry")
    retry_second = client.post(f"/projects/{project_id}/webwright-runs/ww_retry_job_unique/retry")

    assert retry_first.status_code == 200
    assert retry_second.status_code == 200
    retry_first_job = retry_first.json()["jobId"]
    retry_second_job = retry_second.json()["jobId"]
    assert retry_first_job.startswith("wwretry_")
    assert retry_second_job.startswith("wwretry_")
    assert retry_first_job != retry_second_job


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
