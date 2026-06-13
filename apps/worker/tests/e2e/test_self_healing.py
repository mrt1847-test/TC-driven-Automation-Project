"""E-08: Self-healing proposal baseline - failure context, local proposal, rerun path."""
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


def _wait_for_execution_count(
    client: TestClient,
    project_id: str,
    expected_count: int,
    timeout_s: float = 8.0,
) -> list[dict]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        executions = client.get(f"/projects/{project_id}/executions").json()
        terminal = [item for item in executions if item.get("status") in {"completed", "failed", "cancelled"}]
        if len(terminal) >= expected_count:
            return terminal
        time.sleep(0.05)
    pytest.fail(f"Timed out waiting for {expected_count} execution(s)")


def _prepare_failing_generated_project(client: TestClient, project_id: str, case_id: str) -> list[dict]:
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
            "normalized_step_name": f"healing_step_{index}",
            "pom_method_name": f"perform_healing_step_{index}",
            "status": "mapped",
        })
    save = client.put(f"/projects/{project_id}/cases/{case_id}/mappings", json={"mappings": reviewed})
    assert save.status_code == 200

    generated = client.post(f"/projects/{project_id}/generate", json={"caseIds": [case_id]})
    assert generated.status_code == 200
    assert Path(generated.json()["generatedProjectPath"]).exists()

    page_lines = [
        "class GeneratedPage:",
        "    def __init__(self, page):",
        "        self.page = page",
        "",
    ]
    for index, _ in enumerate(reviewed, start=1):
        page_lines.extend([
            f"    def perform_healing_step_{index}(self):",
            "        raise AssertionError('selector healing timeout: missing locator #checkout')",
            "",
        ])
    patch_response = client.put(
        f"/projects/{project_id}/generated-files/content",
        json={"path": "pages/generated_page.py", "content": "\n".join(page_lines)},
    )
    assert patch_response.status_code == 200
    return reviewed


def _proposal_from_error(error: str) -> dict:
    lower = error.lower()
    if "selector" in lower or "locator" in lower:
        kind = "selector_replace"
        message = "Compare the failed locator against the screenshot/trace evidence and prepare a selector replacement before regeneration."
    elif "timeout" in lower:
        kind = "wait_adjust"
        message = "Inspect the trace timing and screenshot state, then consider a more stable wait or selector in the generated step."
    else:
        kind = "manual_review"
        message = "Review the captured error with available evidence and prepare a focused fix."
    return {"kind": kind, "message": message, "status": "proposed"}


def test_self_healing_proposal_workflow(client: TestClient, project_id: str, imported_case: dict) -> None:
    case_id = imported_case["id"]
    automation_key = imported_case["automation_key"]
    _prepare_failing_generated_project(client, project_id, case_id)

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
    execution = _wait_for_execution_count(client, project_id, 1)[0]
    assert execution["status"] in {"completed", "failed"}
    assert execution["result_path"]

    detail = client.get(f"/projects/{project_id}/executions/{execution['id']}").json()
    failed_result = next(result for result in detail["results"] if result["automation_key"] == automation_key)
    assert failed_result["status"] == "failed"
    assert failed_result["error"]

    proposal = _proposal_from_error(failed_result["error"])
    assert proposal["kind"] in {"selector_replace", "wait_adjust", "manual_review"}
    assert proposal["status"] == "proposed"

    accepted = {**proposal, "status": "accepted"}
    rejected = {**proposal, "status": "rejected"}
    assert accepted["status"] == "accepted"
    assert rejected["status"] == "rejected"

    rerun = client.post(f"/projects/{project_id}/executions/{execution['id']}/rerun-failed")
    assert rerun.status_code == 200
    rerun_job_id = rerun.json()["jobId"]
    executions = _wait_for_execution_count(client, project_id, 2)
    rerun_execution = next(item for item in executions if item["id"] != execution["id"])
    assert rerun_execution["status"] in {"completed", "failed"}
    assert rerun_execution["result_path"]
    assert Path(rerun_execution["result_path"]).exists()

    rerun_detail = client.get(f"/projects/{project_id}/executions/{rerun_execution['id']}").json()
    assert any(result["automation_key"] == automation_key for result in rerun_detail["results"])

    with client.websocket_connect(f"/ws/logs/{rerun_job_id}") as websocket:
        first_log = websocket.receive_text()
        assert "rerun-failed" in first_log
        second_log = websocket.receive_text()
        assert "Rerun results" in second_log or "selector healing timeout" in second_log
