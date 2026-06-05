from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from sqlmodel import Session, select

from worker.core.config import new_id
from worker.models.db import (
    CaseActionMapping,
    CaseActionMappingAction,
    PageObject,
    PageObjectMethod,
    PageObjectMethodStatus,
    PageObjectMethodType,
    Project,
    RawAction,
    StructuredFlow,
    StructuredFlowStatus,
    StructuredStep,
    StructuredStepKind,
    TestCase,
    WebwrightRun,
)
from worker.services.generated_file_status import refresh_generated_file_statuses
from worker.models.schemas import MappingItem
from worker.services.mapping import get_mappings


PLANNED_ACTION_TYPES = {
    "goto",
    "click",
    "fill",
    "select",
    "check",
    "uncheck",
    "hover",
    "press",
    "set_input_files",
    "drag_to",
    "wait",
    "wait_for_request",
    "wait_for_response",
    "assert_text",
    "assert_url",
    "assert_visible",
    "assert_hidden",
    "assert_count",
}


def _snake(name: str) -> str:
    return name.lower().replace("-", "_").replace(" ", "_")


def _action_kind(action: RawAction | None) -> str:
    if not action:
        return StructuredStepKind.interaction.value
    if action.type == "goto":
        return StructuredStepKind.navigation.value
    if action.type.startswith("assert_"):
        return StructuredStepKind.assertion.value
    if action.type == "wait" or action.type.startswith("wait_for_"):
        return StructuredStepKind.wait.value
    if action.type == "custom_code" or action.type not in PLANNED_ACTION_TYPES:
        return StructuredStepKind.custom_code.value
    return StructuredStepKind.interaction.value


def _step_kind(actions: list[RawAction]) -> str:
    kinds = [_action_kind(action) for action in actions]
    if StructuredStepKind.custom_code.value in kinds:
        return StructuredStepKind.custom_code.value
    if kinds and all(kind == StructuredStepKind.assertion.value for kind in kinds):
        return StructuredStepKind.assertion.value
    if kinds and all(kind == StructuredStepKind.wait.value for kind in kinds):
        return StructuredStepKind.wait.value
    if kinds and kinds[0] == StructuredStepKind.navigation.value:
        return StructuredStepKind.navigation.value
    return StructuredStepKind.interaction.value


def _is_hard_wait(action: RawAction) -> bool:
    if action.type != "wait" or action.selector:
        return False
    try:
        float(action.value or "")
    except ValueError:
        return False
    return True


def _review_reason(action: RawAction) -> str | None:
    if action.type == "custom_code" or action.type not in PLANNED_ACTION_TYPES:
        return "unsupported_action"
    if _is_hard_wait(action):
        return "hard_wait"
    return None


def _plan_entry(order: int, mapping_id: str | None, action: RawAction) -> dict:
    review_reason = _review_reason(action)
    entry = {
        "order": order,
        "action": action.type,
        "sourceRawActionId": action.id,
        "sourceMappingId": mapping_id,
        "requiresReview": review_reason is not None,
    }
    if action.selector is not None:
        entry["selector"] = action.selector
    if action.value is not None:
        entry["value"] = action.value
    if action.target is not None:
        entry["target"] = action.target
    if review_reason:
        entry["reviewReason"] = review_reason
    return entry


def _missing_action_entry(order: int, mapping_id: str | None, action_id: str) -> dict:
    return {
        "order": order,
        "action": "missing_raw_action",
        "sourceRawActionId": action_id,
        "sourceMappingId": mapping_id,
        "requiresReview": True,
        "reviewReason": "missing_raw_action",
    }


def build_method_body_plan(
    mapping: MappingItem,
    action_by_id: dict[str, RawAction],
) -> tuple[list[dict], list[RawAction], bool]:
    plan: list[dict] = []
    actions: list[RawAction] = []
    requires_review = mapping.status != "mapped"
    for order, action_id in enumerate(mapping.action_ids, start=1):
        action = action_by_id.get(action_id)
        if not action:
            plan.append(_missing_action_entry(order, mapping.id, action_id))
            requires_review = True
            continue
        actions.append(action)
        entry = _plan_entry(order, mapping.id, action)
        plan.append(entry)
        requires_review = requires_review or entry["requiresReview"]
    if not plan:
        requires_review = True
    return plan, actions, requires_review


def _method_type(actions: list[RawAction], requires_review: bool) -> str:
    if not actions:
        return PageObjectMethodType.custom.value
    if len(actions) > 1:
        return PageObjectMethodType.composite.value

    action_type = actions[0].type
    if action_type == "goto":
        return PageObjectMethodType.navigate.value
    if action_type.startswith("assert_"):
        return PageObjectMethodType.assert_.value
    if action_type == "wait" or action_type.startswith("wait_for_"):
        return PageObjectMethodType.wait.value
    if action_type in {
        PageObjectMethodType.click.value,
        PageObjectMethodType.fill.value,
        PageObjectMethodType.select.value,
    }:
        return action_type
    return PageObjectMethodType.custom.value if requires_review else PageObjectMethodType.composite.value


def _actions_for_mappings(session: Session, mappings: list[MappingItem]) -> dict[str, RawAction]:
    action_ids = list(dict.fromkeys(
        action_id
        for mapping in mappings
        for action_id in mapping.action_ids
    ))
    if not action_ids:
        return {}
    actions = session.exec(select(RawAction).where(RawAction.id.in_(action_ids))).all()
    return {action.id: action for action in actions if action.id}


def sync_structured_entities(session: Session, project_id: str, case: TestCase, run: WebwrightRun | None) -> StructuredFlow:
    mappings = get_mappings(session, case.id)
    action_by_id = _actions_for_mappings(session, mappings)

    existing = session.exec(
        select(StructuredFlow).where(StructuredFlow.test_case_id == case.id).order_by(StructuredFlow.version.desc())
    ).first()
    version = (existing.version + 1) if existing else 1

    flow_name = "".join(part.capitalize() for part in case.automation_key.split("_")) + "Flow"
    flow = StructuredFlow(
        id=new_id("sf"),
        project_id=project_id,
        test_case_id=case.id,
        automation_key=case.automation_key,
        name=flow_name,
        status=StructuredFlowStatus.approved.value,
        version=version,
        updated_at=datetime.utcnow(),
    )
    session.add(flow)
    session.flush()

    page = session.exec(
        select(PageObject).where(PageObject.project_id == project_id, PageObject.name == "GeneratedPage")
    ).first()
    if not page:
        page = PageObject(
            id=new_id("po"),
            project_id=project_id,
            name="GeneratedPage",
            file_path="pages/generated_page.py",
        )
        session.add(page)
        session.flush()

    flow_requires_review = False
    for order_index, mapping in enumerate(mappings, start=1):
        body_plan, actions, requires_review = build_method_body_plan(mapping, action_by_id)
        flow_requires_review = flow_requires_review or requires_review
        step_name = mapping.normalized_step_name or mapping.pom_method_name or f"step_{mapping.tc_step_index}"
        method_name = _snake(mapping.pom_method_name or step_name)

        method_type = _method_type(actions, requires_review)
        selector = next((action.selector for action in actions if action.selector is not None), None)
        value_template = next((action.value for action in actions if action.value is not None), None)
        body_plan_json = json.dumps(body_plan, sort_keys=True, separators=(",", ":"))
        method_status = (
            PageObjectMethodStatus.draft.value
            if requires_review
            else PageObjectMethodStatus.approved.value
        )

        pom = session.exec(
            select(PageObjectMethod).where(PageObjectMethod.page_object_id == page.id, PageObjectMethod.name == method_name)
        ).first()
        if not pom:
            pom = PageObjectMethod(
                id=new_id("pom"),
                page_object_id=page.id,
                name=method_name,
                method_type=method_type,
                selector=selector,
                value_template=value_template,
                body_plan_json=body_plan_json,
                source_mapping_id=mapping.id,
                status=method_status,
            )
        else:
            pom.method_type = method_type
            pom.selector = selector
            pom.value_template = value_template
            pom.body_plan_json = body_plan_json
            pom.source_mapping_id = mapping.id
            pom.status = method_status
            pom.updated_at = datetime.utcnow()
        session.add(pom)
        session.flush()

        session.add(StructuredStep(
            id=new_id("ss"),
            structured_flow_id=flow.id,
            mapping_id=mapping.id,
            order_index=order_index,
            name=step_name,
            kind=_step_kind(actions),
            page_object_method_id=pom.id,
            metadata_json=json.dumps({
                "raw_action_ids": mapping.action_ids,
                "requires_review": requires_review,
                "tc_step_index": mapping.tc_step_index,
            }, sort_keys=True, separators=(",", ":")),
        ))

    if flow_requires_review:
        flow.status = StructuredFlowStatus.needs_review.value
        case.status = "needs_review"
    else:
        case.status = "structured"
    session.add(case)
    session.add(flow)
    session.flush()
    return flow


def get_latest_flow(session: Session, case_id: str) -> StructuredFlow | None:
    return session.exec(
        select(StructuredFlow).where(StructuredFlow.test_case_id == case_id).order_by(StructuredFlow.version.desc())
    ).first()


def get_flow_steps(session: Session, flow_id: str) -> list[StructuredStep]:
    return list(session.exec(
        select(StructuredStep).where(StructuredStep.structured_flow_id == flow_id).order_by(StructuredStep.order_index)
    ).all())


def _normalized_action_field(value: str | None) -> str:
    return " ".join((value or "").split())


def _exact_action_signature(action: RawAction) -> tuple[str, str, str, str]:
    return (
        action.type,
        _normalized_action_field(action.selector),
        _normalized_action_field(action.target),
        _normalized_action_field(action.value),
    )


def _semantic_action_signature(action: RawAction) -> tuple[str, str, str] | None:
    target = _normalized_action_field(action.target)
    value = _normalized_action_field(action.value)
    if not target and not value:
        return None
    return action.type, target, value


def _selector_action_signature(action: RawAction) -> tuple[str, str] | None:
    selector = _normalized_action_field(action.selector)
    return (action.type, selector) if selector else None


def _match_unique_actions(
    old_by_id: dict[str, RawAction],
    new_by_id: dict[str, RawAction],
    unmatched_old: set[str],
    unmatched_new: set[str],
    matches: dict[str, str],
    signature,
) -> None:
    old_groups: dict[object, list[str]] = {}
    new_groups: dict[object, list[str]] = {}
    for action_id in unmatched_old:
        key = signature(old_by_id[action_id])
        if key is not None:
            old_groups.setdefault(key, []).append(action_id)
    for action_id in unmatched_new:
        key = signature(new_by_id[action_id])
        if key is not None:
            new_groups.setdefault(key, []).append(action_id)

    for key, old_ids in old_groups.items():
        new_ids = new_groups.get(key, [])
        if len(old_ids) != 1 or len(new_ids) != 1:
            continue
        old_id = old_ids[0]
        new_id = new_ids[0]
        matches[old_id] = new_id
        unmatched_old.remove(old_id)
        unmatched_new.remove(new_id)


def _match_refreshed_actions(
    old_actions: list[RawAction],
    new_actions: list[RawAction],
) -> tuple[dict[str, str], list[str], list[str], str | None]:
    old_by_id = {action.id: action for action in old_actions if action.id}
    new_by_id = {action.id: action for action in new_actions if action.id}
    unmatched_old = set(old_by_id)
    unmatched_new = set(new_by_id)
    matches: dict[str, str] = {}

    if not old_actions or not new_actions:
        return matches, sorted(unmatched_old), sorted(unmatched_new), "empty_action_sequence"
    if len(old_by_id) != len(old_actions):
        return matches, sorted(unmatched_old), sorted(unmatched_new), "duplicate_existing_action_links"

    for signature in (
        _exact_action_signature,
        _semantic_action_signature,
        _selector_action_signature,
    ):
        _match_unique_actions(
            old_by_id,
            new_by_id,
            unmatched_old,
            unmatched_new,
            matches,
            signature,
        )

    if len(old_actions) == len(new_actions):
        old_type_counts = Counter(old_by_id[action_id].type for action_id in unmatched_old)
        new_type_counts = Counter(new_by_id[action_id].type for action_id in unmatched_new)
        for old_action, new_action in zip(old_actions, new_actions):
            if (
                old_action.id in unmatched_old
                and new_action.id in unmatched_new
                and old_action.type == new_action.type
                and old_type_counts[old_action.type] == 1
                and new_type_counts[new_action.type] == 1
            ):
                matches[old_action.id] = new_action.id
                unmatched_old.remove(old_action.id)
                unmatched_new.remove(new_action.id)

    if len(old_actions) != len(new_actions):
        reason = "action_count_changed"
    elif unmatched_old or unmatched_new:
        reason = "ambiguous_action_match"
    else:
        old_order = [action.id for action in old_actions]
        new_positions = {action.id: index for index, action in enumerate(new_actions)}
        matched_positions = [new_positions[matches[action_id]] for action_id in old_order]
        reason = None if matched_positions == sorted(matched_positions) else "action_order_changed"

    return matches, sorted(unmatched_old), sorted(unmatched_new), reason


def _step_metadata(step: StructuredStep) -> dict:
    try:
        metadata = json.loads(step.metadata_json or "{}")
    except json.JSONDecodeError:
        metadata = {}
    return metadata if isinstance(metadata, dict) else {}


def _method_used_by_other_cases(
    session: Session,
    method_id: str,
    case_id: str,
) -> bool:
    steps = session.exec(
        select(StructuredStep).where(StructuredStep.page_object_method_id == method_id)
    ).all()
    for step in steps:
        flow = session.get(StructuredFlow, step.structured_flow_id)
        if flow and flow.test_case_id != case_id:
            return True
    return False


def _mark_raw_refresh_needs_review(
    session: Session,
    *,
    case: TestCase,
    run: WebwrightRun,
    flow: StructuredFlow,
    mappings: list[MappingItem],
    steps: list[StructuredStep],
    reason: str,
    matched_action_ids: dict[str, str],
    unmatched_old_action_ids: list[str],
    unmatched_new_action_ids: list[str],
) -> dict:
    now = datetime.utcnow()
    for mapping in mappings:
        if not mapping.id:
            continue
        row = session.get(CaseActionMapping, mapping.id)
        if row:
            row.status = "needs_review"
            session.add(row)

    refresh_evidence = {
        "status": "conflict",
        "reason": reason,
        "run_id": run.id,
        "matched_action_ids": matched_action_ids,
        "unmatched_old_action_ids": unmatched_old_action_ids,
        "unmatched_new_action_ids": unmatched_new_action_ids,
    }
    for step in steps:
        metadata = _step_metadata(step)
        metadata["requires_review"] = True
        metadata["raw_refresh"] = refresh_evidence
        step.metadata_json = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
        step.updated_at = now
        session.add(step)

    flow.status = StructuredFlowStatus.needs_review.value
    flow.updated_at = now
    case.status = "needs_review"
    case.updated_at = now
    session.add(flow)
    session.add(case)
    session.commit()
    return {
        "status": "needs_review",
        "reason": reason,
        "flowId": flow.id,
        "runId": run.id,
        "matchedActionIds": matched_action_ids,
        "unmatchedOldActionIds": unmatched_old_action_ids,
        "unmatchedNewActionIds": unmatched_new_action_ids,
    }


def merge_refreshed_raw_actions(
    session: Session,
    project_id: str,
    case: TestCase,
    run: WebwrightRun,
) -> dict:
    flow = get_latest_flow(session, case.id)
    if not flow:
        raise ValueError("Existing structured flow required for raw refresh merge")
    if run.project_id != project_id or run.test_case_id != case.id:
        raise ValueError("Webwright run does not belong to selected case")

    mappings = get_mappings(session, case.id)
    steps = get_flow_steps(session, flow.id)
    mapping_ids = [mapping.id for mapping in mappings if mapping.id]
    steps_by_mapping = {step.mapping_id: step for step in steps if step.mapping_id}
    old_action_ids = [
        action_id
        for mapping in mappings
        for action_id in mapping.action_ids
    ]
    old_action_by_id = _actions_for_mappings(session, mappings)
    old_actions = [
        old_action_by_id[action_id]
        for action_id in old_action_ids
        if action_id in old_action_by_id
    ]
    new_actions = list(session.exec(
        select(RawAction)
        .where(RawAction.webwright_run_id == run.id)
        .order_by(RawAction.order_index)
    ).all())

    structural_reason = None
    methods_by_mapping: dict[str, PageObjectMethod] = {}
    if not mappings or len(mapping_ids) != len(mappings):
        structural_reason = "mapping_identity_missing"
    elif any(session.get(CaseActionMapping, mapping_id) is None for mapping_id in mapping_ids):
        structural_reason = "mapping_identity_missing"
    elif len(steps) != len(mappings) or any(mapping_id not in steps_by_mapping for mapping_id in mapping_ids):
        structural_reason = "stable_structure_incomplete"
    elif len(old_actions) != len(old_action_ids):
        structural_reason = "existing_raw_action_missing"
    elif any(mapping.status != "mapped" or not mapping.action_ids for mapping in mappings):
        structural_reason = "existing_mapping_needs_review"
    else:
        for mapping_id in mapping_ids:
            step = steps_by_mapping[mapping_id]
            method = session.get(PageObjectMethod, step.page_object_method_id) if step.page_object_method_id else None
            if not method:
                structural_reason = "stable_structure_incomplete"
                break
            if _method_used_by_other_cases(session, method.id, case.id):
                structural_reason = "shared_page_object_method"
                break
            methods_by_mapping[mapping_id] = method

    matches, unmatched_old, unmatched_new, match_reason = _match_refreshed_actions(old_actions, new_actions)
    reason = structural_reason or match_reason
    if reason:
        return _mark_raw_refresh_needs_review(
            session,
            case=case,
            run=run,
            flow=flow,
            mappings=mappings,
            steps=steps,
            reason=reason,
            matched_action_ids=matches,
            unmatched_old_action_ids=unmatched_old,
            unmatched_new_action_ids=unmatched_new,
        )

    now = datetime.utcnow()
    new_action_by_id = {action.id: action for action in new_actions if action.id}
    flow_requires_review = False
    for mapping in mappings:
        previous_action_ids = list(mapping.action_ids)
        mapping.action_ids = [matches[action_id] for action_id in previous_action_ids]
        row = session.get(CaseActionMapping, mapping.id)
        for link in session.exec(
            select(CaseActionMappingAction).where(CaseActionMappingAction.mapping_id == mapping.id)
        ).all():
            session.delete(link)
        row.raw_action_id = mapping.action_ids[0]
        row.status = "mapped"
        session.add(row)
        for order_index, action_id in enumerate(mapping.action_ids):
            session.add(CaseActionMappingAction(
                mapping_id=mapping.id,
                raw_action_id=action_id,
                order_index=order_index,
            ))

        step = steps_by_mapping[mapping.id]
        method = methods_by_mapping[mapping.id]
        body_plan, actions, requires_review = build_method_body_plan(mapping, new_action_by_id)
        flow_requires_review = flow_requires_review or requires_review
        method.method_type = _method_type(actions, requires_review)
        method.selector = next((action.selector for action in actions if action.selector is not None), None)
        method.value_template = next((action.value for action in actions if action.value is not None), None)
        method.body_plan_json = json.dumps(body_plan, sort_keys=True, separators=(",", ":"))
        method.source_mapping_id = mapping.id
        method.status = (
            PageObjectMethodStatus.draft.value
            if requires_review
            else PageObjectMethodStatus.approved.value
        )
        method.updated_at = now
        session.add(method)

        metadata = _step_metadata(step)
        metadata["raw_action_ids"] = mapping.action_ids
        metadata["requires_review"] = requires_review
        metadata["raw_refresh"] = {
            "status": "merged",
            "run_id": run.id,
            "previous_raw_action_ids": previous_action_ids,
            "current_raw_action_ids": mapping.action_ids,
        }
        step.kind = _step_kind(actions)
        step.metadata_json = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
        step.updated_at = now
        session.add(step)

    flow.status = (
        StructuredFlowStatus.needs_review.value
        if flow_requires_review
        else StructuredFlowStatus.approved.value
    )
    flow.updated_at = now
    case.status = "needs_review" if flow_requires_review else "structured"
    case.updated_at = now
    session.add(flow)
    session.add(case)
    session.commit()
    return {
        "status": "needs_review" if flow_requires_review else "merged",
        "reason": "planner_review_required" if flow_requires_review else None,
        "flowId": flow.id,
        "runId": run.id,
        "matchedActionIds": matches,
        "unmatchedOldActionIds": [],
        "unmatchedNewActionIds": [],
    }


def validate_structure(session: Session, project_id: str, case_id: str) -> dict:
    flow = get_latest_flow(session, case_id)
    mappings = get_mappings(session, case_id)
    issues: list[str] = []
    if not flow:
        issues.append("structured_flow_missing")
    elif flow.status == StructuredFlowStatus.needs_review.value:
        issues.append("flow_needs_review")
    if not mappings:
        issues.append("mappings_missing")
    for mapping in mappings:
        if mapping.status == "needs_review":
            issues.append(f"mapping_needs_review:step_{mapping.tc_step_index}")
        if not mapping.pom_method_name and not mapping.normalized_step_name:
            issues.append(f"missing_step_name:step_{mapping.tc_step_index}")
    steps = get_flow_steps(session, flow.id) if flow else []
    if flow and len(steps) != len(mappings):
        issues.append("step_count_mismatch")
    project = session.get(Project, project_id)
    if project:
        output = Path(project.generated_project_path or Path(project.root_path) / "generated")
        generated_statuses = refresh_generated_file_statuses(session, project_id, output, commit=True)
        for relative_path, item in sorted(generated_statuses.items()):
            if item["status"] in {"edited", "stale", "conflict"}:
                issues.append(f"generated_file_{item['status']}:{relative_path}")
    return {"ok": not issues, "issues": issues, "flowId": flow.id if flow else None}
