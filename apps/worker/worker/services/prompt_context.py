from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, select

from worker.models.db import CasePromptOverride, Project, ProjectPromptContext, TestCase
from worker.models.schemas import PromptComposerUpdateRequest


def _override_payload(row: CasePromptOverride) -> dict:
    return {
        "caseId": row.case_id,
        "automationKey": row.automation_key,
        "promptOverride": row.prompt_override,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
    }


def get_prompt_composer(session: Session, project: Project) -> dict:
    context = session.get(ProjectPromptContext, project.id)
    overrides = session.exec(
        select(CasePromptOverride)
        .where(CasePromptOverride.project_id == project.id)
        .order_by(CasePromptOverride.automation_key, CasePromptOverride.case_id)
    ).all()
    return {
        "projectId": project.id,
        "batchPrompt": context.batch_prompt if context else "",
        "caseOverrides": {
            row.case_id: row.prompt_override
            for row in overrides
            if row.prompt_override.strip()
        },
        "overrides": [_override_payload(row) for row in overrides],
    }


def update_prompt_composer(
    session: Session,
    project: Project,
    request: PromptComposerUpdateRequest,
) -> dict:
    project_id = project.id or ""
    requested_overrides = {
        case_id: value
        for case_id, value in request.case_overrides.items()
    }
    cases_by_id: dict[str, TestCase] = {}
    if requested_overrides:
        cases = session.exec(
            select(TestCase).where(TestCase.id.in_(list(requested_overrides)))
        ).all()
        cases_by_id = {case.id: case for case in cases if case.id}
        invalid_case_ids = sorted(
            case_id
            for case_id in requested_overrides
            if case_id not in cases_by_id or cases_by_id[case_id].project_id != project_id
        )
        if invalid_case_ids:
            raise ValueError(
                "Prompt overrides include cases outside this project: "
                + ", ".join(invalid_case_ids)
            )

    now = datetime.utcnow()
    context = session.get(ProjectPromptContext, project_id)
    if not context:
        context = ProjectPromptContext(
            project_id=project_id,
            created_at=now,
        )
    context.batch_prompt = request.batch_prompt
    context.updated_at = now
    session.add(context)

    existing = {
        row.case_id: row
        for row in session.exec(
            select(CasePromptOverride).where(CasePromptOverride.project_id == project_id)
        ).all()
    }
    for case_id, row in existing.items():
        if case_id not in requested_overrides or not requested_overrides[case_id].strip():
            session.delete(row)

    for case_id, value in requested_overrides.items():
        if not value.strip():
            continue
        case = cases_by_id[case_id]
        row = existing.get(case_id)
        if not row:
            row = CasePromptOverride(
                project_id=project_id,
                case_id=case_id,
                automation_key=case.automation_key,
                created_at=now,
            )
        row.automation_key = case.automation_key
        row.prompt_override = value
        row.updated_at = now
        session.add(row)

    session.commit()
    return get_prompt_composer(session, project)


def effective_prompt_context(session: Session, project_id: str, case: TestCase) -> dict:
    context = session.get(ProjectPromptContext, project_id)
    override = session.get(CasePromptOverride, (project_id, case.id))
    return {
        "batchPrompt": context.batch_prompt if context and context.batch_prompt.strip() else "",
        "casePromptOverride": (
            override.prompt_override
            if override and override.prompt_override.strip()
            else ""
        ),
    }
