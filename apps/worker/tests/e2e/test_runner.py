"""E-05: Automation IDE runner - generated project execution, logs, and results."""
from __future__ import annotations

from pathlib import Path
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


def _wait_for_execution(client: TestClient, project_id: str, timeout_s: float = 5.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        executions = client.get(f"/projects/{project_id}/executions").json()
        for execution in executions:
            if execution.get("status") in {"completed", "failed", "cancelled"}:
                return execution
        time.sleep(0.05)
    pytest.fail("Timed out waiting for execution to finish")


def _prepare_generated_project(client: TestClient, project_id: str, case_id: str) -> str:
    queued = client.post(f"/projects/{project_id}/webwright-runs", json={"caseIds": [case_id]})
    assert queued.status_code == 200
    run = _wait_for_run(client, project_id, case_id)
    assert run["status"] == "completed"

    mappings = client.get(f"/projects/{project_id}/cases/{case_id}/mappings").json()
    reviewed = []
    for index, mapping in enumerate(mappings, start=1):
        reviewed.append({
            **mapping,
            "normalized_step_id": mapping.get("normalized_step_id") or f"flow_{index:03d}",
            "normalized_step_name": f"runner_step_{index}",
            "pom_method_name": f"perform_runner_step_{index}",
            "status": "mapped",
        })
    save = client.put(f"/projects/{project_id}/cases/{case_id}/mappings", json={"mappings": reviewed})
    assert save.status_code == 200

    generated = client.post(f"/projects/{project_id}/generate", json={"caseIds": [case_id]})
    assert generated.status_code == 200
    generated_path = generated.json()["generatedProjectPath"]
    assert Path(generated_path).exists()
    return generated_path


def test_automation_ide_runner_workflow(client: TestClient, project_id: str, imported_case: dict) -> None:
    case_id = imported_case["id"]
    automation_key = imported_case["automation_key"]
    generated_path = _prepare_generated_project(client, project_id, case_id)

    queued = client.post(
        f"/projects/{project_id}/executions",
        json={
            "env": "stg",
            "browser": "chromium",
            "headed": False,
            "target_type": "case",
            "automation_key": automation_key,
            "result_target": "local",
        },
    )
    assert queued.status_code == 200
    queue_body = queued.json()
    assert queue_body["status"] == "queued"
    job_id = queue_body["jobId"]

    execution = _wait_for_execution(client, project_id)
    assert execution["env"] == "stg"
    assert execution["browser"] == "chromium"
    assert execution["headed"] is False
    assert execution["status"] in {"completed", "failed"}
    assert execution["result_path"]
    assert Path(execution["result_path"]).exists()
    assert str(execution["result_path"]).startswith(str(Path(generated_path)))

    detail_response = client.get(f"/projects/{project_id}/executions/{execution['id']}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["run"]["id"] == execution["id"]
    assert detail["summary"]["runId"] == execution["run_id"]
    assert detail["summary"]["env"] == "stg"
    assert detail["summary"]["browser"] == "chromium"
    assert detail["summary"]["summary"]["total"] >= 1

    results = detail["results"]
    assert len(results) >= 1
    assert results[0]["automation_key"] == automation_key
    assert results[0]["status"] in {"passed", "failed"}

    with client.websocket_connect(f"/ws/logs/{job_id}?token=test-worker-token") as websocket:
        first_log = websocket.receive_text()
        assert "runner.cli" in first_log
        second_log = websocket.receive_text()
        assert "Results written to" in second_log or "pytest" in second_log or automation_key in second_log
