from __future__ import annotations

import ast
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

import yaml
from sqlmodel import Session, select

from worker.core.config import load_settings, new_id
from worker.core.runtime import resolve_runtime
from worker.models.db import (
    GeneratedFile,
    GeneratedFileOrigin,
    PageObjectMethod,
    RawAction,
    StructuredFlowStatus,
    TestCase,
    WebwrightRun,
)
from worker.services.mapping import get_mappings
from worker.services.structuring_service import get_flow_steps, get_latest_flow, sync_structured_entities


Origin = tuple[str, str]


def _snake(name: str) -> str:
    return name.lower().replace("-", "_").replace(" ", "_")


def _selector_expression(selector: str, action: str) -> str:
    expression_text = selector.strip()
    try:
        expression = ast.parse(expression_text, mode="eval").body
        if (
            isinstance(expression, ast.Call)
            and isinstance(expression.func, ast.Attribute)
            and expression.func.attr == action
        ):
            expression = expression.func.value
        expression_text = ast.unparse(expression)
    except SyntaxError:
        pass
    if expression_text == "page" or expression_text.startswith("page."):
        return f"self.{expression_text}"
    return expression_text


def _interaction_line(action: str, selector: str | None, value: str | None) -> str | None:
    if not selector:
        return None
    expression = _selector_expression(selector, action)
    if action == "fill":
        return f"{expression}.fill({json.dumps(value or '')})"
    if action == "press":
        return f"{expression}.press({json.dumps(value or '')})"
    if action in {"click", "check", "uncheck", "hover"}:
        return f"{expression}.{action}()"
    return None


def _method_body(pom: PageObjectMethod) -> list[str]:
    lines: list[str] = []
    try:
        plan = json.loads(pom.body_plan_json or "[]")
    except json.JSONDecodeError:
        plan = []
    if plan:
        entry = plan[0]
        action = entry.get("action", pom.method_type)
        selector = entry.get("selector")
        value = entry.get("value") or entry.get("target")
        if action == "goto" and value:
            lines.append(f"        self.page.goto({json.dumps(value)})")
        elif interaction := _interaction_line(action, selector, value):
            lines.append(f"        {interaction}")
        else:
            lines.append(f"        # {action}: {entry.get('target', '')}")
            lines.append("        pass")
    elif pom.selector:
        action = "goto" if pom.method_type == "navigate" else pom.method_type
        if action == "goto":
            lines.append(f"        self.page.goto({json.dumps(pom.value_template or '')})")
        elif interaction := _interaction_line(action, pom.selector, pom.value_template):
            lines.append(f"        {interaction}")
        else:
            lines.append(f"        # {action}: unsupported generated interaction")
            lines.append("        pass")
    else:
        lines.append("        pass")
    return lines


def _case_origins(session: Session, case: TestCase, flow, steps) -> set[Origin]:
    origins: set[Origin] = {("test_case", case.id)}
    if flow and flow.id:
        origins.add(("structured_flow", flow.id))

    method_ids: set[str] = set()
    mapping_ids: set[str] = set()
    for step in steps:
        if step.id:
            origins.add(("structured_step", step.id))
        if step.page_object_method_id:
            method_ids.add(step.page_object_method_id)
        if step.mapping_id:
            mapping_ids.add(step.mapping_id)

    methods = [
        session.get(PageObjectMethod, method_id)
        for method_id in sorted(method_ids)
    ]
    for method in methods:
        if not method or not method.id:
            continue
        origins.add(("page_object_method", method.id))
        origins.add(("page_object", method.page_object_id))
        if method.source_mapping_id:
            mapping_ids.add(method.source_mapping_id)

    action_ids: set[str] = set()
    for mapping in get_mappings(session, case.id):
        if mapping.id:
            mapping_ids.add(mapping.id)
        action_ids.update(mapping.action_ids)
    origins.update(("mapping", mapping_id) for mapping_id in mapping_ids)

    if action_ids:
        actions = session.exec(select(RawAction).where(RawAction.id.in_(action_ids))).all()
        for action in actions:
            if action.id:
                origins.add(("raw_action", action.id))
            if action.webwright_run_id:
                origins.add(("webwright_run", action.webwright_run_id))
    return origins


def _replace_generated_file(
    session: Session,
    *,
    project_id: str,
    relative_path: str,
    content_path: Path,
    automation_key: str | None,
    primary_origin: Origin | None,
    origins: set[Origin],
) -> GeneratedFile:
    rows = session.exec(
        select(GeneratedFile)
        .where(
            GeneratedFile.project_id == project_id,
            GeneratedFile.relative_path == relative_path,
        )
        .order_by(GeneratedFile.updated_at.desc(), GeneratedFile.created_at.desc(), GeneratedFile.id.desc())
    ).all()
    generated_file = rows[0] if rows else GeneratedFile(
        id=new_id("gf"),
        project_id=project_id,
        relative_path=relative_path,
    )

    for row in rows:
        for origin in session.exec(
            select(GeneratedFileOrigin).where(GeneratedFileOrigin.generated_file_id == row.id)
        ).all():
            session.delete(origin)
    for duplicate in rows[1:]:
        session.delete(duplicate)

    generated_file.automation_key = automation_key
    generated_file.source_type = primary_origin[0] if primary_origin else None
    generated_file.source_id = primary_origin[1] if primary_origin else None
    generated_file.content_hash = hashlib.sha256(content_path.read_bytes()).hexdigest()
    generated_file.status = "generated"
    generated_file.updated_at = datetime.utcnow()
    session.add(generated_file)
    session.flush()

    for origin_type, origin_id in sorted(origins):
        session.add(GeneratedFileOrigin(
            generated_file_id=generated_file.id,
            origin_type=origin_type,
            origin_id=origin_id,
        ))
    return generated_file


def generate_project(session: Session, project_id: str, project_root: Path, case_ids: list[str] | None = None) -> Path:
    settings = load_settings()
    profile = resolve_runtime(settings)
    template_path = Path(profile.template_path)
    if not template_path.exists():
        template_path = Path(__file__).resolve().parents[4] / "packages" / "generated-template"
    output = project_root / "generated"
    if output.exists():
        shutil.rmtree(output)
    shutil.copytree(template_path, output)

    query = select(TestCase).where(
        TestCase.project_id == project_id,
        TestCase.status.in_(["mapped", "needs_review", "structured", "generated"]),
    ).order_by(TestCase.automation_key, TestCase.id)
    cases = session.exec(query).all()
    if case_ids:
        cases = [c for c in cases if c.id in case_ids]

    cases_yaml = {"cases": []}
    page_methods: dict[str, list[str]] = {}
    file_origins: dict[str, set[Origin]] = {}
    file_automation_keys: dict[str, set[str]] = {}
    file_primary_origins: dict[str, Origin] = {}

    for case in cases:
        run = session.exec(
            select(WebwrightRun)
            .where(WebwrightRun.test_case_id == case.id)
            .order_by(WebwrightRun.created_at.desc())
        ).first()
        sync_structured_entities(session, project_id, case, run)
        flow = get_latest_flow(session, case.id)
        steps = get_flow_steps(session, flow.id) if flow else []
        origins = _case_origins(session, case, flow, steps)

        flow_class = flow.name if flow else "".join(part.capitalize() for part in case.automation_key.split("_")) + "Flow"
        flow_file = f"flows/{_snake(case.automation_key)}_flow.py"
        test_file = f"tests/test_{_snake(case.automation_key)}.py"
        test_fn = f"test_{_snake(case.automation_key)}"

        flow_lines = [
            "from pages.generated_page import GeneratedPage",
            "",
            f"class {flow_class}:",
            "    def __init__(self, page):",
            "        self.page = page",
            "        self.generated_page = GeneratedPage(page)",
            "",
            "    def execute(self):",
        ]

        for step in steps:
            if not step.page_object_method_id:
                continue
            pom = session.get(PageObjectMethod, step.page_object_method_id)
            if not pom:
                continue
            flow_lines.append(f"        self.generated_page.{pom.name}()")
            if pom.name not in page_methods:
                page_methods[pom.name] = [
                    f"    def {pom.name}(self):",
                    *_method_body(pom),
                    "",
                ]

        (output / flow_file).parent.mkdir(parents=True, exist_ok=True)
        (output / flow_file).write_text("\n".join(flow_lines) + "\n", encoding="utf-8")

        test_content = f'''from playwright.sync_api import Page

from flows.{_snake(case.automation_key)}_flow import {flow_class}


def {test_fn}(page: Page):
    flow = {flow_class}(page)
    flow.execute()
'''
        test_path = output / test_file
        test_path.parent.mkdir(parents=True, exist_ok=True)
        test_path.write_text(test_content, encoding="utf-8")

        primary_origin = ("structured_flow", flow.id) if flow and flow.id else ("test_case", case.id)
        for relative_path in [test_file, flow_file, "pages/generated_page.py", "mappings/cases.yaml"]:
            file_origins.setdefault(relative_path, set()).update(origins)
            file_automation_keys.setdefault(relative_path, set()).add(case.automation_key)
            file_primary_origins.setdefault(relative_path, primary_origin)

        source_loc = json.loads(case.source_location_json or "{}")
        cases_yaml["cases"].append({
            "automationKey": case.automation_key,
            "sourceType": case.source_type,
            "sourceCaseId": case.source_case_id,
            "title": case.title,
            "testFile": test_file,
            "testFunction": test_fn,
            "tags": json.loads(case.tags_json or "[]"),
            "resultTargets": {
                "excel": {
                    "file": source_loc.get("file_path"),
                    "sheet": source_loc.get("sheet_name"),
                    "row": source_loc.get("row_index"),
                }
            },
        })
        case.status = "generated"
        session.add(case)
        if flow:
            flow.status = StructuredFlowStatus.generated.value
            session.add(flow)

    page_path = output / "pages" / "generated_page.py"
    page_path.parent.mkdir(parents=True, exist_ok=True)
    page_lines = ["class GeneratedPage:", "    def __init__(self, page):", "        self.page = page", ""]
    for method_lines in page_methods.values():
        page_lines.extend(method_lines)
    page_path.write_text("\n".join(page_lines), encoding="utf-8")

    mapping_path = output / "mappings" / "cases.yaml"
    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    mapping_path.write_text(yaml.dump(cases_yaml, allow_unicode=True, sort_keys=False), encoding="utf-8")

    for relative_path in sorted(file_origins):
        automation_keys = file_automation_keys[relative_path]
        _replace_generated_file(
            session,
            project_id=project_id,
            relative_path=relative_path,
            content_path=output / relative_path,
            automation_key=next(iter(automation_keys)) if len(automation_keys) == 1 else None,
            primary_origin=file_primary_origins.get(relative_path),
            origins=file_origins[relative_path],
        )

    session.commit()
    return output
