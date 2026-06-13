from __future__ import annotations

import json
from typing import Any

from sqlalchemy import or_
from sqlmodel import Session, select

from worker.models.db import (
    ArtifactAsset,
    CaseActionMapping,
    PageObject,
    PageObjectMethod,
    RawAction,
    SelectorCandidate,
    StructuredFlow,
    StructuredStep,
    TestCase,
    WebwrightRun,
)
from worker.services.artifacts import artifact_asset_payload


def _parse_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _iso(value: object) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def _raw_action_payload(action: RawAction, run: WebwrightRun | None) -> dict[str, Any]:
    return {
        "id": action.id,
        "webwrightRunId": action.webwright_run_id,
        "webwrightRunStatus": run.status if run else None,
        "automationKey": action.automation_key,
        "orderIndex": action.order_index,
        "type": action.type,
        "target": action.target,
        "selector": action.selector,
        "value": action.value,
        "sourceLine": action.source_line,
    }


def _mapping_payload(mapping: CaseActionMapping | None) -> dict[str, Any] | None:
    if not mapping:
        return None
    return {
        "id": mapping.id,
        "tcStepIndex": mapping.tc_step_index,
        "normalizedStepId": mapping.normalized_step_id,
        "normalizedStepName": mapping.normalized_step_name,
        "pomMethodName": mapping.pom_method_name,
        "status": mapping.status,
    }


def _step_payload(
    step: StructuredStep,
    flow: StructuredFlow | None,
    mapping: CaseActionMapping | None,
) -> dict[str, Any]:
    return {
        "id": step.id,
        "structuredFlowId": step.structured_flow_id,
        "structuredFlowVersion": flow.version if flow else None,
        "structuredFlowStatus": flow.status if flow else None,
        "mappingId": step.mapping_id,
        "tcStepIndex": mapping.tc_step_index if mapping else None,
        "orderIndex": step.order_index,
        "name": step.name,
        "kind": step.kind,
        "metadata": _parse_metadata(step.metadata_json),
    }


def _method_payload(
    method: PageObjectMethod,
    *,
    page_object: PageObject | None,
    mapping: CaseActionMapping | None,
    steps: list[StructuredStep],
    flow_by_id: dict[str, StructuredFlow],
    mapping_by_id: dict[str, CaseActionMapping],
) -> dict[str, Any]:
    step_payloads = [
        _step_payload(step, flow_by_id.get(step.structured_flow_id), mapping_by_id.get(step.mapping_id or ""))
        for step in sorted(steps, key=lambda item: (item.order_index, item.id or ""))
    ]
    tc_step_indexes = sorted({
        step_payload["tcStepIndex"]
        for step_payload in step_payloads
        if step_payload["tcStepIndex"] is not None
    })
    return {
        "id": method.id,
        "name": method.name,
        "methodType": method.method_type,
        "selector": method.selector,
        "valueTemplate": method.value_template,
        "returnType": method.return_type,
        "sourceMappingId": method.source_mapping_id,
        "status": method.status,
        "pageObjectId": method.page_object_id,
        "pageObjectName": page_object.name if page_object else None,
        "pageObjectFilePath": page_object.file_path if page_object else None,
        "mapping": _mapping_payload(mapping),
        "structuredSteps": step_payloads,
        "tcStepIndexes": tc_step_indexes,
    }


def _candidate_lite(
    candidate: SelectorCandidate,
    source_artifact: ArtifactAsset | None,
) -> dict[str, Any]:
    source_artifact_id = source_artifact.id if source_artifact else None
    return {
        "id": candidate.id,
        "selectorType": candidate.selector_type,
        "selectorValue": candidate.selector_value,
        "type": candidate.selector_type,
        "value": candidate.selector_value,
        "confidence": candidate.confidence,
        "sourceArtifactId": source_artifact_id,
    }


def _candidate_payload(
    session: Session,
    candidate: SelectorCandidate,
    *,
    raw_action: RawAction | None,
    raw_run: WebwrightRun | None,
    method: PageObjectMethod | None,
    page_object: PageObject | None,
    mapping: CaseActionMapping | None,
    steps: list[StructuredStep],
    flow_by_id: dict[str, StructuredFlow],
    mapping_by_id: dict[str, CaseActionMapping],
    source_artifact: ArtifactAsset | None,
) -> dict[str, Any]:
    payload = {
        **_candidate_lite(candidate, source_artifact),
        "rawActionId": candidate.raw_action_id if raw_action else None,
        "pageObjectMethodId": candidate.page_object_method_id if method else None,
        "metadata": _parse_metadata(candidate.metadata_json),
        "createdAt": _iso(candidate.created_at),
        "rawAction": _raw_action_payload(raw_action, raw_run) if raw_action else None,
        "pageObjectMethod": None,
        "sourceArtifact": artifact_asset_payload(session, source_artifact) if source_artifact else None,
    }
    if method:
        payload["pageObjectMethod"] = _method_payload(
            method,
            page_object=page_object,
            mapping=mapping,
            steps=steps,
            flow_by_id=flow_by_id,
            mapping_by_id=mapping_by_id,
        )
    return payload


def _raw_action_context(
    session: Session,
    *,
    project_id: str,
    case_id: str,
) -> tuple[dict[str, RawAction], dict[str, WebwrightRun]]:
    runs = session.exec(
        select(WebwrightRun)
        .where(WebwrightRun.project_id == project_id, WebwrightRun.test_case_id == case_id)
        .order_by(WebwrightRun.created_at, WebwrightRun.id)
    ).all()
    run_by_id = {run.id: run for run in runs if run.id}
    if not run_by_id:
        return {}, {}
    actions = session.exec(
        select(RawAction)
        .where(RawAction.webwright_run_id.in_(list(run_by_id)))
        .order_by(RawAction.webwright_run_id, RawAction.order_index, RawAction.id)
    ).all()
    return {action.id: action for action in actions if action.id}, run_by_id


def _method_context(
    session: Session,
    *,
    project_id: str,
    case_id: str,
) -> tuple[
    dict[str, PageObjectMethod],
    dict[str, PageObject],
    dict[str, CaseActionMapping],
    dict[str, list[StructuredStep]],
    dict[str, StructuredFlow],
]:
    mappings = session.exec(
        select(CaseActionMapping)
        .where(CaseActionMapping.test_case_id == case_id)
        .order_by(CaseActionMapping.tc_step_index, CaseActionMapping.id)
    ).all()
    mapping_by_id = {mapping.id: mapping for mapping in mappings if mapping.id}

    flows = session.exec(
        select(StructuredFlow)
        .where(StructuredFlow.project_id == project_id, StructuredFlow.test_case_id == case_id)
        .order_by(StructuredFlow.version, StructuredFlow.id)
    ).all()
    flow_by_id = {flow.id: flow for flow in flows if flow.id}

    steps: list[StructuredStep] = []
    if flow_by_id:
        steps = session.exec(
            select(StructuredStep)
            .where(StructuredStep.structured_flow_id.in_(list(flow_by_id)))
            .order_by(StructuredStep.structured_flow_id, StructuredStep.order_index, StructuredStep.id)
        ).all()

    step_method_ids = {
        step.page_object_method_id
        for step in steps
        if step.page_object_method_id
    }
    mapping_ids = set(mapping_by_id)

    method_conditions = []
    if mapping_ids:
        method_conditions.append(PageObjectMethod.source_mapping_id.in_(sorted(mapping_ids)))
    if step_method_ids:
        method_conditions.append(PageObjectMethod.id.in_(sorted(step_method_ids)))
    if not method_conditions:
        return {}, {}, mapping_by_id, {}, flow_by_id

    possible_methods = session.exec(
        select(PageObjectMethod)
        .where(or_(*method_conditions))
        .order_by(PageObjectMethod.name, PageObjectMethod.id)
    ).all()
    page_object_ids = {
        method.page_object_id
        for method in possible_methods
        if method.page_object_id
    }
    page_objects: list[PageObject] = []
    if page_object_ids:
        page_objects = session.exec(
            select(PageObject)
            .where(PageObject.id.in_(sorted(page_object_ids)), PageObject.project_id == project_id)
        ).all()
    page_object_by_id = {page_object.id: page_object for page_object in page_objects if page_object.id}

    method_by_id = {
        method.id: method
        for method in possible_methods
        if method.id and method.page_object_id in page_object_by_id
    }
    steps_by_method: dict[str, list[StructuredStep]] = {}
    for step in steps:
        if step.page_object_method_id in method_by_id:
            steps_by_method.setdefault(step.page_object_method_id, []).append(step)
    return method_by_id, page_object_by_id, mapping_by_id, steps_by_method, flow_by_id


def list_case_selector_candidates(session: Session, case: TestCase) -> dict[str, Any]:
    raw_action_by_id, run_by_id = _raw_action_context(
        session,
        project_id=case.project_id,
        case_id=case.id,
    )
    (
        method_by_id,
        page_object_by_id,
        mapping_by_id,
        steps_by_method,
        flow_by_id,
    ) = _method_context(session, project_id=case.project_id, case_id=case.id)

    conditions = []
    if raw_action_by_id:
        conditions.append(SelectorCandidate.raw_action_id.in_(sorted(raw_action_by_id)))
    if method_by_id:
        conditions.append(SelectorCandidate.page_object_method_id.in_(sorted(method_by_id)))
    candidate_rows: list[SelectorCandidate] = []
    if conditions:
        candidate_rows = session.exec(
            select(SelectorCandidate)
            .where(or_(*conditions))
            .order_by(SelectorCandidate.created_at, SelectorCandidate.id)
        ).all()

    source_artifact_ids = sorted({
        candidate.source_artifact_id
        for candidate in candidate_rows
        if candidate.source_artifact_id
    })
    source_artifact_by_id: dict[str, ArtifactAsset] = {}
    if source_artifact_ids:
        artifacts = session.exec(
            select(ArtifactAsset).where(ArtifactAsset.id.in_(source_artifact_ids))
        ).all()
        source_artifact_by_id = {
            artifact.id: artifact
            for artifact in artifacts
            if artifact.id and artifact.project_id == case.project_id
        }

    candidates: list[dict[str, Any]] = []
    raw_group_ids: dict[str, list[str]] = {}
    method_group_ids: dict[str, list[str]] = {}
    for candidate in candidate_rows:
        raw_action = raw_action_by_id.get(candidate.raw_action_id or "")
        method = method_by_id.get(candidate.page_object_method_id or "")
        if not raw_action and not method:
            continue

        source_artifact = source_artifact_by_id.get(candidate.source_artifact_id or "")
        raw_run = run_by_id.get(raw_action.webwright_run_id) if raw_action else None
        page_object = page_object_by_id.get(method.page_object_id) if method else None
        mapping = mapping_by_id.get(method.source_mapping_id or "") if method else None
        payload = _candidate_payload(
            session,
            candidate,
            raw_action=raw_action,
            raw_run=raw_run,
            method=method,
            page_object=page_object,
            mapping=mapping,
            steps=steps_by_method.get(method.id, []) if method and method.id else [],
            flow_by_id=flow_by_id,
            mapping_by_id=mapping_by_id,
            source_artifact=source_artifact,
        )
        candidates.append(payload)
        if raw_action and raw_action.id and candidate.id:
            raw_group_ids.setdefault(raw_action.id, []).append(candidate.id)
        if method and method.id and candidate.id:
            method_group_ids.setdefault(method.id, []).append(candidate.id)

    raw_action_groups = [
        {
            "rawAction": _raw_action_payload(raw_action_by_id[raw_action_id], run_by_id.get(raw_action_by_id[raw_action_id].webwright_run_id)),
            "candidateIds": candidate_ids,
            "candidateCount": len(candidate_ids),
        }
        for raw_action_id, candidate_ids in sorted(
            raw_group_ids.items(),
            key=lambda item: (
                run_by_id.get(raw_action_by_id[item[0]].webwright_run_id).created_at
                if run_by_id.get(raw_action_by_id[item[0]].webwright_run_id)
                else None,
                raw_action_by_id[item[0]].order_index,
                item[0],
            ),
        )
    ]
    page_object_method_groups = [
        {
            "pageObjectMethod": _method_payload(
                method_by_id[method_id],
                page_object=page_object_by_id.get(method_by_id[method_id].page_object_id),
                mapping=mapping_by_id.get(method_by_id[method_id].source_mapping_id or ""),
                steps=steps_by_method.get(method_id, []),
                flow_by_id=flow_by_id,
                mapping_by_id=mapping_by_id,
            ),
            "candidateIds": candidate_ids,
            "candidateCount": len(candidate_ids),
        }
        for method_id, candidate_ids in sorted(
            method_group_ids.items(),
            key=lambda item: (method_by_id[item[0]].name, item[0]),
        )
    ]

    return {
        "projectId": case.project_id,
        "caseId": case.id,
        "automationKey": case.automation_key,
        "candidateCount": len(candidates),
        "rawActionIds": sorted(raw_action_by_id),
        "pageObjectMethodIds": sorted(method_by_id),
        "candidates": candidates,
        "groups": {
            "rawActions": raw_action_groups,
            "pageObjectMethods": page_object_method_groups,
        },
    }
