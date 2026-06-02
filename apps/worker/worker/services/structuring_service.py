from __future__ import annotations

import json
from datetime import datetime

from sqlmodel import Session, select

from worker.core.config import new_id
from worker.models.db import (
    CaseActionMapping,
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
from worker.services.mapping import get_actions, get_mappings


def _snake(name: str) -> str:
    return name.lower().replace("-", "_").replace(" ", "_")


def _action_kind(action: RawAction | None) -> str:
    if not action:
        return StructuredStepKind.interaction.value
    if action.type == "goto":
        return StructuredStepKind.navigation.value
    if action.type in ("assert", "expect"):
        return StructuredStepKind.assertion.value
    if action.type == "wait":
        return StructuredStepKind.wait.value
    return StructuredStepKind.interaction.value


def sync_structured_entities(session: Session, project_id: str, case: TestCase, run: WebwrightRun | None) -> StructuredFlow:
    mappings = get_mappings(session, case.id)
    actions = get_actions(session, run.id) if run else []
    action_by_id = {a.id: a for a in actions}

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

    for order_index, mapping in enumerate(mappings, start=1):
        action = next((action_by_id[aid] for aid in mapping.action_ids if aid in action_by_id), None)
        step_name = mapping.normalized_step_name or mapping.pom_method_name or f"step_{mapping.tc_step_index}"
        method_name = _snake(mapping.pom_method_name or step_name)

        method_type = PageObjectMethodType.click.value
        selector = None
        value_template = None
        body_plan: list[dict] = []
        if action:
            if action.type == "goto":
                method_type = PageObjectMethodType.navigate.value
            elif action.type in {e.value for e in PageObjectMethodType}:
                method_type = action.type
            else:
                method_type = PageObjectMethodType.custom.value
            selector = action.selector
            value_template = action.value
            body_plan = [{"action": action.type, "selector": action.selector, "value": action.value, "target": action.target}]

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
                body_plan_json=json.dumps(body_plan),
                source_mapping_id=mapping.id,
                status=PageObjectMethodStatus.approved.value,
            )
            session.add(pom)
            session.flush()

        session.add(StructuredStep(
            id=new_id("ss"),
            structured_flow_id=flow.id,
            mapping_id=mapping.id,
            order_index=order_index,
            name=step_name,
            kind=_action_kind(action),
            page_object_method_id=pom.id,
            metadata_json=json.dumps({"tc_step_index": mapping.tc_step_index}),
        ))

    case.status = "structured"
    session.add(case)
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
