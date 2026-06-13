from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sqlmodel import Session, select

from worker.core.config import SECRET_PATTERNS, mask_secrets, new_id, secret_env_placeholders
from worker.models.db import (
    CaseActionMapping,
    CaseActionMappingAction,
    PageObject,
    PageObjectMethod,
    PageObjectMethodStatus,
    PageObjectMethodType,
    Project,
    RawAction,
    SelectorCandidate,
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
EXISTING_VALUE_PLACEHOLDER_RE = re.compile(r"\$\{(?:env|data)\.[^}]+\}")
CREDENTIAL_FIELD_RE = re.compile(
    r"(api[_\-\s]?key|access[_\-\s]?key|private[_\-\s]?key|password|passwd|passcode|"
    r"credential|secret|token|bearer|pin|otp|mfa|2fa)",
    re.IGNORECASE,
)
FIELD_TEXT_RE = re.compile(
    r"(?:get_by_(?:label|placeholder|test_id|text)|locator)\(\s*[rbufRBUF]*['\"]([^'\"]+)",
    re.IGNORECASE,
)
ATTRIBUTE_TEXT_RE = re.compile(
    r"\[(?:name|id|aria-label|placeholder|type)\s*=\s*['\"]?([^'\"\]]+)",
    re.IGNORECASE,
)
ROLE_SELECTOR_RE = re.compile(r"^(?P<role>[^\[]+)(?:\[name=(?P<quote>['\"])(?P<name>.*)(?P=quote)\])?$")
SELECTOR_TYPE_PRIORITY = {
    "test_id": 0,
    "role": 1,
    "text": 2,
    "css": 3,
    "xpath": 4,
}
MIN_SELECTOR_CANDIDATE_CONFIDENCE = 0.7
AMBIGUOUS_SELECTOR_CONFIDENCE_DELTA = 0.0001
DEFAULT_PAGE_OBJECT_NAME = "GeneratedPage"
DEFAULT_PAGE_OBJECT_PATH = "pages/generated_page.py"
TRAJECTORY_COLLECTION_KEYS = (
    "actions",
    "events",
    "steps",
    "trace",
    "items",
    "entries",
)
TRAJECTORY_ORDER_KEYS = (
    "order_index",
    "orderIndex",
    "action_index",
    "actionIndex",
    "index",
    "step_index",
    "stepIndex",
)
TRAJECTORY_URL_KEYS = {
    "currenturl",
    "href",
    "pageurl",
    "targeturl",
    "url",
}
DYNAMIC_ROUTE_SEGMENT_RE = re.compile(
    r"^(?:\d+|[0-9a-f]{8,}|[0-9a-f]{8}-[0-9a-f-]{13,})$",
    re.IGNORECASE,
)
FILLABLE_ROLE_SELECTORS = {"combobox", "searchbox", "spinbutton", "textbox"}
CHECKABLE_ROLE_SELECTORS = {"checkbox", "radio", "switch"}
CLICKABLE_ROLE_SELECTORS = {
    "button",
    "checkbox",
    "link",
    "menuitem",
    "menuitemcheckbox",
    "menuitemradio",
    "option",
    "radio",
    "switch",
    "tab",
    "treeitem",
}
TEXT_SELECTOR_ACTIONS = {
    "click",
    "hover",
    "assert_text",
    "assert_visible",
    "assert_hidden",
    "wait",
}


@dataclass(frozen=True)
class CredentialPlaceholder:
    value: str
    source: str


@dataclass(frozen=True)
class SelectorChoice:
    selector: str | None
    selected: SelectorCandidate | None
    runner_ups: list[SelectorCandidate]
    fallback_reason: str | None = None


def _snake(name: str) -> str:
    return name.lower().replace("-", "_").replace(" ", "_")


def _method_base_name(mapping: MappingItem, step_name: str) -> str:
    return _snake(mapping.pom_method_name or step_name)


def _scoped_method_name(case: TestCase, mapping: MappingItem, base_name: str) -> str:
    return f"{_snake(case.automation_key)}__step_{mapping.tc_step_index}_{base_name}"


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


def _has_existing_placeholder(value: str) -> bool:
    return bool(EXISTING_VALUE_PLACEHOLDER_RE.search(value))


def _placeholder_leaf(text: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    if not normalized:
        return "secret"
    return normalized[:48].strip("_") or "secret"


def _credential_context(action: RawAction) -> str:
    return " ".join(part for part in (action.selector, action.target) if part)


def _credential_placeholder_path(action: RawAction) -> str:
    context = _credential_context(action)
    candidates = [
        match.group(1)
        for pattern in (FIELD_TEXT_RE, ATTRIBUTE_TEXT_RE)
        for match in pattern.finditer(context)
    ]
    candidates.append(context)
    for candidate in candidates:
        if CREDENTIAL_FIELD_RE.search(candidate):
            return f"credentials.{_placeholder_leaf(candidate)}"
    return "credentials.secret"


def _is_credential_field(action: RawAction) -> bool:
    return bool(CREDENTIAL_FIELD_RE.search(_credential_context(action)))


def _is_secret_looking_value(value: str) -> bool:
    text = value.strip()
    if not text or _has_existing_placeholder(text):
        return False
    if mask_secrets(text) != text:
        return True
    if any(pattern.search(text) for pattern in SECRET_PATTERNS):
        return True
    if len(text) < 16 or any(char.isspace() for char in text):
        return False
    classes = sum(
        any(predicate(char) for char in text)
        for predicate in (
            str.islower,
            str.isupper,
            str.isdigit,
            lambda char: not char.isalnum(),
        )
    )
    return classes >= 3


def _credential_placeholder(action: RawAction) -> CredentialPlaceholder | None:
    value = action.value
    if action.type != "fill" or not value or _has_existing_placeholder(value):
        return None

    known_secret_placeholders = secret_env_placeholders()
    if value in known_secret_placeholders:
        return CredentialPlaceholder(known_secret_placeholders[value], "secret_env_value")

    if _is_credential_field(action):
        return CredentialPlaceholder(f"${{env.{_credential_placeholder_path(action)}}}", "credential_field")

    if _is_secret_looking_value(value):
        return CredentialPlaceholder(f"${{env.{_credential_placeholder_path(action)}}}", "secret_literal")

    return None


def _credential_safe_target(target: str | None, literal: str | None, placeholder: str | None) -> str | None:
    if target is None or literal is None or placeholder is None:
        return target
    return target.replace(literal, placeholder)


def _value_template_from_plan(body_plan: list[dict]) -> str | None:
    return next(
        (
            str(entry["value"])
            for entry in body_plan
            if isinstance(entry, dict) and entry.get("value") is not None
        ),
        None,
    )


def _mapping_suffix(mapping: MappingItem) -> str:
    return _snake(mapping.id or f"step_{mapping.tc_step_index}")


def _mapping_method_any_page(session: Session, mapping_id: str | None) -> PageObjectMethod | None:
    if not mapping_id:
        return None
    return session.exec(
        select(PageObjectMethod).where(PageObjectMethod.source_mapping_id == mapping_id)
    ).first()


def _route_slug_part(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    if not text:
        return ""
    if DYNAMIC_ROUTE_SEGMENT_RE.match(text):
        return "item"
    return text


def _pascal_from_slug(slug: str) -> str:
    return "".join(part.capitalize() for part in slug.split("_") if part)


def _route_page_spec(url: str | None) -> tuple[str, str, str | None]:
    if not url:
        return DEFAULT_PAGE_OBJECT_NAME, DEFAULT_PAGE_OBJECT_PATH, None
    text = url.strip()
    if not text or "${" in text:
        return DEFAULT_PAGE_OBJECT_NAME, DEFAULT_PAGE_OBJECT_PATH, None
    try:
        parsed = urlsplit(text)
    except ValueError:
        return DEFAULT_PAGE_OBJECT_NAME, DEFAULT_PAGE_OBJECT_PATH, None
    if not (parsed.scheme or parsed.netloc or text.startswith("/")):
        return DEFAULT_PAGE_OBJECT_NAME, DEFAULT_PAGE_OBJECT_PATH, None

    path = parsed.path or "/"
    parts = [_route_slug_part(part) for part in path.split("/") if part]
    parts = [part for part in parts if part]
    slug = "_".join(parts[:4])
    if not slug:
        slug = _route_slug_part(parsed.netloc) or "root"
    if slug == "generated":
        slug = "generated_route"
    class_name = f"{_pascal_from_slug(slug)}Page"
    return class_name, f"pages/{slug}_page.py", path


def _coerce_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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


def _trajectory_order(item: dict) -> int | None:
    for key in TRAJECTORY_ORDER_KEYS:
        value = _coerce_int(item.get(key))
        if value is not None:
            return value
    action = item.get("action")
    if isinstance(action, dict):
        for key in TRAJECTORY_ORDER_KEYS:
            value = _coerce_int(action.get(key))
            if value is not None:
                return value
    return None


def _trajectory_items_by_order(items: list[dict]) -> tuple[dict[int, dict], list[dict]]:
    explicit: dict[int, dict] = {}
    sequential: list[dict] = []
    for item in items:
        order = _trajectory_order(item)
        if order is None:
            sequential.append(item)
        else:
            explicit[order] = item
    return explicit, sequential


def _url_from_trajectory_value(value: Any, key: str | None = None) -> str | None:
    if isinstance(value, str):
        normalized_key = (key or "").replace("_", "").replace("-", "").lower()
        if normalized_key in TRAJECTORY_URL_KEYS:
            stripped = value.strip()
            return stripped or None
        return None
    if isinstance(value, list):
        for item in value:
            found = _url_from_trajectory_value(item, key)
            if found:
                return found
        return None
    if isinstance(value, dict):
        for item_key, item_value in value.items():
            found = _url_from_trajectory_value(item_value, str(item_key))
            if found:
                return found
    return None


def _trajectory_url_for_action(action: RawAction, run: WebwrightRun | None) -> str | None:
    items = _read_trajectory_items(run.trajectory_path if run else None)
    if not items:
        return None
    explicit, sequential = _trajectory_items_by_order(items)
    item = explicit.get(action.order_index)
    if item is None and 0 < action.order_index <= len(sequential):
        item = sequential[action.order_index - 1]
    return _url_from_trajectory_value(item)


def _runs_for_actions(session: Session, actions: list[RawAction]) -> dict[str, WebwrightRun]:
    run_ids = sorted({action.webwright_run_id for action in actions if action.webwright_run_id})
    if not run_ids:
        return {}
    rows = session.exec(select(WebwrightRun).where(WebwrightRun.id.in_(run_ids))).all()
    return {row.id: row for row in rows if row.id}


def _route_url_for_actions(
    actions: list[RawAction],
    runs_by_id: dict[str, WebwrightRun],
) -> str | None:
    for action in actions:
        url = _trajectory_url_for_action(action, runs_by_id.get(action.webwright_run_id))
        if url:
            return url
    return None


def _ensure_page_object(
    session: Session,
    project_id: str,
    route_url: str | None,
) -> PageObject:
    name, file_path, url_pattern = _route_page_spec(route_url)
    page = session.exec(
        select(PageObject).where(PageObject.project_id == project_id, PageObject.name == name)
    ).first()
    if not page:
        page = PageObject(
            id=new_id("po"),
            project_id=project_id,
            name=name,
            file_path=file_path,
            url_pattern=url_pattern,
        )
    else:
        page.file_path = file_path
        page.url_pattern = url_pattern
        page.updated_at = datetime.utcnow()
    session.add(page)
    session.flush()
    return page


def _ensure_method_page_assignment(
    session: Session,
    method: PageObjectMethod,
    page: PageObject,
    mapping: MappingItem,
) -> None:
    if method.page_object_id == page.id:
        return
    collision = session.exec(
        select(PageObjectMethod).where(
            PageObjectMethod.page_object_id == page.id,
            PageObjectMethod.name == method.name,
        )
    ).first()
    if collision and collision.id != method.id:
        method.name = f"{method.name}__{_mapping_suffix(mapping)}"
    method.page_object_id = page.id


def _selector_candidates_for_actions(
    session: Session,
    action_ids: list[str],
) -> dict[str, list[SelectorCandidate]]:
    if not action_ids:
        return {}
    rows = session.exec(
        select(SelectorCandidate).where(SelectorCandidate.raw_action_id.in_(action_ids))
    ).all()
    grouped: dict[str, list[SelectorCandidate]] = {}
    for row in rows:
        if row.page_object_method_id and not _is_structuring_ranked_candidate(row):
            continue
        if row.raw_action_id:
            grouped.setdefault(row.raw_action_id, []).append(row)
    return grouped


def _selector_rank_key(candidate: SelectorCandidate) -> tuple[int, float, str, str]:
    return (
        SELECTOR_TYPE_PRIORITY.get(candidate.selector_type, 99),
        -candidate.confidence,
        candidate.selector_value,
        candidate.id or "",
    )


def _role_selector_parts(selector_value: str) -> tuple[str, str | None] | None:
    match = ROLE_SELECTOR_RE.match(selector_value.strip())
    if not match:
        return None
    role = match.group("role").strip()
    if not role:
        return None
    return role, match.group("name")


def _selector_expression(candidate: SelectorCandidate) -> str | None:
    value = candidate.selector_value
    if not value:
        return None
    if candidate.selector_type == "test_id":
        return f"page.get_by_test_id({json.dumps(value)})"
    if candidate.selector_type == "role":
        parts = _role_selector_parts(value)
        if not parts:
            return None
        role, name = parts
        if name:
            return f"page.get_by_role({json.dumps(role)}, name={json.dumps(name)})"
        return f"page.get_by_role({json.dumps(role)})"
    if candidate.selector_type == "text":
        return f"page.get_by_text({json.dumps(value)})"
    if candidate.selector_type == "css":
        return f"page.locator({json.dumps(value)})"
    if candidate.selector_type == "xpath":
        selector = value if value.lower().startswith("xpath=") else f"xpath={value}"
        return f"page.locator({json.dumps(selector)})"
    return None


def _role_selector_compatible(action: RawAction, candidate: SelectorCandidate) -> bool:
    parts = _role_selector_parts(candidate.selector_value)
    if not parts:
        return False
    role, _name = parts
    normalized_role = role.lower()
    if action.type in {"click", "hover"}:
        return True
    if action.type == "fill":
        return normalized_role in FILLABLE_ROLE_SELECTORS
    if action.type == "press":
        return normalized_role in FILLABLE_ROLE_SELECTORS or normalized_role in CLICKABLE_ROLE_SELECTORS
    if action.type in {"check", "uncheck"}:
        return normalized_role in CHECKABLE_ROLE_SELECTORS
    if action.type == "select":
        return normalized_role in {"combobox", "listbox"}
    if action.type.startswith("assert_") or action.type == "wait":
        return True
    return False


def _selector_candidate_compatible(action: RawAction, candidate: SelectorCandidate) -> bool:
    if not action.selector or not _selector_expression(candidate):
        return False
    if action.type == "goto":
        return False
    if candidate.selector_type in {"test_id", "css", "xpath"}:
        return True
    if candidate.selector_type == "role":
        return _role_selector_compatible(action, candidate)
    if candidate.selector_type == "text":
        return action.type in TEXT_SELECTOR_ACTIONS or action.type.startswith("assert_")
    return False


def _rank_selector_choice(
    action: RawAction,
    candidates: list[SelectorCandidate],
) -> SelectorChoice:
    compatible = sorted(
        [
            candidate
            for candidate in candidates
            if _selector_candidate_compatible(action, candidate)
        ],
        key=_selector_rank_key,
    )
    if not compatible:
        fallback = "incompatible_candidate" if candidates else None
        return SelectorChoice(None, None, sorted(candidates, key=_selector_rank_key)[:3], fallback)

    top = compatible[0]
    runner_ups = compatible[1:4]
    if top.confidence < MIN_SELECTOR_CANDIDATE_CONFIDENCE:
        return SelectorChoice(None, None, [top, *runner_ups][:3], "low_confidence")

    if runner_ups:
        runner = runner_ups[0]
        same_rank = SELECTOR_TYPE_PRIORITY.get(top.selector_type, 99) == SELECTOR_TYPE_PRIORITY.get(
            runner.selector_type,
            99,
        )
        same_confidence = abs(top.confidence - runner.confidence) <= AMBIGUOUS_SELECTOR_CONFIDENCE_DELTA
        different_value = (top.selector_type, top.selector_value) != (runner.selector_type, runner.selector_value)
        if same_rank and same_confidence and different_value:
            return SelectorChoice(None, None, [top, *runner_ups][:3], "ambiguous_candidate")

    return SelectorChoice(_selector_expression(top), top, runner_ups)


def _selector_candidate_payload(candidate: SelectorCandidate) -> dict:
    return {
        "id": candidate.id,
        "type": candidate.selector_type,
        "value": candidate.selector_value,
        "confidence": candidate.confidence,
        "sourceArtifactId": candidate.source_artifact_id,
    }


def _selector_candidate_metadata_dict(candidate: SelectorCandidate) -> dict:
    try:
        metadata = json.loads(candidate.metadata_json or "{}")
    except json.JSONDecodeError:
        metadata = {}
    return metadata if isinstance(metadata, dict) else {}


def _is_structuring_ranked_candidate(candidate: SelectorCandidate) -> bool:
    return _selector_candidate_metadata_dict(candidate).get("structuring_selector_ranked") is True


def _mark_structuring_ranked_candidate(candidate: SelectorCandidate, method_id: str) -> None:
    metadata = _selector_candidate_metadata_dict(candidate)
    metadata["structuring_selector_ranked"] = True
    metadata["page_object_method_id"] = method_id
    candidate.metadata_json = json.dumps(metadata, sort_keys=True)


def _selector_choice_metadata(raw_selector: str, choice: SelectorChoice) -> dict | None:
    if not choice.selected and not choice.runner_ups and not choice.fallback_reason:
        return None
    metadata = {
        "rawSelector": raw_selector,
        "selectedCandidateId": choice.selected.id if choice.selected else None,
        "selectedType": choice.selected.selector_type if choice.selected else None,
        "selectedValue": choice.selected.selector_value if choice.selected else None,
        "selectedConfidence": choice.selected.confidence if choice.selected else None,
        "runnerUpCandidateIds": [
            candidate.id for candidate in choice.runner_ups if candidate.id
        ],
        "runnerUpCandidates": [
            _selector_candidate_payload(candidate) for candidate in choice.runner_ups
        ],
    }
    if choice.selected and choice.selected.source_artifact_id:
        metadata["sourceArtifactId"] = choice.selected.source_artifact_id
    if choice.fallback_reason:
        metadata["fallbackReason"] = choice.fallback_reason
    return metadata


def _selector_from_plan(body_plan: list[dict]) -> str | None:
    return next(
        (
            str(entry["selector"])
            for entry in body_plan
            if isinstance(entry, dict) and entry.get("selector") is not None
        ),
        None,
    )


def _selector_candidate_ids_from_plan(body_plan: list[dict]) -> set[str]:
    candidate_ids: set[str] = set()
    for entry in body_plan:
        if not isinstance(entry, dict):
            continue
        metadata = entry.get("selectorCandidate")
        if not isinstance(metadata, dict):
            continue
        selected_id = metadata.get("selectedCandidateId")
        if isinstance(selected_id, str):
            candidate_ids.add(selected_id)
        for candidate_id in metadata.get("runnerUpCandidateIds") or []:
            if isinstance(candidate_id, str):
                candidate_ids.add(candidate_id)
    return candidate_ids


def _sync_method_selector_candidate_links(
    session: Session,
    method_id: str | None,
    body_plan: list[dict],
) -> None:
    if not method_id:
        return
    current_ids = _selector_candidate_ids_from_plan(body_plan)
    existing = session.exec(
        select(SelectorCandidate).where(SelectorCandidate.page_object_method_id == method_id)
    ).all()
    for candidate in existing:
        if candidate.id not in current_ids and _is_structuring_ranked_candidate(candidate):
            candidate.page_object_method_id = None
            session.add(candidate)
    for candidate_id in current_ids:
        candidate = session.get(SelectorCandidate, candidate_id)
        if candidate:
            candidate.page_object_method_id = method_id
            _mark_structuring_ranked_candidate(candidate, method_id)
            session.add(candidate)


def _plan_entry(
    order: int,
    mapping_id: str | None,
    action: RawAction,
    selector_candidates: list[SelectorCandidate] | None = None,
) -> dict:
    review_reason = _review_reason(action)
    credential = _credential_placeholder(action)
    selector_choice = _rank_selector_choice(action, selector_candidates or [])
    entry = {
        "order": order,
        "action": action.type,
        "sourceRawActionId": action.id,
        "sourceMappingId": mapping_id,
        "requiresReview": review_reason is not None or credential is not None,
    }
    if action.selector is not None:
        entry["selector"] = selector_choice.selector or action.selector
        selector_metadata = _selector_choice_metadata(action.selector, selector_choice)
        if selector_metadata:
            entry["selectorCandidate"] = selector_metadata
    if action.value is not None:
        entry["value"] = credential.value if credential else action.value
    if action.target is not None:
        entry["target"] = _credential_safe_target(
            action.target,
            action.value,
            credential.value if credential else None,
        )
    if review_reason:
        entry["reviewReason"] = review_reason
    if credential:
        entry["reviewReason"] = "credential_value_placeholder"
        entry["credentialPlaceholder"] = {
            "placeholder": credential.value,
            "source": credential.source,
        }
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
    selector_candidates_by_action_id: dict[str, list[SelectorCandidate]] | None = None,
) -> tuple[list[dict], list[RawAction], bool]:
    plan: list[dict] = []
    actions: list[RawAction] = []
    selector_candidates_by_action_id = selector_candidates_by_action_id or {}
    requires_review = mapping.status != "mapped"
    for order, action_id in enumerate(mapping.action_ids, start=1):
        action = action_by_id.get(action_id)
        if not action:
            plan.append(_missing_action_entry(order, mapping.id, action_id))
            requires_review = True
            continue
        actions.append(action)
        entry = _plan_entry(order, mapping.id, action, selector_candidates_by_action_id.get(action_id, []))
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
    selector_candidates_by_action_id = _selector_candidates_for_actions(session, list(action_by_id))
    runs_by_id = _runs_for_actions(session, list(action_by_id.values()))

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

    flow_requires_review = False
    for order_index, mapping in enumerate(mappings, start=1):
        body_plan, actions, requires_review = build_method_body_plan(
            mapping,
            action_by_id,
            selector_candidates_by_action_id,
        )
        page = _ensure_page_object(
            session,
            project_id,
            _route_url_for_actions(actions, runs_by_id),
        )
        flow_requires_review = flow_requires_review or requires_review
        step_name = mapping.normalized_step_name or mapping.pom_method_name or f"step_{mapping.tc_step_index}"
        base_method_name = _method_base_name(mapping, step_name)
        method_name = _scoped_method_name(case, mapping, base_method_name)

        method_type = _method_type(actions, requires_review)
        selector = _selector_from_plan(body_plan)
        value_template = _value_template_from_plan(body_plan)
        body_plan_json = json.dumps(body_plan, sort_keys=True, separators=(",", ":"))
        method_status = (
            PageObjectMethodStatus.draft.value
            if requires_review
            else PageObjectMethodStatus.approved.value
        )

        pom = session.exec(
            select(PageObjectMethod).where(PageObjectMethod.page_object_id == page.id, PageObjectMethod.name == method_name)
        ).first()
        if pom and pom.source_mapping_id != mapping.id:
            method_name = f"{method_name}__{_mapping_suffix(mapping)}"
            pom = session.exec(
                select(PageObjectMethod).where(
                    PageObjectMethod.page_object_id == page.id,
                    PageObjectMethod.name == method_name,
                )
            ).first()
        if not pom:
            existing_mapping_pom = _mapping_method_any_page(session, mapping.id)
            if existing_mapping_pom and not _method_used_by_other_cases(session, existing_mapping_pom.id, case.id):
                pom = existing_mapping_pom
                pom.name = method_name
                _ensure_method_page_assignment(session, pom, page, mapping)
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
        _sync_method_selector_candidate_links(session, pom.id, body_plan)

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


def _repair_shared_method_for_case(
    session: Session,
    *,
    case: TestCase,
    mapping: MappingItem,
    step: StructuredStep,
    method: PageObjectMethod,
) -> PageObjectMethod:
    step_name = mapping.normalized_step_name or mapping.pom_method_name or step.name or f"step_{mapping.tc_step_index}"
    base_name = _method_base_name(mapping, step_name)
    scoped_name = _scoped_method_name(case, mapping, base_name)
    if method.name == scoped_name:
        return method

    scoped = session.exec(
        select(PageObjectMethod).where(
            PageObjectMethod.page_object_id == method.page_object_id,
            PageObjectMethod.name == scoped_name,
        )
    ).first()
    if not scoped:
        scoped = PageObjectMethod(
            id=new_id("pom"),
            page_object_id=method.page_object_id,
            name=scoped_name,
            method_type=method.method_type,
            selector=method.selector,
            value_template=method.value_template,
            return_type=method.return_type,
            body_plan_json=method.body_plan_json,
            source_mapping_id=mapping.id,
            status=method.status,
        )
    else:
        scoped.method_type = method.method_type
        scoped.selector = method.selector
        scoped.value_template = method.value_template
        scoped.return_type = method.return_type
        scoped.body_plan_json = method.body_plan_json
        scoped.source_mapping_id = mapping.id
        scoped.status = method.status
        scoped.updated_at = datetime.utcnow()
    session.add(scoped)
    session.flush()
    step.page_object_method_id = scoped.id
    step.updated_at = datetime.utcnow()
    session.add(step)
    return scoped


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
                method = _repair_shared_method_for_case(
                    session,
                    case=case,
                    mapping=next(mapping for mapping in mappings if mapping.id == mapping_id),
                    step=step,
                    method=method,
                )
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
    selector_candidates_by_action_id = _selector_candidates_for_actions(session, list(new_action_by_id))
    new_runs_by_id = _runs_for_actions(session, new_actions)
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
        body_plan, actions, requires_review = build_method_body_plan(
            mapping,
            new_action_by_id,
            selector_candidates_by_action_id,
        )
        page = _ensure_page_object(
            session,
            project_id,
            _route_url_for_actions(actions, new_runs_by_id),
        )
        _ensure_method_page_assignment(session, method, page, mapping)
        flow_requires_review = flow_requires_review or requires_review
        method.method_type = _method_type(actions, requires_review)
        method.selector = _selector_from_plan(body_plan)
        method.value_template = _value_template_from_plan(body_plan)
        method.body_plan_json = json.dumps(body_plan, sort_keys=True, separators=(",", ":"))
        method.source_mapping_id = mapping.id
        method.status = (
            PageObjectMethodStatus.draft.value
            if requires_review
            else PageObjectMethodStatus.approved.value
        )
        method.updated_at = now
        session.add(method)
        _sync_method_selector_candidate_links(session, method.id, body_plan)

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
