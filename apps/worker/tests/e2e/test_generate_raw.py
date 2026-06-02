"""E-02: Generate Raw workspace — TC selection, Webwright run, actions, artifacts, logs."""
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


def test_generate_raw_workflow(client: TestClient, project_id: str, imported_case: dict) -> None:
    case_id = imported_case["id"]
    automation_key = imported_case["automation_key"]

    queued = client.post(
        f"/projects/{project_id}/webwright-runs",
        json={"caseIds": [case_id]},
    )
    assert queued.status_code == 200
    queue_body = queued.json()
    job_id = queue_body["jobId"]
    assert queue_body["status"] == "queued"
    assert case_id in queue_body["caseIds"]

    run = _wait_for_run(client, project_id, case_id)
    assert run["status"] == "completed"
    assert run["automation_key"] == automation_key
    assert run.get("final_script_path")
    assert run.get("output_path")
    assert run.get("trajectory_path")

    run_detail = client.get(f"/projects/{project_id}/webwright-runs/{run['id']}")
    assert run_detail.status_code == 200

    case_detail = client.get(f"/projects/{project_id}/cases/{case_id}").json()
    assert case_detail["status"] in {"webwright_completed", "needs_review", "mapped"}
    assert case_detail["automation_key"] == automation_key

    actions = client.get(f"/projects/{project_id}/cases/{case_id}/actions").json()
    assert len(actions) >= 1
    assert actions[0].get("type")

    mappings = client.get(f"/projects/{project_id}/cases/{case_id}/mappings").json()
    assert len(mappings) >= 1

    with client.websocket_connect(f"/ws/logs/{job_id}") as websocket:
        message = websocket.receive_text()
        assert automation_key in message or "mock" in message.lower() or "webwright" in message.lower()


def test_webwright_retry_handoff(client: TestClient, project_id: str, imported_case: dict) -> None:
    case_id = imported_case["id"]

    client.post(f"/projects/{project_id}/webwright-runs", json={"caseIds": [case_id]}).raise_for_status()
    first_run = _wait_for_run(client, project_id, case_id)
    assert first_run["status"] == "completed"

    retry = client.post(f"/projects/{project_id}/webwright-runs/{first_run['id']}/retry")
    assert retry.status_code == 200
    assert retry.json()["status"] == "queued"

    runs = client.get(f"/projects/{project_id}/webwright-runs").json()
    assert len([run for run in runs if run.get("test_case_id") == case_id]) >= 1
