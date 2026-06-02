"""E-03: Automation IDE structure - editable mappings, normalized flow, and POM plan."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient


def _wait_for_run(client: TestClient, project_id: str, case_id: str, timeout_s: float = 5.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        runs = client.get(f"/projects/{project_id}/webwright-runs").json()
        for run in runs:
            if run.get("test_case_id") == case_id and run.get("status") in {"completed", "failed", "cancelled"}:
                return run
        time.sleep(0.05)
    pytest.fail("Timed out waiting for Webwright run to finish")


def test_automation_ide_structure_workflow(client: TestClient, project_id: str, imported_case: dict) -> None:
    case_id = imported_case["id"]

    queued = client.post(f"/projects/{project_id}/webwright-runs", json={"caseIds": [case_id]})
    assert queued.status_code == 200
    run = _wait_for_run(client, project_id, case_id)
    assert run["status"] == "completed"

    case_detail = client.get(f"/projects/{project_id}/cases/{case_id}").json()
    assert case_detail["automation_key"] == imported_case["automation_key"]
    assert len(case_detail["steps"]) >= 1

    actions_response = client.get(f"/projects/{project_id}/cases/{case_id}/actions")
    assert actions_response.status_code == 200
    actions = actions_response.json()
    assert actions

    mappings_response = client.get(f"/projects/{project_id}/cases/{case_id}/mappings")
    assert mappings_response.status_code == 200
    mappings = mappings_response.json()
    assert mappings
    assert mappings[0]["action_ids"]
    assert mappings[0]["normalized_step_name"]
    assert mappings[0]["pom_method_name"]

    edited_mappings = []
    for index, mapping in enumerate(mappings, start=1):
        edited_mappings.append({
            **mapping,
            "normalized_step_id": mapping.get("normalized_step_id") or f"flow_{index:03d}",
            "normalized_step_name": f"reviewed_step_{index}",
            "pom_method_name": f"perform_reviewed_step_{index}",
            "status": "mapped",
        })

    edited_actions = [
        {
            **actions[0],
            "target": "Automation IDE reviewed target",
            "selector": actions[0].get("selector") or "[data-testid='reviewed']",
        }
    ]

    save_response = client.put(
        f"/projects/{project_id}/cases/{case_id}/mappings",
        json={"mappings": edited_mappings, "actions": edited_actions},
    )
    assert save_response.status_code == 200
    saved = save_response.json()
    assert saved[0]["normalized_step_name"] == "reviewed_step_1"
    assert saved[0]["pom_method_name"] == "perform_reviewed_step_1"

    reloaded_mappings = client.get(f"/projects/{project_id}/cases/{case_id}/mappings").json()
    assert [item["normalized_step_name"] for item in reloaded_mappings] == [
        item["normalized_step_name"] for item in edited_mappings
    ]
    assert [item["pom_method_name"] for item in reloaded_mappings] == [
        item["pom_method_name"] for item in edited_mappings
    ]
    assert all(item["status"] == "mapped" for item in reloaded_mappings)

    reloaded_actions = client.get(f"/projects/{project_id}/cases/{case_id}/actions").json()
    assert reloaded_actions[0]["target"] == "Automation IDE reviewed target"

    updated_case = client.get(f"/projects/{project_id}/cases/{case_id}").json()
    assert updated_case["status"] == "mapped"
