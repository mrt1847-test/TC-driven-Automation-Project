from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from worker.core.config import new_id
from worker.core.database import get_session
from worker.models.db import Project, TestCase
from worker.models.schemas import (
    ExcelImportRequest,
    ExcelPreviewRequest,
    GoogleSheetsImportRequest,
    TestRailCloneImportRequest,
    TestRailImportRequest,
)
from worker.services.case_import import case_to_normalized, import_excel, preview_excel
from worker.services.integrations.google_sheets import import_from_google_sheets
from worker.services.integrations.testrail import import_from_testrail
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
    return preview_excel(request)


@router.post("/import/excel")
def excel_import(project_id: str, request: ExcelImportRequest, session: Session = Depends(get_session)):
    _get_project(session, project_id)
    return import_excel(session, project_id, request)


@router.post("/import/testrail-clone")
async def testrail_clone_import(project_id: str, request: TestRailCloneImportRequest, session: Session = Depends(get_session)):
    _get_project(session, project_id)
    existing = {c.automation_key for c in session.exec(select(TestCase).where(TestCase.project_id == project_id)).all()}
    imported = await import_from_testrail_clone(request.project_id, request.suite_id, existing)
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
            status="imported",
        )
        session.add(db)
        saved.append(item)
    session.commit()
    return saved


@router.post("/import/testrail")
async def testrail_import(project_id: str, request: TestRailImportRequest, session: Session = Depends(get_session)):
    _get_project(session, project_id)
    return await import_from_testrail(request.project_id, request.suite_id, {})


@router.post("/import/google-sheets")
async def google_sheets_import(project_id: str, request: GoogleSheetsImportRequest, session: Session = Depends(get_session)):
    _get_project(session, project_id)
    return await import_from_google_sheets(request.spreadsheet_id, request.sheet_name, request.column_mapping)
