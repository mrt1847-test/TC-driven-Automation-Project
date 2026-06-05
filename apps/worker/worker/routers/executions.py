from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlmodel import Session, select

from worker.core.database import get_session
from worker.models.db import ExecutionResult, ExecutionRun, Project, TestCase
from worker.models.schemas import (
    DispositionRetireRequest,
    ExecutionRequest,
    ExportRequest,
    HealingProposalCreateRequest,
)
from worker.services.healing_proposals import create_selector_healing_proposal
from worker.services.retire_disposition import (
    preview_retire_from_failure_disposition,
    retire_from_failure_disposition,
)
from worker.services.project_runner import rerun_failed, run_project
from worker.services.failure_disposition import diagnose_execution_failures
from worker.services.result_export import (
    ExportValidationError,
    export_excel,
    export_google_sheets,
    export_testrail,
    export_testrail_clone,
)

router = APIRouter(prefix="/projects/{project_id}/executions", tags=["executions"])


def _get_execution_run(session: Session, project_id: str, execution_id: str) -> ExecutionRun:
    run = session.get(ExecutionRun, execution_id)
    if not run or run.project_id != project_id:
        raise HTTPException(404, "Execution not found")
    return run


async def _run_execution(project_id: str, request: ExecutionRequest, job_id: str):
    from worker.core.database import engine
    from sqlmodel import Session as SQLSession

    with SQLSession(engine) as session:
        project = session.get(Project, project_id)
        if project:
            await run_project(session, project, request, job_id)


async def _rerun_failed_execution(project_id: str, execution_id: str, job_id: str):
    from worker.core.database import engine
    from sqlmodel import Session as SQLSession

    with SQLSession(engine) as session:
        project = session.get(Project, project_id)
        if project:
            await rerun_failed(session, project, execution_id, job_id)


@router.post("")
async def create_execution(project_id: str, request: ExecutionRequest, background: BackgroundTasks, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    job_id = f"exec_{project_id}"
    background.add_task(_run_execution, project_id, request, job_id)
    return {"jobId": job_id, "status": "queued"}


@router.get("")
def list_executions(project_id: str, session: Session = Depends(get_session)):
    return session.exec(select(ExecutionRun).where(ExecutionRun.project_id == project_id)).all()


@router.get("/{execution_id}")
def get_execution(project_id: str, execution_id: str, session: Session = Depends(get_session)):
    run = _get_execution_run(session, project_id, execution_id)
    results = session.exec(select(ExecutionResult).where(ExecutionResult.execution_run_id == execution_id)).all()
    summary = None
    if run.result_path and Path(run.result_path).exists():
        summary = json.loads(Path(run.result_path).read_text(encoding="utf-8"))
    return {"run": run, "results": results, "summary": summary}


@router.post("/{execution_id}/diagnose")
def diagnose_execution(project_id: str, execution_id: str, session: Session = Depends(get_session)):
    run = _get_execution_run(session, project_id, execution_id)
    return diagnose_execution_failures(session, run)


@router.post("/{execution_id}/healing-proposals")
def create_healing_proposal(
    project_id: str,
    execution_id: str,
    request: HealingProposalCreateRequest,
    session: Session = Depends(get_session),
):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    run = _get_execution_run(session, project_id, execution_id)
    result = session.get(ExecutionResult, request.execution_result_id)
    if not result or result.execution_run_id != execution_id:
        raise HTTPException(404, "Execution result not found")
    try:
        return create_selector_healing_proposal(session, project, run, result)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{execution_id}/results/{result_id}/retire/preview")
def preview_retire_execution_result(
    project_id: str,
    execution_id: str,
    result_id: str,
    request: DispositionRetireRequest,
    session: Session = Depends(get_session),
):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    run = _get_execution_run(session, project_id, execution_id)
    result = session.get(ExecutionResult, result_id)
    if not result or result.execution_run_id != execution_id:
        raise HTTPException(404, "Execution result not found")
    case = session.get(TestCase, request.case_id)
    if not case or case.project_id != project_id:
        raise HTTPException(404, "Case not found")
    try:
        return preview_retire_from_failure_disposition(session, project, run, result, case, request)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{execution_id}/results/{result_id}/retire")
def retire_execution_result(
    project_id: str,
    execution_id: str,
    result_id: str,
    request: DispositionRetireRequest,
    session: Session = Depends(get_session),
):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    run = _get_execution_run(session, project_id, execution_id)
    result = session.get(ExecutionResult, result_id)
    if not result or result.execution_run_id != execution_id:
        raise HTTPException(404, "Execution result not found")
    case = session.get(TestCase, request.case_id)
    if not case or case.project_id != project_id:
        raise HTTPException(404, "Case not found")
    try:
        return retire_from_failure_disposition(session, project, run, result, case, request)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{execution_id}/rerun-failed")
async def rerun_failed_execution(project_id: str, execution_id: str, background: BackgroundTasks, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    _get_execution_run(session, project_id, execution_id)
    job_id = f"rerun_{execution_id}"
    background.add_task(_rerun_failed_execution, project_id, execution_id, job_id)
    return {"jobId": job_id, "status": "queued"}


@router.post("/{execution_id}/cancel")
def cancel_execution(project_id: str, execution_id: str, session: Session = Depends(get_session)):
    run = _get_execution_run(session, project_id, execution_id)
    run.status = "cancelled"
    session.add(run)
    session.commit()
    return run


export_router = APIRouter(prefix="/projects/{project_id}/executions/{execution_id}/export", tags=["export"])


def _raise_export_error(exc: Exception) -> None:
    raise HTTPException(400, str(exc)) from exc


@export_router.post("/testrail-clone")
async def export_tc(project_id: str, execution_id: str, request: ExportRequest, session: Session = Depends(get_session)):
    run = _get_execution_run(session, project_id, execution_id)
    try:
        return await export_testrail_clone(session, run, request.preview)
    except (ExportValidationError, FileNotFoundError) as exc:
        _raise_export_error(exc)


@export_router.post("/testrail")
async def export_tr(project_id: str, execution_id: str, request: ExportRequest, session: Session = Depends(get_session)):
    run = _get_execution_run(session, project_id, execution_id)
    try:
        return await export_testrail(session, run, request.preview)
    except (ExportValidationError, FileNotFoundError) as exc:
        _raise_export_error(exc)


@export_router.post("/excel")
def export_xl(project_id: str, execution_id: str, request: ExportRequest, session: Session = Depends(get_session)):
    run = _get_execution_run(session, project_id, execution_id)
    try:
        return export_excel(session, run, request.preview)
    except (ExportValidationError, FileNotFoundError) as exc:
        _raise_export_error(exc)


@export_router.post("/google-sheets")
async def export_gs(project_id: str, execution_id: str, request: ExportRequest, session: Session = Depends(get_session)):
    run = _get_execution_run(session, project_id, execution_id)
    try:
        return await export_google_sheets(session, run, request.preview)
    except (ExportValidationError, FileNotFoundError) as exc:
        _raise_export_error(exc)
