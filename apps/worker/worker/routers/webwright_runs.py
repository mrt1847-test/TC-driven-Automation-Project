from __future__ import annotations

import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlmodel import Session, select

from worker.core.config import load_settings
from worker.core.database import get_session
from worker.models.db import Project, TestCase, WebwrightRun
from worker.models.schemas import WebwrightRunRequest
from worker.services.action_extraction import enrich_from_trajectory, extract_actions_from_script
from worker.services.mapping import auto_map_case
from worker.services.webwright_adapter import create_mock_run, run_webwright_for_case

router = APIRouter(prefix="/projects/{project_id}/webwright-runs", tags=["webwright"])


async def _process_runs(project_id: str, request: WebwrightRunRequest, job_id: str):
    from worker.core.database import engine
    from sqlmodel import Session as SQLSession

    with SQLSession(engine) as session:
        settings = load_settings()
        use_mock = not settings.webwright.get("root")
        for case_id in request.case_ids:
            case = session.get(TestCase, case_id)
            if not case or case.project_id != project_id:
                continue
            if use_mock:
                run = await create_mock_run(session, project_id, case, job_id)
            else:
                run = await run_webwright_for_case(session, project_id, case, request.ww_model_config, job_id)
            if run.final_script_path:
                actions = extract_actions_from_script(run.final_script_path, case.automation_key, run.id, session)
                enrich_from_trajectory(actions, run.trajectory_path)
                auto_map_case(session, case, run.id)


@router.post("")
async def create_runs(project_id: str, request: WebwrightRunRequest, background: BackgroundTasks, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    job_id = f"ww_{project_id}"
    background.add_task(_process_runs, project_id, request, job_id)
    return {"jobId": job_id, "caseIds": request.case_ids, "status": "queued"}


@router.get("")
def list_runs(project_id: str, session: Session = Depends(get_session)):
    return session.exec(select(WebwrightRun).where(WebwrightRun.project_id == project_id)).all()


@router.get("/{run_id}")
def get_run(project_id: str, run_id: str, session: Session = Depends(get_session)):
    run = session.get(WebwrightRun, run_id)
    if not run or run.project_id != project_id:
        raise HTTPException(404, "Run not found")
    return run


@router.post("/{run_id}/retry")
async def retry_run(project_id: str, run_id: str, background: BackgroundTasks, session: Session = Depends(get_session)):
    run = session.get(WebwrightRun, run_id)
    if not run or run.project_id != project_id:
        raise HTTPException(404, "Run not found")
    case = session.get(TestCase, run.test_case_id)
    if not case or case.project_id != project_id:
        raise HTTPException(404, "Case not found")
    job_id = f"ww_retry_{run_id}"
    background.add_task(_process_runs, project_id, WebwrightRunRequest(case_ids=[case.id]), job_id)
    return {"jobId": job_id, "status": "queued"}


@router.post("/{run_id}/cancel")
def cancel_run(project_id: str, run_id: str, session: Session = Depends(get_session)):
    run = session.get(WebwrightRun, run_id)
    if not run or run.project_id != project_id:
        raise HTTPException(404, "Run not found")
    run.status = "cancelled"
    session.add(run)
    session.commit()
    return run
