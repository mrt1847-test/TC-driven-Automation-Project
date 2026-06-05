from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, select

from worker.core.config import new_id
from worker.models.db import Project, PromptPreset, TestCase, WebwrightPromptPayload, WebwrightRun
from worker.services.case_import import case_to_normalized
from worker.services.prompt_builder import build_webwright_prompt
from worker.services.prompt_context import effective_prompt_context
from worker.services.prompt_presets import BUILT_IN_PROMPT_PRESETS


def _builtin_preset_payload(preset_id: str) -> dict | None:
    for preset in BUILT_IN_PROMPT_PRESETS:
        if preset["id"] == preset_id:
            return {
                "id": preset["id"],
                "projectId": None,
                "category": preset["category"],
                "name": preset["name"],
                "guidance": preset["guidance"],
                "isBuiltin": True,
            }
    return None


def _preset_payload(row: PromptPreset) -> dict:
    return {
        "id": row.id,
        "projectId": row.project_id,
        "category": row.category,
        "name": row.name,
        "guidance": row.guidance,
        "isBuiltin": row.is_builtin,
    }


def resolve_prompt_preset_snapshot(session: Session, project: Project, preset_id: str | None) -> dict | None:
    if not preset_id:
        return None
    row = session.get(PromptPreset, preset_id)
    if row:
        if row.is_builtin or row.project_id == project.id:
            return _preset_payload(row)
        raise ValueError(f"Prompt preset does not belong to project: {preset_id}")
    builtin = _builtin_preset_payload(preset_id)
    if builtin:
        return builtin
    raise ValueError(f"Prompt preset not found: {preset_id}")


def build_webwright_prompt_payload_components(
    session: Session,
    project: Project,
    case: TestCase,
    *,
    preset_id: str | None = None,
    environment: str = "stg",
    start_url_override: str | None = None,
) -> dict:
    preset = resolve_prompt_preset_snapshot(session, project, preset_id)
    context = effective_prompt_context(session, project.id or "", case)
    normalized = case_to_normalized(case)
    start_url = start_url_override or case.start_url or "https://example.com"
    base_prompt = build_webwright_prompt(
        normalized,
        start_url=start_url,
        environment=environment,
    )
    final_prompt = build_webwright_prompt(
        normalized,
        start_url=start_url,
        environment=environment,
        preset_guidance=preset["guidance"] if preset else None,
        batch_prompt=context["batchPrompt"],
        case_prompt_override=context["casePromptOverride"],
    )
    return {
        "preset": preset,
        "parts": {
            "basePrompt": base_prompt,
            "presetGuidance": preset["guidance"] if preset else "",
            "batchPrompt": context["batchPrompt"],
            "casePromptOverride": context["casePromptOverride"],
        },
        "prompt": final_prompt,
        "startUrl": start_url,
        "environment": environment,
    }


def prompt_payload_to_dict(row: WebwrightPromptPayload) -> dict:
    return {
        "id": row.id,
        "projectId": row.project_id,
        "caseId": row.test_case_id,
        "webwrightRunId": row.webwright_run_id,
        "automationKey": row.automation_key,
        "prompt": row.final_prompt,
        "parts": {
            "basePrompt": row.base_prompt,
            "presetGuidance": row.preset_guidance,
            "batchPrompt": row.batch_prompt,
            "casePromptOverride": row.case_prompt_override,
        },
        "preset": (
            {
                "id": row.preset_id,
                "category": row.preset_category,
                "name": row.preset_name,
                "guidance": row.preset_guidance,
            }
            if row.preset_id
            else None
        ),
        "environment": row.environment,
        "startUrl": row.start_url,
        "modelConfig": row.webwright_model_config,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
    }


def record_webwright_prompt_payload(
    session: Session,
    *,
    project: Project,
    case: TestCase,
    run: WebwrightRun,
    components: dict,
    model_config: str,
) -> WebwrightPromptPayload:
    existing = session.exec(
        select(WebwrightPromptPayload).where(WebwrightPromptPayload.webwright_run_id == run.id)
    ).first()
    if existing:
        return existing

    preset = components["preset"]
    parts = components["parts"]
    row = WebwrightPromptPayload(
        id=new_id("prompt"),
        project_id=project.id or "",
        test_case_id=case.id or "",
        webwright_run_id=run.id or "",
        automation_key=case.automation_key,
        final_prompt=components["prompt"],
        base_prompt=parts["basePrompt"],
        preset_id=preset["id"] if preset else None,
        preset_category=preset["category"] if preset else None,
        preset_name=preset["name"] if preset else None,
        preset_guidance=parts["presetGuidance"],
        batch_prompt=parts["batchPrompt"],
        case_prompt_override=parts["casePromptOverride"],
        environment=components["environment"],
        start_url=components["startUrl"],
        webwright_model_config=model_config,
        created_at=datetime.utcnow(),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def list_webwright_prompt_payloads(
    session: Session,
    project: Project,
    *,
    case_id: str | None = None,
    run_id: str | None = None,
) -> dict:
    query = select(WebwrightPromptPayload).where(WebwrightPromptPayload.project_id == project.id)
    if case_id:
        query = query.where(WebwrightPromptPayload.test_case_id == case_id)
    if run_id:
        query = query.where(WebwrightPromptPayload.webwright_run_id == run_id)
    rows = session.exec(
        query.order_by(
            WebwrightPromptPayload.created_at,
            WebwrightPromptPayload.id,
        )
    ).all()
    return {
        "projectId": project.id,
        "payloads": [prompt_payload_to_dict(row) for row in rows],
    }


def get_webwright_prompt_payload(session: Session, project: Project, payload_id: str) -> dict:
    row = session.get(WebwrightPromptPayload, payload_id)
    if not row or row.project_id != project.id:
        raise ValueError("Prompt payload not found")
    return prompt_payload_to_dict(row)
