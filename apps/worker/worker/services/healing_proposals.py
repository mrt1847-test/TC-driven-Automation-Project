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
_EXTENDED_PROPOSAL_KINDS = {
    HealingProposalKind.wait_adjust.value,
    HealingProposalKind.assertion_update.value,
    HealingProposalKind.pom_method_patch.value,
}
_POM_PATCH_ACTIONS = {
    "goto",
    "click",
    "fill",
    "select",
    "check",
    "uncheck",
    "press",
    "set_input_files",
    "drag_to",
    "wait",
    "assert_text",
    "assert_url",
    "assert_visible",
    "assert_hidden",
    "assert_count",
}
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


def _json_payload(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _load_json_object(value: str | None, field_name: str) -> dict:
    try:
        payload = json.loads(value or "{}")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Healing proposal {field_name} is invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Healing proposal {field_name} must be an object")
    return payload


def _load_json_list(value: str | None, field_name: str) -> list:
    try:
        payload = json.loads(value or "[]")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Healing proposal {field_name} is invalid") from exc
    if not isinstance(payload, list):
        raise ValueError(f"Healing proposal {field_name} must be a list")
    return payload


def _clamped_confidence(value: object, default: float) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = default
    return max(0.0, min(1.0, confidence))


def _as_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


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


def _entry_timeout_ms(entry: dict) -> int | None:
    for key in ("timeoutMs", "timeout_ms", "timeout"):
        timeout = _as_int(entry.get(key))
        if timeout is not None:
            return timeout
    return None


def _target_method_step_flow(
    session: Session,
    project: Project,
    proposal: HealingProposal,
) -> tuple[PageObjectMethod, StructuredStep, StructuredFlow]:
    if not proposal.page_object_method_id or not proposal.structured_step_id:
        raise ValueError("Healing proposal target is incomplete")
    method = session.get(PageObjectMethod, proposal.page_object_method_id)
    step = session.get(StructuredStep, proposal.structured_step_id)
    if not method or not step or step.page_object_method_id != method.id:
        raise ValueError("Healing proposal target is missing")
    flow = session.get(StructuredFlow, step.structured_flow_id)
    if not flow or flow.project_id != project.id:
        raise ValueError("Healing proposal target flow is missing")
    return method, step, flow


def _patch_wait_adjust(method: PageObjectMethod, step: StructuredStep, proposal: HealingProposal) -> dict:
    old = _load_json_object(proposal.old_value, "old_value")
    new = _load_json_object(proposal.new_value, "new_value")
    index = _as_int(new.get("bodyPlanIndex"))
    if index is None:
        raise ValueError("Healing proposal wait patch is incomplete")
    index -= 1
    new_timeout = _as_int(new.get("timeoutMs"))
    if new_timeout is None:
        raise ValueError("Healing proposal wait timeout is invalid")

    plan = _load_body_plan(method)
    if index < 0 or index >= len(plan):
        raise ValueError("Healing proposal target is stale")
    entry = plan[index]
    if entry.get("action") != "wait":
        raise ValueError("Healing proposal target is stale")
    old_timeout = old.get("timeoutMs")
    if _entry_timeout_ms(entry) != old_timeout:
        raise ValueError("Healing proposal target is stale")

    entry["timeoutMs"] = new_timeout
    wait_payload = _load_json_object(step.wait_json, "step wait_json") if step.wait_json else {}
    wait_payload["timeoutMs"] = new_timeout
    wait_payload["sourceProposalId"] = proposal.id
    step.wait_json = _json_payload(wait_payload)
    step.updated_at = datetime.utcnow()
    method.body_plan_json = _json_payload(plan)
    method.status = PageObjectMethodStatus.approved.value
    method.updated_at = datetime.utcnow()
    return {
        "kind": HealingProposalKind.wait_adjust.value,
        "pageObjectMethodId": method.id,
        "structuredStepId": step.id,
        "bodyPlanIndex": index + 1,
        "oldTimeoutMs": old_timeout,
        "newTimeoutMs": new_timeout,
    }


def _patch_assertion_update(method: PageObjectMethod, step: StructuredStep, proposal: HealingProposal) -> dict:
    old = _load_json_object(proposal.old_value, "old_value")
    new = _load_json_object(proposal.new_value, "new_value")
    index = _as_int(new.get("bodyPlanIndex"))
    if index is None:
        raise ValueError("Healing proposal assertion patch is incomplete")
    index -= 1
    if "value" not in new:
        raise ValueError("Healing proposal assertion value is missing")

    plan = _load_body_plan(method)
    if index < 0 or index >= len(plan):
        raise ValueError("Healing proposal target is stale")
    entry = plan[index]
    if not str(entry.get("action", "")).startswith("assert_"):
        raise ValueError("Healing proposal target is stale")
    if entry.get("value") != old.get("value"):
        raise ValueError("Healing proposal target is stale")

    new_value = str(new.get("value"))
    entry["value"] = new_value
    assertion_payload = _load_json_object(step.assertion_json, "step assertion_json") if step.assertion_json else {}
    assertion_payload["value"] = new_value
    assertion_payload["expected"] = new_value
    assertion_payload["sourceProposalId"] = proposal.id
    step.assertion_json = _json_payload(assertion_payload)
    step.updated_at = datetime.utcnow()
    method.value_template = new_value
    method.body_plan_json = _json_payload(plan)
    method.status = PageObjectMethodStatus.approved.value
    method.updated_at = datetime.utcnow()
    return {
        "kind": HealingProposalKind.assertion_update.value,
        "pageObjectMethodId": method.id,
        "structuredStepId": step.id,
        "bodyPlanIndex": index + 1,
        "oldValue": old.get("value"),
        "newValue": new_value,
    }


def _validated_patch_body_plan(value: object) -> list[dict]:
    if not isinstance(value, list) or not value:
        raise ValueError("POM method patch bodyPlan must be a non-empty list")
    body_plan: list[dict] = []
    for entry in value:
        if not isinstance(entry, dict):
            raise ValueError("POM method patch bodyPlan entries must be objects")
        action = str(entry.get("action", "")).strip()
        if action not in _POM_PATCH_ACTIONS:
            raise ValueError("POM method patch contains unsupported action")
        body_plan.append(dict(entry))
    return body_plan


def _patch_pom_method(method: PageObjectMethod, proposal: HealingProposal) -> dict:
    old = _load_json_object(proposal.old_value, "old_value")
    new = _load_json_object(proposal.new_value, "new_value")
    old_plan = old.get("bodyPlan")
    current_plan = _load_body_plan(method)
    if isinstance(old_plan, list) and current_plan != old_plan:
        raise ValueError("Healing proposal target is stale")

    changed_fields: list[str] = []
    if "bodyPlan" in new:
        method.body_plan_json = _json_payload(_validated_patch_body_plan(new["bodyPlan"]))
        changed_fields.append("bodyPlan")
    if "methodType" in new:
        method.method_type = str(new["methodType"])
        changed_fields.append("methodType")
    if "selector" in new:
        method.selector = str(new["selector"]) if new["selector"] is not None else None
        changed_fields.append("selector")
    if "valueTemplate" in new:
        method.value_template = str(new["valueTemplate"]) if new["valueTemplate"] is not None else None
        changed_fields.append("valueTemplate")
    if not changed_fields:
        raise ValueError("POM method patch is empty")
    method.status = PageObjectMethodStatus.approved.value
    method.updated_at = datetime.utcnow()
    return {
        "kind": HealingProposalKind.pom_method_patch.value,
        "pageObjectMethodId": method.id,
        "changedFields": changed_fields,
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
    if proposal.kind not in {
        HealingProposalKind.selector_replace.value,
        HealingProposalKind.wait_adjust.value,
        HealingProposalKind.assertion_update.value,
        HealingProposalKind.pom_method_patch.value,
    }:
        raise ValueError("Unsupported healing proposal kind")
    method, step, flow = _target_method_step_flow(session, project, proposal)

    original_selector = method.selector
    original_method_type = method.method_type
    original_value_template = method.value_template
    original_body_plan_json = method.body_plan_json
    original_status = method.status
    original_updated_at = method.updated_at
    original_assertion_json = step.assertion_json
    original_wait_json = step.wait_json
    original_step_updated_at = step.updated_at
    if proposal.kind == HealingProposalKind.selector_replace.value:
        mutation = _patch_method_selector(method, proposal.old_value, proposal.new_value)
    elif proposal.kind == HealingProposalKind.wait_adjust.value:
        mutation = _patch_wait_adjust(method, step, proposal)
    elif proposal.kind == HealingProposalKind.assertion_update.value:
        mutation = _patch_assertion_update(method, step, proposal)
    else:
        mutation = _patch_pom_method(method, proposal)
    session.add(method)
    session.add(step)
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
        method.method_type = original_method_type
        method.value_template = original_value_template
        method.body_plan_json = original_body_plan_json
        method.status = original_status
        method.updated_at = original_updated_at
        step.assertion_json = original_assertion_json
        step.wait_json = original_wait_json
        step.updated_at = original_step_updated_at
        session.add(method)
        session.add(step)
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


def _artifact_metadata(session: Session, artifact_ids: list[str]) -> list[tuple[str, dict]]:
    if not artifact_ids:
        return []
    artifacts = session.exec(select(ArtifactAsset).where(ArtifactAsset.id.in_(artifact_ids))).all()
    metadata: list[tuple[str, dict]] = []
    for artifact in artifacts:
        if not artifact.metadata_json:
            continue
        try:
            parsed = json.loads(artifact.metadata_json)
        except (TypeError, ValueError):
            continue
        if isinstance(parsed, dict) and artifact.id:
            metadata.append((artifact.id, parsed))
    return metadata


def _metadata_proposal_hint(session: Session, diagnosis) -> tuple[str | None, dict]:
    artifact_ids = list(dict.fromkeys([
        *diagnosis.evidence_artifact_ids,
        *diagnosis.target.artifact_ids,
    ]))
    for artifact_id, metadata in _artifact_metadata(session, artifact_ids):
        for key in ("healing_proposal", "healingProposal", "proposal"):
            value = metadata.get(key)
            if not isinstance(value, dict):
                continue
            kind = value.get("kind") or metadata.get("proposal_kind") or metadata.get("proposalKind")
            if kind in _EXTENDED_PROPOSAL_KINDS:
                return str(kind), {"sourceArtifactId": artifact_id, **value}
        kind = metadata.get("proposal_kind") or metadata.get("proposalKind")
        if kind in _EXTENDED_PROPOSAL_KINDS:
            return str(kind), {"sourceArtifactId": artifact_id, **metadata}
    return None, {}


def _proposal_target_for_diagnosis(
    session: Session,
    project: Project,
    diagnosis,
) -> tuple[PageObjectMethod, StructuredStep, StructuredFlow] | None:
    target = diagnosis.target
    if target.status != "resolved" or not target.page_object_method_id or not target.structured_step_id:
        return None
    proposal = HealingProposal(
        project_id=project.id or "",
        automation_key=diagnosis.automation_key or "",
        page_object_method_id=target.page_object_method_id,
        structured_step_id=target.structured_step_id,
        kind=HealingProposalKind.pom_method_patch.value,
        new_value="{}",
    )
    try:
        return _target_method_step_flow(session, project, proposal)
    except ValueError:
        return None


def _body_plan_index(value: object, allowed_indexes: list[int]) -> int | None:
    requested = _as_int(value)
    if requested is not None:
        index = requested - 1
        return index if index in allowed_indexes else None
    return allowed_indexes[0] if allowed_indexes else None


def _extract_timeout_ms(error: str | None) -> int | None:
    if not error:
        return None
    match = re.search(r"(?P<ms>\d{3,6})\s*ms", error, re.IGNORECASE)
    return _as_int(match.group("ms")) if match else None


def _extract_assertion_actual(error: str | None) -> str | None:
    if not error:
        return None
    patterns = [
        r"(?:Received|Actual)(?: string)?:\s*['\"](?P<value>[^'\"]+)['\"]",
        r"(?:Received|Actual)(?: string)?:\s*(?P<value>[^\r\n]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, error, re.IGNORECASE)
        if match:
            value = match.group("value").strip()
            if value:
                return value
    return None


def _extended_evidence(
    *,
    kind: str,
    diagnosis,
    method: PageObjectMethod,
    step: StructuredStep,
    proposal_data: dict,
) -> list[dict]:
    evidence = [{
        "type": "extended_proposal",
        "kind": kind,
        "diagnosis_reason": diagnosis.reason,
        "diagnosis_disposition": diagnosis.disposition,
        "page_object_method_id": method.id,
        "structured_step_id": step.id,
        "proposal_input_keys": sorted(
            key for key in proposal_data
            if key not in {"sourceArtifactId", "sourceArtifactID"}
        ),
    }]
    source_artifact_id = proposal_data.get("sourceArtifactId") or proposal_data.get("sourceArtifactID")
    if source_artifact_id:
        evidence[0]["source_artifact_id"] = source_artifact_id
    for artifact_id in diagnosis.evidence_artifact_ids:
        evidence.append({
            "type": "diagnosis_artifact",
            "artifact_id": artifact_id,
            "diagnosis_reason": diagnosis.reason,
        })
    return evidence


def _wait_adjust_spec(
    *,
    result: ExecutionResult,
    diagnosis,
    method: PageObjectMethod,
    step: StructuredStep,
    proposal_data: dict,
) -> dict | None:
    plan = _load_body_plan(method)
    wait_indexes = [
        index
        for index, entry in enumerate(plan)
        if entry.get("action") == "wait"
    ]
    index = _body_plan_index(
        proposal_data.get("bodyPlanIndex") or proposal_data.get("body_plan_index"),
        wait_indexes,
    )
    if index is None:
        return None
    entry = plan[index]
    old_timeout = _entry_timeout_ms(entry)
    requested_timeout = (
        proposal_data.get("timeoutMs")
        or proposal_data.get("timeout_ms")
        or proposal_data.get("timeout")
    )
    new_timeout = _as_int(requested_timeout)
    if new_timeout is None:
        base_timeout = old_timeout or _extract_timeout_ms(result.error) or 5000
        new_timeout = max(10000, min(60000, base_timeout * 2))
    if old_timeout == new_timeout:
        return None
    old_value = {
        "bodyPlanIndex": index + 1,
        "timeoutMs": old_timeout,
        "entry": entry,
    }
    new_value = {
        "bodyPlanIndex": index + 1,
        "timeoutMs": new_timeout,
    }
    return {
        "kind": HealingProposalKind.wait_adjust.value,
        "old_value": _json_payload(old_value),
        "new_value": _json_payload(new_value),
        "confidence": _clamped_confidence(proposal_data.get("confidence"), 0.74),
        "evidence": _extended_evidence(
            kind=HealingProposalKind.wait_adjust.value,
            diagnosis=diagnosis,
            method=method,
            step=step,
            proposal_data=proposal_data,
        ),
        "reason": "wait_adjust_patch_proposed",
    }


def _assertion_update_spec(
    *,
    result: ExecutionResult,
    diagnosis,
    method: PageObjectMethod,
    step: StructuredStep,
    proposal_data: dict,
) -> dict | None:
    plan = _load_body_plan(method)
    assertion_indexes = [
        index
        for index, entry in enumerate(plan)
        if str(entry.get("action", "")).startswith("assert_")
    ]
    index = _body_plan_index(
        proposal_data.get("bodyPlanIndex") or proposal_data.get("body_plan_index"),
        assertion_indexes,
    )
    if index is None:
        return None
    entry = plan[index]
    new_value = (
        proposal_data.get("value")
        or proposal_data.get("expectedValue")
        or proposal_data.get("expected_value")
        or proposal_data.get("actualValue")
        or proposal_data.get("actual_value")
        or _extract_assertion_actual(result.error)
    )
    if new_value is None:
        return None
    old_value = {
        "bodyPlanIndex": index + 1,
        "value": entry.get("value"),
        "entry": entry,
    }
    new_value_payload = {
        "bodyPlanIndex": index + 1,
        "value": str(new_value),
    }
    if old_value["value"] == new_value_payload["value"]:
        return None
    return {
        "kind": HealingProposalKind.assertion_update.value,
        "old_value": _json_payload(old_value),
        "new_value": _json_payload(new_value_payload),
        "confidence": _clamped_confidence(proposal_data.get("confidence"), 0.7),
        "evidence": _extended_evidence(
            kind=HealingProposalKind.assertion_update.value,
            diagnosis=diagnosis,
            method=method,
            step=step,
            proposal_data=proposal_data,
        ),
        "reason": "assertion_update_patch_proposed",
    }


def _pom_method_patch_spec(
    *,
    diagnosis,
    method: PageObjectMethod,
    step: StructuredStep,
    proposal_data: dict,
) -> dict | None:
    new_value: dict = {}
    if "bodyPlan" in proposal_data or "body_plan" in proposal_data:
        new_value["bodyPlan"] = _validated_patch_body_plan(
            proposal_data.get("bodyPlan") or proposal_data.get("body_plan")
        )
    if "methodType" in proposal_data or "method_type" in proposal_data:
        new_value["methodType"] = proposal_data.get("methodType") or proposal_data.get("method_type")
    if "selector" in proposal_data:
        new_value["selector"] = proposal_data.get("selector")
    if "valueTemplate" in proposal_data or "value_template" in proposal_data:
        new_value["valueTemplate"] = proposal_data.get("valueTemplate") or proposal_data.get("value_template")
    if not new_value:
        return None
    old_value = {
        "bodyPlan": _load_body_plan(method),
        "methodType": method.method_type,
        "selector": method.selector,
        "valueTemplate": method.value_template,
    }
    return {
        "kind": HealingProposalKind.pom_method_patch.value,
        "old_value": _json_payload(old_value),
        "new_value": _json_payload(new_value),
        "confidence": _clamped_confidence(proposal_data.get("confidence"), 0.62),
        "evidence": _extended_evidence(
            kind=HealingProposalKind.pom_method_patch.value,
            diagnosis=diagnosis,
            method=method,
            step=step,
            proposal_data=proposal_data,
        ),
        "reason": "pom_method_patch_proposed",
    }


def _infer_extended_kind(result: ExecutionResult, method: PageObjectMethod) -> str | None:
    error = (result.error or "").lower()
    plan = _load_body_plan(method)
    if "timeout" in error and any(entry.get("action") == "wait" for entry in plan):
        return HealingProposalKind.wait_adjust.value
    assertion_terms = {"assert", "expect", "expected", "received", "actual"}
    if any(term in error for term in assertion_terms) and any(
        str(entry.get("action", "")).startswith("assert_")
        for entry in plan
    ):
        return HealingProposalKind.assertion_update.value
    return None


def _extended_proposal_spec(
    session: Session,
    project: Project,
    result: ExecutionResult,
    diagnosis,
    requested_kind: str | None,
    requested_proposal: dict | None,
) -> dict | None:
    target = _proposal_target_for_diagnosis(session, project, diagnosis)
    if target is None:
        return None
    method, step, _flow = target
    hint_kind, hint_proposal = _metadata_proposal_hint(session, diagnosis)
    proposal_data = requested_proposal if requested_proposal else hint_proposal
    proposal_data = proposal_data or {}
    kind = requested_kind or hint_kind or _infer_extended_kind(result, method)
    if kind not in _EXTENDED_PROPOSAL_KINDS:
        return None
    if kind == HealingProposalKind.wait_adjust.value:
        return _wait_adjust_spec(
            result=result,
            diagnosis=diagnosis,
            method=method,
            step=step,
            proposal_data=proposal_data,
        )
    if kind == HealingProposalKind.assertion_update.value:
        return _assertion_update_spec(
            result=result,
            diagnosis=diagnosis,
            method=method,
            step=step,
            proposal_data=proposal_data,
        )
    return _pom_method_patch_spec(
        diagnosis=diagnosis,
        method=method,
        step=step,
        proposal_data=proposal_data,
    )


def _create_extended_healing_proposal(
    session: Session,
    project: Project,
    result: ExecutionResult,
    diagnosis,
    base: dict,
    requested_kind: str | None,
    requested_proposal: dict | None,
) -> dict | None:
    spec = _extended_proposal_spec(
        session,
        project,
        result,
        diagnosis,
        requested_kind,
        requested_proposal,
    )
    if spec is None:
        return None
    target = diagnosis.target
    target_proposals = session.exec(
        select(HealingProposal)
        .where(HealingProposal.project_id == project.id)
        .where(HealingProposal.execution_result_id == result.id)
        .where(HealingProposal.page_object_method_id == target.page_object_method_id)
        .where(HealingProposal.structured_step_id == target.structured_step_id)
        .where(HealingProposal.kind == spec["kind"])
        .order_by(HealingProposal.created_at)
    ).all()
    existing = next(
        (
            proposal
            for proposal in target_proposals
            if proposal.old_value == spec["old_value"] and proposal.new_value == spec["new_value"]
        ),
        None,
    )
    if existing:
        return {
            **base,
            "status": "existing",
            "reason": "matching_proposal_exists",
            "proposal": _proposal_payload(existing),
        }
    if target_proposals:
        existing_target = target_proposals[0]
        return {
            **base,
            "status": "existing",
            "reason": "target_proposal_exists",
            "proposal": _proposal_payload(existing_target),
        }

    proposal = HealingProposal(
        id=new_id("heal"),
        project_id=project.id or "",
        automation_key=result.automation_key,
        execution_result_id=result.id,
        page_object_method_id=target.page_object_method_id,
        structured_step_id=target.structured_step_id,
        kind=spec["kind"],
        old_value=spec["old_value"],
        new_value=spec["new_value"],
        confidence=spec["confidence"],
        status=HealingProposalStatus.proposed.value,
        evidence_json=_json_payload(spec["evidence"]),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(proposal)
    session.commit()
    session.refresh(proposal)
    return {
        **base,
        "status": "created",
        "reason": spec["reason"],
        "proposal": _proposal_payload(proposal),
    }


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


def create_healing_proposal(
    session: Session,
    project: Project,
    execution_run: ExecutionRun,
    result: ExecutionResult,
    requested_kind: str | None = None,
    requested_proposal: dict | None = None,
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
    requested_proposal = requested_proposal or {}
    if requested_kind in _EXTENDED_PROPOSAL_KINDS:
        extended = _create_extended_healing_proposal(
            session,
            project,
            result,
            diagnosis,
            base,
            requested_kind,
            requested_proposal,
        )
        if extended is not None:
            return extended
        return {
            **base,
            "status": "not_applicable",
            "reason": f"kind:{requested_kind};target:{target.status}",
            "proposal": None,
        }
    if diagnosis.disposition != "selector_changed" or target.status != "resolved":
        extended = _create_extended_healing_proposal(
            session,
            project,
            result,
            diagnosis,
            base,
            None,
            requested_proposal,
        )
        if extended is not None:
            return extended
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


def create_selector_healing_proposal(
    session: Session,
    project: Project,
    execution_run: ExecutionRun,
    result: ExecutionResult,
) -> dict:
    return create_healing_proposal(session, project, execution_run, result)
