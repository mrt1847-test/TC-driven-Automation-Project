from __future__ import annotations

from sqlmodel import Session, select

from worker.models.db import (
    CasePromptOverride,
    ProjectPromptContext,
    PromptPreset,
    RawAction,
    TestCase as DbTestCase,
    WebwrightRun,
)


def _insert_case(
    project_id: str,
    case_id: str,
    automation_key: str,
    *,
    title: str = "Preview case",
) -> None:
    import worker.core.database as database

    with Session(database.engine) as session:
        session.add(
            DbTestCase(
                id=case_id,
                project_id=project_id,
                source_type="excel",
                source_case_id=case_id.upper(),
                title=title,
                preconditions_json='["User is signed in"]',
                steps_json='[{"index": 1, "action": "Open dashboard", "expected": "Dashboard loads"}]',
                expected_result="Dashboard loads",
                automation_key=automation_key,
                start_url="https://example.test/dashboard",
            )
        )
        session.commit()


def _counts() -> dict[str, int]:
    import worker.core.database as database

    with Session(database.engine) as session:
        return {
            "runs": len(session.exec(select(WebwrightRun)).all()),
            "actions": len(session.exec(select(RawAction)).all()),
            "presets": len(session.exec(select(PromptPreset)).all()),
        }


def test_prompt_preview_combines_base_builtin_preset_and_saved_context_without_mutation(
    client,
    project_id: str,
) -> None:
    import worker.core.database as database

    _insert_case(project_id, "tc_preview", "preview_case")
    with Session(database.engine) as session:
        session.add(ProjectPromptContext(
            project_id=project_id,
            batch_prompt="Use the signed-in admin workspace.",
        ))
        session.add(CasePromptOverride(
            project_id=project_id,
            case_id="tc_preview",
            automation_key="preview_case",
            prompt_override="Open the reports tab before assertions.",
        ))
        session.commit()

    before = _counts()
    response = client.post(
        f"/projects/{project_id}/prompt-preview",
        json={
            "caseId": "tc_preview",
            "presetId": "preset_builtin_login",
            "environment": "qa",
            "startUrlOverride": "https://example.test/override",
        },
    )
    after = _counts()

    assert response.status_code == 200
    body = response.json()
    assert body["projectId"] == project_id
    assert body["caseId"] == "tc_preview"
    assert body["automationKey"] == "preview_case"
    assert body["environment"] == "qa"
    assert body["startUrl"] == "https://example.test/override"
    assert body["preset"]["id"] == "preset_builtin_login"
    assert body["preset"]["isBuiltin"] is True
    assert body["parts"]["presetGuidance"] == body["preset"]["guidance"]
    assert body["parts"]["batchPrompt"] == "Use the signed-in admin workspace."
    assert body["parts"]["casePromptOverride"] == "Open the reports tab before assertions."
    assert "Additional Prompt Context" not in body["parts"]["basePrompt"]

    prompt = body["prompt"]
    assert "Start URL:\nhttps://example.test/override" in prompt
    assert "Environment:\nqa" in prompt
    assert prompt.index("Automation Key:\npreview_case") < prompt.index("Prompt Preset Guidance:")
    assert prompt.index("Prompt Preset Guidance:") < prompt.index("Batch Shared Prompt:")
    assert prompt.index("Batch Shared Prompt:") < prompt.index("Per-Case Prompt Override:")
    assert before == after


def test_prompt_preview_includes_selected_project_preset_when_requested(client, project_id: str) -> None:
    _insert_case(project_id, "tc_project_preset", "project_preset_case")
    saved = client.put(
        f"/projects/{project_id}/prompt-presets",
        json={
            "presets": [
                {
                    "id": "preset_project_preview",
                    "category": "checkout",
                    "name": "Checkout preview",
                    "guidance": "Assert cart totals before submitting payment.",
                }
            ]
        },
    )
    assert saved.status_code == 200
    before = _counts()

    response = client.post(
        f"/projects/{project_id}/prompt-preview",
        json={"caseId": "tc_project_preset", "presetId": "preset_project_preview"},
    )
    after = _counts()

    assert response.status_code == 200
    body = response.json()
    assert body["preset"] == {
        "id": "preset_project_preview",
        "projectId": project_id,
        "category": "checkout",
        "name": "Checkout preview",
        "guidance": "Assert cart totals before submitting payment.",
        "isBuiltin": False,
    }
    assert "Prompt Preset Guidance:\nAssert cart totals before submitting payment." in body["prompt"]
    assert before == after


def test_prompt_preview_rejects_foreign_case_and_foreign_preset_without_run_mutation(
    client,
    project_id: str,
) -> None:
    _insert_case(project_id, "tc_project_a", "project_a_case")
    other_project_id = client.post("/projects", json={"name": "Other"}).json()["id"]
    _insert_case(other_project_id, "tc_project_b", "project_b_case")
    preset_response = client.put(
        f"/projects/{other_project_id}/prompt-presets",
        json={
            "presets": [
                {
                    "id": "preset_other_project",
                    "category": "foreign",
                    "name": "Foreign preset",
                    "guidance": "This belongs to another project.",
                }
            ]
        },
    )
    assert preset_response.status_code == 200
    before = _counts()

    foreign_case = client.post(
        f"/projects/{project_id}/prompt-preview",
        json={"caseId": "tc_project_b"},
    )
    foreign_preset = client.post(
        f"/projects/{project_id}/prompt-preview",
        json={"caseId": "tc_project_a", "presetId": "preset_other_project"},
    )
    missing_preset = client.post(
        f"/projects/{project_id}/prompt-preview",
        json={"caseId": "tc_project_a", "presetId": "preset_missing"},
    )
    after = _counts()

    assert foreign_case.status_code == 400
    assert foreign_case.json()["detail"] == "Case not found"
    assert foreign_preset.status_code == 400
    assert "does not belong to project" in foreign_preset.json()["detail"]
    assert missing_preset.status_code == 400
    assert missing_preset.json()["detail"] == "Prompt preset not found: preset_missing"
    assert before == after


def test_prompt_preview_without_preset_matches_existing_no_context_prompt_shape(client, project_id: str) -> None:
    _insert_case(project_id, "tc_plain_preview", "plain_preview")
    before = _counts()

    response = client.post(
        f"/projects/{project_id}/prompt-preview",
        json={"caseId": "tc_plain_preview"},
    )
    after = _counts()

    assert response.status_code == 200
    body = response.json()
    assert body["preset"] is None
    assert body["parts"]["presetGuidance"] == ""
    assert body["parts"]["batchPrompt"] == ""
    assert body["parts"]["casePromptOverride"] == ""
    assert body["prompt"] == body["parts"]["basePrompt"]
    assert "Additional Prompt Context" not in body["prompt"]
    assert before == after
