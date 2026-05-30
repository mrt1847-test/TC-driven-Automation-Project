from __future__ import annotations

import json
from slugify import slugify
from sqlmodel import Session, select

from worker.core.config import new_id
from worker.models.db import CaseActionMapping, RawAction, TestCase
from worker.models.schemas import ActionItem, MappingItem, MappingUpdateRequest


def auto_map_case(session: Session, case: TestCase, run_id: str) -> tuple[list[MappingItem], str]:
    steps = json.loads(case.steps_json or "[]")
    actions = session.exec(
        select(RawAction).where(RawAction.webwright_run_id == run_id).order_by(RawAction.order_index)
    ).all()

    for mapping in session.exec(select(CaseActionMapping).where(CaseActionMapping.test_case_id == case.id)).all():
        session.delete(mapping)

    mappings: list[MappingItem] = []
    status = "mapped"

    if not steps:
        return mappings, "needs_review"

    if len(steps) != len(actions):
        status = "needs_review"

    for idx, step in enumerate(steps):
        step_index = step.get("index", idx + 1)
        action = actions[idx] if idx < len(actions) else None
        step_name = slugify(step.get("action", f"step_{step_index}"), separator="_")[:40] or f"step_{step_index}"
        mapping = MappingItem(
            tc_step_index=step_index,
            action_ids=[action.id] if action else [],
            normalized_step_id=f"flow_{step_index:03d}",
            normalized_step_name=step_name,
            pom_method_name=step_name,
            status="mapped" if action else "unmapped",
        )
        mappings.append(mapping)
        session.add(CaseActionMapping(
            id=new_id("map"),
            test_case_id=case.id,
            raw_action_id=action.id if action else None,
            tc_step_index=step_index,
            normalized_step_id=mapping.normalized_step_id,
            normalized_step_name=mapping.normalized_step_name,
            pom_method_name=mapping.pom_method_name,
            status=mapping.status,
        ))

    if status == "needs_review":
        case.status = "needs_review"
    else:
        case.status = "mapped"
    session.add(case)
    session.commit()
    return mappings, status


def get_mappings(session: Session, case_id: str) -> list[MappingItem]:
    rows = session.exec(select(CaseActionMapping).where(CaseActionMapping.test_case_id == case_id)).all()
    grouped: dict[int, MappingItem] = {}
    for row in rows:
        if row.tc_step_index not in grouped:
            grouped[row.tc_step_index] = MappingItem(
                tc_step_index=row.tc_step_index,
                normalized_step_id=row.normalized_step_id,
                normalized_step_name=row.normalized_step_name,
                pom_method_name=row.pom_method_name,
                status=row.status,
            )
        if row.raw_action_id:
            grouped[row.tc_step_index].action_ids.append(row.raw_action_id)
    return list(grouped.values())


def get_actions(session: Session, run_id: str) -> list[ActionItem]:
    rows = session.exec(select(RawAction).where(RawAction.webwright_run_id == run_id).order_by(RawAction.order_index)).all()
    return [
        ActionItem(
            id=r.id,
            type=r.type,
            target=r.target,
            selector=r.selector,
            value=r.value,
            source_line=r.source_line,
            order_index=r.order_index,
        )
        for r in rows
    ]


def update_mappings(session: Session, case: TestCase, request: MappingUpdateRequest) -> list[MappingItem]:
    for mapping in session.exec(select(CaseActionMapping).where(CaseActionMapping.test_case_id == case.id)).all():
        session.delete(mapping)

    if request.actions:
        run_actions = session.exec(select(RawAction).where(RawAction.automation_key == case.automation_key)).all()
        action_by_id = {a.id: a for a in run_actions}
        for action in request.actions:
            if action.id and action.id in action_by_id:
                db = action_by_id[action.id]
                db.type = action.type
                db.selector = action.selector
                db.value = action.value
                db.target = action.target
                db.order_index = action.order_index
                session.add(db)

    for item in request.mappings:
        for action_id in item.action_ids or [None]:
            session.add(CaseActionMapping(
                id=new_id("map"),
                test_case_id=case.id,
                raw_action_id=action_id,
                tc_step_index=item.tc_step_index,
                normalized_step_id=item.normalized_step_id,
                normalized_step_name=item.normalized_step_name,
                pom_method_name=item.pom_method_name,
                status=item.status,
            ))

    unmapped = [m for m in request.mappings if not m.action_ids]
    case.status = "needs_review" if unmapped else "mapped"
    session.add(case)
    session.commit()
    return request.mappings
