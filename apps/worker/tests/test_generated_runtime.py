from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sqlmodel import SQLModel, Session, create_engine, select

from worker.models.db import ExecutionResult, Project
from worker.models.schemas import ExecutionRequest
from worker.services.generated_runtime import ensure_generated_runtime
from worker.services.project_runner import run_project


class _BrokenRuntimeProfile:
    python = "__missing_python_for_bootstrap__"

    def subprocess_env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        return extra or {}


def test_generated_runtime_file_checks_report_success_and_missing_requirements(tmp_path: Path) -> None:
    generated = tmp_path / "generated"
    (generated / "runner").mkdir(parents=True)
    (generated / "mappings").mkdir()
    (generated / "runner" / "cli.py").write_text("print('runner')\n", encoding="utf-8")
    (generated / "mappings" / "cases.yaml").write_text("cases: []\n", encoding="utf-8")

    missing = ensure_generated_runtime(generated, install=False)
    assert missing["ok"] is False
    assert missing["allOk"] is False
    assert missing["message"] == "requirements.txt missing"
    assert missing["checks"]["requirements"] is False

    (generated / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    ready = ensure_generated_runtime(generated, install=False)
    assert ready["ok"] is True
    assert ready["allOk"] is True
    assert ready["message"] == "Generated project runtime files are present"


def test_generated_runtime_reports_broken_python_as_pip_failure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("worker.services.generated_runtime.resolve_runtime", lambda: _BrokenRuntimeProfile())
    generated = tmp_path / "generated"
    (generated / "runner").mkdir(parents=True)
    (generated / "mappings").mkdir()
    (generated / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (generated / "runner" / "cli.py").write_text("print('runner')\n", encoding="utf-8")
    (generated / "mappings" / "cases.yaml").write_text("cases: []\n", encoding="utf-8")

    result = ensure_generated_runtime(generated, install=True)
    assert result["ok"] is False
    assert result["message"] == "pip install failed"
    assert "__missing_python_for_bootstrap__" in result["pipError"]


def test_runner_bootstrap_failure_stops_before_runner_cli(monkeypatch, tmp_path: Path) -> None:
    async def fail_if_runner_starts(*args, **kwargs):  # pragma: no cover - failure path assertion
        raise AssertionError("runner.cli subprocess should not start when bootstrap fails")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fail_if_runner_starts)

    engine = create_engine(f"sqlite:///{tmp_path / 'studio.db'}")
    SQLModel.metadata.create_all(engine)
    generated = tmp_path / "generated"
    generated.mkdir()
    project = Project(
        id="proj_bootstrap",
        name="Bootstrap Project",
        root_path=str(tmp_path),
        generated_project_path=str(generated),
    )
    request = ExecutionRequest(
        env="stg",
        browser="chromium",
        headed=False,
        target_type="case",
        automation_key="case_bootstrap",
        result_target="local",
    )

    with Session(engine) as session:
        session.add(project)
        session.commit()
        execution = asyncio.run(run_project(session, project, request, "job_bootstrap"))

        assert execution.status == "failed"
        assert execution.result_path is not None
        result_path = Path(execution.result_path)
        assert result_path.exists()
        data = json.loads(result_path.read_text(encoding="utf-8"))
        assert data["bootstrap"]["ok"] is False
        assert data["bootstrap"]["message"] == "requirements.txt missing"
        assert data["cases"][0]["automationKey"] == "case_bootstrap"

        results = session.exec(select(ExecutionResult).where(ExecutionResult.execution_run_id == execution.id)).all()
        assert len(results) == 1
        assert results[0].automation_key == "case_bootstrap"
        assert results[0].status == "failed"
        assert results[0].error == "requirements.txt missing"


def test_runner_bootstrap_failure_redacts_secret_values(monkeypatch, tmp_path: Path) -> None:
    secret = "value-visible-only-via-env-123456789"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    monkeypatch.setattr(
        "worker.services.project_runner.ensure_generated_runtime",
        lambda *args, **kwargs: {
            "ok": False,
            "message": f"pip failed with {secret}",
            "checks": {"requirements": True},
            "pip": f"install stdout {secret}",
            "pipError": f"install stderr {secret}",
        },
    )

    async def fail_if_runner_starts(*args, **kwargs):  # pragma: no cover - failure path assertion
        raise AssertionError("runner.cli subprocess should not start when bootstrap fails")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fail_if_runner_starts)

    engine = create_engine(f"sqlite:///{tmp_path / 'studio.db'}")
    SQLModel.metadata.create_all(engine)
    generated = tmp_path / "generated"
    generated.mkdir()
    project = Project(
        id="proj_bootstrap_secret",
        name="Bootstrap Secret Project",
        root_path=str(tmp_path),
        generated_project_path=str(generated),
    )
    request = ExecutionRequest(
        env="stg",
        browser="chromium",
        headed=False,
        target_type="case",
        automation_key="case_bootstrap_secret",
        result_target="local",
    )

    with Session(engine) as session:
        session.add(project)
        session.commit()
        execution = asyncio.run(run_project(session, project, request, "job_bootstrap_secret"))

        run_dir = Path(execution.result_path).parent
        stdout_text = (run_dir / "stdout.log").read_text(encoding="utf-8")
        stderr_text = (run_dir / "stderr.log").read_text(encoding="utf-8")
        results_text = Path(execution.result_path).read_text(encoding="utf-8")

        assert secret not in stdout_text
        assert secret not in stderr_text
        assert secret not in results_text
        assert "***MASKED***" in stdout_text
        assert "***MASKED***" in stderr_text
        assert "***MASKED***" in results_text
