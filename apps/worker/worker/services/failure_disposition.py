from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Optional

from sqlmodel import Session, select

from worker.models.db import (
    ArtifactAsset,
    ExecutionResult,
    ExecutionRun,
    PageObjectMethod,
    RawAction,
    SelectorCandidate,
)
from worker.models.schemas import (
    ExecutionDiagnosis,
    FailureDispositionDiagnosis,
    FailureTargetResolution,
)
from worker.services.failure_target_resolver import resolve_failure_target

_SELECTOR_CATEGORIES = {
    "locator_not_found",
    "selector_changed",
    "selector_not_found",
    "strict_mode_violation",
}
_RAW_REFRESH_CATEGORIES = {
    "action_sequence_changed",
    "flow_changed",
    "raw_refresh_required",
    "ux_flow_changed",
    "workflow_changed",
}
_FEATURE_REMOVED_CATEGORIES = {
    "feature_removed",
    "feature_removed_retire_tc",
    "page_removed",
    "route_removed",
    "tc_obsolete",
}
_SIGNAL_METADATA_KEYS = {
    "category",
    "disposition",
    "error_category",
    "failure_disposition",
}


def _ids(values: Iterable[object]) -> list[str]:
    return sorted({value.id for value in values if getattr(value, "id", None)})


def _metadata_categories(artifacts: list[ArtifactAsset]) -> set[str]:
    categories: set[str] = set()
    for artifact in artifacts:
        if not artifact.metadata_json:
            continue
        try:
            metadata = json.loads(artifact.metadata_json)
        except (TypeError, ValueError):
            continue
        if not isinstance(metadata, dict):
            continue
        for key in _SIGNAL_METADATA_KEYS:
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                categories.add(value.strip().lower().replace("-", "_").replace(" ", "_"))
    return categories


def _error_signals(error: Optional[str]) -> set[str]:
    if not error:
        return set()
    text = error.lower()
    signals: set[str] = set()
    selector_term = re.search(r"\b(selector|locator|strict[- ]mode)\b", text)
    selector_failure = re.search(
        r"\b(not found|no element|timeout|timed out|failed|violation|resolved to)\b",
        text,
    )
    if selector_term and selector_failure:
        signals.add("selector_changed")
    if re.search(
        r"\b(raw refresh|required raw|flow changed|workflow changed|"
        r"action sequence changed|ux flow changed|unexpected page)\b",
        text,
    ):
        signals.add("raw_refresh_required")
    if re.search(
        r"\b(feature removed|page removed|route removed|no longer exists|"
        r"410 gone|obsolete test|retire tc)\b",
        text,
    ):
        signals.add("feature_removed_retire_tc")
    return signals


def _metadata_signals(categories: set[str]) -> set[str]:
    signals: set[str] = set()
    if categories & _SELECTOR_CATEGORIES:
        signals.add("selector_changed")
    if categories & _RAW_REFRESH_CATEGORIES:
        signals.add("raw_refresh_required")
    if categories & _FEATURE_REMOVED_CATEGORIES:
        signals.add("feature_removed_retire_tc")
    return signals


def _linked_selector_evidence(
    session: Session,
    target: FailureTargetResolution,
) -> tuple[list[SelectorCandidate], list[str]]:
    candidates: list[SelectorCandidate] = []
    if target.raw_action_ids:
        candidates.extend(
            session.exec(
                select(SelectorCandidate).where(
                    SelectorCandidate.raw_action_id.in_(target.raw_action_ids)
                )
            ).all()
        )
    if target.page_object_method_id:
        candidates.extend(
            session.exec(
                select(SelectorCandidate).where(
                    SelectorCandidate.page_object_method_id == target.page_object_method_id
                )
            ).all()
        )
    candidates = list({candidate.id: candidate for candidate in candidates if candidate.id}.values())

    has_linked_selector = bool(candidates)
    if not has_linked_selector and target.raw_action_ids:
        actions = session.exec(select(RawAction).where(RawAction.id.in_(target.raw_action_ids))).all()
        has_linked_selector = any(action.selector for action in actions)
    if not has_linked_selector and target.page_object_method_id:
        method = session.get(PageObjectMethod, target.page_object_method_id)
        has_linked_selector = bool(method and method.selector)

    artifact_ids = sorted({
        candidate.source_artifact_id
        for candidate in candidates
        if candidate.source_artifact_id
    })
    return candidates, artifact_ids if has_linked_selector else []


def classify_failure_disposition(
    session: Session,
    execution_result_id: str,
) -> FailureDispositionDiagnosis:
    result = session.get(ExecutionResult, execution_result_id)
    target = resolve_failure_target(session, execution_result_id)
    automation_key = result.automation_key if result else target.automation_key
    base = {
        "execution_result_id": execution_result_id,
        "automation_key": automation_key,
        "target": target,
    }
    if result is None:
        return FailureDispositionDiagnosis(
            disposition="unknown",
            reason="execution_result_missing",
            confidence=0,
            **base,
        )
    if result.status != "failed":
        return FailureDispositionDiagnosis(
            disposition="unknown",
            reason="execution_result_not_failed",
            confidence=0,
            **base,
        )

    artifacts: list[ArtifactAsset] = []
    if target.artifact_ids:
        artifacts = list(
            session.exec(
                select(ArtifactAsset).where(ArtifactAsset.id.in_(target.artifact_ids))
            ).all()
        )
    candidates, candidate_artifact_ids = _linked_selector_evidence(session, target)
    project_candidate_artifacts: list[ArtifactAsset] = []
    if candidate_artifact_ids and target.project_id:
        project_candidate_artifacts = list(
            session.exec(
                select(ArtifactAsset)
                .where(ArtifactAsset.id.in_(candidate_artifact_ids))
                .where(ArtifactAsset.project_id == target.project_id)
            ).all()
        )
    artifacts = list({
        artifact.id: artifact
        for artifact in [*artifacts, *project_candidate_artifacts]
        if artifact.id
    }.values())
    evidence_artifact_ids = _ids(artifacts)
    selector_candidate_ids = _ids(candidates)

    if target.status != "resolved":
        return FailureDispositionDiagnosis(
            disposition="unknown",
            reason=f"target_{target.status}:{target.reason}",
            confidence=0,
            evidence_artifact_ids=evidence_artifact_ids,
            selector_candidate_ids=selector_candidate_ids,
            **base,
        )

    categories = _metadata_categories(artifacts)
    metadata_signals = _metadata_signals(categories)
    error_signals = _error_signals(result.error)
    signals = metadata_signals | error_signals
    if len(signals) > 1:
        return FailureDispositionDiagnosis(
            disposition="unknown",
            reason="mixed_failure_signals",
            confidence=0.2,
            evidence_artifact_ids=evidence_artifact_ids,
            selector_candidate_ids=selector_candidate_ids,
            **base,
        )
    if not signals:
        return FailureDispositionDiagnosis(
            disposition="unknown",
            reason="insufficient_failure_evidence",
            confidence=0.1,
            evidence_artifact_ids=evidence_artifact_ids,
            selector_candidate_ids=selector_candidate_ids,
            **base,
        )

    disposition = next(iter(signals))
    if disposition == "selector_changed":
        has_selector_context = bool(candidates)
        if not has_selector_context and target.raw_action_ids:
            actions = session.exec(
                select(RawAction).where(RawAction.id.in_(target.raw_action_ids))
            ).all()
            has_selector_context = any(action.selector for action in actions)
        if not has_selector_context and target.page_object_method_id:
            method = session.get(PageObjectMethod, target.page_object_method_id)
            has_selector_context = bool(method and method.selector)
        if not has_selector_context:
            return FailureDispositionDiagnosis(
                disposition="unknown",
                reason="selector_signal_without_linked_selector_evidence",
                confidence=0.2,
                evidence_artifact_ids=evidence_artifact_ids,
                selector_candidate_ids=selector_candidate_ids,
                **base,
            )
        confidence = 0.9 if "selector_changed" in metadata_signals else 0.82
        reason = "linked_selector_failure_evidence"
    elif disposition == "raw_refresh_required":
        confidence = 0.8 if disposition in metadata_signals else 0.7
        reason = "linked_flow_change_evidence"
    else:
        confidence = 0.85 if disposition in metadata_signals else 0.75
        reason = "linked_feature_removed_evidence"

    return FailureDispositionDiagnosis(
        disposition=disposition,
        reason=reason,
        confidence=confidence,
        evidence_artifact_ids=evidence_artifact_ids,
        selector_candidate_ids=selector_candidate_ids,
        **base,
    )


def diagnose_execution_failures(
    session: Session,
    execution_run: ExecutionRun,
) -> ExecutionDiagnosis:
    failed_results = session.exec(
        select(ExecutionResult)
        .where(ExecutionResult.execution_run_id == execution_run.id)
        .where(ExecutionResult.status == "failed")
        .order_by(ExecutionResult.id)
    ).all()
    return ExecutionDiagnosis(
        project_id=execution_run.project_id,
        execution_id=execution_run.id or "",
        diagnoses=[
            classify_failure_disposition(session, result.id or "")
            for result in failed_results
        ],
    )
