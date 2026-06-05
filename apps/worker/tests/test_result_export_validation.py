from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from worker.models.db import ExecutionResult, ExecutionRun, ExportLog


_DEFAULT_MAPPING = object()


def _case_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "automationKey": "case_export_001",
        "sourceType": "excel",
        "sourceCaseId": "TC-001",
        "title": "Export validation case",
        "status": "passed",
        "durationMs": 25,
        "artifacts": {"screenshot": "artifacts/screenshot.png"},
    }
    row.update(overrides)
    return row


def _mapping_row(source_file: Path, **overrides: Any) -> dict[str, Any]:
    row = {
        "automationKey": "case_export_001",
        "sourceType": "excel",
        "sourceCaseId": "TC-001",
        "title": "Export validation case",
        "resultTargets": {
            "excel": {
                "file": str(source_file),
                "sheet": "Cases",
                "row": 2,
            }
        },
    }
    row.update(overrides)
    return row


def _insert_export_fixture(
    project_id: str,
    tmp_path: Path,
    *,
    result_case: dict[str, Any] | None = None,
    mapping_case: dict[str, Any] | object | None = _DEFAULT_MAPPING,
    db_case: dict[str, Any] | None = None,
) -> tuple[str, Path]:
    import worker.core.database as database

    source_file = tmp_path / "source_cases.xlsx"
    source_file.write_text("source workbook placeholder", encoding="utf-8")
    result_case = result_case or _case_row()
    if mapping_case is _DEFAULT_MAPPING:
        mapping_case = _mapping_row(source_file)
    db_case = db_case or result_case

    generated_root = tmp_path / "generated-export"
    result_path = generated_root / "artifacts" / "runs" / "run_export_001" / "results.json"
    mapping_path = generated_root / "mappings" / "cases.yaml"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps({"runId": "run_export_001", "cases": [result_case]}, ensure_ascii=False),
        encoding="utf-8",
    )
    mapping_path.write_text(
        json.dumps({"cases": [] if mapping_case is None else [mapping_case]}, ensure_ascii=False),
        encoding="utf-8",
    )

    with Session(database.engine) as session:
        execution = ExecutionRun(
            id="exec_export_validation",
            project_id=project_id,
            run_id="run_export_001",
            env="stg",
            browser="chromium",
            status="completed",
            result_path=str(result_path),
        )
        session.add(execution)
        session.add(ExecutionResult(
            id="res_export_validation",
            execution_run_id=execution.id,
            automation_key=db_case.get("automationKey"),
            source_type=db_case.get("sourceType"),
            source_case_id=db_case.get("sourceCaseId"),
            title=db_case.get("title"),
            status=db_case.get("status", "passed"),
            duration_ms=db_case.get("durationMs"),
        ))
        session.commit()

    return "exec_export_validation", source_file


def _export_logs(execution_id: str) -> list[ExportLog]:
    import worker.core.database as database

    with Session(database.engine) as session:
        return session.exec(select(ExportLog).where(ExportLog.execution_run_id == execution_id)).all()


def test_export_preview_returns_validation_and_does_not_mutate(
    client: TestClient,
    project_id: str,
    tmp_path: Path,
) -> None:
    execution_id, source_file = _insert_export_fixture(project_id, tmp_path)
    before = source_file.read_text(encoding="utf-8")

    response = client.post(
        f"/projects/{project_id}/executions/{execution_id}/export/excel",
        json={"preview": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["preview"] is True
    assert body["validation"] == {"ok": True, "checked": 1, "issues": []}
    assert body["updates"][0]["automationKey"] == "case_export_001"
    assert body["updates"][0]["sourceCaseId"] == "TC-001"
    assert source_file.read_text(encoding="utf-8") == before
    assert _export_logs(execution_id) == []


def test_testrail_clone_preview_returns_payload_without_external_mutation(
    client: TestClient,
    project_id: str,
    tmp_path: Path,
) -> None:
    execution_id, _ = _insert_export_fixture(project_id, tmp_path)

    response = client.post(
        f"/projects/{project_id}/executions/{execution_id}/export/testrail-clone",
        json={"preview": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["preview"] is True
    assert body["validation"] == {"ok": True, "checked": 1, "issues": []}
    assert body["payload"]["runId"] == "run_export_001"
    assert body["payload"]["results"][0]["automationKey"] == "case_export_001"
    assert body["payload"]["results"][0]["sourceCaseId"] == "TC-001"
    assert _export_logs(execution_id) == []


def test_export_preview_reports_mapping_mismatch_without_log(
    client: TestClient,
    project_id: str,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "source_cases.xlsx"
    execution_id, _ = _insert_export_fixture(
        project_id,
        tmp_path,
        mapping_case=_mapping_row(source_file, sourceCaseId="TC-OTHER"),
    )

    response = client.post(
        f"/projects/{project_id}/executions/{execution_id}/export/testrail",
        json={"preview": True},
    )

    assert response.status_code == 200
    validation = response.json()["validation"]
    assert validation["ok"] is False
    assert {issue["kind"] for issue in validation["issues"]} == {"source_case_id_mismatch"}
    assert _export_logs(execution_id) == []


def test_export_rejects_mapping_mismatch_before_mutation(
    client: TestClient,
    project_id: str,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "source_cases.xlsx"
    execution_id, _ = _insert_export_fixture(
        project_id,
        tmp_path,
        mapping_case=_mapping_row(source_file, sourceCaseId="TC-OTHER"),
    )

    response = client.post(
        f"/projects/{project_id}/executions/{execution_id}/export/testrail",
        json={"preview": False},
    )

    assert response.status_code == 400
    assert "source_case_id_mismatch" in response.json()["detail"]
    assert _export_logs(execution_id) == []


def test_export_rejects_missing_generated_mapping_before_mutation(
    client: TestClient,
    project_id: str,
    tmp_path: Path,
) -> None:
    execution_id, _ = _insert_export_fixture(project_id, tmp_path, mapping_case=None)

    response = client.post(
        f"/projects/{project_id}/executions/{execution_id}/export/google-sheets",
        json={"preview": False},
    )

    assert response.status_code == 400
    assert "missing_mapping" in response.json()["detail"]
    assert _export_logs(execution_id) == []


def test_valid_export_still_persists_export_log(
    client: TestClient,
    project_id: str,
    tmp_path: Path,
) -> None:
    execution_id, _ = _insert_export_fixture(project_id, tmp_path)

    response = client.post(
        f"/projects/{project_id}/executions/{execution_id}/export/google-sheets",
        json={"preview": False},
    )

    assert response.status_code == 200
    assert response.json()["updated"] == 1
    logs = _export_logs(execution_id)
    assert len(logs) == 1
    assert logs[0].target == "google-sheets"
    assert logs[0].status == "success"
