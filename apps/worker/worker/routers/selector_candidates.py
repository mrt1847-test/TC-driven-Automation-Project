from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from worker.core.database import get_session
from worker.models.db import TestCase
from worker.services.selector_candidate_read import list_case_selector_candidates

router = APIRouter(
    prefix="/projects/{project_id}/cases/{case_id}/selector-candidates",
    tags=["selector-candidates"],
)


def _get_case(session: Session, project_id: str, case_id: str) -> TestCase:
    case = session.get(TestCase, case_id)
    if not case or case.project_id != project_id:
        raise HTTPException(404, "Case not found")
    return case


@router.get("")
def list_selector_candidates(
    project_id: str,
    case_id: str,
    session: Session = Depends(get_session),
):
    case = _get_case(session, project_id, case_id)
    return list_case_selector_candidates(session, case)
