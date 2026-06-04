from __future__ import annotations

import json
from datetime import datetime

from sqlmodel import Session, select

from worker.core.config import new_id
from worker.models.db import (
    PageObject,
    PageObjectMethod,
    PageObjectMethodStatus,
    PageObjectMethodType,
    RawAction,
    StructuredFlow,
    StructuredFlowStatus,
    StructuredStep,
    StructuredStepKind,
    TestCase,
    WebwrightRun,
)
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
    return {"ok": not issues, "issues": issues, "flowId": flow.id if flow else None}
