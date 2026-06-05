from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, select

from worker.core.config import new_id
from worker.models.db import Project, PromptPreset
from worker.models.schemas import PromptPresetUpdateRequest


BUILT_IN_PROMPT_PRESETS = [
    {
        "id": "preset_builtin_general",
        "category": "general",
        "name": "General automation",
        "guidance": "Prefer stable selectors, explicit waits, readable steps, and assertions tied to the expected result.",
    },
    {
        "id": "preset_builtin_login",
        "category": "login",
        "name": "Login-required flow",
        "guidance": "Account for authentication setup, session reuse, guarded redirects, and post-login landing state before executing TC steps.",
    },
    {
        "id": "preset_builtin_search",
        "category": "search",
        "name": "Search flow",
        "guidance": "Treat query entry, result loading, empty states, and result assertions as first-class checkpoints.",
    },
    {
        "id": "preset_builtin_crud",
        "category": "crud",
        "name": "CRUD flow",
        "guidance": "Use deterministic test data, verify create/update/delete transitions, and clean up records where the flow allows it.",
    },
    {
        "id": "preset_builtin_assertion_heavy",
        "category": "assertion_heavy",
        "name": "Assertion-heavy flow",
        "guidance": "Favor explicit UI assertions, state checks, and clear failure messages over only navigation or click completion.",
    },
]


def _preset_payload(row: PromptPreset) -> dict:
    return {
        "id": row.id,
        "projectId": row.project_id,
        "category": row.category,
        "name": row.name,
        "guidance": row.guidance,
        "isBuiltin": row.is_builtin,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
    }


def _ordered(rows: list[PromptPreset]) -> list[PromptPreset]:
    return sorted(
        rows,
        key=lambda row: (
            0 if row.is_builtin else 1,
            row.category,
            row.name,
            row.id or "",
        ),
    )


def ensure_builtin_prompt_presets(session: Session) -> None:
    now = datetime.utcnow()
    for preset in BUILT_IN_PROMPT_PRESETS:
        row = session.get(PromptPreset, preset["id"])
        if not row:
            row = PromptPreset(
                id=preset["id"],
                project_id=None,
                created_at=now,
            )
        row.project_id = None
        row.category = preset["category"]
        row.name = preset["name"]
        row.guidance = preset["guidance"]
        row.is_builtin = True
        row.updated_at = now
        session.add(row)
    session.commit()


def list_prompt_presets(session: Session, project: Project) -> dict:
    ensure_builtin_prompt_presets(session)
    rows = session.exec(
        select(PromptPreset).where(
            (PromptPreset.is_builtin == True)  # noqa: E712
            | (PromptPreset.project_id == project.id)
        )
    ).all()
    return {
        "projectId": project.id,
        "presets": [_preset_payload(row) for row in _ordered(rows)],
    }


def replace_project_prompt_presets(
    session: Session,
    project: Project,
    request: PromptPresetUpdateRequest,
) -> dict:
    ensure_builtin_prompt_presets(session)
    project_id = project.id or ""
    seen_ids: set[str] = set()
    requested: list[tuple[str, str, str, str]] = []
    for item in request.presets:
        preset_id = (item.id or new_id("preset")).strip()
        category = item.category.strip()
        name = item.name.strip()
        guidance = item.guidance.strip()
        if not category or not name or not guidance:
            raise ValueError("Prompt presets require category, name, and guidance")
        if preset_id in seen_ids:
            raise ValueError(f"Duplicate prompt preset id: {preset_id}")
        if preset_id.startswith("preset_builtin_"):
            raise ValueError("Built-in prompt presets cannot be replaced")
        existing = session.get(PromptPreset, preset_id)
        if existing and (existing.is_builtin or existing.project_id != project_id):
            raise ValueError(f"Prompt preset does not belong to project: {preset_id}")
        seen_ids.add(preset_id)
        requested.append((preset_id, category, name, guidance))

    existing_project_rows = {
        row.id: row
        for row in session.exec(
            select(PromptPreset).where(PromptPreset.project_id == project_id)
        ).all()
        if row.id
    }
    for preset_id, row in existing_project_rows.items():
        if preset_id not in seen_ids:
            session.delete(row)

    now = datetime.utcnow()
    for preset_id, category, name, guidance in requested:
        row = existing_project_rows.get(preset_id)
        if not row:
            row = PromptPreset(
                id=preset_id,
                project_id=project_id,
                created_at=now,
            )
        row.project_id = project_id
        row.category = category
        row.name = name
        row.guidance = guidance
        row.is_builtin = False
        row.updated_at = now
        session.add(row)

    session.commit()
    return list_prompt_presets(session, project)
