from __future__ import annotations

from sqlmodel import Session, select

from worker.models.db import PromptPreset, TestCase as DbTestCase
from worker.models.schemas import NormalizedTestCase, TestStep as PromptTestStep
from worker.services.prompt_builder import build_webwright_prompt
from worker.services.prompt_context import effective_prompt_context


def _project_presets(payload: dict) -> list[dict]:
    return [preset for preset in payload["presets"] if not preset["isBuiltin"]]


def test_prompt_presets_seed_builtin_rows_in_deterministic_order(client, project_id: str) -> None:
    import worker.core.database as database

    first = client.get(f"/projects/{project_id}/prompt-presets")
    second = client.get(f"/projects/{project_id}/prompt-presets")

    assert first.status_code == 200
    assert second.status_code == 200
    first_body = first.json()
    second_body = second.json()
    assert first_body["projectId"] == project_id
    assert [preset["id"] for preset in first_body["presets"]] == [
        "preset_builtin_assertion_heavy",
        "preset_builtin_crud",
        "preset_builtin_general",
        "preset_builtin_login",
        "preset_builtin_search",
    ]
    assert [preset["id"] for preset in second_body["presets"]] == [
        preset["id"] for preset in first_body["presets"]
    ]
    assert all(preset["isBuiltin"] for preset in first_body["presets"])
    assert all(preset["createdAt"] and preset["updatedAt"] for preset in first_body["presets"])

    with Session(database.engine) as session:
        rows = session.exec(
            select(PromptPreset)
            .where(PromptPreset.is_builtin == True)  # noqa: E712
            .order_by(PromptPreset.category)
        ).all()
        assert [row.id for row in rows] == [preset["id"] for preset in first_body["presets"]]
        assert {row.project_id for row in rows} == {None}


def test_project_prompt_presets_round_trip_and_replace_project_rows(client, project_id: str) -> None:
    import worker.core.database as database

    payload = {
        "presets": [
            {
                "id": "preset_project_checkout",
                "category": "checkout",
                "name": "Checkout flow",
                "guidance": "Use deterministic cart data and assert order totals.",
            },
            {
                "id": "preset_project_dashboard",
                "category": "dashboard",
                "name": "Dashboard verification",
                "guidance": "Wait for analytics cards and assert visible metric labels.",
            },
        ]
    }
    saved = client.put(f"/projects/{project_id}/prompt-presets", json=payload)
    assert saved.status_code == 200
    project_rows = _project_presets(saved.json())
    assert [row["id"] for row in project_rows] == [
        "preset_project_checkout",
        "preset_project_dashboard",
    ]
    assert project_rows[0]["projectId"] == project_id
    assert project_rows[0]["category"] == "checkout"
    assert project_rows[0]["name"] == "Checkout flow"
    assert project_rows[0]["guidance"] == "Use deterministic cart data and assert order totals."
    assert project_rows[0]["createdAt"] and project_rows[0]["updatedAt"]

    replaced = client.put(
        f"/projects/{project_id}/prompt-presets",
        json={
            "presets": [
                {
                    "id": "preset_project_checkout",
                    "category": "checkout",
                    "name": "Checkout flow v2",
                    "guidance": "Assert totals, confirmation, and cleanup affordances.",
                }
            ]
        },
    )
    assert replaced.status_code == 200
    project_rows = _project_presets(replaced.json())
    assert [row["id"] for row in project_rows] == ["preset_project_checkout"]
    assert project_rows[0]["name"] == "Checkout flow v2"

    with Session(database.engine) as session:
        assert session.get(PromptPreset, "preset_project_dashboard") is None
        checkout = session.get(PromptPreset, "preset_project_checkout")
        assert checkout is not None
        assert checkout.project_id == project_id
        assert checkout.is_builtin is False
        assert checkout.guidance == "Assert totals, confirmation, and cleanup affordances."


def test_project_prompt_presets_are_project_isolated(client, project_id: str) -> None:
    first = client.put(
        f"/projects/{project_id}/prompt-presets",
        json={
            "presets": [
                {
                    "id": "preset_project_private",
                    "category": "private",
                    "name": "Private project preset",
                    "guidance": "Only project A should see this guidance.",
                }
            ]
        },
    )
    assert first.status_code == 200
    other_project = client.post("/projects", json={"name": "Other Project"}).json()["id"]

    other = client.get(f"/projects/{other_project}/prompt-presets")
    assert other.status_code == 200
    assert "preset_project_private" not in [preset["id"] for preset in other.json()["presets"]]

    collision = client.put(
        f"/projects/{other_project}/prompt-presets",
        json={
            "presets": [
                {
                    "id": "preset_project_private",
                    "category": "private",
                    "name": "Collision",
                    "guidance": "This should be rejected.",
                }
            ]
        },
    )
    assert collision.status_code == 400
    assert "does not belong to project" in collision.json()["detail"]


def test_prompt_presets_do_not_affect_existing_effective_prompt_context(client, project_id: str) -> None:
    import worker.core.database as database

    response = client.put(
        f"/projects/{project_id}/prompt-presets",
        json={
            "presets": [
                {
                    "id": "preset_project_no_impact",
                    "category": "login",
                    "name": "No impact login preset",
                    "guidance": "This preset guidance should not be applied yet.",
                }
            ]
        },
    )
    assert response.status_code == 200

    case = DbTestCase(
        id="tc_no_impact",
        project_id=project_id,
        source_type="excel",
        source_case_id="TC-NO-IMPACT",
        title="No impact prompt case",
        steps_json="[]",
        automation_key="no_impact",
    )
    with Session(database.engine) as session:
        session.add(case)
        session.commit()
        saved_case = session.get(DbTestCase, "tc_no_impact")
        assert effective_prompt_context(session, project_id, saved_case) == {
            "batchPrompt": "",
            "casePromptOverride": "",
        }

    prompt = build_webwright_prompt(
        NormalizedTestCase(
            source_type="excel",
            source_id="TC-NO-IMPACT",
            title="No impact prompt case",
            steps=[PromptTestStep(index=1, action="Open the login page")],
            expected_result="Login page is visible",
            automation_key="no_impact",
        )
    )
    assert "Additional Prompt Context" not in prompt
    assert "This preset guidance should not be applied yet" not in prompt
