"""E-06: Result Export - execution results to preview/write-back and export log."""
from __future__ import annotations

from pathlib import Path
import shutil
import time

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from worker.models.db import ExportLog

ROOT = Path(__file__).resolve().parents[4]
EXCEL_FIXTURE = ROOT / "fixtures" / "sample_cases.xlsx"


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


def _import_case_from_excel_copy(client: TestClient, project_id: str, tmp_path: Path) -> dict:
    if not EXCEL_FIXTURE.exists():
        pytest.skip(f"Missing Excel fixture: {EXCEL_FIXTURE}")
    export_source = tmp_path / "export_cases.xlsx"
    shutil.copy2(EXCEL_FIXTURE, export_source)
    response = client.post(
        f"/projects/{project_id}/cases/import/excel",
        json={"file_path": str(export_source)},
    )
    assert response.status_code == 200
    cases = response.json()
    assert cases
    return cases[0]


def _prepare_execution(client: TestClient, project_id: str, case: dict) -> dict:
    case_id = case["id"]
    automation_key = case["automation_key"]

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
            "normalized_step_name": f"export_step_{index}",
            "pom_method_name": f"perform_export_step_{index}",
            "status": "mapped",
        })
    save = client.put(f"/projects/{project_id}/cases/{case_id}/mappings", json={"mappings": reviewed})
    assert save.status_code == 200

    generated = client.post(f"/projects/{project_id}/generate", json={"caseIds": [case_id]})
    assert generated.status_code == 200

    execution_queued = client.post(
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
    assert execution_queued.status_code == 200
    execution = _wait_for_execution(client, project_id)
    assert execution["result_path"]
    assert Path(execution["result_path"]).exists()
    return execution


def test_result_export_workflow(client: TestClient, project_id: str, tmp_path: Path) -> None:
    case = _import_case_from_excel_copy(client, project_id, tmp_path)
    execution = _prepare_execution(client, project_id, case)

    preview_response = client.post(
        f"/projects/{project_id}/executions/{execution['id']}/export/excel",
        json={"preview": True},
    )
    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert preview["preview"] is True
    assert len(preview["updates"]) == 1
    assert preview["updates"][0]["automationKey"] == case["automation_key"]
    assert preview["updates"][0]["sourceCaseId"] == case["source_id"]
    assert preview["updates"][0]["runId"] == execution["run_id"]

    export_response = client.post(
        f"/projects/{project_id}/executions/{execution['id']}/export/excel",
        json={"preview": False},
    )
    assert export_response.status_code == 200
    assert export_response.json()["updated"] == 1

    import worker.core.database as database

    with Session(database.engine) as session:
        logs = session.exec(
            select(ExportLog).where(
                ExportLog.execution_run_id == execution["id"],
                ExportLog.target == "excel",
            )
        ).all()

    assert len(logs) == 1
    assert logs[0].status == "success"
