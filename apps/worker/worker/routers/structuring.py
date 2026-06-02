from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from worker.core.database import get_session
from worker.models.db import Project, TestCase
from worker.services.structuring_service import sync_structured_entities, validate_structure
from worker.models.db import WebwrightRun
from sqlmodel import select

router = APIRouter(prefix="/projects/{project_id}/cases/{case_id}/structure", tags=["structuring"])


@router.post("/sync")
def sync_structure(project_id: str, case_id: str, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    case = session.get(TestCase, case_id)
    if not project or not case or case.project_id != project_id:
        raise HTTPException(404, "Case not found")
    run = session.exec(
        select(WebwrightRun).where(WebwrightRun.test_case_id == case_id).order_by(WebwrightRun.created_at.desc())
    ).first()
    flow = sync_structured_entities(session, project_id, case, run)
    session.commit()
    return {"flowId": flow.id, "automationKey": case.automation_key}


@router.get("/validate")
def validate(project_id: str, case_id: str, session: Session = Depends(get_session)):
    case = session.get(TestCase, case_id)
    if not case or case.project_id != project_id:
        raise HTTPException(404, "Case not found")
    return validate_structure(session, project_id, case_id)
