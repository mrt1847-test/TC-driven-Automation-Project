from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Optional

from sqlmodel import Session, select

from worker.models.db import (
    ArtifactAsset,
    CaseActionMapping,
    CaseActionMappingAction,
    ExecutionResult,
    ExecutionRun,
    GeneratedFile,
    GeneratedFileOrigin,
    PageObject,
    PageObjectMethod,
    RawAction,
    StructuredFlow,
    StructuredStep,
    WebwrightRun,
)
from worker.models.schemas import FailureTargetResolution


def _ids(values: Iterable[object]) -> list[str]:
    return sorted({value.id for value in values if getattr(value, "id", None)})


def _latest_generated_files(files: list[GeneratedFile]) -> list[GeneratedFile]:
    latest_by_path: dict[str, GeneratedFile] = {}
    for generated_file in files:
        current = latest_by_path.get(generated_file.relative_path)
        candidate_key = (
            generated_file.updated_at,
            generated_file.created_at,
            generated_file.id or "",
        )
        if current is None:
            latest_by_path[generated_file.relative_path] = generated_file
            continue
        current_key = (current.updated_at, current.created_at, current.id or "")
        if candidate_key > current_key:
            latest_by_path[generated_file.relative_path] = generated_file
    return sorted(latest_by_path.values(), key=lambda item: (item.relative_path, item.id or ""))


def _method_mentioned(error: Optional[str], method_name: str) -> bool:
    if not error:
        return False
    pattern = rf"(?<![A-Za-z0-9_]){re.escape(method_name)}(?![A-Za-z0-9_])"
    return re.search(pattern, error) is not None


def _artifact_ids_for_sources(
    session: Session,
    project_id: str,
    source_pairs: set[tuple[str, Optional[str]]],
) -> list[str]:
    artifacts = [
        artifact
        for artifact in session.exec(
            select(ArtifactAsset).where(ArtifactAsset.project_id == project_id)
        ).all()
        if (artifact.source_type, artifact.source_id) in source_pairs
    ]
    return _ids(artifacts)


def resolve_failure_target(session: Session, execution_result_id: str) -> FailureTargetResolution:
    result = session.get(ExecutionResult, execution_result_id)
    if result is None:
        return FailureTargetResolution(
            status="missing",
            reason="execution_result_missing",
            execution_result_id=execution_result_id,
        )

    base = {
        "execution_result_id": result.id,
        "execution_run_id": result.execution_run_id,
        "automation_key": result.automation_key,
        "source_type": result.source_type,
        "source_case_id": result.source_case_id,
    }
    if result.status != "failed":
        return FailureTargetResolution(
            status="missing",
            reason="execution_result_not_failed",
            **base,
        )

    execution_run = session.get(ExecutionRun, result.execution_run_id)
    if execution_run is None:
        return FailureTargetResolution(
            status="missing",
            reason="execution_run_missing",
            **base,
        )

    base["project_id"] = execution_run.project_id
    core_source_pairs = {
        ("execution_result", result.id),
        ("execution_run", execution_run.id),
    }
    core_artifact_ids = _artifact_ids_for_sources(
        session,
        execution_run.project_id,
        core_source_pairs,
    )
    generated_files = list(
        session.exec(
            select(GeneratedFile)
            .where(GeneratedFile.project_id == execution_run.project_id)
            .where(GeneratedFile.automation_key == result.automation_key)
        ).all()
    )
    latest_files = _latest_generated_files(generated_files)
    if not latest_files:
        return FailureTargetResolution(
            status="missing",
            reason="generated_files_missing",
            artifact_ids=core_artifact_ids,
            **base,
        )

    origin_pairs = {
        (generated_file.source_type, generated_file.source_id)
        for generated_file in latest_files
        if generated_file.source_type and generated_file.source_id
    }
    latest_file_ids = _ids(latest_files)
    origins = list(
        session.exec(
            select(GeneratedFileOrigin).where(
                GeneratedFileOrigin.generated_file_id.in_(latest_file_ids)
            )
        ).all()
    )
    origin_pairs.update((origin.origin_type, origin.origin_id) for origin in origins)

    flow_origin_ids = {
        origin_id for origin_type, origin_id in origin_pairs if origin_type == "structured_flow"
    }
    project_flows = list(
        session.exec(
            select(StructuredFlow)
            .where(StructuredFlow.project_id == execution_run.project_id)
            .where(StructuredFlow.automation_key == result.automation_key)
        ).all()
    )
    flows = [flow for flow in project_flows if flow.id in flow_origin_ids]
    flow_ids = _ids(flows)

    step_origin_ids = {
        origin_id for origin_type, origin_id in origin_pairs if origin_type == "structured_step"
    }
    candidate_steps: list[StructuredStep] = []
    if flow_ids:
        candidate_steps.extend(
            session.exec(
                select(StructuredStep).where(StructuredStep.structured_flow_id.in_(flow_ids))
            ).all()
        )
    if step_origin_ids:
        explicit_steps = session.exec(
            select(StructuredStep).where(StructuredStep.id.in_(step_origin_ids))
        ).all()
        valid_flow_ids = {
            flow.id
            for flow in session.exec(
                select(StructuredFlow)
                .where(StructuredFlow.id.in_({step.structured_flow_id for step in explicit_steps}))
                .where(StructuredFlow.project_id == execution_run.project_id)
                .where(StructuredFlow.automation_key == result.automation_key)
            ).all()
        }
        candidate_steps.extend(
            step for step in explicit_steps if step.structured_flow_id in valid_flow_ids
        )
    candidate_steps = list({step.id: step for step in candidate_steps if step.id}.values())
    flow_ids = sorted({*flow_ids, *(step.structured_flow_id for step in candidate_steps)})
    linked_flows = [flow for flow in project_flows if flow.id in flow_ids]

    pom_origin_ids = {
        origin_id for origin_type, origin_id in origin_pairs if origin_type == "page_object_method"
    }
    candidate_pom_ids = {
        step.page_object_method_id for step in candidate_steps if step.page_object_method_id
    }
    candidate_pom_ids.update(pom_origin_ids)
    candidate_poms: list[PageObjectMethod] = []
    if candidate_pom_ids:
        possible_poms = session.exec(
            select(PageObjectMethod).where(PageObjectMethod.id.in_(candidate_pom_ids))
        ).all()
        page_object_ids = {pom.page_object_id for pom in possible_poms}
        valid_page_object_ids = {
            page_object.id
            for page_object in session.exec(
                select(PageObject)
                .where(PageObject.id.in_(page_object_ids))
                .where(PageObject.project_id == execution_run.project_id)
            ).all()
        }
        candidate_poms = [pom for pom in possible_poms if pom.page_object_id in valid_page_object_ids]

    candidate_step_ids = _ids(candidate_steps)
    candidate_pom_ids_list = _ids(candidate_poms)
    selected_poms = [pom for pom in candidate_poms if _method_mentioned(result.error, pom.name)]
    if not selected_poms and len(candidate_poms) == 1:
        selected_poms = candidate_poms

    selected_steps: list[StructuredStep] = []
    if len(selected_poms) == 1:
        selected_steps = [
            step for step in candidate_steps if step.page_object_method_id == selected_poms[0].id
        ]
    target_is_resolved = len(selected_poms) == 1 and len(selected_steps) == 1
    evidence_steps = selected_steps if target_is_resolved else candidate_steps
    evidence_poms = selected_poms if target_is_resolved else candidate_poms

    mapping_origin_ids = {
        origin_id
        for origin_type, origin_id in origin_pairs
        if origin_type in {"mapping", "case_action_mapping"}
    }
    mapping_ids = set(mapping_origin_ids)
    mapping_ids.update(step.mapping_id for step in evidence_steps if step.mapping_id)
    mapping_ids.update(pom.source_mapping_id for pom in evidence_poms if pom.source_mapping_id)

    mappings: list[CaseActionMapping] = []
    mapping_actions: list[CaseActionMappingAction] = []
    if mapping_ids:
        possible_mappings = list(
            session.exec(select(CaseActionMapping).where(CaseActionMapping.id.in_(mapping_ids))).all()
        )
        valid_mapping_case_ids = {flow.test_case_id for flow in linked_flows}
        mappings = [
            mapping for mapping in possible_mappings
            if mapping.test_case_id in valid_mapping_case_ids
        ]
        mapping_ids = set(_ids(mappings))
        mapping_actions = list(
            session.exec(
                select(CaseActionMappingAction).where(
                    CaseActionMappingAction.mapping_id.in_(mapping_ids)
                )
            ).all()
        )

    raw_action_ids = {
        origin_id for origin_type, origin_id in origin_pairs if origin_type == "raw_action"
    }
    raw_action_ids.update(mapping.raw_action_id for mapping in mappings if mapping.raw_action_id)
    raw_action_ids.update(action.raw_action_id for action in mapping_actions)
    possible_raw_actions: list[RawAction] = []
    if raw_action_ids:
        possible_raw_actions = list(
            session.exec(select(RawAction).where(RawAction.id.in_(raw_action_ids))).all()
        )

    webwright_run_ids = {action.webwright_run_id for action in possible_raw_actions}
    webwright_runs: list[WebwrightRun] = []
    if webwright_run_ids:
        webwright_runs = list(
            session.exec(
                select(WebwrightRun)
                .where(WebwrightRun.id.in_(webwright_run_ids))
                .where(WebwrightRun.project_id == execution_run.project_id)
                .where(WebwrightRun.automation_key == result.automation_key)
            ).all()
        )
    valid_webwright_run_ids = set(_ids(webwright_runs))
    raw_actions = [
        action for action in possible_raw_actions
        if action.webwright_run_id in valid_webwright_run_ids
    ]
    raw_action_ids = set(_ids(raw_actions))

    source_pairs = {
        ("execution_result", result.id),
        ("execution_run", execution_run.id),
        *(("generated_file", generated_file_id) for generated_file_id in latest_file_ids),
        *(("mapping", mapping_id) for mapping_id in mapping_ids),
        *(("raw_action", raw_action_id) for raw_action_id in raw_action_ids),
        *(("webwright_run", run_id) for run_id in _ids(webwright_runs)),
    }
    artifact_ids = _artifact_ids_for_sources(session, execution_run.project_id, source_pairs)
    test_case_ids = {
        flow.test_case_id for flow in linked_flows
    }
    test_case_ids.update(run.test_case_id for run in webwright_runs)

    details = {
        **base,
        "test_case_ids": sorted(test_case_ids),
        "generated_file_ids": latest_file_ids,
        "structured_flow_ids": flow_ids,
        "structured_step_ids": candidate_step_ids,
        "page_object_method_ids": candidate_pom_ids_list,
        "mapping_ids": sorted(mapping_ids),
        "raw_action_ids": sorted(raw_action_ids),
        "webwright_run_ids": _ids(webwright_runs),
        "artifact_ids": artifact_ids,
    }
    if not candidate_steps:
        return FailureTargetResolution(
            status="missing",
            reason="structured_step_missing",
            **details,
        )
    if not candidate_poms:
        return FailureTargetResolution(
            status="missing",
            reason="page_object_method_missing",
            **details,
        )
    if len(selected_poms) == 1 and not selected_steps:
        return FailureTargetResolution(
            status="missing",
            reason="structured_target_link_missing",
            **details,
        )
    if not target_is_resolved:
        return FailureTargetResolution(
            status="ambiguous",
            reason="multiple_structured_targets",
            **details,
        )
    return FailureTargetResolution(
        status="resolved",
        reason="unique_structured_target",
        structured_step_id=selected_steps[0].id,
        page_object_method_id=selected_poms[0].id,
        **details,
    )
