from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml
from sqlmodel import Session, select

from worker.core.config import load_settings, new_id
from worker.models.db import GeneratedFile, TestCase
from worker.services.mapping import get_actions, get_mappings
from worker.models.db import WebwrightRun


def _snake(name: str) -> str:
    return name.lower().replace("-", "_").replace(" ", "_")


def generate_project(session: Session, project_id: str, project_root: Path, case_ids: list[str] | None = None) -> Path:
    settings = load_settings()
    template_path = Path(settings.generator.get("templatePath") or Path(__file__).resolve().parents[4] / "packages" / "generated-template")
    output = project_root / "generated"
    if output.exists():
        shutil.rmtree(output)
    shutil.copytree(template_path, output)

    query = select(TestCase).where(TestCase.project_id == project_id, TestCase.status.in_(["mapped", "needs_review", "structured", "generated"]))
    cases = session.exec(query).all()
    if case_ids:
        cases = [c for c in cases if c.id in case_ids]

    cases_yaml = {"cases": []}
    pages: dict[str, list[str]] = {}
    flows: dict[str, list[str]] = {}

    for case in cases:
        run = session.exec(
            select(WebwrightRun)
            .where(WebwrightRun.test_case_id == case.id)
            .order_by(WebwrightRun.created_at.desc())
        ).first()
        mappings = get_mappings(session, case.id)
        actions = get_actions(session, run.id) if run else []
        action_by_id = {a.id: a for a in actions}

        flow_class = "".join(part.capitalize() for part in case.automation_key.split("_")) + "Flow"
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
        page_methods: list[str] = ["    def __init__(self, page):", "        self.page = page", ""]

        for mapping in mappings:
            method = mapping.pom_method_name or mapping.normalized_step_name or f"step_{mapping.tc_step_index}"
            method = _snake(method)
            action = next((action_by_id[aid] for aid in mapping.action_ids if aid in action_by_id), None)
            flow_lines.append(f"        self.generated_page.{method}()")
            if action:
                if action.type == "goto":
                    page_methods.extend([
                        f"    def {method}(self):",
                        f"        self.page.goto({json.dumps(action.target or action.value or '')})",
                        "",
                    ])
                elif action.type == "click":
                    sel = action.selector or 'self.page.locator("body")'
                    page_methods.extend([
                        f"    def {method}(self):",
                        f"        {sel}.click()",
                        "",
                    ])
                else:
                    page_methods.extend([
                        f"    def {method}(self):",
                        f"        # {action.type}: {action.target or ''}",
                        f"        pass",
                        "",
                    ])
            else:
                page_methods.extend([
                    f"    def {method}(self):",
                    "        pass",
                    "",
                ])

        pages.setdefault("generated_page.py", [])
        pages["generated_page.py"] = page_methods

        flows[flow_file] = flow_lines + [""]
        (output / flow_file).parent.mkdir(parents=True, exist_ok=True)
        (output / flow_file).write_text("\n".join(flow_lines), encoding="utf-8")

        test_content = f'''import pytest
from {_snake(case.automation_key)}_flow import {flow_class}


def {test_fn}(page):
    flow = {flow_class}(page)
    flow.execute()
'''
        test_path = output / test_file
        test_path.parent.mkdir(parents=True, exist_ok=True)
        # fix import path
        test_content = test_content.replace(
            f"from {_snake(case.automation_key)}_flow",
            f"from flows.{_snake(case.automation_key)}_flow",
        )
        test_path.write_text(test_content, encoding="utf-8")

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

        session.exec(select(GeneratedFile).where(GeneratedFile.project_id == project_id))
        for rel in [test_file, flow_file, "pages/generated_page.py", "mappings/cases.yaml"]:
            session.add(GeneratedFile(id=new_id("gf"), project_id=project_id, relative_path=rel, automation_key=case.automation_key))

    page_path = output / "pages" / "generated_page.py"
    page_path.parent.mkdir(parents=True, exist_ok=True)
    if pages.get("generated_page.py"):
        page_path.write_text("\n".join([
            "class GeneratedPage:",
            *pages["generated_page.py"],
        ]), encoding="utf-8")

    mapping_path = output / "mappings" / "cases.yaml"
    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    mapping_path.write_text(yaml.dump(cases_yaml, allow_unicode=True, sort_keys=False), encoding="utf-8")

    session.commit()
    return output
