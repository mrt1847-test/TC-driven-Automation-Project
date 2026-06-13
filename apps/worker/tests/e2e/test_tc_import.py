"""E-01: TC Import workflow — Excel preview/import and connector preview via Worker APIs."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from worker.models.schemas import NormalizedTestCase
from worker.models.schemas import TestStep as ImportStep

EXCEL_FIXTURE = os.path.join(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")),
    "fixtures",
    "sample_cases.xlsx",
)


@pytest.fixture(scope="module", autouse=True)
def _ensure_excel_fixture() -> None:
    if not os.path.exists(EXCEL_FIXTURE):
        pytest.skip(f"Missing Excel fixture: {EXCEL_FIXTURE}")


def test_excel_preview_import_and_list_handoff(client: TestClient, project_id: str) -> None:
    preview = client.post(
        f"/projects/{project_id}/cases/import/excel/preview",
        json={"file_path": EXCEL_FIXTURE},
    )
    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["totalRows"] >= 1
    assert len(preview_body["preview"]) >= 1
    assert preview_body["preview"][0]["automationKey"] == "sample_case_001"

    imported = client.post(
        f"/projects/{project_id}/cases/import/excel",
        json={"file_path": EXCEL_FIXTURE},
    )
    assert imported.status_code == 200
    cases = imported.json()
    assert len(cases) >= 1
    assert cases[0]["automation_key"] == "sample_case_001"
    assert cases[0]["source_type"] == "excel"

    listed = client.get(f"/projects/{project_id}/cases")
    assert listed.status_code == 200
    list_body = listed.json()
    assert len(list_body) >= 1
    assert any(item["automation_key"] == "sample_case_001" for item in list_body)

    case_id = cases[0]["id"]
    detail = client.get(f"/projects/{project_id}/cases/{case_id}")
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["automation_key"] == "sample_case_001"
    assert detail_body["status"] == "imported"
    assert len(detail_body["steps"]) >= 1


def test_testrail_connector_preview(client: TestClient, project_id: str) -> None:
    response = client.post(
        f"/projects/{project_id}/cases/import/testrail/preview",
        json={"project_id": 12, "suite_id": 3, "mock": True},
    )
    assert response.status_code == 200
    cases = response.json()
    assert len(cases) >= 1
    assert cases[0]["source_type"] == "testrail"
    assert cases[0]["automation_key"]


@patch("worker.routers.cases.import_from_testrail_clone", new_callable=AsyncMock)
def test_testrail_clone_connector_preview(mock_import: AsyncMock, client: TestClient, project_id: str) -> None:
    mock_import.return_value = [
        NormalizedTestCase(
            source_type="testrail-clone",
            source_id="CLONE-001",
            title="Clone connector case",
            steps=[ImportStep(index=1, action="Open app", expected="App loads")],
            automation_key="clone_case_001",
            expected_result="Ready",
        )
    ]

    response = client.post(
        f"/projects/{project_id}/cases/import/testrail-clone/preview",
        json={"project_id": "demo-project", "suite_id": "suite-1"},
    )
    assert response.status_code == 200
    cases = response.json()
    assert len(cases) == 1
    assert cases[0]["source_type"] == "testrail-clone"
    assert cases[0]["source_id"] == "CLONE-001"
    assert cases[0]["automation_key"] == "clone_case_001"
    mock_import.assert_awaited_once()
