"""E-07: Reverse handoff rerun - Automation IDE context back to Generate Raw."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient


def _runs_for_case(client: TestClient, project_id: str, case_id: str) -> list[dict]:
    runs = client.get(f"/projects/{project_id}/webwright-runs").json()
    return [run for run in runs if run.get("test_case_id") == case_id]


def _wait_for_run_count(
    client: TestClient,
    project_id: str,
    case_id: str,
    expected_count: int,
    timeout_s: float = 5.0,
) -> list[dict]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        runs = _runs_for_case(client, project_id, case_id)
        terminal = [run for run in runs if run.get("status") in {"completed", "failed", "cancelled"}]
        if len(terminal) >= expected_count:
            return terminal
        time.sleep(0.05)
    pytest.fail(f"Timed out waiting for {expected_count} Webwright run(s)")


def test_reverse_handoff_rerun_workflow(client: TestClient, project_id: str, imported_case: dict) -> None:
    case_id = imported_case["id"]
    automation_key = imported_case["automation_key"]

    first_queue = client.post(f"/projects/{project_id}/webwright-runs", json={"caseIds": [case_id]})
    assert first_queue.status_code == 200
    first_run = _wait_for_run_count(client, project_id, case_id, 1)[0]
    assert first_run["status"] == "completed"

    selected_case_context = client.get(f"/projects/{project_id}/cases/{case_id}").json()
    assert selected_case_context["id"] == case_id
    assert selected_case_context["automation_key"] == automation_key

    initial_actions = client.get(f"/projects/{project_id}/cases/{case_id}/actions").json()
    initial_mappings = client.get(f"/projects/{project_id}/cases/{case_id}/mappings").json()
    assert initial_actions
    assert initial_mappings
    assert initial_mappings[0]["action_ids"]

    gap_payload = {
        "mappings": [
            {
                **mapping,
                "action_ids": [],
                "status": "unmapped",
            }
            for mapping in initial_mappings
        ]
    }
    gap_save = client.put(f"/projects/{project_id}/cases/{case_id}/mappings", json=gap_payload)
    assert gap_save.status_code == 200
    assert client.get(f"/projects/{project_id}/cases/{case_id}").json()["status"] == "needs_review"

    retry = client.post(f"/projects/{project_id}/webwright-runs/{first_run['id']}/retry")
    assert retry.status_code == 200
    retry_body = retry.json()
    assert retry_body["status"] == "queued"
    retry_job_id = retry_body["jobId"]

    runs = _wait_for_run_count(client, project_id, case_id, 2)
    run_ids = {run["id"] for run in runs}
    assert first_run["id"] in run_ids
    assert len(run_ids) >= 2
    latest_run = next(run for run in runs if run["id"] != first_run["id"])
    assert latest_run["automation_key"] == automation_key
    assert latest_run["status"] == "completed"

    refreshed_actions = client.get(f"/projects/{project_id}/cases/{case_id}/actions").json()
    refreshed_mappings = client.get(f"/projects/{project_id}/cases/{case_id}/mappings").json()
    refreshed_case = client.get(f"/projects/{project_id}/cases/{case_id}").json()

    assert refreshed_case["automation_key"] == automation_key
    assert refreshed_case["status"] in {"mapped", "needs_review", "webwright_completed"}
    assert refreshed_actions
    assert refreshed_actions[0]["id"] not in {action["id"] for action in initial_actions}
    assert refreshed_mappings
    assert refreshed_mappings[0]["action_ids"]
    assert refreshed_mappings[0]["status"] == "mapped"

    with client.websocket_connect(f"/ws/logs/{retry_job_id}") as websocket:
        message = websocket.receive_text()
        assert automation_key in message or "mock" in message.lower() or "webwright" in message.lower()
