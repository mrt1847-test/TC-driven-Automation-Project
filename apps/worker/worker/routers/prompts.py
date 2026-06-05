from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from worker.core.database import get_session
from worker.models.db import Project
from worker.models.schemas import PromptComposerUpdateRequest, PromptPresetUpdateRequest, PromptPreviewRequest
from worker.services.prompt_context import get_prompt_composer, update_prompt_composer
from worker.services.prompt_payloads import get_webwright_prompt_payload, list_webwright_prompt_payloads
from worker.services.prompt_preview import preview_webwright_prompt
from worker.services.prompt_presets import list_prompt_presets, replace_project_prompt_presets

router = APIRouter(prefix="/projects/{project_id}/prompt-composer", tags=["prompts"])
preset_router = APIRouter(prefix="/projects/{project_id}/prompt-presets", tags=["prompts"])
preview_router = APIRouter(prefix="/projects/{project_id}/prompt-preview", tags=["prompts"])
payload_router = APIRouter(prefix="/projects/{project_id}/prompt-payloads", tags=["prompts"])


def _get_project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@router.get("")
def read_prompt_composer(project_id: str, session: Session = Depends(get_session)):
    project = _get_project(session, project_id)
    return get_prompt_composer(session, project)


@router.put("")
def save_prompt_composer(
    project_id: str,
    request: PromptComposerUpdateRequest,
    session: Session = Depends(get_session),
):
    project = _get_project(session, project_id)
    try:
        return update_prompt_composer(session, project, request)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@preset_router.get("")
def read_prompt_presets(project_id: str, session: Session = Depends(get_session)):
    project = _get_project(session, project_id)
    return list_prompt_presets(session, project)


@preset_router.put("")
def save_prompt_presets(
    project_id: str,
    request: PromptPresetUpdateRequest,
    session: Session = Depends(get_session),
):
    project = _get_project(session, project_id)
    try:
        return replace_project_prompt_presets(session, project, request)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@preview_router.post("")
def preview_prompt(
    project_id: str,
    request: PromptPreviewRequest,
    session: Session = Depends(get_session),
):
    project = _get_project(session, project_id)
    try:
        return preview_webwright_prompt(session, project, request)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@payload_router.get("")
def read_prompt_payloads(
    project_id: str,
    case_id: str | None = Query(default=None, alias="caseId"),
    run_id: str | None = Query(default=None, alias="runId"),
    case_id_snake: str | None = Query(default=None, alias="case_id"),
    run_id_snake: str | None = Query(default=None, alias="run_id"),
    session: Session = Depends(get_session),
):
    project = _get_project(session, project_id)
    return list_webwright_prompt_payloads(
        session,
        project,
        case_id=case_id or case_id_snake,
        run_id=run_id or run_id_snake,
    )


@payload_router.get("/{payload_id}")
def read_prompt_payload(
    project_id: str,
    payload_id: str,
    session: Session = Depends(get_session),
):
    project = _get_project(session, project_id)
    try:
        return get_webwright_prompt_payload(session, project, payload_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
