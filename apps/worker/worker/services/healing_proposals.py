from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from sqlmodel import Session, select

from worker.core.config import load_settings, new_id
from worker.models.db import (
    ArtifactAsset,
    ExecutionResult,
    ExecutionRun,
    GeneratedFile,
    GeneratedFileStatus,
    HealingProposal,
    HealingProposalKind,
    HealingProposalStatus,
    PageObjectMethod,
    PageObjectMethodStatus,
    Project,
    RawAction,
    SelectorCandidate,
    StructuredFlow,
    StructuredStep,
)
from worker.services.failure_disposition import classify_failure_disposition
from worker.services.project_generator import (
    GenerationConflictError,
    GenerationResult,
    generate_project,
)

_AUTO_APPLY_MIN_CONFIDENCE = 0.95
_AUTO_APPLY_FAILURE_CATEGORIES = {
    "locator_not_found",
    "selector_not_found",
    "strict_mode_violation",
}
_AUTO_APPLY_SELECTOR_TYPES = {"role", "text", "test_id"}
_SIGNAL_METADATA_KEYS = {
    "category",
    "disposition",
    "error_category",
    "failure_disposition",
}
_ROLE_SELECTOR_PATTERN = re.compile(
    r"get_by_role\(\s*['\"](?P<role>[^'\"]+)['\"](?:\s*,\s*name\s*=\s*['\"](?P<name>[^'\"]+)['\"])?",
    re.IGNORECASE,
)
_TEXT_SELECTOR_PATTERN = re.compile(r"get_by_(?:text|label|placeholder)\(\s*['\"](?P<text>[^'\"]+)['\"]", re.IGNORECASE)
_TEST_ID_SELECTOR_PATTERN = re.compile(r"get_by_test_id\(\s*['\"](?P<test_id>[^'\"]+)['\"]", re.IGNORECASE)
_DATA_TEST_ID_PATTERN = re.compile(r"data-testid\s*=\s*['\"]?(?P<test_id>[^'\"\]]+)", re.IGNORECASE)


def _quote(value: str) -> str:
    return json.dumps(value)


def _selector_expression(candidate: SelectorCandidate) -> str:
    value = candidate.selector_value
    if candidate.selector_type == "test_id":
        return f"page.get_by_test_id({_quote(value)})"
    if candidate.selector_type == "text":
        return f"page.get_by_text({_quote(value)})"
    if candidate.selector_type == "role":
        role = value
        name: str | None = None
        if "[name='" in value and value.endswith("']"):
            role, name = value.split("[name='", 1)
            name = name[:-2]
        if name:
            return f"page.get_by_role({_quote(role)}, name={_quote(name)})"
        return f"page.get_by_role({_quote(role)})"
    if candidate.selector_type == "xpath":
        return f"page.locator({_quote('xpath=' + value)})"
    return f"page.locator({_quote(value)})"


def _canonical_selector(value: str | None) -> str:
    if not value:
        return ""
    return value.replace("'", '"').replace(" ", "")


def _proposal_payload(proposal: HealingProposal) -> dict:
    try:
        evidence = json.loads(proposal.evidence_json or "[]")
    except (TypeError, ValueError):
        evidence = []
    return {
        "id": proposal.id,
        "project_id": proposal.project_id,
        "automation_key": proposal.automation_key,
        "execution_result_id": proposal.execution_result_id,
        "page_object_method_id": proposal.page_object_method_id,
        "structured_step_id": proposal.structured_step_id,
        "kind": proposal.kind,
        "old_value": proposal.old_value,
        "new_value": proposal.new_value,
        "confidence": proposal.confidence,
        "status": proposal.status,
        "evidence": evidence,
        "created_at": proposal.created_at.isoformat() if proposal.created_at else None,
        "updated_at": proposal.updated_at.isoformat() if proposal.updated_at else None,
    }


def healing_proposal_payload(proposal: HealingProposal) -> dict:
    return _proposal_payload(proposal)


def _generation_payload(generation: GenerationResult) -> dict:
    return {
        "generatedProjectPath": str(generation.output),
        "generationMode": generation.mode,
        "selectedCaseIds": generation.selected_case_ids,
        "affectedFiles": generation.affected_files,
        "changedFiles": generation.changed_files,
        "preservedFiles": generation.preserved_files,
        "editedFiles": generation.edited_files,
        "staleFiles": generation.stale_files,
        "conflictFiles": generation.conflict_files,
    }


def _evidence_list(proposal: HealingProposal) -> list[dict]:
    try:
        evidence = json.loads(proposal.evidence_json or "[]")
    except (TypeError, ValueError):
        evidence = []
    return evidence if isinstance(evidence, list) else []


def _append_proposal_evidence(
    session: Session,
    proposal: HealingProposal,
    entry: dict,
) -> None:
    evidence = _evidence_list(proposal)
    comparable = {key: value for key, value in entry.items() if key != "at"}
    duplicate = any(
        item.get("type") == comparable.get("type")
        and item.get("status") == comparable.get("status")
        and item.get("reason") == comparable.get("reason")
        for item in evidence
        if isinstance(item, dict)
    )
    if not duplicate:
        evidence.append({
            **entry,
            "at": datetime.utcnow().isoformat(),
        })
        proposal.evidence_json = json.dumps(evidence, sort_keys=True)
    proposal.updated_at = datetime.utcnow()
    session.add(proposal)
    session.commit()
    session.refresh(proposal)


def _settings_auto_apply_enabled(project_id: str) -> bool:
    settings = load_settings()
    config = getattr(settings, "self_healing", {}) or {}
    project_ids = config.get("autoApplyProjectIds") or config.get("auto_apply_project_ids") or []
    if not isinstance(project_ids, list):
        return False
    return project_id in {str(item) for item in project_ids}


def _load_selector_candidates(session: Session, diagnosis) -> list[SelectorCandidate]:
    if not diagnosis.selector_candidate_ids:
        return []
    return sorted(
        session.exec(
            select(SelectorCandidate).where(
                SelectorCandidate.id.in_(diagnosis.selector_candidate_ids)
            )
        ).all(),
        key=lambda item: (-item.confidence, item.id or ""),
    )


def _proposal_candidate_id(proposal: HealingProposal) -> str | None:
    for item in _evidence_list(proposal):
        if isinstance(item, dict) and item.get("type") == "selector_candidate":
            candidate_id = item.get("selector_candidate_id")
            return str(candidate_id) if candidate_id else None
    return None


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


def _auto_apply_failure_signal(
    session: Session,
    diagnosis,
) -> str | None:
    artifacts: list[ArtifactAsset] = []
    if diagnosis.evidence_artifact_ids:
        artifacts = session.exec(
            select(ArtifactAsset).where(ArtifactAsset.id.in_(diagnosis.evidence_artifact_ids))
        ).all()
    exact_categories = sorted(_metadata_categories(artifacts) & _AUTO_APPLY_FAILURE_CATEGORIES)
    if exact_categories:
        return exact_categories[0]

    result = session.get(ExecutionResult, diagnosis.execution_result_id)
    text = (result.error if result else "") or ""
    lowered = text.lower()
    if "strict" in lowered and ("violation" in lowered or "resolved to" in lowered or "mismatch" in lowered):
        return "strict_mode_violation"
    selector_term = re.search(r"\b(selector|locator)\b", lowered)
    missing_term = re.search(r"\b(not found|no element|timeout|timed out|failed)\b", lowered)
    if selector_term and missing_term:
        return "selector_not_found"
    return None


def _selector_semantics(value: str | None) -> tuple[str, ...] | None:
    if not value:
        return None
    if match := _ROLE_SELECTOR_PATTERN.search(value):
        role = match.group("role").strip().lower()
        name = (match.group("name") or "").strip()
        return ("role", role, name)
    if match := _TEXT_SELECTOR_PATTERN.search(value):
        return ("text", match.group("text").strip())
    if match := _TEST_ID_SELECTOR_PATTERN.search(value):
        return ("test_id", match.group("test_id").strip())
    if match := _DATA_TEST_ID_PATTERN.search(value):
        return ("test_id", match.group("test_id").strip())
    return None


def _candidate_semantics(candidate: SelectorCandidate) -> tuple[str, ...] | None:
    value = candidate.selector_value.strip()
    if candidate.selector_type == "test_id":
        return ("test_id", value)
    if candidate.selector_type == "text":
        return ("text", value)
    if candidate.selector_type == "role":
        role = value
        name = ""
        if "[name='" in value and value.endswith("']"):
            role, name = value.split("[name='", 1)
            name = name[:-2]
        return ("role", role.strip().lower(), name.strip())
    return None


def _semantic_guard(old_value: str | None, candidate: SelectorCandidate) -> str | None:
    if candidate.selector_type not in _AUTO_APPLY_SELECTOR_TYPES:
        return "selector_semantics_unsupported"
    old_semantics = _selector_semantics(old_value)
    if old_semantics is None:
        return None
    if old_semantics == _candidate_semantics(candidate):
        return None
    return "selector_semantics_mismatch"


def _target_stale_reason(
    session: Session,
    project: Project,
    proposal: HealingProposal,
) -> str | None:
    if not proposal.page_object_method_id or not proposal.structured_step_id:
        return "proposal_target_incomplete"
    method = session.get(PageObjectMethod, proposal.page_object_method_id)
    step = session.get(StructuredStep, proposal.structured_step_id)
    if not method or not step:
        return "proposal_target_missing"
    if step.page_object_method_id != method.id:
        return "proposal_target_stale"
    flow = session.get(StructuredFlow, step.structured_flow_id)
    if not flow or flow.project_id != project.id:
        return "proposal_target_stale"
    if proposal.old_value and method.selector != proposal.old_value:
        return "proposal_target_stale"
    return None


def _generated_file_guard_reason(
    session: Session,
    diagnosis,
) -> dict | None:
    target = diagnosis.target
    if not target.generated_file_ids:
        return None
    rows = session.exec(
        select(GeneratedFile).where(GeneratedFile.id.in_(target.generated_file_ids))
    ).all()
    blocked = [
        row
        for row in rows
        if row.status in {
            GeneratedFileStatus.edited.value,
            GeneratedFileStatus.conflict.value,
            GeneratedFileStatus.stale.value,
        }
    ]
    if not blocked:
        return None
    return {
        "reason": "target_generated_file_" + sorted({row.status for row in blocked})[0],
        "files": sorted(row.relative_path for row in blocked),
    }


def _auto_apply_policy(
    session: Session,
    project: Project,
    proposal: HealingProposal,
    diagnosis,
) -> dict:
    project_id = project.id or ""
    if not _settings_auto_apply_enabled(project_id):
        return {"status": "disabled", "reason": "project_auto_apply_disabled"}
    if proposal.status == HealingProposalStatus.applied.value:
        return {"status": "applied", "reason": "proposal_already_applied"}
    if proposal.status != HealingProposalStatus.proposed.value:
        return {"status": "blocked", "reason": "proposal_not_proposed"}
    if proposal.kind != HealingProposalKind.selector_replace.value:
        return {"status": "blocked", "reason": "unsupported_proposal_kind"}

    failure_signal = _auto_apply_failure_signal(session, diagnosis)
    if not failure_signal:
        return {"status": "blocked", "reason": "failure_signal_not_auto_safe"}

    candidates = _load_selector_candidates(session, diagnosis)
    high_confidence = [
        candidate
        for candidate in candidates
        if candidate.confidence >= _AUTO_APPLY_MIN_CONFIDENCE
    ]
    if not high_confidence:
        return {
            "status": "blocked",
            "reason": "low_confidence_candidate",
            "confidenceThreshold": _AUTO_APPLY_MIN_CONFIDENCE,
        }
    if len(high_confidence) > 1:
        return {
            "status": "blocked",
            "reason": "ambiguous_selector_candidates",
            "candidateIds": [candidate.id for candidate in high_confidence],
        }

    candidate = high_confidence[0]
    if _proposal_candidate_id(proposal) != candidate.id:
        return {"status": "blocked", "reason": "proposal_candidate_not_high_confidence"}
    if semantic_reason := _semantic_guard(proposal.old_value, candidate):
        return {"status": "blocked", "reason": semantic_reason}
    if stale_reason := _target_stale_reason(session, project, proposal):
        return {"status": "blocked", "reason": stale_reason}
    if generated_reason := _generated_file_guard_reason(session, diagnosis):
        return {"status": "blocked", **generated_reason}

    return {
        "status": "eligible",
        "reason": "auto_apply_policy_matched",
        "failureSignal": failure_signal,
        "candidateId": candidate.id,
        "confidence": candidate.confidence,
        "confidenceThreshold": _AUTO_APPLY_MIN_CONFIDENCE,
    }


def accept_healing_proposal(session: Session, project: Project, proposal: HealingProposal) -> dict:
    if proposal.project_id != project.id:
        raise ValueError("Healing proposal does not belong to project")
    if proposal.status in {
        HealingProposalStatus.accepted.value,
        HealingProposalStatus.applied.value,
    }:
        return {
            "status": proposal.status,
            "proposal": _proposal_payload(proposal),
        }
    if proposal.status == HealingProposalStatus.rejected.value:
        raise ValueError("Rejected healing proposal cannot be accepted")
    proposal.status = HealingProposalStatus.accepted.value
    proposal.updated_at = datetime.utcnow()
    session.add(proposal)
    session.commit()
    session.refresh(proposal)
    return {
        "status": proposal.status,
        "proposal": _proposal_payload(proposal),
    }


def reject_healing_proposal(session: Session, project: Project, proposal: HealingProposal) -> dict:
    if proposal.project_id != project.id:
        raise ValueError("Healing proposal does not belong to project")
    if proposal.status == HealingProposalStatus.rejected.value:
        return {
            "status": proposal.status,
            "proposal": _proposal_payload(proposal),
        }
    if proposal.status == HealingProposalStatus.applied.value:
        raise ValueError("Applied healing proposal cannot be rejected")
    if proposal.status == HealingProposalStatus.accepted.value:
        raise ValueError("Accepted healing proposal cannot be rejected")
    proposal.status = HealingProposalStatus.rejected.value
    proposal.updated_at = datetime.utcnow()
    session.add(proposal)
    session.commit()
    session.refresh(proposal)
    return {
        "status": proposal.status,
        "proposal": _proposal_payload(proposal),
    }


def _load_body_plan(method: PageObjectMethod) -> list[dict]:
    try:
        plan = json.loads(method.body_plan_json or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError("Page object method body plan is invalid") from exc
    if not isinstance(plan, list) or any(not isinstance(item, dict) for item in plan):
        raise ValueError("Page object method body plan must be a list")
    return plan


def _patch_method_selector(method: PageObjectMethod, old_value: str | None, new_value: str) -> dict:
    plan = _load_body_plan(method)
    changed_entries: list[int] = []
    for index, entry in enumerate(plan):
        if entry.get("selector") == old_value:
            entry["selector"] = new_value
            changed_entries.append(index)
    if not changed_entries and plan and "selector" in plan[0]:
        plan[0]["selector"] = new_value
        changed_entries.append(0)

    method.selector = new_value
    method.body_plan_json = json.dumps(plan, sort_keys=True, separators=(",", ":"))
    method.status = PageObjectMethodStatus.approved.value
    method.updated_at = datetime.utcnow()
    return {
        "pageObjectMethodId": method.id,
        "oldSelector": old_value,
        "newSelector": new_value,
        "bodyPlanSelectorIndexes": changed_entries,
    }


def apply_healing_proposal(session: Session, project: Project, proposal: HealingProposal) -> dict:
    if proposal.project_id != project.id:
        raise ValueError("Healing proposal does not belong to project")
    if proposal.status == HealingProposalStatus.applied.value:
        return {
            "status": "applied",
            "alreadyApplied": True,
            "proposal": _proposal_payload(proposal),
            "mutation": None,
            "generation": None,
            "rerun": _rerun_context(project.id or "", proposal.execution_result_id),
        }
    if proposal.status != HealingProposalStatus.accepted.value:
        raise ValueError("Healing proposal must be accepted before apply")
    if proposal.kind != HealingProposalKind.selector_replace.value:
        raise ValueError("Unsupported healing proposal kind")
    if not proposal.page_object_method_id or not proposal.structured_step_id:
        raise ValueError("Healing proposal target is incomplete")

    method = session.get(PageObjectMethod, proposal.page_object_method_id)
    step = session.get(StructuredStep, proposal.structured_step_id)
    if not method or not step or step.page_object_method_id != method.id:
        raise ValueError("Healing proposal target is missing")
    flow = session.get(StructuredFlow, step.structured_flow_id)
    if not flow or flow.project_id != project.id:
        raise ValueError("Healing proposal target flow is missing")

    original_selector = method.selector
    original_body_plan_json = method.body_plan_json
    original_status = method.status
    original_updated_at = method.updated_at
    mutation = _patch_method_selector(method, proposal.old_value, proposal.new_value)
    session.add(method)
    session.flush()

    try:
        generation = generate_project(
            session,
            project.id or "",
            Path(project.root_path),
            [flow.test_case_id],
            mode="incremental",
        )
    except GenerationConflictError:
        method.selector = original_selector
        method.body_plan_json = original_body_plan_json
        method.status = original_status
        method.updated_at = original_updated_at
        session.add(method)
        session.commit()
        raise

    proposal.status = HealingProposalStatus.applied.value
    proposal.updated_at = datetime.utcnow()
    session.add(proposal)
    session.commit()
    session.refresh(proposal)
    return {
        "status": "applied",
        "alreadyApplied": False,
        "proposal": _proposal_payload(proposal),
        "mutation": mutation,
        "generation": _generation_payload(generation),
        "rerun": _rerun_context(project.id or "", proposal.execution_result_id),
    }


def _rerun_context(project_id: str, execution_result_id: str | None) -> dict:
    if not execution_result_id:
        return {"status": "unavailable", "reason": "execution_result_missing"}
    return {
        "status": "ready",
        "executionResultId": execution_result_id,
        "hint": "rerun failed cases with the existing execution rerun endpoint",
        "endpointTemplate": f"/projects/{project_id}/executions/{{execution_id}}/rerun-failed",
    }


def _old_selector(session: Session, target) -> str | None:
    if target.page_object_method_id:
        method = session.get(PageObjectMethod, target.page_object_method_id)
        if method and method.selector:
            return method.selector
    if target.raw_action_ids:
        actions = session.exec(
            select(RawAction).where(RawAction.id.in_(target.raw_action_ids))
        ).all()
        for action in sorted(actions, key=lambda item: (item.order_index, item.id or "")):
            if action.selector:
                return action.selector
    return None


def _candidate_evidence(
    diagnosis,
    candidate: SelectorCandidate,
) -> list[dict]:
    evidence = [{
        "type": "selector_candidate",
        "selector_candidate_id": candidate.id,
        "selector_type": candidate.selector_type,
        "selector_value": candidate.selector_value,
        "confidence": candidate.confidence,
        "artifact_id": candidate.source_artifact_id,
        "diagnosis_reason": diagnosis.reason,
    }]
    for artifact_id in diagnosis.evidence_artifact_ids:
        if artifact_id != candidate.source_artifact_id:
            evidence.append({
                "type": "diagnosis_artifact",
                "artifact_id": artifact_id,
                "diagnosis_reason": diagnosis.reason,
            })
    return evidence


def _auto_apply_decision_entry(policy: dict) -> dict:
    return {
        "type": "auto_apply_decision",
        "status": policy.get("status"),
        "reason": policy.get("reason"),
        "confidenceThreshold": policy.get("confidenceThreshold"),
        "candidateId": policy.get("candidateId"),
        "failureSignal": policy.get("failureSignal"),
        "files": policy.get("files"),
    }


def _finalize_selector_healing_response(
    session: Session,
    project: Project,
    proposal: HealingProposal,
    diagnosis,
    response: dict,
) -> dict:
    policy = _auto_apply_policy(session, project, proposal, diagnosis)
    if policy["status"] == "disabled":
        return {
            **response,
            "autoApply": policy,
        }
    if policy["status"] == "applied":
        return {
            **response,
            "status": "auto_applied",
            "reason": "proposal_already_applied",
            "proposal": _proposal_payload(proposal),
            "autoApply": {
                **policy,
                "alreadyApplied": True,
            },
        }
    if policy["status"] == "blocked":
        _append_proposal_evidence(session, proposal, _auto_apply_decision_entry(policy))
        return {
            **response,
            "status": "blocked",
            "reason": policy["reason"],
            "proposal": _proposal_payload(proposal),
            "autoApply": policy,
        }

    _append_proposal_evidence(session, proposal, _auto_apply_decision_entry(policy))
    try:
        accept_healing_proposal(session, project, proposal)
        session.refresh(proposal)
        applied = apply_healing_proposal(session, project, proposal)
    except GenerationConflictError as exc:
        proposal.status = HealingProposalStatus.proposed.value
        blocked_policy = {
            "status": "blocked",
            "reason": "generated_file_conflict",
            "message": str(exc),
            **exc.summary(),
        }
        _append_proposal_evidence(session, proposal, _auto_apply_decision_entry(blocked_policy))
        return {
            **response,
            "status": "blocked",
            "reason": "generated_file_conflict",
            "proposal": _proposal_payload(proposal),
            "autoApply": blocked_policy,
        }

    applied_policy = {
        "status": "applied",
        "reason": "auto_apply_policy_matched",
        "candidateId": policy.get("candidateId"),
        "failureSignal": policy.get("failureSignal"),
        "confidence": policy.get("confidence"),
        "confidenceThreshold": policy.get("confidenceThreshold"),
    }
    _append_proposal_evidence(session, proposal, _auto_apply_decision_entry(applied_policy))
    applied["proposal"] = _proposal_payload(proposal)
    return {
        **response,
        "status": "auto_applied",
        "reason": "auto_apply_policy_matched",
        "proposal": applied["proposal"],
        "autoApply": applied_policy,
        "apply": applied,
    }


def create_selector_healing_proposal(
    session: Session,
    project: Project,
    execution_run: ExecutionRun,
    result: ExecutionResult,
) -> dict:
    if execution_run.project_id != project.id:
        raise ValueError("Execution does not belong to project")
    if result.execution_run_id != execution_run.id:
        raise ValueError("Execution result does not belong to execution")

    diagnosis = classify_failure_disposition(session, result.id or "")
    target = diagnosis.target
    base = {
        "projectId": project.id,
        "executionId": execution_run.id,
        "executionResultId": result.id,
        "automationKey": result.automation_key,
        "diagnosis": diagnosis.model_dump(),
    }
    if diagnosis.disposition != "selector_changed" or target.status != "resolved":
        return {
            **base,
            "status": "not_applicable",
            "reason": f"disposition:{diagnosis.disposition};target:{target.status}",
            "proposal": None,
        }

    candidates = []
    if diagnosis.selector_candidate_ids:
        candidates = session.exec(
            select(SelectorCandidate).where(
                SelectorCandidate.id.in_(diagnosis.selector_candidate_ids)
            )
        ).all()
    old_value = _old_selector(session, target)
    old_canonical = _canonical_selector(old_value)
    ranked_candidates = sorted(
        candidates,
        key=lambda item: (-item.confidence, item.id or ""),
    )
    selected: SelectorCandidate | None = None
    new_value: str | None = None
    for candidate in ranked_candidates:
        expression = _selector_expression(candidate)
        if _canonical_selector(expression) == old_canonical:
            continue
        selected = candidate
        new_value = expression
        break
    if not selected or not new_value:
        return {
            **base,
            "status": "not_applicable",
            "reason": "selector_candidate_missing",
            "proposal": None,
        }

    target_proposals = session.exec(
        select(HealingProposal)
        .where(HealingProposal.project_id == project.id)
        .where(HealingProposal.execution_result_id == result.id)
        .where(HealingProposal.page_object_method_id == target.page_object_method_id)
        .where(HealingProposal.structured_step_id == target.structured_step_id)
        .where(HealingProposal.kind == HealingProposalKind.selector_replace.value)
        .order_by(HealingProposal.created_at)
    ).all()
    existing = next(
        (
            proposal
            for proposal in target_proposals
            if proposal.old_value == old_value and proposal.new_value == new_value
        ),
        None,
    )
    if existing:
        response = {
            **base,
            "status": "existing",
            "reason": "matching_proposal_exists",
            "proposal": _proposal_payload(existing),
        }
        return _finalize_selector_healing_response(session, project, existing, diagnosis, response)
    if target_proposals:
        existing_target = target_proposals[0]
        response = {
            **base,
            "status": "existing",
            "reason": "target_proposal_exists",
            "proposal": _proposal_payload(existing_target),
        }
        return _finalize_selector_healing_response(session, project, existing_target, diagnosis, response)

    proposal = HealingProposal(
        id=new_id("heal"),
        project_id=project.id or "",
        automation_key=result.automation_key,
        execution_result_id=result.id,
        page_object_method_id=target.page_object_method_id,
        structured_step_id=target.structured_step_id,
        kind=HealingProposalKind.selector_replace.value,
        old_value=old_value,
        new_value=new_value,
        confidence=selected.confidence,
        status=HealingProposalStatus.proposed.value,
        evidence_json=json.dumps(_candidate_evidence(diagnosis, selected), sort_keys=True),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(proposal)
    session.commit()
    session.refresh(proposal)
    response = {
        **base,
        "status": "created",
        "reason": diagnosis.reason,
        "proposal": _proposal_payload(proposal),
    }
    return _finalize_selector_healing_response(session, project, proposal, diagnosis, response)
