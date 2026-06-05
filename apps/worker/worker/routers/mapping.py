from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from worker.core.database import get_session
from worker.models.db import TestCase, WebwrightRun
from worker.models.schemas import (
    ActionCreateRequest,
    ActionUpdateRequest,
    MappingUpdateRequest,
    StepActionCreateRequest,
    StepActionUpdateRequest,
)
from worker.services.mapping import (
    MappingValidationError,
    auto_map_case,
    create_action,
    delete_action,
    get_actions,
    get_mappings,
    insert_step_review_action,
    update_action,
    update_mappings,
    update_step_review_action,
)
from sqlmodel import select

router = APIRouter(prefix="/projects/{project_id}/cases/{case_id}", tags=["mapping"])


def _get_case(session: Session, project_id: str, case_id: str) -> TestCase:
    case = session.get(TestCase, case_id)
    if not case or case.project_id != project_id:
        raise HTTPException(404, "Case not found")
    return case


@router.get("/actions")
def list_actions(project_id: str, case_id: str, session: Session = Depends(get_session)):
    _get_case(session, project_id, case_id)
    run = session.exec(
        select(WebwrightRun)
        .where(WebwrightRun.project_id == project_id, WebwrightRun.test_case_id == case_id)
        .order_by(WebwrightRun.created_at.desc())
    ).first()
    if not run:
        return []
    return get_actions(session, run.id)


@router.post("/actions", status_code=201)
def add_action(project_id: str, case_id: str, request: ActionCreateRequest, session: Session = Depends(get_session)):
    case = _get_case(session, project_id, case_id)
    try:
        return create_action(session, case, request)
    except MappingValidationError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.patch("/actions/{action_id}")
def patch_action(
    project_id: str,
    case_id: str,
    action_id: str,
    request: ActionUpdateRequest,
    session: Session = Depends(get_session),
):
    case = _get_case(session, project_id, case_id)
    try:
        return update_action(session, case, action_id, request)
    except MappingValidationError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/actions/{action_id}")
def remove_action(project_id: str, case_id: str, action_id: str, session: Session = Depends(get_session)):
    case = _get_case(session, project_id, case_id)
    try:
        return delete_action(session, case, action_id)
    except MappingValidationError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/steps/{tc_step_index}/actions", status_code=201)
def add_step_action(
    project_id: str,
    case_id: str,
    tc_step_index: int,
    request: StepActionCreateRequest,
    session: Session = Depends(get_session),
):
    case = _get_case(session, project_id, case_id)
    try:
        return insert_step_review_action(session, case, tc_step_index, request)
    except MappingValidationError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.patch("/steps/{tc_step_index}/actions/{action_id}")
def patch_step_action(
    project_id: str,
    case_id: str,
    tc_step_index: int,
    action_id: str,
    request: StepActionUpdateRequest,
    session: Session = Depends(get_session),
):
    case = _get_case(session, project_id, case_id)
    try:
        return update_step_review_action(session, case, tc_step_index, action_id, request)
    except MappingValidationError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/mappings")
def list_mappings(project_id: str, case_id: str, session: Session = Depends(get_session)):
    _get_case(session, project_id, case_id)
    return get_mappings(session, case_id)


@router.put("/mappings")
def save_mappings(project_id: str, case_id: str, request: MappingUpdateRequest, session: Session = Depends(get_session)):
    case = _get_case(session, project_id, case_id)
    try:
        return update_mappings(session, case, request)
    except MappingValidationError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/normalize")
def normalize_case(project_id: str, case_id: str, session: Session = Depends(get_session)):
    case = _get_case(session, project_id, case_id)
    run = session.exec(
        select(WebwrightRun)
        .where(WebwrightRun.project_id == project_id, WebwrightRun.test_case_id == case_id)
        .order_by(WebwrightRun.created_at.desc())
    ).first()
    if not run:
        raise HTTPException(400, "No webwright run")
    mappings, status = auto_map_case(session, case, run.id)
    return {"mappings": mappings, "status": status}
