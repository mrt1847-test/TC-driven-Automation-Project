from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session, select

from worker.core.config import new_id
from worker.models.db import RawAction
from worker.models.schemas import ActionItem

CORE_ACTION_TYPES = (
    "goto",
    "click",
    "fill",
    "select",
    "check",
    "uncheck",
    "hover",
    "press",
    "wait",
    "wait_for_request",
    "wait_for_response",
    "assert_text",
    "assert_url",
    "assert_visible",
    "assert_hidden",
    "assert_count",
    "custom_code",
)
EXTENDED_ACTION_TYPES = ("set_input_files", "drag_to")
SUPPORTED_ACTION_TYPES = (*CORE_ACTION_TYPES, *EXTENDED_ACTION_TYPES)

_INTERACTION_METHODS = {
    "click": "click",
    "fill": "fill",
    "select_option": "select",
    "check": "check",
    "uncheck": "uncheck",
    "hover": "hover",
    "press": "press",
    "set_input_files": "set_input_files",
    "drag_to": "drag_to",
}
_ASSERTION_METHODS = {
    "to_have_text": "assert_text",
    "to_contain_text": "assert_text",
    "to_have_url": "assert_url",
    "to_be_visible": "assert_visible",
    "to_be_hidden": "assert_hidden",
    "to_have_count": "assert_count",
}
_WAIT_METHODS = {
    "wait_for": "wait",
    "wait_for_timeout": "wait",
    "wait_for_load_state": "wait",
    "wait_for_selector": "wait",
    "wait_for_url": "wait",
    "wait_for_function": "wait",
    "wait_for_event": "wait",
    "wait_for_request": "wait_for_request",
    "expect_request": "wait_for_request",
    "wait_for_response": "wait_for_response",
    "expect_response": "wait_for_response",
}
_LOCATOR_BUILDERS = {
    "locator",
    "frame_locator",
    "filter",
    "first",
    "last",
    "nth",
}


@dataclass(frozen=True)
class _ExtractedAction:
    action_type: str
    target: str | None = None
    selector: str | None = None
    value: str | None = None


def _node_source(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    return ast.unparse(node)


def _node_value(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Constant):
        return str(node.value)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "compile"
        and node.args
    ):
        return _node_value(node.args[0])
    return ast.unparse(node)


def _argument_value(call: ast.Call, preferred_keywords: tuple[str, ...] = ()) -> str | None:
    if call.args:
        return _node_value(call.args[0])
    for keyword_name in preferred_keywords:
        keyword = next((item for item in call.keywords if item.arg == keyword_name), None)
        if keyword:
            return _node_value(keyword.value)
    return None


def _call_method(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _expect_target(call: ast.Call) -> ast.AST | None:
    if not isinstance(call.func, ast.Attribute):
        return None
    expect_call = call.func.value
    if not isinstance(expect_call, ast.Call) or not expect_call.args:
        return None
    expect_name = _node_source(expect_call.func)
    if expect_name not in {"expect", "async_expect"}:
        return None
    return expect_call.args[0]


def _selector_for_wait(call: ast.Call, method: str) -> str | None:
    if not isinstance(call.func, ast.Attribute):
        return None
    base = _node_source(call.func.value)
    if method == "wait_for_selector" and call.args:
        return f"page.locator({_node_source(call.args[0])})"
    if method == "wait_for" and base != "page":
        return base
    return None


def _looks_like_playwright_call(call: ast.Call) -> bool:
    method = _call_method(call)
    if not method:
        return False
    if method in _LOCATOR_BUILDERS or method.startswith("get_by_"):
        return False
    source = _node_source(call) or ""
    base = _node_source(call.func.value) if isinstance(call.func, ast.Attribute) else ""
    return (
        "expect(" in source
        or "async_expect(" in source
        or base == "page"
        or (base or "").startswith("page.")
        or ".locator(" in (base or "")
        or ".get_by_" in (base or "")
    )


def _extract_call(call: ast.Call, raw_line: str) -> _ExtractedAction | None:
    method = _call_method(call)
    if not method:
        return None

    expect_target = _expect_target(call)
    if expect_target is not None:
        action_type = _ASSERTION_METHODS.get(method)
        if not action_type:
            return _ExtractedAction("custom_code", target=raw_line)
        selector = _node_source(expect_target)
        if selector == "page":
            selector = None
        value = _argument_value(call)
        return _ExtractedAction(
            action_type,
            target=value or action_type,
            selector=selector,
            value=value,
        )

    if method == "goto":
        value = _argument_value(call, ("url",))
        return _ExtractedAction("goto", target=value, value=value)

    if method in _INTERACTION_METHODS:
        action_type = _INTERACTION_METHODS[method]
        selector = _node_source(call.func.value) if isinstance(call.func, ast.Attribute) else None
        value_keywords = {
            "fill": ("value",),
            "select": ("value", "label", "index"),
            "press": ("key",),
            "set_input_files": ("files",),
            "drag_to": ("target",),
        }.get(action_type, ())
        value = _argument_value(call, value_keywords)
        return _ExtractedAction(
            action_type,
            target="click target" if action_type == "click" else value or action_type,
            selector=selector,
            value=value,
        )

    if method in _WAIT_METHODS:
        action_type = _WAIT_METHODS[method]
        value = _argument_value(call, ("state", "url", "selector"))
        return _ExtractedAction(
            action_type,
            target=value or action_type,
            selector=_selector_for_wait(call, method),
            value=value,
        )

    if _looks_like_playwright_call(call):
        return _ExtractedAction("custom_code", target=raw_line)
    return None


def _statement_calls(raw_line: str) -> list[ast.Call]:
    source = raw_line
    if raw_line.startswith("async with "):
        source = f"{raw_line[len('async '):]}\n    pass"
    elif raw_line.startswith("with "):
        source = f"{raw_line}\n    pass"
    try:
        module = ast.parse(source)
    except SyntaxError:
        return []

    calls: list[ast.Call] = []
    for statement in module.body:
        node: ast.AST | None = None
        if isinstance(statement, ast.Expr):
            node = statement.value
        elif isinstance(statement, (ast.Assign, ast.AnnAssign)):
            node = statement.value
        elif isinstance(statement, (ast.With, ast.AsyncWith)):
            for item in statement.items:
                context = item.context_expr
                if isinstance(context, ast.Await):
                    context = context.value
                if isinstance(context, ast.Call):
                    calls.append(context)
            continue
        if isinstance(node, ast.Await):
            node = node.value
        if isinstance(node, ast.Call):
            calls.append(node)
    return calls


def _persist_action(
    session: Session,
    run_id: str,
    automation_key: str,
    action: _ExtractedAction,
    line_no: int,
    order: int,
) -> ActionItem:
    item = ActionItem(
        id=new_id("act"),
        type=action.action_type,
        target=action.target,
        selector=action.selector,
        value=action.value,
        source_line=line_no,
        order_index=order,
    )
    session.add(
        RawAction(
            id=item.id,
            webwright_run_id=run_id,
            automation_key=automation_key,
            order_index=order,
            type=item.type,
            target=item.target,
            selector=item.selector,
            value=item.value,
            source_line=item.source_line,
        )
    )
    return item


def extract_actions_from_script(
    script_path: str,
    automation_key: str,
    run_id: str,
    session: Session,
) -> list[ActionItem]:
    path = Path(script_path)
    if not path.exists():
        return []

    for action in session.exec(select(RawAction).where(RawAction.webwright_run_id == run_id)).all():
        session.delete(action)

    actions: list[ActionItem] = []
    order = 1
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for call in _statement_calls(stripped):
            extracted = _extract_call(call, stripped)
            if extracted is None:
                continue
            actions.append(
                _persist_action(
                    session,
                    run_id,
                    automation_key,
                    extracted,
                    line_no,
                    order,
                )
            )
            order += 1

    session.commit()
    return actions


def enrich_from_trajectory(actions: list[ActionItem], trajectory_path: str | None) -> list[ActionItem]:
    if not trajectory_path or not Path(trajectory_path).exists():
        return actions
    try:
        data = json.loads(Path(trajectory_path).read_text(encoding="utf-8"))
        if isinstance(data, list) and len(data) > len(actions):
            pass
    except Exception:
        pass
    return actions
