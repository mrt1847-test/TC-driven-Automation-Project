from __future__ import annotations

import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlmodel import Session, select

from worker.core.runtime import resolve_runtime
from worker.core.database import get_session
from worker.core.log_stream import log_streams
from worker.models.db import Project, TestCase, WebwrightRun
from worker.models.schemas import WebwrightRunRequest
from worker.services.action_extraction import enrich_from_trajectory, extract_actions_from_script
from worker.services.mapping import auto_map_case
from worker.services.selector_candidates import extract_selector_candidates_for_run
from worker.services.structuring_service import get_latest_flow, merge_refreshed_raw_actions
from worker.models.db import WebwrightRunStatus
from worker.services.webwright_adapter import cancel_webwright_run, create_mock_run, run_webwright_for_case

router = APIRouter(prefix="/projects/{project_id}/webwright-runs", tags=["webwright"])


async def _process_runs(project_id: str, request: WebwrightRunRequest, job_id: str):
    from worker.core.database import engine
    from sqlmodel import Session as SQLSession

    with SQLSession(engine) as session:
        profile = resolve_runtime()
        webwright_readiness = profile.check_webwright_readiness()
        use_mock = not webwright_readiness.live_ok
        for case_id in request.case_ids:
            case = session.get(TestCase, case_id)
            if not case or case.project_id != project_id:
                continue
            if use_mock:
                run = await create_mock_run(
                    session,
                    project_id,
                    case,
                    job_id,
                    model_config=request.ww_model_config,
                    preset_id=request.preset_id,
                    environment=request.environment,
                    start_url_override=request.start_url_override,
                )
            else:
                run = await run_webwright_for_case(
                    session,
                    project_id,
                    case,
                    request.ww_model_config,
                    job_id,
                    preset_id=request.preset_id,
                    environment=request.environment,
                    start_url_override=request.start_url_override,
                )
            if run.status == WebwrightRunStatus.completed.value and run.final_script_path:
                actions = extract_actions_from_script(run.final_script_path, case.automation_key, run.id, session)
                enrich_from_trajectory(actions, run.trajectory_path)
                extract_selector_candidates_for_run(session, run.id)
                if get_latest_flow(session, case.id):
                    result = merge_refreshed_raw_actions(session, project_id, case, run)
                    await log_streams.publish(
                        job_id,
                        f"[raw-refresh] {case.automation_key}: {result['status']}"
                        + (f" ({result['reason']})" if result.get("reason") else ""),
                    )
                else:
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
async def cancel_run(project_id: str, run_id: str, session: Session = Depends(get_session)):
    run = session.get(WebwrightRun, run_id)
    if not run or run.project_id != project_id:
        raise HTTPException(404, "Run not found")
    run.status = WebwrightRunStatus.cancelled.value
    case = session.get(TestCase, run.test_case_id)
    if case and case.project_id == project_id:
        case.status = "cancelled"
        session.add(case)
    session.add(run)
    session.commit()
    await cancel_webwright_run(run_id)
    session.refresh(run)
    return run
