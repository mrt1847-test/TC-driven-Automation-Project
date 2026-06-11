from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

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

TOKEN_RE = re.compile(r"[a-z0-9]+")
TEXTUAL_TRAJECTORY_KEYS = {
    "accessibility",
    "accessible_name",
    "aria",
    "aria_label",
    "current_url",
    "currenturl",
    "label",
    "name",
    "page_title",
    "pagetitle",
    "placeholder",
    "selector",
    "snapshot",
    "surrounding_text",
    "target",
    "text",
    "title",
    "url",
    "value",
}
TRAJECTORY_COLLECTION_KEYS = (
    "actions",
    "events",
    "steps",
    "trace",
    "items",
    "entries",
)
ORDER_KEYS = (
    "order_index",
    "orderIndex",
    "action_index",
    "actionIndex",
    "index",
    "step",
)
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "be",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "page",
    "should",
    "the",
    "then",
    "to",
    "using",
    "with",
}
TOKEN_SYNONYMS = {
    "auth": {"authenticate", "authentication", "login", "signin"},
    "authenticate": {"auth", "authentication", "login", "signin"},
    "button": {"submit", "continue"},
    "credential": {"credentials", "email", "password", "username"},
    "credentials": {"credential", "email", "password", "username"},
    "e": {"email"},
    "email": {"e", "mail", "username", "user"},
    "log": {"login", "signin"},
    "login": {"log", "signin", "sign", "authenticate", "auth"},
    "pass": {"password", "passwd", "pwd", "credential", "credentials"},
    "password": {"pass", "passwd", "pwd", "credential", "credentials"},
    "sign": {"login", "signin", "authenticate", "auth"},
    "signin": {"login", "sign", "authenticate", "auth"},
    "submit": {"button", "continue", "login"},
    "user": {"username", "email"},
    "username": {"user", "email"},
    "verify": {"assert", "expect", "see", "visible"},
    "visible": {"see", "shown", "displayed"},
}
ACTION_HINTS = {
    "goto": {"go", "goto", "navigate", "open", "visit", "url", "page"},
    "click": {"click", "tap", "press", "submit", "choose", "select"},
    "fill": {"fill", "enter", "input", "provide", "set", "type"},
    "press": {"press", "key", "keyboard", "type"},
    "select": {"select", "choose", "dropdown", "option"},
    "check": {"check", "tick", "enable"},
    "uncheck": {"uncheck", "untick", "disable"},
    "set_input_files": {"attach", "file", "upload"},
    "drag_to": {"drag", "drop"},
    "wait": {"wait", "load", "loaded"},
}
ASSERTION_HINTS = {"assert", "check", "confirm", "expect", "see", "should", "verify", "visible", "displayed"}
LOGIN_HINTS = {"auth", "authenticate", "credential", "credentials", "log", "login", "signin"}
FIELD_CREDENTIAL_HINTS = {"email", "mail", "password", "passwd", "pwd", "user", "username"}
SUBMIT_HINTS = {"continue", "login", "signin", "submit"}


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


def _safe_steps(case: TestCase) -> list[dict]:
    try:
        steps = json.loads(case.steps_json or "[]")
    except json.JSONDecodeError:
        return []
    return [step for step in steps if isinstance(step, dict)]


def _normalize_step_index(step: dict, fallback: int) -> int:
    value = step.get("index", fallback)
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _step_display_text(step: dict) -> str:
    return " ".join(
        str(value)
        for value in (step.get("action"), step.get("expected"))
        if value is not None
    )


def _step_slug(step: dict, step_index: int) -> str:
    return slugify(step.get("action", f"step_{step_index}"), separator="_")[:40] or f"step_{step_index}"


def _tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    return {
        token
        for token in TOKEN_RE.findall(text.lower())
        if token and token not in STOPWORDS
    }


def _expanded_tokens(text: str | None) -> set[str]:
    tokens = _tokens(text)
    expanded = set(tokens)
    if "sign" in tokens and "in" in tokens:
        expanded.add("login")
        expanded.add("signin")
    for token in list(tokens):
        expanded.update(TOKEN_SYNONYMS.get(token, set()))
    return expanded - STOPWORDS


def _read_trajectory_items(path: str | None) -> list[dict]:
    if not path:
        return []
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return []

    if isinstance(data, dict):
        for key in TRAJECTORY_COLLECTION_KEYS:
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [data]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _trajectory_order(item: dict) -> int | None:
    for key in ORDER_KEYS:
        value = _coerce_int(item.get(key))
        if value is not None:
            return value
    action = item.get("action")
    if isinstance(action, dict):
        for key in ORDER_KEYS:
            value = _coerce_int(action.get(key))
            if value is not None:
                return value
    return None


def _collect_trajectory_strings(value: Any, key: str | None = None) -> list[str]:
    if isinstance(value, str):
        if key is None or key.lower() in TEXTUAL_TRAJECTORY_KEYS:
            return [value]
        return []
    if isinstance(value, (int, float, bool)) or value is None:
        return []
    if isinstance(value, list):
        strings: list[str] = []
        for item in value:
            strings.extend(_collect_trajectory_strings(item, key))
        return strings
    if isinstance(value, dict):
        strings: list[str] = []
        for item_key, item_value in value.items():
            normalized_key = str(item_key).replace("-", "_").lower()
            strings.extend(_collect_trajectory_strings(item_value, normalized_key))
        return strings
    return []


def _trajectory_text(item: dict | None) -> str:
    if not item:
        return ""
    return " ".join(_collect_trajectory_strings(item))


def _trajectory_by_action(actions: list[RawAction], items: list[dict]) -> dict[str, str]:
    if not actions or not items:
        return {}

    explicit: dict[int, dict] = {}
    sequential: list[dict] = []
    for item in items:
        order = _trajectory_order(item)
        if order is None:
            sequential.append(item)
        else:
            explicit[order] = item

    by_id: dict[str, str] = {}
    for position, action in enumerate(actions, start=1):
        item = explicit.get(action.order_index) or explicit.get(position)
        if item is None and position <= len(sequential):
            item = sequential[position - 1]
        if item is not None and action.id:
            by_id[action.id] = _trajectory_text(item)
    return by_id


def _action_evidence_text(action: RawAction, trajectory_text: str = "") -> str:
    return " ".join(
        str(value)
        for value in (
            action.type,
            action.selector,
            action.target,
            action.value,
            trajectory_text,
        )
        if value is not None
    )


def _has_action_hint(action_type: str, step_tokens: set[str]) -> bool:
    if action_type.startswith("assert_"):
        return bool(step_tokens & ASSERTION_HINTS)
    if action_type.startswith("wait_for_"):
        return bool(step_tokens & ACTION_HINTS["wait"])
    return bool(step_tokens & ACTION_HINTS.get(action_type, set()))


def _is_login_step(step_tokens: set[str]) -> bool:
    return bool(step_tokens & LOGIN_HINTS)


def _action_score(step: dict, action: RawAction, evidence_text: str) -> float:
    step_text = _step_display_text(step)
    expected_text = str(step.get("expected") or "")
    step_tokens = _expanded_tokens(step_text)
    expected_tokens = _expanded_tokens(expected_text)
    action_tokens = _expanded_tokens(evidence_text)
    score = 0.0

    overlap = step_tokens & action_tokens
    if overlap:
        score += min(len(overlap), 6) * 1.15

    if _has_action_hint(action.type, step_tokens):
        score += 1.75

    if action.type.startswith("assert_"):
        assertion_overlap = (expected_tokens or step_tokens) & action_tokens
        if assertion_overlap:
            score += min(len(assertion_overlap), 5) * 1.5
        if step_tokens & ASSERTION_HINTS:
            score += 2.0

    if _is_login_step(step_tokens):
        if action.type == "goto" and action_tokens & {"auth", "login", "signin"}:
            score += 2.0
        if action.type == "fill" and action_tokens & FIELD_CREDENTIAL_HINTS:
            score += 2.5
        if action.type in {"click", "press"} and action_tokens & SUBMIT_HINTS:
            score += 2.25

    if step_tokens & {"credential", "credentials"} and action.type == "fill" and action_tokens & FIELD_CREDENTIAL_HINTS:
        score += 1.5

    return score


def _chunk_pattern_score(step: dict, actions: list[RawAction]) -> float:
    if not actions:
        return -3.0
    step_tokens = _expanded_tokens(_step_display_text(step))
    action_types = [action.type for action in actions]
    score = 0.0

    if _is_login_step(step_tokens):
        has_fill = any(action_type == "fill" for action_type in action_types)
        has_submit = any(action_type in {"click", "press"} for action_type in action_types)
        if has_fill and has_submit:
            score += 2.5
        if action_types and action_types[0] == "goto" and has_fill:
            score += 1.0

    if step_tokens & ASSERTION_HINTS:
        if all(action_type.startswith("assert_") for action_type in action_types):
            score += 2.0
        elif any(action_type.startswith("assert_") for action_type in action_types):
            score += 0.75

    if step_tokens & ACTION_HINTS["goto"] and action_types[0] == "goto":
        score += 1.5

    if sum(1 for action_type in action_types if action_type == "goto") > 1:
        score -= 4.0
    if any(action_type == "goto" for action_type in action_types[1:]):
        score -= 2.0

    return score


def _chunk_score(
    step: dict,
    actions: list[RawAction],
    scores: list[float],
    *,
    step_position: int,
    step_count: int,
    action_start: int,
    action_end: int,
    action_count: int,
) -> float:
    score = sum(scores) + _chunk_pattern_score(step, actions)
    if actions:
        ideal_start = round((step_position - 1) * action_count / step_count)
        ideal_end = round(step_position * action_count / step_count)
        score -= 0.05 * (abs(action_start - ideal_start) + abs(action_end - ideal_end))
        score -= 0.03 * max(0, len(actions) - 1)
    return score


def _fallback_chunks(step_count: int, action_count: int) -> list[list[int]]:
    chunks: list[list[int]] = []
    if step_count <= 0:
        return chunks
    if action_count == 0:
        return [[] for _ in range(step_count)]
    if action_count < step_count:
        for index in range(step_count):
            chunks.append([index] if index < action_count else [])
        return chunks

    base = action_count // step_count
    remainder = action_count % step_count
    cursor = 0
    for step_index in range(step_count):
        size = base + (1 if step_index >= step_count - remainder else 0)
        chunks.append(list(range(cursor, cursor + size)))
        cursor += size
    return chunks


def _planned_chunks(steps: list[dict], actions: list[RawAction], score_matrix: list[list[float]]) -> list[list[int]]:
    step_count = len(steps)
    action_count = len(actions)
    if step_count == 0:
        return []
    if action_count == 0:
        return [[] for _ in steps]
    if not any(score > 0 for row in score_matrix for score in row):
        return _fallback_chunks(step_count, action_count)

    best = [[float("-inf")] * (action_count + 1) for _ in range(step_count + 1)]
    parent: list[list[int | None]] = [[None] * (action_count + 1) for _ in range(step_count + 1)]
    best[0][0] = 0.0

    for step_position in range(1, step_count + 1):
        step = steps[step_position - 1]
        for consumed in range(action_count + 1):
            for previous in range(consumed + 1):
                if best[step_position - 1][previous] == float("-inf"):
                    continue
                chunk_actions = actions[previous:consumed]
                chunk_scores = score_matrix[step_position - 1][previous:consumed]
                candidate = best[step_position - 1][previous] + _chunk_score(
                    step,
                    chunk_actions,
                    chunk_scores,
                    step_position=step_position,
                    step_count=step_count,
                    action_start=previous,
                    action_end=consumed,
                    action_count=action_count,
                )
                if candidate > best[step_position][consumed]:
                    best[step_position][consumed] = candidate
                    parent[step_position][consumed] = previous

    chunks = [[] for _ in steps]
    consumed = action_count
    for step_position in range(step_count, 0, -1):
        previous = parent[step_position][consumed]
        if previous is None:
            return _fallback_chunks(step_count, action_count)
        chunks[step_position - 1] = list(range(previous, consumed))
        consumed = previous
    return chunks


def _supported_action(
    step: dict,
    action: RawAction,
    score: float,
    chunk_scores: list[float],
    action_position: int,
) -> bool:
    if score >= 1.0:
        return True
    if action.type == "goto" and action_position == 0 and any(item >= 1.5 for item in chunk_scores[1:]):
        return True
    if action.type.startswith("wait_for_") and any(item >= 1.5 for item in chunk_scores):
        return True
    if action.type == "wait" and any(item >= 1.5 for item in chunk_scores):
        return True
    step_tokens = _expanded_tokens(_step_display_text(step))
    action_tokens = _expanded_tokens(_action_evidence_text(action))
    return (
        _is_login_step(step_tokens)
        and action.type in {"fill", "click", "press"}
        and bool(action_tokens & (FIELD_CREDENTIAL_HINTS | SUBMIT_HINTS))
    )


def _mapping_status(step: dict, actions: list[RawAction], scores: list[float]) -> str:
    if not actions:
        return "unmapped"
    if any(action.type == "custom_code" for action in actions):
        return "needs_review"
    supported = [
        _supported_action(step, action, score, scores, index)
        for index, (action, score) in enumerate(zip(actions, scores))
    ]
    if all(supported):
        return "mapped"
    matched = sum(1 for score in scores if score >= 1.0)
    if matched and sum(scores) + _chunk_pattern_score(step, actions) >= max(2.0, len(actions) * 1.1):
        return "mapped" if matched == len(actions) else "needs_review"
    return "needs_review"


def auto_map_case(session: Session, case: TestCase, run_id: str) -> tuple[list[MappingItem], str]:
    steps = _safe_steps(case)
    actions = session.exec(
        select(RawAction)
        .where(RawAction.webwright_run_id == run_id)
        .order_by(RawAction.order_index, RawAction.id)
    ).all()
    run = session.get(WebwrightRun, run_id)
    trajectory_text_by_id = _trajectory_by_action(
        actions,
        _read_trajectory_items(run.trajectory_path if run else None),
    )

    _clear_mappings(session, case.id)

    mappings: list[MappingItem] = []

    if not steps:
        return mappings, "needs_review"

    evidence_texts = [
        _action_evidence_text(action, trajectory_text_by_id.get(action.id or "", ""))
        for action in actions
    ]
    score_matrix = [
        [
            _action_score(step, action, evidence_text)
            for action, evidence_text in zip(actions, evidence_texts)
        ]
        for step in steps
    ]
    chunks = _planned_chunks(steps, actions, score_matrix)

    for idx, step in enumerate(steps):
        step_index = _normalize_step_index(step, idx + 1)
        action_indexes = chunks[idx] if idx < len(chunks) else []
        chunk_actions = [actions[action_index] for action_index in action_indexes]
        chunk_scores = [score_matrix[idx][action_index] for action_index in action_indexes]
        action_ids = [action.id for action in chunk_actions if action.id]
        step_name = _step_slug(step, step_index)
        mapping = MappingItem(
            tc_step_index=step_index,
            action_ids=action_ids,
            normalized_step_id=f"flow_{step_index:03d}",
            normalized_step_name=step_name,
            pom_method_name=step_name,
            status=_mapping_status(step, chunk_actions, chunk_scores),
        )
        mappings.append(mapping)
        _add_mapping(session, case.id, mapping)

    if any(mapping.status != "mapped" for mapping in mappings):
        status = "needs_review"
        case.status = "needs_review"
    else:
        status = "mapped"
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
