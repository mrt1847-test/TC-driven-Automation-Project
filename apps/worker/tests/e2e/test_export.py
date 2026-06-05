"""E-06: Result Export - execution results to preview/write-back and export log."""
from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from worker.models.db import ExecutionResult, ExecutionRun, ExportLog

ROOT = Path(__file__).resolve().parents[4]
EXCEL_FIXTURE = ROOT / "fixtures" / "sample_cases.xlsx"


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


def _prepare_execution(project_id: str, case: dict, tmp_path: Path) -> dict:
    import worker.core.database as database

    source_location = case["source_location"]
    automation_key = case["automation_key"]
    run_id = "e2e_export_run"
    generated_root = tmp_path / "generated-export-project"
    result_path = generated_root / "artifacts" / "runs" / run_id / "results.json"
    mapping_path = generated_root / "mappings" / "cases.yaml"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    mapping_path.parent.mkdir(parents=True, exist_ok=True)

    result_case = {
        "automationKey": automation_key,
        "sourceType": case["source_type"],
        "sourceCaseId": case["source_id"],
        "title": case["title"],
        "status": "passed",
        "durationMs": 120,
        "artifacts": {},
    }
    mapping_case = {
        "automationKey": automation_key,
        "sourceType": case["source_type"],
        "sourceCaseId": case["source_id"],
        "title": case["title"],
        "resultTargets": {
            "excel": {
                "file": source_location["file_path"],
                "sheet": source_location.get("sheet_name"),
                "row": source_location["row_index"],
            },
        },
    }
    result_path.write_text(
        json.dumps({"runId": run_id, "cases": [result_case]}, ensure_ascii=False),
        encoding="utf-8",
    )
    mapping_path.write_text(
        json.dumps({"cases": [mapping_case]}, ensure_ascii=False),
        encoding="utf-8",
    )

    with Session(database.engine) as session:
        execution = ExecutionRun(
            id="exec_e2e_export",
            project_id=project_id,
            run_id=run_id,
            env="stg",
            browser="chromium",
            status="completed",
            result_path=str(result_path),
        )
        session.add(execution)
        session.add(ExecutionResult(
            id="er_e2e_export",
            execution_run_id=execution.id,
            automation_key=automation_key,
            source_type=case["source_type"],
            source_case_id=case["source_id"],
            title=case["title"],
            status="passed",
            duration_ms=120,
        ))
        session.commit()

    return {"id": "exec_e2e_export", "run_id": run_id, "result_path": str(result_path)}


def test_result_export_workflow(client: TestClient, project_id: str, tmp_path: Path) -> None:
    case = _import_case_from_excel_copy(client, project_id, tmp_path)
    execution = _prepare_execution(project_id, case, tmp_path)

    preview_response = client.post(
        f"/projects/{project_id}/executions/{execution['id']}/export/excel",
        json={"preview": True},
    )
    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert preview["preview"] is True
    assert preview["validation"] == {"ok": True, "checked": 1, "issues": []}
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
