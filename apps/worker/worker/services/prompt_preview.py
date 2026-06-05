from __future__ import annotations

from sqlmodel import Session

from worker.models.db import Project, PromptPreset, TestCase
from worker.models.schemas import PromptPreviewRequest
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


def _resolve_preset(session: Session, project: Project, preset_id: str | None) -> dict | None:
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


def preview_webwright_prompt(
    session: Session,
    project: Project,
    request: PromptPreviewRequest,
) -> dict:
    case = session.get(TestCase, request.case_id)
    if not case or case.project_id != project.id:
        raise ValueError("Case not found")
    preset = _resolve_preset(session, project, request.preset_id)
    context = effective_prompt_context(session, project.id or "", case)
    normalized = case_to_normalized(case)
    base_prompt = build_webwright_prompt(
        normalized,
        start_url=request.start_url_override,
        environment=request.environment,
    )
    prompt = build_webwright_prompt(
        normalized,
        start_url=request.start_url_override,
        environment=request.environment,
        preset_guidance=preset["guidance"] if preset else None,
        batch_prompt=context["batchPrompt"],
        case_prompt_override=context["casePromptOverride"],
    )
    return {
        "projectId": project.id,
        "caseId": case.id,
        "automationKey": case.automation_key,
        "environment": request.environment,
        "startUrl": request.start_url_override or case.start_url or "https://example.com",
        "preset": preset,
        "parts": {
            "basePrompt": base_prompt,
            "presetGuidance": preset["guidance"] if preset else "",
            "batchPrompt": context["batchPrompt"],
            "casePromptOverride": context["casePromptOverride"],
        },
        "prompt": prompt,
    }
