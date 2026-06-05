from __future__ import annotations

import asyncio
from pathlib import Path

from sqlmodel import SQLModel, Session, create_engine, select

from worker.models.db import (
    CasePromptOverride,
    Project,
    ProjectPromptContext,
    PromptPreset,
    TestCase as DbTestCase,
    WebwrightPromptPayload,
    WebwrightRun,
    WebwrightRunStatus,
)
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
    pid = 4321

    def __init__(self) -> None:
        self.returncode: int | None = None
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
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
    session.add(
        Project(
            id="proj_test",
            name="Prompt Payload Project",
            root_path=str(tmp_path / "project"),
            generated_project_path=str(tmp_path / "project" / "generated"),
        )
    )
    case = DbTestCase(
        id="tc_test",
        project_id="proj_test",
        source_type="excel",
        source_case_id="CASE-1",
        title="Prompt payload case",
        preconditions_json='["User is signed in"]',
        steps_json='[{"index": 1, "action": "Open billing", "expected": "Billing loads"}]',
        expected_result="Billing loads",
        automation_key="payload_case",
        start_url="https://example.test/case",
    )
    session.add(case)
    session.commit()
    session.refresh(case)
    return session, case


def _patch_successful_webwright(monkeypatch, tmp_path: Path, captured_prompt: list[str]) -> None:
    profile = _Profile(tmp_path, tmp_path / "runs")

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured_prompt.append(args[args.index("-t") + 1])
        output_root = Path(args[args.index("-o") + 1])
        (output_root / "final_script.py").write_text("print('ok')\n", encoding="utf-8")
        return _FakeProcess()

    async def capture_publish(_job_id: str, _message: str) -> None:
        return None

    monkeypatch.setattr(webwright_adapter, "resolve_runtime", lambda: profile)
    monkeypatch.setattr(webwright_adapter.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(webwright_adapter.log_streams, "publish", capture_publish)
    monkeypatch.setattr(webwright_adapter, "index_webwright_run_artifacts", lambda *_args: None)


def test_webwright_run_records_prompt_payload_with_selected_context(monkeypatch, tmp_path: Path) -> None:
    session, case = _session_with_case(tmp_path)
    session.add(PromptPreset(
        id="preset_project_payload",
        project_id="proj_test",
        category="billing",
        name="Billing flow",
        guidance="Assert invoice totals before leaving the page.",
    ))
    session.add(ProjectPromptContext(
        project_id="proj_test",
        batch_prompt="Use the signed-in admin workspace.",
    ))
    session.add(CasePromptOverride(
        project_id="proj_test",
        case_id="tc_test",
        automation_key="payload_case",
        prompt_override="Open the billing tab first.",
    ))
    session.commit()
    captured_prompt: list[str] = []
    _patch_successful_webwright(monkeypatch, tmp_path, captured_prompt)

    run = asyncio.run(webwright_adapter.run_webwright_for_case(
        session,
        "proj_test",
        case,
        "request_model.yaml",
        "job_test",
        preset_id="preset_project_payload",
        environment="qa",
        start_url_override="https://example.test/override",
    ))

    rows = session.exec(select(WebwrightPromptPayload)).all()
    assert run.status == WebwrightRunStatus.completed.value
    assert len(rows) == 1
    payload = rows[0]
    assert payload.project_id == "proj_test"
    assert payload.test_case_id == "tc_test"
    assert payload.webwright_run_id == run.id
    assert payload.automation_key == "payload_case"
    assert payload.final_prompt == captured_prompt[0]
    assert payload.preset_id == "preset_project_payload"
    assert payload.preset_category == "billing"
    assert payload.preset_name == "Billing flow"
    assert payload.preset_guidance == "Assert invoice totals before leaving the page."
    assert payload.batch_prompt == "Use the signed-in admin workspace."
    assert payload.case_prompt_override == "Open the billing tab first."
    assert payload.environment == "qa"
    assert payload.start_url == "https://example.test/override"
    assert payload.webwright_model_config == "model_openai.yaml"
    assert "Start URL:\nhttps://example.test/override" in payload.final_prompt
    assert payload.final_prompt.index("Prompt Preset Guidance:") < payload.final_prompt.index("Batch Shared Prompt:")
    assert payload.final_prompt.index("Batch Shared Prompt:") < payload.final_prompt.index("Per-Case Prompt Override:")
    session.close()


def test_no_context_webwright_run_records_empty_prompt_payload(monkeypatch, tmp_path: Path) -> None:
    session, case = _session_with_case(tmp_path)
    captured_prompt: list[str] = []
    _patch_successful_webwright(monkeypatch, tmp_path, captured_prompt)

    run = asyncio.run(webwright_adapter.run_webwright_for_case(
        session,
        "proj_test",
        case,
        "request_model.yaml",
        "job_test",
    ))

    payload = session.exec(
        select(WebwrightPromptPayload).where(WebwrightPromptPayload.webwright_run_id == run.id)
    ).one()
    assert payload.final_prompt == captured_prompt[0]
    assert payload.final_prompt == payload.base_prompt
    assert payload.preset_id is None
    assert payload.preset_guidance == ""
    assert payload.batch_prompt == ""
    assert payload.case_prompt_override == ""
    assert payload.environment == "stg"
    assert payload.start_url == "https://example.test/case"
    assert "Additional Prompt Context" not in payload.final_prompt
    session.close()


def test_each_retry_or_new_run_gets_its_own_prompt_payload(monkeypatch, tmp_path: Path) -> None:
    session, case = _session_with_case(tmp_path)
    captured_prompt: list[str] = []
    _patch_successful_webwright(monkeypatch, tmp_path, captured_prompt)

    first = asyncio.run(webwright_adapter.run_webwright_for_case(
        session,
        "proj_test",
        case,
        "model_openai.yaml",
        "job_first",
    ))
    second = asyncio.run(webwright_adapter.run_webwright_for_case(
        session,
        "proj_test",
        case,
        "model_openai.yaml",
        "job_second",
    ))

    rows = session.exec(
        select(WebwrightPromptPayload).where(WebwrightPromptPayload.test_case_id == "tc_test")
    ).all()
    assert len(rows) == 2
    assert {row.webwright_run_id for row in rows} == {first.id, second.id}
    assert len(captured_prompt) == 2
    session.close()


def _insert_api_payload(project_id: str, case_id: str, run_id: str, payload_id: str) -> None:
    import worker.core.database as database

    with Session(database.engine) as session:
        session.add(DbTestCase(
            id=case_id,
            project_id=project_id,
            source_type="excel",
            source_case_id=case_id.upper(),
            title=f"Case {case_id}",
            steps_json="[]",
            automation_key=f"{case_id}_key",
        ))
        session.add(WebwrightRun(
            id=run_id,
            project_id=project_id,
            test_case_id=case_id,
            automation_key=f"{case_id}_key",
            status=WebwrightRunStatus.completed.value,
        ))
        session.add(WebwrightPromptPayload(
            id=payload_id,
            project_id=project_id,
            test_case_id=case_id,
            webwright_run_id=run_id,
            automation_key=f"{case_id}_key",
            final_prompt=f"final prompt for {case_id}",
            base_prompt=f"base prompt for {case_id}",
            environment="stg",
            start_url="https://example.test",
            webwright_model_config="model_openai.yaml",
        ))
        session.commit()


def test_prompt_payload_api_lists_reads_and_filters_project_history(client, project_id: str) -> None:
    _insert_api_payload(project_id, "tc_payload_a", "ww_payload_a", "prompt_payload_a")
    other_project_id = client.post("/projects", json={"name": "Other"}).json()["id"]
    _insert_api_payload(other_project_id, "tc_payload_b", "ww_payload_b", "prompt_payload_b")

    all_response = client.get(f"/projects/{project_id}/prompt-payloads")
    by_case = client.get(f"/projects/{project_id}/prompt-payloads?caseId=tc_payload_a")
    by_run = client.get(f"/projects/{project_id}/prompt-payloads?runId=ww_payload_a")
    foreign_run = client.get(f"/projects/{project_id}/prompt-payloads?runId=ww_payload_b")
    detail = client.get(f"/projects/{project_id}/prompt-payloads/prompt_payload_a")
    foreign_detail = client.get(f"/projects/{project_id}/prompt-payloads/prompt_payload_b")

    assert all_response.status_code == 200
    assert [row["id"] for row in all_response.json()["payloads"]] == ["prompt_payload_a"]
    assert by_case.status_code == 200
    assert [row["caseId"] for row in by_case.json()["payloads"]] == ["tc_payload_a"]
    assert by_run.status_code == 200
    assert [row["webwrightRunId"] for row in by_run.json()["payloads"]] == ["ww_payload_a"]
    assert foreign_run.status_code == 200
    assert foreign_run.json()["payloads"] == []
    assert detail.status_code == 200
    assert detail.json()["prompt"] == "final prompt for tc_payload_a"
    assert detail.json()["parts"]["basePrompt"] == "base prompt for tc_payload_a"
    assert foreign_detail.status_code == 404
