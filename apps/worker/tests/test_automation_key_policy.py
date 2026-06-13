from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlmodel import Session

from worker.models.db import ExecutionResult, ExecutionRun, TestCase as DbTestCase
from worker.models.schemas import ExcelColumnMapping, NormalizedTestCase, TestStep as ImportStep
from worker.services.integrations.google_sheets import normalize_google_sheet_values
from worker.services.integrations.testrail import normalize_testrail_cases
from worker.services.project_generator import _merge_mapping_entries, generate_project
from worker.services.result_export import _validate_export


def _write_excel(path: Path, rows: list[list[str]]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append([
        "Case ID",
        "Title",
        "Precondition",
        "Step",
        "Expected Result",
        "Priority",
        "Automation Key",
        "Start URL",
    ])
    for row in rows:
        sheet.append(row)
    workbook.save(path)


def _excel_row(case_id: str, title: str, automation_key: str = "") -> list[str]:
    return [
        case_id,
        title,
        "",
        "Open page",
        "Page opens",
        "High",
        automation_key,
        "https://example.test",
    ]


def _db_engine():
    import worker.core.database as database

    return database.engine


def test_excel_import_normalizes_and_suffixes_explicit_and_generated_duplicates(
    client: TestClient,
    project_id: str,
    tmp_path: Path,
) -> None:
    workbook_path = tmp_path / "duplicate_keys.xlsx"
    _write_excel(
        workbook_path,
        [
            _excel_row("TC-1", "Login", "Login Case"),
            _excel_row("TC-2", "Login duplicate", "login_case"),
            _excel_row("GEN 1", "Generated duplicate"),
            _excel_row("GEN 1", "Generated duplicate copy"),
        ],
    )

    response = client.post(
        f"/projects/{project_id}/cases/import/excel",
        json={"file_path": str(workbook_path)},
    )

    assert response.status_code == 200
    assert [case["automation_key"] for case in response.json()] == [
        "login_case",
        "login_case_001",
        "gen_1",
        "gen_1_001",
    ]


def test_import_reuses_retired_deleted_keys_but_suffixes_active_existing_case(
    client: TestClient,
    project_id: str,
    tmp_path: Path,
) -> None:
    with Session(_db_engine()) as session:
        session.add(DbTestCase(
            id="tc_retired_key",
            project_id=project_id,
            source_type="excel",
            source_case_id="RET",
            title="Retired case",
            automation_key="legacy_case",
            status="retired",
        ))
        session.add(DbTestCase(
            id="tc_deleted_key",
            project_id=project_id,
            source_type="excel",
            source_case_id="DEL",
            title="Deleted case",
            automation_key="deleted_case",
            status="deleted",
        ))
        session.add(DbTestCase(
            id="tc_active_key",
            project_id=project_id,
            source_type="excel",
            source_case_id="ACT",
            title="Active case",
            automation_key="active_case",
            status="imported",
        ))
        session.commit()

    workbook_path = tmp_path / "terminal_status_keys.xlsx"
    _write_excel(
        workbook_path,
        [
            _excel_row("TC-RET", "Retired replacement", "Legacy Case"),
            _excel_row("TC-DEL", "Deleted replacement", "deleted_case"),
            _excel_row("TC-ACT", "Active replacement", "active case"),
        ],
    )

    response = client.post(
        f"/projects/{project_id}/cases/import/excel",
        json={"file_path": str(workbook_path)},
    )

    assert response.status_code == 200
    assert [case["automation_key"] for case in response.json()] == [
        "legacy_case",
        "deleted_case",
        "active_case_001",
    ]


def test_connector_normalizers_share_automation_key_policy() -> None:
    testrail_cases = normalize_testrail_cases(
        [
            {"id": 1, "title": "Checkout", "custom_automation_key": "Checkout Works"},
            {"id": 2, "title": "Checkout duplicate", "custom_automation_key": "checkout_works"},
        ],
        project_id=12,
        suite_id=None,
        config={"base_url": "https://testrail.example"},
        existing_keys=set(),
    )
    sheet_cases = normalize_google_sheet_values(
        [
            ["Case ID", "Title", "Step", "Expected Result", "Automation Key"],
            ["GS-1", "Sheet checkout", "Open", "Visible", "Checkout Works"],
            ["GS-2", "Sheet checkout duplicate", "Open", "Visible", "checkout_works"],
        ],
        "sheet-123",
        "Cases",
        mapping=ExcelColumnMapping(),
        existing_keys=set(),
    )

    assert [case.automation_key for case in testrail_cases] == ["checkout_works", "checkout_works_001"]
    assert [case.automation_key for case in sheet_cases] == ["checkout_works", "checkout_works_001"]


@patch("worker.routers.cases.import_from_testrail_clone", new_callable=AsyncMock)
def test_testrail_clone_import_save_guard_suffixes_duplicate_connector_keys(
    mock_import: AsyncMock,
    client: TestClient,
    project_id: str,
) -> None:
    mock_import.return_value = [
        NormalizedTestCase(
            source_type="testrail-clone",
            source_id="CLONE-1",
            title="Clone duplicate one",
            steps=[ImportStep(index=1, action="Open", expected="Visible")],
            automation_key="Clone Case",
        ),
        NormalizedTestCase(
            source_type="testrail-clone",
            source_id="CLONE-2",
            title="Clone duplicate two",
            steps=[ImportStep(index=1, action="Open", expected="Visible")],
            automation_key="clone_case",
        ),
    ]

    response = client.post(
        f"/projects/{project_id}/cases/import/testrail-clone",
        json={"project_id": "demo-project", "suite_id": "suite-1"},
    )

    assert response.status_code == 200
    assert [case["automation_key"] for case in response.json()] == ["clone_case", "clone_case_001"]


def test_generation_rejects_duplicate_active_automation_keys_before_overwrite(
    monkeypatch: pytest.MonkeyPatch,
    project_id: str,
    tmp_path: Path,
) -> None:
    import worker.services.project_generator as project_generator

    template = tmp_path / "template"
    template.mkdir()
    monkeypatch.setattr(project_generator, "load_settings", lambda: None)
    monkeypatch.setattr(
        project_generator,
        "resolve_runtime",
        lambda _settings: SimpleNamespace(template_path=str(template)),
    )
    with Session(_db_engine()) as session:
        session.add(DbTestCase(
            id="tc_duplicate_a",
            project_id=project_id,
            source_type="excel",
            source_case_id="A",
            title="Duplicate A",
            automation_key="Duplicate Key",
            status="mapped",
        ))
        session.add(DbTestCase(
            id="tc_duplicate_b",
            project_id=project_id,
            source_type="excel",
            source_case_id="B",
            title="Duplicate B",
            automation_key="duplicate_key",
            status="mapped",
        ))
        session.commit()

        with pytest.raises(ValueError, match="Duplicate active automation_key"):
            generate_project(session, project_id, tmp_path / "project", mode="full")


def test_mapping_merge_rejects_duplicate_existing_or_replacement_keys() -> None:
    with pytest.raises(ValueError, match="Existing mappings/cases.yaml contains duplicate automationKey"):
        _merge_mapping_entries(
            [{"automationKey": "case_a"}, {"automationKey": "case_a"}],
            [{"automationKey": "case_b"}],
        )

    with pytest.raises(ValueError, match="Replacement mappings contains duplicate automationKey"):
        _merge_mapping_entries(
            [{"automationKey": "case_a"}],
            [{"automationKey": "case_b"}, {"automationKey": "case_b"}],
        )


def test_export_validation_reports_duplicate_result_and_active_case_identity(
    project_id: str,
) -> None:
    with Session(_db_engine()) as session:
        execution = ExecutionRun(
            id="exec_duplicate_identity",
            project_id=project_id,
            run_id="run_duplicate_identity",
            env="stg",
            browser="chromium",
            status="completed",
        )
        session.add(execution)
        session.add(DbTestCase(
            id="tc_export_duplicate_a",
            project_id=project_id,
            source_type="excel",
            source_case_id="A",
            title="Export duplicate A",
            automation_key="Export Duplicate",
            status="imported",
        ))
        session.add(DbTestCase(
            id="tc_export_duplicate_b",
            project_id=project_id,
            source_type="excel",
            source_case_id="B",
            title="Export duplicate B",
            automation_key="export_duplicate",
            status="mapped",
        ))
        for result_id in ["res_duplicate_a", "res_duplicate_b"]:
            session.add(ExecutionResult(
                id=result_id,
                execution_run_id=execution.id,
                automation_key="export_duplicate",
                source_type="excel",
                source_case_id="A",
                title="Export duplicate",
                status="passed",
            ))
        session.commit()

        validation = _validate_export(
            session,
            execution,
            [
                {
                    "automationKey": "export_duplicate",
                    "sourceType": "excel",
                    "sourceCaseId": "A",
                    "status": "passed",
                },
                {
                    "automationKey": "export_duplicate",
                    "sourceType": "excel",
                    "sourceCaseId": "A",
                    "status": "failed",
                },
            ],
            [
                {
                    "automationKey": "export_duplicate",
                    "sourceType": "excel",
                    "sourceCaseId": "A",
                    "resultTargets": {"excel": {"file": "cases.xlsx", "row": 2}},
                }
            ],
        )

    kinds = {issue["kind"] for issue in validation["issues"]}
    assert validation["ok"] is False
    assert {
        "ambiguous_active_case",
        "ambiguous_execution_result",
        "ambiguous_result_update",
    }.issubset(kinds)
