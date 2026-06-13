from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from worker.core.config import load_settings, new_id
from worker.core.database import get_session
from worker.models.db import Project, TestCase, TestCaseStatus
from worker.models.schemas import (
    ExcelImportRequest,
    ExcelPreviewRequest,
    GoogleSheetsImportRequest,
    TestRailCloneImportRequest,
    TestRailImportRequest,
)
from worker.services.case_import import case_to_normalized, import_excel, preview_excel
from worker.services.automation_keys import active_automation_keys, reserve_normalized_case_keys
from worker.services.integrations.google_sheets import GoogleSheetsConnectorError, import_from_google_sheets
from worker.services.integrations.testrail import TestRailConnectorError, import_from_testrail
from worker.services.integrations.testrail_clone import import_from_testrail_clone

router = APIRouter(prefix="/projects/{project_id}/cases", tags=["cases"])


def _get_project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@router.get("")
def list_cases(project_id: str, session: Session = Depends(get_session)):
    _get_project(session, project_id)
    return session.exec(select(TestCase).where(TestCase.project_id == project_id)).all()


@router.get("/{case_id}")
def get_case(project_id: str, case_id: str, session: Session = Depends(get_session)):
    case = session.get(TestCase, case_id)
    if not case or case.project_id != project_id:
        raise HTTPException(404, "Case not found")
    return case_to_normalized(case)


@router.patch("/{case_id}")
def patch_case(project_id: str, case_id: str, payload: dict, session: Session = Depends(get_session)):
    case = session.get(TestCase, case_id)
    if not case or case.project_id != project_id:
        raise HTTPException(404, "Case not found")
    if "startUrl" in payload:
        case.start_url = payload["startUrl"]
    if "status" in payload:
        case.status = payload["status"]
    session.add(case)
    session.commit()
    return case_to_normalized(case)


@router.post("/import/excel/preview")
def excel_preview(project_id: str, request: ExcelPreviewRequest, session: Session = Depends(get_session)):
    _get_project(session, project_id)
    return preview_excel(request, active_automation_keys(session, project_id))


@router.post("/import/excel")
def excel_import(project_id: str, request: ExcelImportRequest, session: Session = Depends(get_session)):
    _get_project(session, project_id)
    return import_excel(session, project_id, request)


@router.post("/import/testrail-clone/preview")
async def testrail_clone_preview(project_id: str, request: TestRailCloneImportRequest, session: Session = Depends(get_session)):
    _get_project(session, project_id)
    return await import_from_testrail_clone(request.project_id, request.suite_id, set())


@router.post("/import/testrail-clone")
async def testrail_clone_import(project_id: str, request: TestRailCloneImportRequest, session: Session = Depends(get_session)):
    _get_project(session, project_id)
    existing = active_automation_keys(session, project_id)
    imported = await import_from_testrail_clone(request.project_id, request.suite_id, existing)
    return _save_imported_cases(session, project_id, imported)


@router.post("/import/testrail/preview")
async def testrail_preview(project_id: str, request: TestRailImportRequest, session: Session = Depends(get_session)):
    _get_project(session, project_id)
    existing = active_automation_keys(session, project_id)
    try:
        return await import_from_testrail(request.project_id, request.suite_id, _testrail_config(request), existing)
    except TestRailConnectorError as error:
        raise HTTPException(error.status_code, error.message) from error


@router.post("/import/testrail")
async def testrail_import(project_id: str, request: TestRailImportRequest, session: Session = Depends(get_session)):
    _get_project(session, project_id)
    existing = active_automation_keys(session, project_id)
    try:
        imported = await import_from_testrail(request.project_id, request.suite_id, _testrail_config(request), existing)
    except TestRailConnectorError as error:
        raise HTTPException(error.status_code, error.message) from error
    return _save_imported_cases(session, project_id, imported)


def _testrail_config(request: TestRailImportRequest) -> dict:
    settings = load_settings()
    integration = settings.integrations.get("testrail", {})
    return {
        "base_url": request.base_url or integration.get("baseUrl") or integration.get("base_url") or "",
        "username": request.username or integration.get("username") or "",
        "api_token": request.api_token or "",
        "mock": request.mock or bool(integration.get("mock")),
    }


def _save_imported_cases(session: Session, project_id: str, imported):
    imported = reserve_normalized_case_keys(session, project_id, imported)
    saved = []
    for item in imported:
        item.id = new_id("tc")
        db = TestCase(
            id=item.id,
            project_id=project_id,
            source_type=item.source_type,
            source_case_id=item.source_id,
            title=item.title,
            steps_json=json.dumps([s.model_dump() for s in item.steps]),
            expected_result=item.expected_result,
            automation_key=item.automation_key,
            source_location_json=json.dumps(item.source_location.model_dump() if item.source_location else {}),
            preconditions_json=json.dumps(item.preconditions),
            tags_json=json.dumps(item.tags),
            priority=item.priority,
            start_url=item.start_url,
            status=TestCaseStatus.imported.value,
        )
        session.add(db)
        saved.append(item)
    session.commit()
    return saved


@router.post("/import/google-sheets/preview")
async def google_sheets_preview(project_id: str, request: GoogleSheetsImportRequest, session: Session = Depends(get_session)):
    _get_project(session, project_id)
    existing = active_automation_keys(session, project_id)
    try:
        return await import_from_google_sheets(
            _google_sheets_spreadsheet_id(request),
            request.sheet_name,
            request.column_mapping,
            _google_sheets_config(request),
            existing,
        )
    except GoogleSheetsConnectorError as error:
        raise HTTPException(error.status_code, error.message) from error


@router.post("/import/google-sheets")
async def google_sheets_import(project_id: str, request: GoogleSheetsImportRequest, session: Session = Depends(get_session)):
    _get_project(session, project_id)
    existing = active_automation_keys(session, project_id)
    try:
        imported = await import_from_google_sheets(
            _google_sheets_spreadsheet_id(request),
            request.sheet_name,
            request.column_mapping,
            _google_sheets_config(request),
            existing,
        )
    except GoogleSheetsConnectorError as error:
        raise HTTPException(error.status_code, error.message) from error
    return _save_imported_cases(session, project_id, imported)


def _google_sheets_config(request: GoogleSheetsImportRequest) -> dict:
    settings = load_settings()
    integration = settings.integrations.get("googleSheets", {})
    return {
        "credential_json": request.credential_json or "",
        "mock": request.mock or bool(integration.get("mock")),
    }


def _google_sheets_spreadsheet_id(request: GoogleSheetsImportRequest) -> str:
    if request.spreadsheet_id:
        return request.spreadsheet_id
    settings = load_settings()
    integration = settings.integrations.get("googleSheets", {})
    return str(integration.get("spreadsheetId") or integration.get("spreadsheet_id") or "")
