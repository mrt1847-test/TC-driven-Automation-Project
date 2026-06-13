from __future__ import annotations

from sqlmodel import Session

from worker.models.db import CasePromptOverride, ProjectPromptContext, PromptPreset, TestCase as DbTestCase


def _insert_case(project_id: str, case_id: str, automation_key: str) -> None:
    import worker.core.database as database

    with Session(database.engine) as session:
        session.add(
            DbTestCase(
                id=case_id,
                project_id=project_id,
                source_type="excel",
                source_case_id=case_id.upper(),
                title=f"Case {case_id}",
                steps_json='[{"index": 1, "action": "Open the page", "expected": "Page loads"}]',
                automation_key=automation_key,
                start_url="https://example.com",
            )
        )
        session.commit()


def test_prompt_composer_round_trips_batch_and_case_overrides(client, project_id: str) -> None:
    import worker.core.database as database

    _insert_case(project_id, "tc_prompt", "prompt_case")

    default_response = client.get(f"/projects/{project_id}/prompt-composer")
    assert default_response.status_code == 200
    assert default_response.json()["batchPrompt"] == ""
    assert default_response.json()["selectedPresetId"] is None
    assert default_response.json()["caseOverrides"] == {}

    payload = {
        "batchPrompt": "Use the signed-in admin workspace.",
        "selectedPresetId": "preset_builtin_login",
        "caseOverrides": {
            "tc_prompt": " Prefer the accessible search field. ",
        },
    }
    save_response = client.put(f"/projects/{project_id}/prompt-composer", json=payload)
    assert save_response.status_code == 200
    saved = save_response.json()
    assert saved["projectId"] == project_id
    assert saved["batchPrompt"] == payload["batchPrompt"]
    assert saved["selectedPresetId"] == payload["selectedPresetId"]
    assert saved["caseOverrides"] == payload["caseOverrides"]
    assert saved["overrides"] == [
        {
            "caseId": "tc_prompt",
            "automationKey": "prompt_case",
            "promptOverride": " Prefer the accessible search field. ",
            "updatedAt": saved["overrides"][0]["updatedAt"],
        }
    ]

    read_response = client.get(f"/projects/{project_id}/prompt-composer")
    assert read_response.status_code == 200
    assert read_response.json()["batchPrompt"] == payload["batchPrompt"]
    assert read_response.json()["selectedPresetId"] == payload["selectedPresetId"]
    assert read_response.json()["caseOverrides"] == payload["caseOverrides"]

    with Session(database.engine) as session:
        context = session.get(ProjectPromptContext, project_id)
        override = session.get(CasePromptOverride, (project_id, "tc_prompt"))
        assert context is not None
        assert context.batch_prompt == payload["batchPrompt"]
        assert context.selected_preset_id == payload["selectedPresetId"]
        assert context.created_at is not None
        assert context.updated_at is not None
        assert override is not None
        assert override.automation_key == "prompt_case"
        assert override.prompt_override == payload["caseOverrides"]["tc_prompt"]
        assert override.created_at is not None
        assert override.updated_at is not None


def test_prompt_composer_rejects_case_overrides_outside_project(client, project_id: str) -> None:
    import worker.core.database as database

    _insert_case(project_id, "tc_project_a", "project_a_case")
    other_project_response = client.post("/projects", json={"name": "Other"})
    assert other_project_response.status_code == 200
    other_project_id = other_project_response.json()["id"]
    _insert_case(other_project_id, "tc_project_b", "project_b_case")

    response = client.put(
        f"/projects/{project_id}/prompt-composer",
        json={
            "batchPrompt": "Shared prompt should not be partially saved.",
            "caseOverrides": {
                "tc_project_b": "This belongs to the other project.",
            },
        },
    )

    assert response.status_code == 400
    assert "outside this project" in response.json()["detail"]

    with Session(database.engine) as session:
        assert session.get(ProjectPromptContext, project_id) is None
        assert session.get(CasePromptOverride, (project_id, "tc_project_b")) is None


def test_prompt_composer_rejects_foreign_selected_preset(client, project_id: str) -> None:
    import worker.core.database as database

    other_project_response = client.post("/projects", json={"name": "Other"})
    assert other_project_response.status_code == 200
    other_project_id = other_project_response.json()["id"]
    with Session(database.engine) as session:
        session.add(
            PromptPreset(
                id="preset_project_foreign",
                project_id=other_project_id,
                category="login",
                name="Foreign preset",
                guidance="Foreign project guidance.",
                is_builtin=False,
            )
        )
        session.commit()

    response = client.put(
        f"/projects/{project_id}/prompt-composer",
        json={
            "batchPrompt": "Shared prompt should not be partially saved.",
            "selectedPresetId": "preset_project_foreign",
            "caseOverrides": {},
        },
    )

    assert response.status_code == 400
    assert "does not belong to project" in response.json()["detail"]
    with Session(database.engine) as session:
        assert session.get(ProjectPromptContext, project_id) is None


def test_prompt_composer_removes_blank_or_missing_case_overrides(client, project_id: str) -> None:
    import worker.core.database as database

    _insert_case(project_id, "tc_prompt", "prompt_case")
    response = client.put(
        f"/projects/{project_id}/prompt-composer",
        json={
            "batchPrompt": "Shared instructions",
            "caseOverrides": {
                "tc_prompt": "Use the billing tab.",
            },
        },
    )
    assert response.status_code == 200

    response = client.put(
        f"/projects/{project_id}/prompt-composer",
        json={
            "batchPrompt": "Shared instructions v2",
            "caseOverrides": {
                "tc_prompt": "   ",
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["batchPrompt"] == "Shared instructions v2"
    assert response.json()["caseOverrides"] == {}
    assert response.json()["overrides"] == []

    with Session(database.engine) as session:
        assert session.get(ProjectPromptContext, project_id) is not None
        assert session.get(CasePromptOverride, (project_id, "tc_prompt")) is None
