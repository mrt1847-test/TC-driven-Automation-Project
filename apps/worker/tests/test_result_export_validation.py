from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from worker.models.db import ExecutionResult, ExecutionRun, ExportLog
from worker.services import result_export as result_export_module


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


def _google_case_row(**overrides: Any) -> dict[str, Any]:
    row = _case_row(
        sourceType="google_sheets",
        sourceCaseId="GS-001",
        title="Google Sheets export validation case",
    )
    row.update(overrides)
    return row


def _google_mapping_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "automationKey": "case_export_001",
        "sourceType": "google_sheets",
        "sourceCaseId": "GS-001",
        "title": "Google Sheets export validation case",
        "resultTargets": {
            "googleSheets": {
                "sheet": "Results",
                "row": 7,
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


def test_google_sheets_preview_resolves_payload_without_credential_or_log(
    client: TestClient,
    project_id: str,
    tmp_path: Path,
) -> None:
    execution_id, _ = _insert_export_fixture(
        project_id,
        tmp_path,
        result_case=_google_case_row(),
        mapping_case=_google_mapping_row(),
    )
    client.put(
        "/settings",
        json={
            "integrations": {
                "googleSheets": {
                    "enabled": True,
                    "spreadsheetId": "sheet-123",
                    "sheetName": "Results",
                }
            }
        },
    )

    response = client.post(
        f"/projects/{project_id}/executions/{execution_id}/export/google-sheets",
        json={"preview": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["preview"] is True
    assert body["validation"] == {"ok": True, "checked": 1, "issues": []}
    assert body["targetPayload"][0]["spreadsheetId"] == "sheet-123"
    assert body["targetPayload"][0]["sheetName"] == "Results"
    assert body["targetPayload"][0]["row"] == 7
    assert _export_logs(execution_id) == []


def test_google_sheets_real_export_requires_secure_credential_when_enabled(
    client: TestClient,
    project_id: str,
    tmp_path: Path,
) -> None:
    execution_id, _ = _insert_export_fixture(
        project_id,
        tmp_path,
        result_case=_google_case_row(),
        mapping_case=_google_mapping_row(),
    )
    client.put(
        "/settings",
        json={
            "integrations": {
                "googleSheets": {
                    "enabled": True,
                    "spreadsheetId": "sheet-123",
                    "sheetName": "Results",
                }
            }
        },
    )

    response = client.post(
        f"/projects/{project_id}/executions/{execution_id}/export/google-sheets",
        json={"preview": False},
    )

    assert response.status_code == 400
    assert "credentialJson" in response.json()["detail"]
    assert _export_logs(execution_id) == []


def test_google_sheets_real_export_posts_batch_update_and_logs_success(
    monkeypatch,
    client: TestClient,
    project_id: str,
    tmp_path: Path,
) -> None:
    import httpx

    secret = "google-access-token-secret-abcdef"
    execution_id, _ = _insert_export_fixture(
        project_id,
        tmp_path,
        result_case=_google_case_row(),
        mapping_case=_google_mapping_row(),
    )
    client.put(
        "/settings",
        json={
            "integrations": {
                "googleSheets": {
                    "enabled": True,
                    "spreadsheetId": "sheet-123",
                    "sheetName": "Results",
                }
            }
        },
    )
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append({
            "method": request.method,
            "url": str(request.url),
            "auth": request.headers.get("Authorization"),
            "body": json.loads(request.content.decode("utf-8")) if request.content else None,
        })
        if request.method == "GET":
            return httpx.Response(200, json={"values": [["Case ID", "Title"]]})
        return httpx.Response(200, json={"totalUpdatedCells": 8})

    class FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(result_export_module.httpx, "AsyncClient", FakeAsyncClient)

    response = client.post(
        f"/projects/{project_id}/executions/{execution_id}/export/google-sheets",
        json={"preview": False, "config": {"credentialJson": json.dumps({"access_token": secret})}},
    )

    assert response.status_code == 200
    assert secret not in response.text
    body = response.json()
    assert body["updated"] == 1
    assert body["responses"][0]["response"]["totalUpdatedCells"] == 8
    assert captured[0]["method"] == "GET"
    assert "spreadsheets/sheet-123/values/" in captured[0]["url"]
    assert captured[0]["auth"] == f"Bearer {secret}"
    assert captured[1]["method"] == "POST"
    assert captured[1]["url"].endswith("/spreadsheets/sheet-123/values:batchUpdate")
    assert captured[1]["auth"] == f"Bearer {secret}"
    update_ranges = {item["range"]: item["values"][0][0] for item in captured[1]["body"]["data"]}
    assert update_ranges["'Results'!C1:C1"] == "Automation Result"
    assert update_ranges["'Results'!D1:D1"] == "Automation Run ID"
    assert update_ranges["'Results'!E1:E1"] == "Automation Executed At"
    assert update_ranges["'Results'!F1:F1"] == "Automation Comment"
    assert update_ranges["'Results'!C7:C7"] == "passed"
    assert update_ranges["'Results'!D7:D7"] == "run_export_001"
    assert update_ranges["'Results'!F7:F7"] == "Automation passed"

    logs = _export_logs(execution_id)
    assert len(logs) == 1
    assert logs[0].target == "google-sheets"
    assert logs[0].status == "success"
    assert secret not in (logs[0].message or "")


def test_google_sheets_real_export_api_error_is_masked_and_logged_failed(
    monkeypatch,
    client: TestClient,
    project_id: str,
    tmp_path: Path,
) -> None:
    import httpx

    secret = "google-access-token-secret-abcdef"
    execution_id, _ = _insert_export_fixture(
        project_id,
        tmp_path,
        result_case=_google_case_row(),
        mapping_case=_google_mapping_row(),
    )
    client.put(
        "/settings",
        json={
            "integrations": {
                "googleSheets": {
                    "enabled": True,
                    "spreadsheetId": "sheet-123",
                    "sheetName": "Results",
                }
            }
        },
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"values": [["Case ID", "Title"]]})
        return httpx.Response(403, json={"error": {"message": f"denied for token {secret}"}})

    class FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(result_export_module.httpx, "AsyncClient", FakeAsyncClient)

    response = client.post(
        f"/projects/{project_id}/executions/{execution_id}/export/google-sheets",
        json={"preview": False, "config": {"credentialJson": json.dumps({"access_token": secret})}},
    )

    assert response.status_code == 400
    assert secret not in response.text
    assert "***MASKED***" in response.text
    logs = _export_logs(execution_id)
    assert len(logs) == 1
    assert logs[0].target == "google-sheets"
    assert logs[0].status == "failed"
    assert secret not in (logs[0].message or "")
    assert "***MASKED***" in (logs[0].message or "")


def test_testrail_real_export_requires_secure_token_when_enabled(
    client: TestClient,
    project_id: str,
    tmp_path: Path,
) -> None:
    execution_id, _ = _insert_export_fixture(project_id, tmp_path)
    client.put(
        "/settings",
        json={
            "integrations": {
                "testrail": {
                    "enabled": True,
                    "baseUrl": "https://testrail.example",
                    "username": "qa@example.com",
                    "resultRunId": "42",
                }
            }
        },
    )

    response = client.post(
        f"/projects/{project_id}/executions/{execution_id}/export/testrail",
        json={"preview": False},
    )

    assert response.status_code == 400
    assert "apiToken" in response.json()["detail"]
    assert _export_logs(execution_id) == []


def test_testrail_export_defaults_to_local_mock_when_integration_disabled(
    client: TestClient,
    project_id: str,
    tmp_path: Path,
) -> None:
    execution_id, _ = _insert_export_fixture(project_id, tmp_path)

    response = client.post(
        f"/projects/{project_id}/executions/{execution_id}/export/testrail",
        json={"preview": False},
    )

    assert response.status_code == 200
    assert response.json()["updated"] == 1
    assert response.json()["mode"] == "local-mock"
    logs = _export_logs(execution_id)
    assert len(logs) == 1
    assert logs[0].target == "testrail"
    assert logs[0].status == "success"


def test_testrail_real_export_posts_results_and_logs_success(
    monkeypatch,
    client: TestClient,
    project_id: str,
    tmp_path: Path,
) -> None:
    import base64
    import httpx

    secret = "tr-secret-token-value-abcdef"
    execution_id, _ = _insert_export_fixture(project_id, tmp_path)
    client.put(
        "/settings",
        json={
            "integrations": {
                "testrail": {
                    "enabled": True,
                    "baseUrl": "https://testrail.example",
                    "username": "qa@example.com",
                    "resultRunId": "42",
                }
            }
        },
    )
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append({
            "url": str(request.url),
            "auth": request.headers.get("Authorization"),
            "body": json.loads(request.content.decode("utf-8")),
        })
        return httpx.Response(200, json={"id": 9001})

    class FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(result_export_module.httpx, "AsyncClient", FakeAsyncClient)

    response = client.post(
        f"/projects/{project_id}/executions/{execution_id}/export/testrail",
        json={"preview": False, "config": {"apiToken": secret}},
    )

    assert response.status_code == 200
    assert secret not in response.text
    body = response.json()
    assert body["updated"] == 1
    assert body["responses"][0]["response"]["id"] == 9001
    assert "add_result_for_case/42/TC-001" in captured[0]["url"]
    assert captured[0]["auth"] == "Basic " + base64.b64encode(b"qa@example.com:tr-secret-token-value-abcdef").decode()
    assert captured[0]["body"]["status_id"] == 1
    assert captured[0]["body"]["elapsed"] == "1s"
    assert "case_export_001" in captured[0]["body"]["comment"]

    logs = _export_logs(execution_id)
    assert len(logs) == 1
    assert logs[0].target == "testrail"
    assert logs[0].status == "success"
    assert secret not in (logs[0].message or "")


def test_testrail_real_export_api_error_is_masked_and_logged_failed(
    monkeypatch,
    client: TestClient,
    project_id: str,
    tmp_path: Path,
) -> None:
    import httpx

    secret = "tr-secret-token-value-abcdef"
    execution_id, _ = _insert_export_fixture(project_id, tmp_path)
    client.put(
        "/settings",
        json={
            "integrations": {
                "testrail": {
                    "enabled": True,
                    "baseUrl": "https://testrail.example",
                    "username": "qa@example.com",
                    "resultRunId": "42",
                }
            }
        },
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": f"bad token {secret}"})

    class FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(result_export_module.httpx, "AsyncClient", FakeAsyncClient)

    response = client.post(
        f"/projects/{project_id}/executions/{execution_id}/export/testrail",
        json={"preview": False, "config": {"apiToken": secret}},
    )

    assert response.status_code == 400
    assert secret not in response.text
    assert "***MASKED***" in response.text
    logs = _export_logs(execution_id)
    assert len(logs) == 1
    assert logs[0].target == "testrail"
    assert logs[0].status == "failed"
    assert secret not in (logs[0].message or "")
    assert "***MASKED***" in (logs[0].message or "")
