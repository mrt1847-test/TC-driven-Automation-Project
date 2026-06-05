from __future__ import annotations

from pathlib import Path

from sqlmodel import Session

from worker.models.db import ExecutionResult, ExecutionRun, Project, TestCase
from worker.models.schemas import DispositionRetireRequest
from worker.services.failure_disposition import classify_failure_disposition
from worker.services.project_generator import retire_generated_case


def retire_from_failure_disposition(
    session: Session,
    project: Project,
    execution_run: ExecutionRun,
    result: ExecutionResult,
    case: TestCase,
    request: DispositionRetireRequest,
) -> dict:
    if not request.confirmed:
        raise ValueError("Retire disposition action requires confirmed=true")
    if execution_run.project_id != project.id:
        raise ValueError("Execution does not belong to project")
    if result.execution_run_id != execution_run.id:
        raise ValueError("Execution result does not belong to execution")
    if case.project_id != project.id:
        raise ValueError("Case does not belong to project")

    diagnosis = classify_failure_disposition(session, result.id or "")
    target = diagnosis.target
    if target.status != "resolved":
        raise ValueError(f"Failure target is not resolved: {target.status}")
    if diagnosis.disposition != "feature_removed_retire_tc":
        raise ValueError(
            "Failure disposition is not feature_removed_retire_tc: "
            f"{diagnosis.disposition}"
        )
    if target.project_id != project.id or target.execution_run_id != execution_run.id:
        raise ValueError("Failure diagnosis target does not match execution")
    if (
        diagnosis.automation_key != case.automation_key
        or target.automation_key != case.automation_key
        or result.automation_key != case.automation_key
    ):
        raise ValueError("Failure diagnosis automation key does not match selected case")
    if target.test_case_ids != [case.id]:
        raise ValueError("Failure diagnosis target does not match selected case")
    if target.source_case_id and target.source_case_id != case.source_case_id:
        raise ValueError("Failure diagnosis source case does not match selected case")
    if result.source_case_id and result.source_case_id != case.source_case_id:
        raise ValueError("Execution result source case does not match selected case")
    if result.source_type and result.source_type != case.source_type:
        raise ValueError("Execution result source type does not match selected case")

    output = Path(project.generated_project_path or Path(project.root_path) / "generated")
    cleanup = retire_generated_case(
        session,
        project.id or "",
        output,
        case.id or "",
        action=request.action,
        reason=diagnosis.reason,
    )
    return {
        "status": cleanup["status"],
        "projectId": project.id,
        "executionId": execution_run.id,
        "executionResultId": result.id,
        "caseId": case.id,
        "automationKey": case.automation_key,
        "diagnosis": diagnosis.model_dump(),
        "cleanup": cleanup,
    }
