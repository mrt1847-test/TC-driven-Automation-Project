from __future__ import annotations

from pathlib import Path

from sqlmodel import Session, select

from worker.core.runtime import resolve_runtime
from worker.models.db import Project, TestCase, WebwrightRun, WebwrightRunStatus
from worker.services.action_extraction import enrich_from_trajectory, extract_actions_from_script
from worker.services.project_generator import GenerationResult, generate_project
from worker.services.selector_candidates import extract_selector_candidates_for_run
from worker.services.structuring_service import merge_refreshed_raw_actions
from worker.services.webwright_adapter import create_mock_run, run_webwright_for_case


def _run_summary(run: WebwrightRun, mode: str) -> dict:
    return {
        "id": run.id,
        "mode": mode,
        "status": run.status,
        "error": run.error_message,
        "outputPath": run.output_path,
        "finalScriptPath": run.final_script_path,
        "trajectoryPath": run.trajectory_path,
    }


def _generation_summary(result: GenerationResult) -> dict:
    return {
        "mode": result.mode,
        "selectedCaseIds": result.selected_case_ids,
        "affectedFiles": result.affected_files,
        "changedFiles": result.changed_files,
        "preservedFiles": result.preserved_files,
    }


async def refresh_and_regenerate_case(
    session: Session,
    project: Project,
    case: TestCase,
    *,
    model_config: str,
    job_id: str,
) -> dict:
    previous_run_ids = list(session.exec(
        select(WebwrightRun.id)
        .where(WebwrightRun.project_id == project.id, WebwrightRun.test_case_id == case.id)
        .order_by(WebwrightRun.created_at, WebwrightRun.id)
    ).all())

    profile = resolve_runtime()
    run_mode = "live" if profile.check_webwright_readiness().live_ok else "mock"
    if run_mode == "live":
        run = await run_webwright_for_case(session, project.id, case, model_config, job_id)
    else:
        run = await create_mock_run(session, project.id, case, job_id)

    base_result = {
        "jobId": job_id,
        "projectId": project.id,
        "caseId": case.id,
        "automationKey": case.automation_key,
        "previousRunIds": previous_run_ids,
        "run": _run_summary(run, run_mode),
        "merge": None,
        "generation": None,
    }
    if run.status != WebwrightRunStatus.completed.value or not run.final_script_path:
        return {"status": "run_failed", **base_result}

    actions = extract_actions_from_script(run.final_script_path, case.automation_key, run.id, session)
    enrich_from_trajectory(actions, run.trajectory_path)
    extract_selector_candidates_for_run(session, run.id)
    merge = merge_refreshed_raw_actions(session, project.id, case, run)
    if merge["status"] != "merged":
        return {
            "status": "needs_review",
            **base_result,
            "merge": merge,
        }

    try:
        generation = generate_project(
            session,
            project.id,
            Path(project.root_path),
            [case.id],
            mode="incremental",
        )
    except ValueError as exc:
        return {
            "status": "generation_failed",
            **base_result,
            "merge": merge,
            "generation": {"error": str(exc)},
        }
    project.generated_project_path = str(generation.output)
    session.add(project)
    session.commit()
    return {
        "status": "completed",
        **base_result,
        "merge": merge,
        "generation": _generation_summary(generation),
    }
