from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from worker.core.database import get_session
from worker.models.db import TestCase, WebwrightRun
from worker.models.schemas import MappingUpdateRequest
from worker.services.mapping import auto_map_case, get_actions, get_mappings, update_mappings
from sqlmodel import select

router = APIRouter(prefix="/projects/{project_id}/cases/{case_id}", tags=["mapping"])


@router.get("/actions")
def list_actions(project_id: str, case_id: str, session: Session = Depends(get_session)):
    case = session.get(TestCase, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    run = session.exec(select(WebwrightRun).where(WebwrightRun.test_case_id == case_id).order_by(WebwrightRun.created_at.desc())).first()
    if not run:
        return []
    return get_actions(session, run.id)


@router.get("/mappings")
def list_mappings(project_id: str, case_id: str, session: Session = Depends(get_session)):
    case = session.get(TestCase, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    return get_mappings(session, case_id)


@router.put("/mappings")
def save_mappings(project_id: str, case_id: str, request: MappingUpdateRequest, session: Session = Depends(get_session)):
    case = session.get(TestCase, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    return update_mappings(session, case, request)


@router.post("/normalize")
def normalize_case(project_id: str, case_id: str, session: Session = Depends(get_session)):
    case = session.get(TestCase, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    run = session.exec(select(WebwrightRun).where(WebwrightRun.test_case_id == case_id).order_by(WebwrightRun.created_at.desc())).first()
    if not run:
        raise HTTPException(400, "No webwright run")
    mappings, status = auto_map_case(session, case, run.id)
    return {"mappings": mappings, "status": status}
