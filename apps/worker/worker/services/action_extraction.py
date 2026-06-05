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


@dataclass(frozen=True)
class _CallCandidate:
    call: ast.Call
    source: str
    line_no: int
    aliases: dict[str, str] | None = None


def _node_source(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    return ast.unparse(node)


def _root_name(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Await):
        return _root_name(node.value)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _root_name(node.value)
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Attribute):
            return _root_name(node.func.value)
        return _root_name(node.func)
    if isinstance(node, ast.Subscript):
        return _root_name(node.value)
    return None


def _source_with_aliases(
    node: ast.AST | None,
    aliases: dict[str, str] | None = None,
) -> str | None:
    source = _node_source(node)
    if source is None or not aliases:
        return source
    root = _root_name(node)
    if not root or root not in aliases:
        return source
    if source == root:
        return aliases[root]
    if source.startswith(f"{root}.") or source.startswith(f"{root}["):
        return f"{aliases[root]}{source[len(root):]}"
    return source


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


def _selector_for_wait(
    call: ast.Call,
    method: str,
    aliases: dict[str, str] | None = None,
) -> str | None:
    if not isinstance(call.func, ast.Attribute):
        return None
    base = _source_with_aliases(call.func.value, aliases)
    if method == "wait_for_selector" and call.args:
        return f"page.locator({_node_source(call.args[0])})"
    if method == "wait_for" and base not in {"page", "self.page"}:
        return base
    return None


def _looks_like_playwright_source(source: str | None) -> bool:
    if not source:
        return False
    return (
        source == "page"
        or source == "self.page"
        or source.startswith("page.")
        or source.startswith("self.page.")
        or ".locator(" in source
        or ".get_by_" in source
        or ".frame_locator(" in source
    )


def _selector_alias_source(
    node: ast.AST | None,
    aliases: dict[str, str] | None = None,
) -> str | None:
    if isinstance(node, ast.Await):
        node = node.value
    if isinstance(node, ast.Name) and aliases:
        return aliases.get(node.id)

    source = _source_with_aliases(node, aliases)
    if source is None:
        return None

    if isinstance(node, ast.Attribute):
        if node.attr in _LOCATOR_BUILDERS and _looks_like_playwright_source(
            _source_with_aliases(node.value, aliases)
        ):
            return source
        return None

    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return None

    method = node.func.attr
    base = _source_with_aliases(node.func.value, aliases)
    if (method in _LOCATOR_BUILDERS or method.startswith("get_by_")) and (
        _looks_like_playwright_source(base) or _looks_like_playwright_source(source)
    ):
        return source
    return None


def _looks_like_playwright_call(
    call: ast.Call,
    aliases: dict[str, str] | None = None,
) -> bool:
    method = _call_method(call)
    if not method:
        return False
    if method in _LOCATOR_BUILDERS or method.startswith("get_by_"):
        return False
    source = _source_with_aliases(call, aliases) or ""
    base = _source_with_aliases(call.func.value, aliases) if isinstance(call.func, ast.Attribute) else ""
    return (
        "expect(" in source
        or "async_expect(" in source
        or _looks_like_playwright_source(base)
    )


def _extract_call(
    call: ast.Call,
    raw_line: str,
    aliases: dict[str, str] | None = None,
) -> _ExtractedAction | None:
    method = _call_method(call)
    if not method:
        return None

    expect_target = _expect_target(call)
    if expect_target is not None:
        action_type = _ASSERTION_METHODS.get(method)
        if not action_type:
            return _ExtractedAction("custom_code", target=raw_line)
        selector = _source_with_aliases(expect_target, aliases)
        if selector in {"page", "self.page"}:
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
        selector = _source_with_aliases(call.func.value, aliases) if isinstance(call.func, ast.Attribute) else None
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
            selector=_selector_for_wait(call, method, aliases),
            value=value,
        )

    if _looks_like_playwright_call(call, aliases):
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


def _statement_source(source: str, statement: ast.stmt) -> str:
    segment = ast.get_source_segment(source, statement)
    if segment:
        return segment.strip()
    return ""


def _candidate_source(source: str, statement: ast.stmt | None, call: ast.Call) -> str:
    call_segment = (ast.get_source_segment(source, call) or "").strip()
    if statement is None:
        return call_segment
    statement_segment = _statement_source(source, statement)
    if isinstance(statement, (ast.Expr, ast.Assign, ast.AnnAssign)):
        return statement_segment or call_segment
    return call_segment or statement_segment


class _ActionCallVisitor(ast.NodeVisitor):
    def __init__(self, source: str) -> None:
        self.source = source
        self.statement_stack: list[ast.stmt] = []
        self.aliases: dict[str, str] = {}
        self.candidates: list[_CallCandidate] = []

    def visit(self, node: ast.AST) -> None:
        if isinstance(node, ast.stmt):
            self.statement_stack.append(node)
            try:
                super().visit(node)
            finally:
                self.statement_stack.pop()
            return
        super().visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        statement = self.statement_stack[-1] if self.statement_stack else None
        self.candidates.append(
            _CallCandidate(
                call=node,
                source=_candidate_source(self.source, statement, node),
                line_no=getattr(node, "lineno", 0) or 0,
                aliases=dict(self.aliases),
            )
        )
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_scoped(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_scoped(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_scoped(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        selector = _selector_alias_source(node.value, self.aliases)
        for target in node.targets:
            self._set_alias(target, selector)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        selector = _selector_alias_source(node.value, self.aliases)
        self._set_alias(node.target, selector)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._set_alias(node.target, None)
        self.generic_visit(node)

    def _set_alias(self, target: ast.AST, selector: str | None) -> None:
        if isinstance(target, ast.Name):
            if selector:
                self.aliases[target.id] = selector
            else:
                self.aliases.pop(target.id, None)
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            for item in target.elts:
                self._set_alias(item, None)

    def _visit_scoped(self, node: ast.AST) -> None:
        aliases = dict(self.aliases)
        try:
            self.generic_visit(node)
        finally:
            self.aliases = aliases


def _ast_call_candidates(source: str) -> list[_CallCandidate] | None:
    try:
        module = ast.parse(source)
    except SyntaxError:
        return None
    visitor = _ActionCallVisitor(source)
    visitor.visit(module)
    return visitor.candidates


def _line_call_candidates(source: str) -> list[_CallCandidate]:
    candidates: list[_CallCandidate] = []
    for line_no, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        candidates.extend(
            _CallCandidate(call=call, source=stripped, line_no=line_no)
            for call in _statement_calls(stripped)
        )
    return candidates


def _extract_candidates(source: str) -> list[_CallCandidate]:
    return _ast_call_candidates(source) or _line_call_candidates(source)


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
    source = path.read_text(encoding="utf-8")
    for candidate in _extract_candidates(source):
        extracted = _extract_call(candidate.call, candidate.source, candidate.aliases)
        if extracted is None:
            continue
        actions.append(
            _persist_action(
                session,
                run_id,
                automation_key,
                extracted,
                candidate.line_no,
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
