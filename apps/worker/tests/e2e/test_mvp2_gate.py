"""H-02: MVP 2 gate - Automation IDE edit, regenerate, and debug loop."""
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


def _wait_for_execution(client: TestClient, project_id: str, timeout_s: float = 8.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        executions = client.get(f"/projects/{project_id}/executions").json()
        for execution in executions:
            if execution.get("status") in {"completed", "failed", "cancelled"}:
                return execution
        time.sleep(0.05)
    pytest.fail("Timed out waiting for execution to finish")


def _save_reviewed_mappings(client: TestClient, project_id: str, case_id: str, prefix: str) -> list[dict]:
    mappings = client.get(f"/projects/{project_id}/cases/{case_id}/mappings").json()
    assert mappings

    reviewed = []
    for index, mapping in enumerate(mappings, start=1):
        reviewed.append({
            **mapping,
            "normalized_step_id": mapping.get("normalized_step_id") or f"flow_{index:03d}",
            "normalized_step_name": f"{prefix}_step_{index}",
            "pom_method_name": f"perform_{prefix}_step_{index}",
            "status": "mapped",
        })
    save = client.put(f"/projects/{project_id}/cases/{case_id}/mappings", json={"mappings": reviewed})
    assert save.status_code == 200
    return reviewed


def _read_file(client: TestClient, project_id: str, path: str) -> str:
    response = client.get(f"/projects/{project_id}/generated-files/content", params={"path": path})
    assert response.status_code == 200
    return response.json()["content"]


def _write_file(client: TestClient, project_id: str, path: str, content: str) -> None:
    response = client.put(f"/projects/{project_id}/generated-files/content", json={"path": path, "content": content})
    assert response.status_code == 200


def _diagnosis_from_result(result: dict, automation_key: str) -> dict:
    error = result.get("error") or ""
    lower = error.lower()
    if "mvp2 debug failure" in lower:
        kind = "generated_step_failure"
    elif "locator" in lower or "selector" in lower:
        kind = "selector_investigation"
    else:
        kind = "runner_failure_review"
    return {
        "automation_key": automation_key,
        "kind": kind,
        "status": "proposed",
        "evidence": error,
    }


def test_mvp2_automation_ide_edit_regenerate_debug_gate(
    client: TestClient,
    project_id: str,
    imported_case: dict,
) -> None:
    case_id = imported_case["id"]
    automation_key = imported_case["automation_key"]

    queued = client.post(f"/projects/{project_id}/webwright-runs", json={"caseIds": [case_id]})
    assert queued.status_code == 200
    run = _wait_for_run(client, project_id, case_id)
    assert run["status"] == "completed"
    assert run["automation_key"] == automation_key

    _save_reviewed_mappings(client, project_id, case_id, "mvp2")
    generated = client.post(f"/projects/{project_id}/generate", json={"caseIds": [case_id]})
    assert generated.status_code == 200
    generated_path = Path(generated.json()["generatedProjectPath"])
    assert generated_path.exists()

    page_path = "pages/generated_page.py"
    page_content = _read_file(client, project_id, page_path)
    assert "perform_mvp2_step_1" in page_content

    edit_marker = f"# mvp2 manual edit for {automation_key}"
    _write_file(client, project_id, page_path, f"{page_content.rstrip()}\n{edit_marker}\n")
    saved_content = _read_file(client, project_id, page_path)
    assert edit_marker in saved_content

    search_results = client.get(f"/projects/{project_id}/search", params={"q": automation_key}).json()
    assert any(item.get("automationKey") == automation_key for item in search_results)
    assert any(item.get("path") == "mappings/cases.yaml" for item in search_results)
    edit_search = client.get(f"/projects/{project_id}/search", params={"q": "mvp2 manual edit"}).json()
    assert any(item.get("path") == page_path for item in edit_search)

    regenerated_mappings = _save_reviewed_mappings(client, project_id, case_id, "mvp2_regenerated")
    regenerated = client.post(f"/projects/{project_id}/generate", json={"caseIds": [case_id]})
    assert regenerated.status_code == 200

    regenerated_page = _read_file(client, project_id, page_path)
    assert "perform_mvp2_regenerated_step_1" in regenerated_page
    assert edit_marker not in regenerated_page

    failure_message = f"mvp2 debug failure for {automation_key}"
    failure_page_lines = [
        "class GeneratedPage:",
        "    def __init__(self, page):",
        "        self.page = page",
        "",
    ]
    for mapping in regenerated_mappings:
        failure_page_lines.extend([
            f"    def {mapping['pom_method_name']}(self):",
            f"        raise AssertionError({failure_message!r})",
            "",
        ])
    _write_file(client, project_id, page_path, "\n".join(failure_page_lines))

    flow_class = "".join(part.capitalize() for part in automation_key.split("_")) + "Flow"
    test_path = f"tests/test_{automation_key.lower().replace('-', '_').replace(' ', '_')}.py"
    fake_test = "\n".join([
        f"from flows.{automation_key.lower().replace('-', '_').replace(' ', '_')}_flow import {flow_class}",
        "",
        "",
        "class FakePage:",
        "    pass",
        "",
        "",
        f"def test_{automation_key.lower().replace('-', '_').replace(' ', '_')}():",
        "    flow = " + flow_class + "(FakePage())",
        "    flow.execute()",
        "",
    ])
    _write_file(client, project_id, test_path, fake_test)
    _write_file(
        client,
        project_id,
        "conftest.py",
        "\n".join([
            "def pytest_addoption(parser):",
            "    parser.addoption('--browser', action='store', default='chromium')",
            "    parser.addoption('--headed', action='store', default='false')",
            "",
        ]),
    )

    execution_queue = client.post(
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
    assert execution_queue.status_code == 200
    job_id = execution_queue.json()["jobId"]

    execution = _wait_for_execution(client, project_id)
    assert execution["status"] in {"completed", "failed"}
    assert execution["result_path"]
    assert Path(execution["result_path"]).exists()

    detail = client.get(f"/projects/{project_id}/executions/{execution['id']}").json()
    failed_result = next(result for result in detail["results"] if result["automation_key"] == automation_key)
    assert failed_result["status"] == "failed"
    assert failure_message in (failed_result["error"] or "")

    diagnosis = _diagnosis_from_result(failed_result, automation_key)
    assert diagnosis["automation_key"] == automation_key
    assert diagnosis["kind"] == "generated_step_failure"
    assert diagnosis["status"] == "proposed"

    with client.websocket_connect(f"/ws/logs/{job_id}?token=test-worker-token") as websocket:
        first_log = websocket.receive_text()
        assert "runner.cli" in first_log
        second_log = websocket.receive_text()
        assert "Results written to" in second_log or failure_message in second_log
