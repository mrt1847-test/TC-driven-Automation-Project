"""E-10: generated pytest/browser contract through the Worker runner path."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

from sqlmodel import SQLModel, Session, create_engine, select

from worker.models.db import ExecutionResult, Project
from worker.models.schemas import ExecutionRequest
from worker.services.project_runner import run_project


ROOT = Path(__file__).resolve().parents[4]
TEMPLATE = ROOT / "packages" / "generated-template"


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _prepare_generated_project(tmp_path: Path) -> Path:
    generated = tmp_path / "generated-browser-contract"
    shutil.copytree(
        TEMPLATE,
        generated,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "artifacts"),
    )
    _write_text(
        generated / "config" / "env.stg.json",
        """
{
  "name": "stg",
  "baseUrl": "https://contract.example",
  "viewport": {
    "width": 1024,
    "height": 768
  }
}
""".lstrip(),
    )
    _write_text(
        generated / "mappings" / "cases.yaml",
        """
cases:
  - automationKey: browser_contract
    sourceType: excel
    sourceCaseId: TC-BROWSER
    title: Browser fixture contract
    testFile: tests/test_browser_contract.py
    testFunction: test_browser_contract
    tags:
      - e10
""".lstrip(),
    )
    _write_text(
        generated / "tests" / "test_browser_contract.py",
        """
import os


def test_browser_contract(page, context, base_url, artifact_dir, tc_env_name, env_config):
    assert tc_env_name == "stg"
    assert base_url == "https://contract.example"
    assert env_config["viewport"]["width"] == 1024
    assert artifact_dir.exists()
    assert artifact_dir.name == os.environ["TC_RUN_ID"]
    assert page.context == context

    page.set_content("<main><h1>Generated browser contract</h1></main>")
    assert page.locator("h1").inner_text() == "Generated browser contract"
""".lstrip(),
    )
    return generated


def test_generated_project_browser_contract_runs_through_worker(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TC_STUDIO_DATA_DIR", str(tmp_path / ".data"))
    monkeypatch.setenv("TC_STUDIO_PYTHON", sys.executable)
    monkeypatch.setenv("TC_SCREENSHOT", "all")
    monkeypatch.setenv("TC_TRACE", "all")
    monkeypatch.setenv("TC_VIDEO", "off")

    engine = create_engine(f"sqlite:///{tmp_path / 'studio.db'}")
    SQLModel.metadata.create_all(engine)
    generated = _prepare_generated_project(tmp_path)
    project = Project(
        id="proj_e10",
        name="E10 Browser Contract",
        root_path=str(tmp_path),
        generated_project_path=str(generated),
    )
    request = ExecutionRequest(
        env="stg",
        browser="chromium",
        headed=False,
        target_type="case",
        automation_key="browser_contract",
        result_target="local",
    )

    with Session(engine) as session:
        session.add(project)
        session.commit()
        execution = asyncio.run(run_project(session, project, request, "job_e10"))

        assert execution.status == "completed"
        assert execution.result_path is not None
        result_path = Path(execution.result_path)
        assert result_path.exists()
        assert result_path.parent.name == execution.run_id

        payload = json.loads(result_path.read_text(encoding="utf-8"))
        assert payload["env"] == "stg"
        assert payload["browser"] == "chromium"
        assert payload["summary"] == {"total": 1, "passed": 1, "failed": 0, "skipped": 0}
        assert payload["pytest"]["returnCode"] == 0
        assert payload["pytest"]["stdoutPath"] == f"artifacts/runs/{execution.run_id}/stdout.log"
        assert payload["pytest"]["stderrPath"] == f"artifacts/runs/{execution.run_id}/stderr.log"
        assert (generated / payload["pytest"]["stdoutPath"]).exists()
        assert (generated / payload["pytest"]["stderrPath"]).exists()
        assert payload["pytest"]["command"][1:3] == ["-m", "pytest"]
        assert "--browser=chromium" in payload["pytest"]["command"]
        assert "1 passed" in (generated / payload["pytest"]["stdoutPath"]).read_text(encoding="utf-8")
        assert "Results written to" in (
            generated / "artifacts" / "runs" / execution.run_id / "worker_stdout.log"
        ).read_text(encoding="utf-8")

        case = payload["cases"][0]
        assert case["automationKey"] == "browser_contract"
        assert case["status"] == "passed"
        assert case["artifacts"]["screenshot"] == (
            f"artifacts/runs/{execution.run_id}/tests_test_browser_contract.py__test_browser_contract[chromium].png"
        )
        assert case["artifacts"]["trace"] == (
            f"artifacts/runs/{execution.run_id}/tests_test_browser_contract.py__test_browser_contract[chromium].zip"
        )
        assert case["artifacts"]["video"] is None
        assert (generated / case["artifacts"]["screenshot"]).exists()
        assert (generated / case["artifacts"]["trace"]).exists()

        rows = session.exec(select(ExecutionResult).where(ExecutionResult.execution_run_id == execution.id)).all()
        assert len(rows) == 1
        assert rows[0].automation_key == "browser_contract"
        assert rows[0].status == "passed"
        assert rows[0].screenshot_path == case["artifacts"]["screenshot"]
        assert rows[0].trace_path == case["artifacts"]["trace"]
