from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from worker.core.config import MASK
from worker.services.integrations import google_sheets as sheets_module
from worker.services.integrations.google_sheets import GoogleSheetsConnectorError, import_from_google_sheets


def test_google_sheets_preview_requires_secure_credential(client: TestClient, project_id: str) -> None:
    client.put(
        "/settings",
        json={
            "integrations": {
                "googleSheets": {
                    "enabled": True,
                    "spreadsheetId": "sheet-123",
                    "serviceAccountEmail": "svc@example.iam.gserviceaccount.com",
                }
            }
        },
    )

    response = client.post(
        f"/projects/{project_id}/cases/import/google-sheets/preview",
        json={"spreadsheet_id": "sheet-123", "sheet_name": "Cases"},
    )

    assert response.status_code == 400
    assert "credential JSON" in response.text
    assert "svc@example" not in response.text


def test_google_sheets_preview_and_import_normalize_rows(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    project_id: str,
) -> None:
    secret = "ya29.google-access-token-secret"
    credential = json.dumps({"access_token": secret})
    captured: list[dict] = []

    async def fake_fetch(spreadsheet_id: str, sheet_name: str, access_token: str, credential_json: str) -> list[list[str]]:
        captured.append(
            {
                "spreadsheet_id": spreadsheet_id,
                "sheet_name": sheet_name,
                "access_token": access_token,
                "credential_json": credential_json,
            }
        )
        return [
            [
                "Case ID",
                "Title",
                "Precondition",
                "Step",
                "Expected Result",
                "Priority",
                "Automation Key",
                "Start URL",
            ],
            [
                "GS-101",
                "Checkout sheet case",
                "User is logged in\nCart has an item",
                "Open checkout\nSubmit order",
                "Checkout page opens\nConfirmation is shown",
                "High",
                "checkout_sheet_case",
                "https://shop.example/checkout",
            ],
        ]

    monkeypatch.setattr(sheets_module, "_fetch_sheet_values", fake_fetch)

    preview = client.post(
        f"/projects/{project_id}/cases/import/google-sheets/preview",
        json={
            "spreadsheet_id": "sheet-123",
            "sheet_name": "Cases",
            "credentialJson": credential,
        },
    )

    assert preview.status_code == 200
    assert secret not in preview.text
    preview_case = preview.json()[0]
    assert preview_case["source_type"] == "google_sheets"
    assert preview_case["source_id"] == "GS-101"
    assert preview_case["automation_key"] == "checkout_sheet_case"
    assert preview_case["preconditions"] == ["User is logged in", "Cart has an item"]
    assert preview_case["steps"][1]["expected"] == "Confirmation is shown"
    assert preview_case["priority"] == "High"
    assert preview_case["start_url"] == "https://shop.example/checkout"
    assert preview_case["source_location"]["sheet_name"] == "Cases"
    assert preview_case["source_location"]["row_index"] == 2
    assert preview_case["source_location"]["api_endpoint"].startswith(
        "https://sheets.googleapis.com/v4/spreadsheets/sheet-123/values/Cases"
    )

    imported = client.post(
        f"/projects/{project_id}/cases/import/google-sheets",
        json={
            "spreadsheet_id": "sheet-123",
            "sheet_name": "Cases",
            "credentialJson": credential,
        },
    )

    assert imported.status_code == 200
    assert secret not in imported.text
    imported_case = imported.json()[0]
    detail = client.get(f"/projects/{project_id}/cases/{imported_case['id']}")
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["status"] == "imported"
    assert detail_body["source_type"] == "google_sheets"
    assert detail_body["automation_key"] == "checkout_sheet_case"
    assert detail_body["source_location"]["sheet_name"] == "Cases"
    assert captured[-1] == {
        "spreadsheet_id": "sheet-123",
        "sheet_name": "Cases",
        "access_token": secret,
        "credential_json": credential,
    }


def test_google_sheets_mock_mode_keeps_local_connector_flow(client: TestClient, project_id: str) -> None:
    response = client.post(
        f"/projects/{project_id}/cases/import/google-sheets/preview",
        json={"spreadsheet_id": "sheet-123", "sheet_name": "Cases", "mock": True},
    )

    assert response.status_code == 200
    assert response.json()[0]["automation_key"] == "sample_google_sheets_case"


def test_google_sheets_api_error_masks_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    secret = "ya29.google-access-token-secret"
    credential = json.dumps({"access_token": secret})

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {secret}"
        assert request.url.path.endswith("/values/Cases")
        return httpx.Response(403, json={"error": {"message": f"denied token {secret}"}})

    class FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(sheets_module.httpx, "AsyncClient", FakeAsyncClient)

    with pytest.raises(GoogleSheetsConnectorError) as exc:
        import asyncio

        asyncio.run(import_from_google_sheets("sheet-123", "Cases", None, {"credential_json": credential}, set()))

    assert exc.value.status_code == 403
    assert secret not in exc.value.message
    assert MASK in exc.value.message
