from __future__ import annotations

import json
from slugify import slugify
from sqlmodel import Session, select

from worker.core.config import new_id
from worker.models.db import CaseActionMapping, CaseActionMappingAction, RawAction, TestCase, WebwrightRun
from worker.models.schemas import (
    ActionCreateRequest,
    ActionItem,
    ActionUpdateRequest,
    MappingItem,
    MappingUpdateRequest,
    StepActionCreateRequest,
    StepActionUpdateRequest,
)


REVIEW_INSERT_ACTION_TYPES = {
    "wait",
    "wait_for_request",
    "wait_for_response",
    "assert_text",
    "assert_url",
    "assert_visible",
    "assert_hidden",
    "assert_count",
}


class MappingValidationError(ValueError):
    pass


def _action_item(row: RawAction) -> ActionItem:
    return ActionItem(
        id=row.id,
        type=row.type,
        target=row.target,
        selector=row.selector,
        value=row.value,
        source_line=row.source_line,
        order_index=row.order_index,
    )


def _latest_case_run(session: Session, case: TestCase) -> WebwrightRun | None:
    return session.exec(
        select(WebwrightRun)
        .where(
            WebwrightRun.project_id == case.project_id,
            WebwrightRun.test_case_id == case.id,
        )
        .order_by(WebwrightRun.created_at.desc())
    ).first()


def _clear_mappings(session: Session, case_id: str) -> None:
    mappings = session.exec(select(CaseActionMapping).where(CaseActionMapping.test_case_id == case_id)).all()
    for mapping in mappings:
        if mapping.id:
            for link in session.exec(
                select(CaseActionMappingAction).where(CaseActionMappingAction.mapping_id == mapping.id)
            ).all():
                session.delete(link)
        session.delete(mapping)


def _add_mapping(session: Session, case_id: str, item: MappingItem) -> CaseActionMapping:
    action_ids = item.action_ids or []
    mapping = CaseActionMapping(
        id=new_id("map"),
        test_case_id=case_id,
        raw_action_id=action_ids[0] if action_ids else None,
        tc_step_index=item.tc_step_index,
        normalized_step_id=item.normalized_step_id,
        normalized_step_name=item.normalized_step_name,
        pom_method_name=item.pom_method_name,
        status=item.status,
    )
    session.add(mapping)

    for order_index, action_id in enumerate(action_ids):
        session.add(CaseActionMappingAction(
            mapping_id=mapping.id,
            raw_action_id=action_id,
            order_index=order_index,
        ))
    return mapping


def _case_actions_by_id(session: Session, case: TestCase) -> dict[str, RawAction]:
    run_ids = session.exec(
        select(WebwrightRun.id).where(
            WebwrightRun.project_id == case.project_id,
            WebwrightRun.test_case_id == case.id,
        )
    ).all()
    if not run_ids:
        return {}

    actions = session.exec(select(RawAction).where(RawAction.webwright_run_id.in_(run_ids))).all()
    return {action.id: action for action in actions if action.id}


def _owned_action(session: Session, case: TestCase, action_id: str) -> RawAction:
    action_by_id = _case_actions_by_id(session, case)
    action = action_by_id.get(action_id)
    if not action:
        raise MappingValidationError(
            f"Action ID does not belong to case {case.id}: {action_id}"
        )
    return action


def _validate_action_type(action_type: str | None) -> str:
    normalized = (action_type or "").strip()
    if not normalized:
        raise MappingValidationError("Action type is required")
    return normalized


def _validate_order_index(order_index: int | None) -> int | None:
    if order_index is None:
        return None
    if order_index < 1:
        raise MappingValidationError("Action order_index must be greater than zero")
    return order_index


def _validate_review_insert_action_type(action_type: str | None) -> str:
    normalized = _validate_action_type(action_type)
    if normalized not in REVIEW_INSERT_ACTION_TYPES:
        raise MappingValidationError(
            "Step review action type must be an assertion or wait action"
        )
    return normalized


def _step_name(case: TestCase, tc_step_index: int) -> str:
    try:
        steps = json.loads(case.steps_json or "[]")
    except json.JSONDecodeError:
        steps = []
    for idx, step in enumerate(steps):
        if step.get("index", idx + 1) == tc_step_index:
            return slugify(step.get("action", f"step_{tc_step_index}"), separator="_")[:40] or f"step_{tc_step_index}"
    return f"step_{tc_step_index}"


def _mappings_for_step(session: Session, case: TestCase, tc_step_index: int) -> list[CaseActionMapping]:
    return list(session.exec(
        select(CaseActionMapping).where(
            CaseActionMapping.test_case_id == case.id,
            CaseActionMapping.tc_step_index == tc_step_index,
        )
    ).all())


def _mapping_for_step(session: Session, case: TestCase, tc_step_index: int) -> CaseActionMapping | None:
    if tc_step_index < 1:
        raise MappingValidationError("TC step index must be greater than zero")
    mappings = _mappings_for_step(session, case, tc_step_index)
    if len(mappings) > 1:
        raise MappingValidationError(f"Ambiguous mapping for TC step {tc_step_index}")
    return mappings[0] if mappings else None


def _mapping_action_ids(session: Session, mapping: CaseActionMapping) -> list[str]:
    links = session.exec(
        select(CaseActionMappingAction)
        .where(CaseActionMappingAction.mapping_id == mapping.id)
        .order_by(CaseActionMappingAction.order_index)
    ).all() if mapping.id else []
    action_ids = [link.raw_action_id for link in links]
    if not action_ids and mapping.raw_action_id:
        action_ids = [mapping.raw_action_id]
    return list(dict.fromkeys(action_ids))


def _replace_mapping_action_ids(
    session: Session,
    mapping: CaseActionMapping,
    action_ids: list[str],
) -> None:
    if not mapping.id:
        raise MappingValidationError("Mapping ID is required")
    for link in session.exec(
        select(CaseActionMappingAction).where(CaseActionMappingAction.mapping_id == mapping.id)
    ).all():
        session.delete(link)
    mapping.raw_action_id = action_ids[0] if action_ids else None
    mapping.status = "mapped" if action_ids and mapping.status == "unmapped" else mapping.status
    for order_index, action_id in enumerate(action_ids):
        session.add(CaseActionMappingAction(
            mapping_id=mapping.id,
            raw_action_id=action_id,
            order_index=order_index,
        ))
    session.add(mapping)


def _validate_mapping_update(
    session: Session,
    case: TestCase,
    request: MappingUpdateRequest,
) -> dict[str, RawAction]:
    action_by_id = _case_actions_by_id(session, case)
    seen_step_indexes: set[int] = set()
    requested_action_ids: set[str] = set()

    for mapping in request.mappings:
        if mapping.tc_step_index in seen_step_indexes:
            raise MappingValidationError(f"Duplicate TC step index: {mapping.tc_step_index}")
        seen_step_indexes.add(mapping.tc_step_index)

        if len(mapping.action_ids) != len(set(mapping.action_ids)):
            raise MappingValidationError(
                f"Duplicate action IDs for TC step {mapping.tc_step_index}"
            )
        requested_action_ids.update(mapping.action_ids)

    if request.actions:
        requested_action_ids.update(action.id for action in request.actions if action.id)

    invalid_action_ids = sorted(requested_action_ids - action_by_id.keys())
    if invalid_action_ids:
        raise MappingValidationError(
            f"Action IDs do not belong to case {case.id}: {', '.join(invalid_action_ids)}"
        )
    return action_by_id


def _case_status_from_mappings(session: Session, case: TestCase) -> str:
    mappings = get_mappings(session, case.id)
    if not mappings or any(
        mapping.status != "mapped" or not mapping.action_ids for mapping in mappings
    ):
        return "needs_review"
    return "mapped"


def _assert_no_foreign_mapping_links(session: Session, case: TestCase, action_id: str) -> None:
    linked_mapping_ids = [
        link.mapping_id
        for link in session.exec(
            select(CaseActionMappingAction).where(CaseActionMappingAction.raw_action_id == action_id)
        ).all()
    ]
    legacy_rows = session.exec(
        select(CaseActionMapping).where(CaseActionMapping.raw_action_id == action_id)
    ).all()
    linked_mapping_ids.extend(row.id for row in legacy_rows if row.id)

    for mapping_id in sorted(set(linked_mapping_ids)):
        mapping = session.get(CaseActionMapping, mapping_id)
        if mapping and mapping.test_case_id != case.id:
            raise MappingValidationError(
                f"Action ID is referenced by another case mapping: {action_id}"
            )


def _remaining_action_ids(session: Session, mapping: CaseActionMapping, deleted_action_id: str) -> list[str]:
    return [
        action_id
        for action_id in _mapping_action_ids(session, mapping)
        if action_id != deleted_action_id
    ]


def auto_map_case(session: Session, case: TestCase, run_id: str) -> tuple[list[MappingItem], str]:
    steps = json.loads(case.steps_json or "[]")
    actions = session.exec(
        select(RawAction).where(RawAction.webwright_run_id == run_id).order_by(RawAction.order_index)
    ).all()

    _clear_mappings(session, case.id)

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
        _add_mapping(session, case.id, mapping)

    if status == "needs_review":
        case.status = "needs_review"
    else:
        case.status = "mapped"
    session.add(case)
    session.commit()
    return mappings, status


def get_mappings(session: Session, case_id: str) -> list[MappingItem]:
    rows = session.exec(
        select(CaseActionMapping)
        .where(CaseActionMapping.test_case_id == case_id)
        .order_by(CaseActionMapping.tc_step_index)
    ).all()
    grouped: dict[int, MappingItem] = {}
    for row in rows:
        if row.tc_step_index not in grouped:
            grouped[row.tc_step_index] = MappingItem(
                id=row.id,
                tc_step_index=row.tc_step_index,
                normalized_step_id=row.normalized_step_id,
                normalized_step_name=row.normalized_step_name,
                pom_method_name=row.pom_method_name,
                status=row.status,
            )
        links = []
        if row.id:
            links = session.exec(
                select(CaseActionMappingAction)
                .where(CaseActionMappingAction.mapping_id == row.id)
                .order_by(CaseActionMappingAction.order_index)
            ).all()
        action_ids = [link.raw_action_id for link in links]
        if not action_ids and row.raw_action_id:
            action_ids = [row.raw_action_id]
        for action_id in action_ids:
            if action_id not in grouped[row.tc_step_index].action_ids:
                grouped[row.tc_step_index].action_ids.append(action_id)
    return list(grouped.values())


def get_actions(session: Session, run_id: str) -> list[ActionItem]:
    rows = session.exec(
        select(RawAction)
        .where(RawAction.webwright_run_id == run_id)
        .order_by(RawAction.order_index, RawAction.id)
    ).all()
    return [_action_item(row) for row in rows]


def create_action(session: Session, case: TestCase, request: ActionCreateRequest) -> ActionItem:
    run = _latest_case_run(session, case)
    if not run:
        raise MappingValidationError("No webwright run")
    action_type = _validate_action_type(request.type)
    order_index = _validate_order_index(request.order_index)
    if order_index is None:
        existing_orders = session.exec(
            select(RawAction.order_index).where(RawAction.webwright_run_id == run.id)
        ).all()
        order_index = (max(existing_orders) if existing_orders else 0) + 1

    action = RawAction(
        id=new_id("act"),
        webwright_run_id=run.id,
        automation_key=case.automation_key,
        order_index=order_index,
        type=action_type,
        target=request.target,
        selector=request.selector,
        value=request.value,
        source_line=request.source_line,
    )
    session.add(action)
    session.commit()
    session.refresh(action)
    return _action_item(action)


def update_action(
    session: Session,
    case: TestCase,
    action_id: str,
    request: ActionUpdateRequest,
) -> ActionItem:
    action = _owned_action(session, case, action_id)
    fields = request.model_fields_set
    if not fields:
        raise MappingValidationError("No action fields supplied")

    if "type" in fields:
        action.type = _validate_action_type(request.type)
    if "target" in fields:
        action.target = request.target
    if "selector" in fields:
        action.selector = request.selector
    if "value" in fields:
        action.value = request.value
    if "source_line" in fields:
        action.source_line = request.source_line
    if "order_index" in fields:
        action.order_index = _validate_order_index(request.order_index) or action.order_index

    session.add(action)
    session.commit()
    session.refresh(action)
    return _action_item(action)


def delete_action(session: Session, case: TestCase, action_id: str) -> dict:
    action = _owned_action(session, case, action_id)
    _assert_no_foreign_mapping_links(session, case, action_id)
    affected_mapping_ids: list[str] = []

    try:
        mappings = session.exec(
            select(CaseActionMapping).where(CaseActionMapping.test_case_id == case.id)
        ).all()
        for mapping in mappings:
            if not mapping.id:
                continue
            links = session.exec(
                select(CaseActionMappingAction).where(CaseActionMappingAction.mapping_id == mapping.id)
            ).all()
            removed_link = False
            for link in links:
                if link.raw_action_id == action_id:
                    session.delete(link)
                    removed_link = True

            legacy_match = mapping.raw_action_id == action_id
            if not removed_link and not legacy_match:
                continue

            remaining_ids = _remaining_action_ids(session, mapping, action_id)
            mapping.raw_action_id = remaining_ids[0] if remaining_ids else None
            if not remaining_ids:
                mapping.status = "unmapped"
            session.add(mapping)
            affected_mapping_ids.append(mapping.id)

        session.delete(action)
        case.status = _case_status_from_mappings(session, case)
        session.add(case)
        session.commit()
    except Exception:
        session.rollback()
        raise

    return {
        "deletedActionId": action_id,
        "affectedMappingIds": affected_mapping_ids,
        "caseStatus": case.status,
    }


def insert_step_review_action(
    session: Session,
    case: TestCase,
    tc_step_index: int,
    request: StepActionCreateRequest,
) -> dict:
    run = _latest_case_run(session, case)
    if not run:
        raise MappingValidationError("No webwright run")

    action_type = _validate_review_insert_action_type(request.type)
    order_index = _validate_order_index(request.order_index)
    mapping = _mapping_for_step(session, case, tc_step_index)
    existing_action_ids = _mapping_action_ids(session, mapping) if mapping else []
    insert_after_action_id = request.insert_after_action_id
    if insert_after_action_id and insert_after_action_id not in existing_action_ids:
        raise MappingValidationError(
            f"insertAfterActionId does not belong to TC step {tc_step_index}: {insert_after_action_id}"
        )
    if order_index is None:
        existing_orders = session.exec(
            select(RawAction.order_index).where(RawAction.webwright_run_id == run.id)
        ).all()
        order_index = (max(existing_orders) if existing_orders else 0) + 1

    try:
        if not mapping:
            step_name = _step_name(case, tc_step_index)
            mapping = CaseActionMapping(
                id=new_id("map"),
                test_case_id=case.id,
                tc_step_index=tc_step_index,
                normalized_step_id=f"flow_{tc_step_index:03d}",
                normalized_step_name=step_name,
                pom_method_name=step_name,
                status="mapped",
            )
            session.add(mapping)
            session.flush()

        action = RawAction(
            id=new_id("act"),
            webwright_run_id=run.id,
            automation_key=case.automation_key,
            order_index=order_index,
            type=action_type,
            target=request.target,
            selector=request.selector,
            value=request.value,
            source_line=request.source_line,
        )
        session.add(action)
        session.flush()

        action_ids = list(existing_action_ids)
        if insert_after_action_id:
            insert_at = action_ids.index(insert_after_action_id) + 1
            action_ids.insert(insert_at, action.id)
        else:
            action_ids.append(action.id)
        _replace_mapping_action_ids(session, mapping, action_ids)
        case.status = _case_status_from_mappings(session, case)
        session.add(case)
        session.commit()
        session.refresh(action)
    except Exception:
        session.rollback()
        raise

    mappings = get_mappings(session, case.id)
    mapping_item = next(item for item in mappings if item.id == mapping.id)
    return {
        "action": _action_item(action),
        "mapping": mapping_item,
    }


def update_step_review_action(
    session: Session,
    case: TestCase,
    tc_step_index: int,
    action_id: str,
    request: StepActionUpdateRequest,
) -> dict:
    action = _owned_action(session, case, action_id)
    mapping = _mapping_for_step(session, case, tc_step_index)
    if not mapping:
        raise MappingValidationError(f"Mapping not found for TC step {tc_step_index}")
    action_ids = _mapping_action_ids(session, mapping)
    if action_id not in action_ids:
        raise MappingValidationError(
            f"Action ID does not belong to TC step {tc_step_index}: {action_id}"
        )

    fields = request.model_fields_set
    if not fields:
        raise MappingValidationError("No action fields supplied")

    if "type" in fields:
        action.type = _validate_review_insert_action_type(request.type)
    if "target" in fields:
        action.target = request.target
    if "selector" in fields:
        action.selector = request.selector
    if "value" in fields:
        action.value = request.value
    if "source_line" in fields:
        action.source_line = request.source_line
    if "order_index" in fields:
        action.order_index = _validate_order_index(request.order_index) or action.order_index

    session.add(action)
    session.commit()
    session.refresh(action)
    mappings = get_mappings(session, case.id)
    return {
        "action": _action_item(action),
        "mapping": next(item for item in mappings if item.id == mapping.id),
    }


def update_mappings(session: Session, case: TestCase, request: MappingUpdateRequest) -> list[MappingItem]:
    action_by_id = _validate_mapping_update(session, case, request)

    try:
        _clear_mappings(session, case.id)

        if request.actions:
            for action in request.actions:
                if action.id:
                    db = action_by_id[action.id]
                    db.type = action.type
                    db.selector = action.selector
                    db.value = action.value
                    db.target = action.target
                    db.order_index = action.order_index
                    session.add(db)

        for item in request.mappings:
            _add_mapping(session, case.id, item)

        unmapped = [mapping for mapping in request.mappings if not mapping.action_ids]
        case.status = "needs_review" if not request.mappings or unmapped else "mapped"
        session.add(case)
        session.commit()
    except Exception:
        session.rollback()
        raise

    return get_mappings(session, case.id)
