"""H-01: MVP 1 gate - Excel TC to Generate Raw to Automation IDE run."""
from __future__ import annotations

from pathlib import Path
import time

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[4]
EXCEL_FIXTURE = ROOT / "fixtures" / "sample_cases.xlsx"


def _wait_for_webwright_run(client: TestClient, project_id: str, case_id: str, timeout_s: float = 5.0) -> dict:
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


def test_mvp1_excel_to_automation_ide_run_gate(client: TestClient, project_id: str) -> None:
    if not EXCEL_FIXTURE.exists():
        pytest.skip(f"Missing Excel fixture: {EXCEL_FIXTURE}")

    preview = client.post(
        f"/projects/{project_id}/cases/import/excel/preview",
        json={"file_path": str(EXCEL_FIXTURE)},
    )
    assert preview.status_code == 200
    assert preview.json()["totalRows"] >= 1

    imported = client.post(
        f"/projects/{project_id}/cases/import/excel",
        json={"file_path": str(EXCEL_FIXTURE)},
    )
    assert imported.status_code == 200
    case = imported.json()[0]
    case_id = case["id"]
    automation_key = case["automation_key"]
    assert automation_key

    queued = client.post(f"/projects/{project_id}/webwright-runs", json={"caseIds": [case_id]})
    assert queued.status_code == 200
    raw_job_id = queued.json()["jobId"]
    webwright_run = _wait_for_webwright_run(client, project_id, case_id)
    assert webwright_run["status"] == "completed"
    assert webwright_run["automation_key"] == automation_key
    assert webwright_run["final_script_path"]

    actions = client.get(f"/projects/{project_id}/cases/{case_id}/actions").json()
    mappings = client.get(f"/projects/{project_id}/cases/{case_id}/mappings").json()
    assert actions
    assert mappings
    assert mappings[0]["action_ids"]

    reviewed_mappings = []
    for index, mapping in enumerate(mappings, start=1):
        reviewed_mappings.append({
            **mapping,
            "normalized_step_id": mapping.get("normalized_step_id") or f"flow_{index:03d}",
            "normalized_step_name": f"mvp1_step_{index}",
            "pom_method_name": f"perform_mvp1_step_{index}",
            "status": "mapped",
        })
    save = client.put(f"/projects/{project_id}/cases/{case_id}/mappings", json={"mappings": reviewed_mappings})
    assert save.status_code == 200

    generated = client.post(f"/projects/{project_id}/generate", json={"caseIds": [case_id]})
    assert generated.status_code == 200
    generated_path = Path(generated.json()["generatedProjectPath"])
    assert generated_path.exists()

    file_paths = {item["path"] for item in client.get(f"/projects/{project_id}/generated-files").json()}
    assert {
        "mappings/cases.yaml",
        "pages/generated_page.py",
        f"flows/{automation_key}_flow.py",
        f"tests/test_{automation_key}.py",
        "runner/cli.py",
    }.issubset(file_paths)

    page_content = client.get(
        f"/projects/{project_id}/generated-files/content",
        params={"path": "pages/generated_page.py"},
    ).json()["content"]
    assert "perform_mvp1_step_1" in page_content

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
    execution_job_id = execution_queue.json()["jobId"]
    execution = _wait_for_execution(client, project_id)
    assert execution["status"] == "completed"
    assert execution["result_path"]
    assert Path(execution["result_path"]).exists()

    detail = client.get(f"/projects/{project_id}/executions/{execution['id']}").json()
    assert detail["summary"]["runId"] == execution["run_id"]
    assert detail["summary"]["summary"]["total"] >= 1
    assert any(result["automation_key"] == automation_key for result in detail["results"])

    with client.websocket_connect(f"/ws/logs/{raw_job_id}?token=test-worker-token") as raw_ws:
        raw_log = raw_ws.receive_text()
        assert automation_key in raw_log or "mock" in raw_log.lower() or "webwright" in raw_log.lower()

    with client.websocket_connect(f"/ws/logs/{execution_job_id}?token=test-worker-token") as runner_ws:
        runner_log = runner_ws.receive_text()
        assert "runner.cli" in runner_log
