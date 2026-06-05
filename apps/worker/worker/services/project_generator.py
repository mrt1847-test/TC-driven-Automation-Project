from __future__ import annotations

import ast
import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml
from sqlmodel import Session, select

from worker.core.config import load_settings, new_id
from worker.core.runtime import resolve_runtime
from worker.models.db import (
    GeneratedFile,
    GeneratedFileOrigin,
    GeneratedFileStatus,
    PageObjectMethod,
    RawAction,
    StructuredFlowStatus,
    TestCase,
    TestCaseStatus,
    WebwrightRun,
)
from worker.services.generated_file_status import (
    latest_generated_files_by_path,
    refresh_generated_file_statuses,
)
from worker.services.mapping import get_mappings
from worker.services.structuring_service import get_flow_steps, get_latest_flow, sync_structured_entities


Origin = tuple[str, str]
RUNTIME_MANIFEST_PATH = "config/runtime-manifest.json"
RUNTIME_MANIFEST_SCHEMA = "tc-studio.generated-runtime-manifest"
RUNTIME_MANIFEST_VERSION = 1
GIT_READY_GITIGNORE = """# TC Automation Studio generated project

# Python caches
__pycache__/
*.py[cod]
*$py.class
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
coverage.xml
htmlcov/

# Local environments and secrets
.env
.env.*
!.env.example
config/*.local.json
config/*.secret.json
config/*.secrets.json
config/secrets*.json
config/storage-state*.json
config/auth-state*.json
.venv/
venv/
env/

# Runner and Playwright artifacts
artifacts/runs/*
!artifacts/runs/.gitkeep
test-results/
playwright-report/
blob-report/
*.log

# OS and editor files
.DS_Store
Thumbs.db
.idea/
.vscode/
"""
GIT_METADATA_NAMES = {".git", ".gitattributes", ".gitmodules"}
TEMPLATE_COPY_IGNORE = shutil.ignore_patterns(
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "*.pyc",
    "artifacts",
    ".env",
    ".env.*",
    "*.local.json",
    "*.secret.json",
    "*.secrets.json",
    "secrets*.json",
    "storage-state*.json",
    "auth-state*.json",
)


@dataclass(frozen=True)
class GenerationResult:
    output: Path
    mode: str
    selected_case_ids: list[str]
    affected_files: list[str]
    changed_files: list[str]
    preserved_files: list[str]
    edited_files: list[str]
    stale_files: list[str]
    conflict_files: list[str]


class GenerationConflictError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        edited_files: list[str],
        stale_files: list[str],
        conflict_files: list[str],
        affected_files: list[str],
        preserved_files: list[str],
    ) -> None:
        super().__init__(message)
        self.edited_files = edited_files
        self.stale_files = stale_files
        self.conflict_files = conflict_files
        self.affected_files = affected_files
        self.preserved_files = preserved_files

    def summary(self) -> dict:
        return {
            "editedFiles": self.edited_files,
            "staleFiles": self.stale_files,
            "conflictFiles": self.conflict_files,
            "affectedFiles": self.affected_files,
            "preservedFiles": self.preserved_files,
        }


@dataclass
class CaseGeneration:
    case: TestCase
    flow: object
    steps: list
    origins: set[Origin]
    test_file: str
    flow_file: str
    test_content: str
    flow_content: str
    mapping_entry: dict


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


def _file_paths(root: Path) -> set[str]:
    if not root.exists():
        return set()
    paths: set[str] = set()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative_path = path.relative_to(root).as_posix()
        if _is_git_metadata_path(relative_path):
            continue
        paths.add(relative_path)
    return paths


def _is_git_metadata_path(relative_path: str) -> bool:
    return relative_path in GIT_METADATA_NAMES or relative_path.startswith(".git/")


def _file_hashes(root: Path, relative_paths: set[str]) -> dict[str, str]:
    return {
        relative_path: hashlib.sha256(path.read_bytes()).hexdigest()
        for relative_path in sorted(relative_paths)
        if (path := root / relative_path).is_file()
    }


def _changed_files_from_hashes(root: Path, before_hashes: dict[str, str], after_files: set[str]) -> list[str]:
    after_hashes = _file_hashes(root, after_files)
    return sorted(
        relative_path
        for relative_path in after_files
        if before_hashes.get(relative_path) != after_hashes.get(relative_path)
    )


def _changed_files_from_planned(
    before_hashes: dict[str, str],
    planned_contents: dict[str, str],
    relative_paths: set[str],
) -> list[str]:
    return sorted(
        relative_path
        for relative_path in relative_paths
        if hashlib.sha256(planned_contents[relative_path].encode("utf-8")).hexdigest()
        != before_hashes.get(relative_path)
    )


def _ensure_git_ready_files(output: Path) -> None:
    gitignore = output / ".gitignore"
    if not gitignore.exists() or gitignore.read_text(encoding="utf-8") != GIT_READY_GITIGNORE:
        gitignore.write_text(GIT_READY_GITIGNORE, encoding="utf-8")
    runs_dir = output / "artifacts" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    gitkeep = runs_dir / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.write_text("", encoding="utf-8")


def _reset_output_from_template(output: Path, template_path: Path) -> None:
    if output.exists():
        for child in output.iterdir():
            if child.name in GIT_METADATA_NAMES:
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        shutil.copytree(template_path, output, dirs_exist_ok=True, ignore=TEMPLATE_COPY_IGNORE)
    else:
        shutil.copytree(template_path, output, ignore=TEMPLATE_COPY_IGNORE)
    _ensure_git_ready_files(output)


def _generated_file_origins(session: Session, project_id: str, relative_path: str) -> set[Origin]:
    generated_file = session.exec(
        select(GeneratedFile)
        .where(
            GeneratedFile.project_id == project_id,
            GeneratedFile.relative_path == relative_path,
        )
        .order_by(GeneratedFile.updated_at.desc(), GeneratedFile.created_at.desc(), GeneratedFile.id.desc())
    ).first()
    if not generated_file:
        return set()
    origins = session.exec(
        select(GeneratedFileOrigin).where(GeneratedFileOrigin.generated_file_id == generated_file.id)
    ).all()
    return {(origin.origin_type, origin.origin_id) for origin in origins}


def _shared_case_ids(session: Session, project_id: str, relative_path: str) -> set[str]:
    return {
        origin_id
        for origin_type, origin_id in _generated_file_origins(session, project_id, relative_path)
        if origin_type == "test_case"
    }


def _mapping_entry(case: TestCase, test_file: str, test_fn: str) -> dict:
    source_loc = json.loads(case.source_location_json or "{}")
    return {
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
    }


def _case_generation(
    session: Session,
    case: TestCase,
    flow,
    steps,
) -> CaseGeneration:
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
        if pom:
            flow_lines.append(f"        self.generated_page.{pom.name}()")

    test_content = f'''from playwright.sync_api import Page

from flows.{_snake(case.automation_key)}_flow import {flow_class}


def {test_fn}(page: Page):
    flow = {flow_class}(page)
    flow.execute()
'''
    return CaseGeneration(
        case=case,
        flow=flow,
        steps=steps,
        origins=origins,
        test_file=test_file,
        flow_file=flow_file,
        test_content=test_content,
        flow_content="\n".join(flow_lines) + "\n",
        mapping_entry=_mapping_entry(case, test_file, test_fn),
    )


def _write_text(path: Path, content: str, rewritten_files: set[str], output: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    rewritten_files.add(path.relative_to(output).as_posix())


def _write_text_if_changed(path: Path, content: str, rewritten_files: set[str], output: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.read_text(encoding="utf-8") == content:
        return
    path.write_text(content, encoding="utf-8")
    rewritten_files.add(path.relative_to(output).as_posix())


def _manifest_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _manifest_int(value: object) -> int | None:
    if value in {None, ""}:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _manifest_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() not in {"0", "false", "no", "off"}
    return default


def _settings_section(settings: object, name: str) -> dict:
    value = getattr(settings, name, None) if settings is not None else None
    return value if isinstance(value, dict) else {}


def _requirements_manifest(template_path: Path) -> dict:
    requirements_path = template_path / "requirements.txt"
    if not requirements_path.is_file():
        return {
            "file": "requirements.txt",
            "sha256": None,
            "requirements": [],
        }
    content = requirements_path.read_text(encoding="utf-8")
    requirements = [
        line.strip()
        for line in content.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    return {
        "file": "requirements.txt",
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "requirements": requirements,
    }


def _runtime_manifest_content(settings: object, profile: object, template_path: Path) -> str:
    runner = _settings_section(settings, "runner")
    default_env = _manifest_string(runner.get("defaultEnv")) or "stg"
    default_browser = _manifest_string(runner.get("defaultBrowser")) or "chromium"
    headless = _manifest_bool(runner.get("headless"), True)
    browser_cache = _manifest_string(getattr(profile, "playwright_browsers_path", None))
    manifest = {
        "commands": {
            "bootstrap": [
                "python -m pip install -r requirements.txt",
                f"python -m playwright install {default_browser}",
            ],
            "standalone": [
                "python -m runner.cli list-cases",
                f"python -m runner.cli run --env {default_env} --browser {default_browser} --all",
                f"python -m runner.cli run --env {default_env} --browser {default_browser} --case-key <automationKey>",
                "python -m runner.cli rerun-failed --from-run-id <runId>",
                "python -m runner.cli export --run-id <runId> --target testrail-clone",
            ],
            "studio": {
                "bootstrapBeforeRun": True,
                "entrypoint": "runner.cli",
                "runtimeProfilePython": _manifest_string(getattr(profile, "python", None)),
                "usesRuntimeProfile": True,
            },
        },
        "compatibility": {
            "standalone": True,
            "studio": True,
        },
        "fixturePolicy": {
            "artifactsRoot": "artifacts/runs/{runId}",
            "browserContext": {
                "authState": "TC_STORAGE_STATE or config env storageState",
                "baseUrl": "TC_BASE_URL or config/env.{env}.json baseUrl",
                "ignoreHttpsErrorsDefault": True,
                "viewportEnv": ["TC_VIEWPORT_WIDTH", "TC_VIEWPORT_HEIGHT"],
            },
            "environment": [
                "TC_ENV",
                "TC_RUN_ID",
                "TC_ARTIFACT_DIR",
                "TC_BASE_URL",
                "TC_HEADLESS",
                "TC_BROWSER",
                "TC_STORAGE_STATE",
                "TC_TRACE",
                "TC_SCREENSHOT",
                "TC_VIDEO",
                "PLAYWRIGHT_BROWSERS_PATH",
            ],
            "pytestPlugins": [
                "pytest_playwright.pytest_playwright",
                "fixtures.browser_fixture",
                "fixtures.env_fixture",
            ],
            "version": "B3-04",
        },
        "manifestVersion": RUNTIME_MANIFEST_VERSION,
        "packages": _requirements_manifest(template_path),
        "playwright": {
            "browserCache": {
                "env": "PLAYWRIGHT_BROWSERS_PATH",
                "studioDefault": browser_cache,
            },
            "defaultBrowser": default_browser,
            "installCommand": f"python -m playwright install {default_browser}",
            "supportedBrowsers": [default_browser],
        },
        "python": {
            "runtimeProfileField": "python",
            "standaloneCommand": "python",
            "studioDefault": _manifest_string(getattr(profile, "python", None)),
        },
        "runtimeProfileDefaults": {
            "apiProvider": _manifest_string(getattr(profile, "api_provider", None)),
            "baseConfig": _manifest_string(getattr(profile, "base_config", None)),
            "executionMode": _manifest_string(getattr(profile, "execution_mode", None)),
            "mode": _manifest_string(getattr(profile, "mode", None)),
            "modelConfig": _manifest_string(getattr(profile, "model_config", None)),
            "modelName": _manifest_string(getattr(profile, "model_name", None)),
            "playwrightBrowsersPath": browser_cache,
            "templatePath": str(template_path),
            "webwrightOutputRoot": _manifest_string(getattr(profile, "webwright_output_root", None)),
            "webwrightPython": _manifest_string(getattr(profile, "webwright_python", None)),
            "webwrightRoot": _manifest_string(getattr(profile, "webwright_root", None)),
            "webwrightRunTimeoutSeconds": _manifest_int(getattr(profile, "webwright_run_timeout_seconds", None)),
            "webwrightShell": _manifest_string(getattr(profile, "webwright_shell", None)),
            "webwrightStepLimit": _manifest_int(getattr(profile, "webwright_step_limit", None)),
        },
        "runnerDefaults": {
            "browser": default_browser,
            "env": default_env,
            "headless": headless,
        },
        "schema": RUNTIME_MANIFEST_SCHEMA,
    }
    return json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _page_content(session: Session, generations: list[CaseGeneration]) -> str:
    page_methods: dict[str, list[str]] = {}
    for generation in sorted(generations, key=lambda item: (item.case.automation_key, item.case.id)):
        for step in generation.steps:
            if not step.page_object_method_id:
                continue
            pom = session.get(PageObjectMethod, step.page_object_method_id)
            if pom and pom.name not in page_methods:
                page_methods[pom.name] = [
                    f"    def {pom.name}(self):",
                    *_method_body(pom),
                    "",
                ]
    lines = ["class GeneratedPage:", "    def __init__(self, page):", "        self.page = page", ""]
    for method_name in sorted(page_methods):
        lines.extend(page_methods[method_name])
    return "\n".join(lines)


def _load_cases_yaml(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError("Existing mappings/cases.yaml is invalid; incremental generation was not applied") from exc
    cases = payload.get("cases", []) if isinstance(payload, dict) else None
    if not isinstance(cases, list) or any(not isinstance(entry, dict) for entry in cases):
        raise ValueError("Existing mappings/cases.yaml must contain a cases list for incremental generation")
    return cases


def _merge_mapping_entries(existing: list[dict], replacements: list[dict]) -> list[dict]:
    replacements_by_key = {
        entry["automationKey"]: entry
        for entry in replacements
    }
    merged: list[dict] = []
    used: set[str] = set()
    for entry in existing:
        key = entry.get("automationKey")
        if key in replacements_by_key:
            merged.append(replacements_by_key[key])
            used.add(key)
        else:
            merged.append(entry)
    for key in sorted(replacements_by_key):
        if key not in used:
            merged.append(replacements_by_key[key])
    return merged


def _latest_generation(session: Session, case: TestCase) -> CaseGeneration | None:
    flow = get_latest_flow(session, case.id)
    if not flow:
        return None
    return _case_generation(session, case, flow, get_flow_steps(session, flow.id))


def generate_project(
    session: Session,
    project_id: str,
    project_root: Path,
    case_ids: list[str] | None = None,
    *,
    mode: str | None = None,
    dry_run: bool = False,
) -> GenerationResult:
    settings = load_settings()
    profile = resolve_runtime(settings)
    template_path = Path(profile.template_path)
    if not template_path.exists():
        template_path = Path(__file__).resolve().parents[4] / "packages" / "generated-template"
    runtime_manifest_content = _runtime_manifest_content(settings, profile, template_path)
    output = project_root / "generated"
    selection_requested = case_ids is not None
    requested_case_ids = sorted(set(case_ids or []))
    generation_mode = mode or ("incremental" if selection_requested else "full")
    if generation_mode not in {"incremental", "full"}:
        raise ValueError("Generation mode must be incremental or full")
    if generation_mode == "incremental" and not requested_case_ids:
        raise ValueError("Incremental generation requires caseIds")

    before_files = _file_paths(output)
    initialized = not output.exists()

    query = select(TestCase).where(
        TestCase.project_id == project_id,
        TestCase.status.in_(["mapped", "needs_review", "structured", "generated"]),
    ).order_by(TestCase.automation_key, TestCase.id)
    all_cases = session.exec(query).all()
    all_cases_by_id = {case.id: case for case in all_cases}
    if generation_mode == "full":
        cases = all_cases
        selected_case_ids = [case.id for case in cases]
    else:
        missing_case_ids = [case_id for case_id in requested_case_ids if case_id not in all_cases_by_id]
        if missing_case_ids:
            raise ValueError(f"Selected cases are not generation-ready: {', '.join(missing_case_ids)}")
        cases = [all_cases_by_id[case_id] for case_id in requested_case_ids]
        selected_case_ids = requested_case_ids

    rewritten_files: set[str] = set()
    generated: dict[str, CaseGeneration] = {}
    file_origins: dict[str, set[Origin]] = {}
    file_automation_keys: dict[str, set[str]] = {}
    file_primary_origins: dict[str, Origin] = {}

    for case in cases:
        run = session.exec(
            select(WebwrightRun)
            .where(WebwrightRun.test_case_id == case.id)
            .order_by(WebwrightRun.created_at.desc())
        ).first()
        flow = get_latest_flow(session, case.id) if generation_mode == "incremental" else None
        if not flow:
            flow = sync_structured_entities(session, project_id, case, run)
        if generation_mode == "incremental" and (
            case.status == "needs_review"
            or (flow and flow.status == StructuredFlowStatus.needs_review.value)
        ):
            raise ValueError(
                f"Selected case requires structure review before incremental generation: {case.id}"
            )
        steps = get_flow_steps(session, flow.id) if flow else []
        generation = _case_generation(session, case, flow, steps)
        generated[case.id] = generation

    if generation_mode == "full":
        page_case_ids = set(generated)
        mapping_entries = [generation.mapping_entry for generation in generated.values()]
    else:
        page_case_ids = _shared_case_ids(session, project_id, "pages/generated_page.py")
        page_case_ids.update(selected_case_ids)
        mapping_path = output / "mappings" / "cases.yaml"
        existing_entries = [] if initialized else _load_cases_yaml(mapping_path)
        mapping_entries = _merge_mapping_entries(
            existing_entries,
            [generated[case_id].mapping_entry for case_id in selected_case_ids],
        )

    shared_generations: dict[str, CaseGeneration] = dict(generated)
    for case_id in sorted(page_case_ids):
        if case_id in shared_generations:
            continue
        case = all_cases_by_id.get(case_id)
        generation = _latest_generation(session, case) if case else None
        if generation:
            shared_generations[case_id] = generation

    shared_origins: set[Origin] = set()
    shared_automation_keys: set[str] = set()
    shared_primary_origins: list[Origin] = []
    for generation in shared_generations.values():
        shared_origins.update(generation.origins)
        shared_automation_keys.add(generation.case.automation_key)
        shared_primary_origins.append(
            ("structured_flow", generation.flow.id)
            if generation.flow and generation.flow.id
            else ("test_case", generation.case.id)
        )

    page_relative_path = "pages/generated_page.py"
    file_origins[page_relative_path] = shared_origins
    file_automation_keys[page_relative_path] = shared_automation_keys
    if shared_primary_origins:
        file_primary_origins[page_relative_path] = sorted(shared_primary_origins)[0]

    mapping_relative_path = "mappings/cases.yaml"
    mapping_path = output / mapping_relative_path
    page_content = _page_content(session, list(shared_generations.values()))
    mapping_content = yaml.dump({"cases": mapping_entries}, allow_unicode=True, sort_keys=False)
    existing_mapping_origins = (
        set()
        if generation_mode == "full" or initialized
        else _generated_file_origins(session, project_id, mapping_relative_path)
    )
    selected_existing_origins = set().union(*(
        _generated_file_origins(session, project_id, generated[case_id].test_file)
        for case_id in selected_case_ids
    )) if selected_case_ids else set()
    mapping_origins = (
        (existing_mapping_origins - selected_existing_origins) | shared_origins
        if selected_case_ids
        else existing_mapping_origins
    )
    if generation_mode == "full":
        mapping_origins = shared_origins
    file_origins[mapping_relative_path] = mapping_origins
    mapping_keys = {
        entry.get("automationKey")
        for entry in mapping_entries
        if entry.get("automationKey")
    }
    file_automation_keys[mapping_relative_path] = mapping_keys
    if shared_primary_origins:
        file_primary_origins[mapping_relative_path] = sorted(shared_primary_origins)[0]

    file_origins[RUNTIME_MANIFEST_PATH] = set()
    file_automation_keys[RUNTIME_MANIFEST_PATH] = set()

    planned_rewritten_files = {
        RUNTIME_MANIFEST_PATH,
        page_relative_path,
        mapping_relative_path,
        *(
            relative_path
            for generation in generated.values()
            for relative_path in [generation.flow_file, generation.test_file]
        ),
    }
    planned_contents = {
        RUNTIME_MANIFEST_PATH: runtime_manifest_content,
        page_relative_path: page_content,
        mapping_relative_path: mapping_content,
        **{
            generation.flow_file: generation.flow_content
            for generation in generated.values()
        },
        **{
            generation.test_file: generation.test_content
            for generation in generated.values()
        },
    }
    before_hashes = (
        _file_hashes(output, before_files)
        if not initialized
        else {}
    )
    tracked_paths = set(latest_generated_files_by_path(session, project_id))
    planned_deletions = (
        (tracked_paths - set(planned_contents))
        if generation_mode == "full"
        else set()
    )
    guard_paths = (
        (tracked_paths | planned_rewritten_files)
        if generation_mode == "full"
        else planned_rewritten_files
    )
    status_preflight: dict[str, dict] = {}
    edited_files: list[str] = []
    stale_files: list[str] = []
    conflict_files: list[str] = []
    if not initialized:
        status_preflight = refresh_generated_file_statuses(
            session,
            project_id,
            output,
            relative_paths=guard_paths,
            planned_contents=planned_contents,
            planned_deletions=planned_deletions,
        )
        edited_files = sorted(
            path for path, item in status_preflight.items()
            if item["status"] == GeneratedFileStatus.edited.value
        )
        stale_files = sorted(
            path for path, item in status_preflight.items()
            if item["status"] == GeneratedFileStatus.stale.value
        )
        conflict_files = sorted(
            path for path, item in status_preflight.items()
            if item["status"] == GeneratedFileStatus.conflict.value
        )
        manifest_target = output / RUNTIME_MANIFEST_PATH
        if RUNTIME_MANIFEST_PATH not in tracked_paths and manifest_target.exists():
            try:
                manifest_matches_plan = (
                    manifest_target.is_file()
                    and manifest_target.read_text(encoding="utf-8") == runtime_manifest_content
                )
            except (OSError, UnicodeDecodeError):
                manifest_matches_plan = False
            if not manifest_matches_plan:
                edited_files.append(RUNTIME_MANIFEST_PATH)
        if conflict_files or edited_files:
            if dry_run:
                session.rollback()
            else:
                session.commit()
            blocked = conflict_files or edited_files
            raise GenerationConflictError(
                "Generated files require review before regeneration: " + ", ".join(blocked),
                edited_files=edited_files,
                stale_files=stale_files,
                conflict_files=conflict_files,
                affected_files=sorted(guard_paths),
                preserved_files=sorted(before_files - guard_paths),
            )

    if dry_run:
        changed_files = (
            sorted(planned_rewritten_files)
            if initialized
            else _changed_files_from_planned(before_hashes, planned_contents, planned_rewritten_files)
        )
        return GenerationResult(
            output=output,
            mode=generation_mode,
            selected_case_ids=selected_case_ids,
            affected_files=sorted(planned_rewritten_files),
            changed_files=changed_files,
            preserved_files=sorted(before_files - planned_rewritten_files),
            edited_files=edited_files,
            stale_files=stale_files,
            conflict_files=conflict_files,
        )

    if generation_mode == "full" or not output.exists():
        _reset_output_from_template(output, template_path)
    else:
        _ensure_git_ready_files(output)

    _write_text_if_changed(output / RUNTIME_MANIFEST_PATH, runtime_manifest_content, rewritten_files, output)

    for generation in generated.values():
        _write_text(output / generation.flow_file, generation.flow_content, rewritten_files, output)
        _write_text(output / generation.test_file, generation.test_content, rewritten_files, output)
        primary_origin = (
            ("structured_flow", generation.flow.id)
            if generation.flow and generation.flow.id
            else ("test_case", generation.case.id)
        )
        for relative_path in [generation.test_file, generation.flow_file]:
            file_origins.setdefault(relative_path, set()).update(generation.origins)
            file_automation_keys.setdefault(relative_path, set()).add(generation.case.automation_key)
            file_primary_origins.setdefault(relative_path, primary_origin)
        generation.case.status = "generated"
        session.add(generation.case)
        if generation.flow:
            generation.flow.status = StructuredFlowStatus.generated.value
            session.add(generation.flow)

    _write_text(output / page_relative_path, page_content, rewritten_files, output)
    _write_text(mapping_path, mapping_content, rewritten_files, output)

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
    after_files = _file_paths(output)
    if initialized:
        affected_files = sorted(after_files)
        changed_files = affected_files
        preserved_files: list[str] = []
    elif generation_mode == "full":
        affected_files = sorted(before_files | after_files)
        changed_files = _changed_files_from_hashes(output, before_hashes, after_files)
        preserved_files = []
    else:
        affected_files = sorted(rewritten_files)
        preserved_files = sorted(before_files - rewritten_files)
        changed_files = _changed_files_from_hashes(output, before_hashes, rewritten_files)
    return GenerationResult(
        output=output,
        mode=generation_mode,
        selected_case_ids=selected_case_ids,
        affected_files=affected_files,
        changed_files=changed_files,
        preserved_files=preserved_files,
        edited_files=edited_files,
        stale_files=stale_files,
        conflict_files=conflict_files,
    )


def retire_generated_case(
    session: Session,
    project_id: str,
    output: Path,
    case_id: str,
    *,
    action: str,
    reason: str | None = None,
    preview: bool = False,
) -> dict:
    if action not in {"retire", "delete"}:
        raise ValueError("Retire cleanup action must be retire or delete")
    case_status = (
        TestCaseStatus.retired.value
        if action == "retire"
        else TestCaseStatus.deleted.value
    )
    case = session.get(TestCase, case_id)
    if not case or case.project_id != project_id:
        raise ValueError("Case not found")

    before_files = _file_paths(output)
    rows = list(session.exec(
        select(GeneratedFile).where(GeneratedFile.project_id == project_id)
    ).all())
    rows_by_path: dict[str, list[GeneratedFile]] = {}
    for row in rows:
        rows_by_path.setdefault(row.relative_path, []).append(row)
    latest_by_path = {
        relative_path: sorted(
            path_rows,
            key=lambda row: (row.updated_at, row.created_at, row.id or ""),
            reverse=True,
        )[0]
        for relative_path, path_rows in rows_by_path.items()
    }
    origins_by_path = {
        relative_path: _generated_file_origins(session, project_id, relative_path)
        for relative_path in latest_by_path
    }

    project_cases = {
        item.id: item
        for item in session.exec(select(TestCase).where(TestCase.project_id == project_id)).all()
        if item.id
    }
    active_case_ids = {
        item.id
        for item in project_cases.values()
        if item.id != case_id
        and item.status not in {TestCaseStatus.retired.value, TestCaseStatus.deleted.value}
    }
    selected_origin = ("test_case", case_id)
    impacted_files = {
        relative_path
        for relative_path, origins in origins_by_path.items()
        if selected_origin in origins or latest_by_path[relative_path].automation_key == case.automation_key
    }
    control_paths = {"pages/generated_page.py", "mappings/cases.yaml"}
    expected_private_paths = {
        f"flows/{_snake(case.automation_key)}_flow.py",
        f"tests/test_{_snake(case.automation_key)}.py",
    }

    conflict_files: set[str] = set()
    for relative_path in sorted(expected_private_paths):
        if (output / relative_path).exists() and relative_path not in impacted_files:
            conflict_files.add(relative_path)

    mapping_entries: list[dict] = []
    mapping_path = output / "mappings" / "cases.yaml"
    if mapping_path.exists():
        try:
            mapping_entries = _load_cases_yaml(mapping_path)
        except ValueError:
            conflict_files.add("mappings/cases.yaml")
        if (
            any(entry.get("automationKey") == case.automation_key for entry in mapping_entries)
            and "mappings/cases.yaml" not in impacted_files
        ):
            conflict_files.add("mappings/cases.yaml")

    for relative_path in sorted(impacted_files):
        row = latest_by_path[relative_path]
        target = output / relative_path
        origins = origins_by_path[relative_path]
        other_active_case_ids = {
            origin_id
            for origin_type, origin_id in origins
            if origin_type == "test_case" and origin_id in active_case_ids
        }
        if relative_path not in control_paths and other_active_case_ids:
            conflict_files.add(relative_path)
        if row.status in {GeneratedFileStatus.edited.value, GeneratedFileStatus.conflict.value}:
            conflict_files.add(relative_path)
        if target.is_file():
            current_hash = hashlib.sha256(target.read_bytes()).hexdigest()
            if not row.content_hash or current_hash != row.content_hash:
                conflict_files.add(relative_path)
        elif target.exists():
            conflict_files.add(relative_path)
        elif relative_path in control_paths:
            conflict_files.add(relative_path)

    control_plans: dict[str, tuple[str, set[Origin], set[str], Origin | None]] = {}
    remaining_mapping_case_ids = {
        active_case.id
        for active_case in project_cases.values()
        if active_case.id in active_case_ids
        and any(
            entry.get("automationKey") == active_case.automation_key
            for entry in mapping_entries
        )
    }
    for relative_path in sorted(control_paths & impacted_files):
        origins = origins_by_path[relative_path]
        origin_active_case_ids = {
            origin_id
            for origin_type, origin_id in origins
            if origin_type == "test_case" and origin_id in active_case_ids
        }
        if origin_active_case_ids != remaining_mapping_case_ids:
            conflict_files.add(relative_path)
        if relative_path == "mappings/cases.yaml":
            entries = [
                entry for entry in mapping_entries
                if entry.get("automationKey") != case.automation_key
            ]
            content = yaml.dump({"cases": entries}, allow_unicode=True, sort_keys=False)
        else:
            content = ""

        generations: list[CaseGeneration] = []
        for remaining_case_id in sorted(remaining_mapping_case_ids):
            generation = _latest_generation(session, project_cases[remaining_case_id])
            if not generation:
                conflict_files.add(relative_path)
                continue
            generations.append(generation)
        if relative_path == "pages/generated_page.py":
            content = _page_content(session, generations)

        refreshed_origins: set[Origin] = set()
        automation_keys: set[str] = set()
        primary_origins: list[Origin] = []
        for generation in generations:
            refreshed_origins.update(generation.origins)
            automation_keys.add(generation.case.automation_key)
            primary_origins.append(
                ("structured_flow", generation.flow.id)
                if generation.flow and generation.flow.id
                else ("test_case", generation.case.id)
            )
        control_plans[relative_path] = (
            content,
            refreshed_origins,
            automation_keys,
            sorted(primary_origins)[0] if primary_origins else None,
        )

    if conflict_files:
        conflict_summary = {
            "status": "conflict",
            "preview": preview,
            "action": action,
            "reason": reason,
            "caseId": case.id,
            "automationKey": case.automation_key,
            "caseStatus": case.status,
            "affectedFiles": sorted(impacted_files | conflict_files),
            "removedFiles": [],
            "updatedFiles": [],
            "obsoleteFiles": [],
            "preservedSharedFiles": sorted(control_paths & impacted_files),
            "preservedFiles": sorted(before_files),
            "conflictFiles": sorted(conflict_files),
            "unaffectedCaseIds": sorted(active_case_ids),
        }
        if preview:
            return conflict_summary
        for relative_path in sorted(conflict_files):
            row = latest_by_path.get(relative_path)
            if row and row.status != GeneratedFileStatus.edited.value:
                row.status = GeneratedFileStatus.conflict.value
                row.updated_at = datetime.utcnow()
                session.add(row)
        session.commit()
        return conflict_summary

    obsolete_files = impacted_files - set(control_plans)
    if preview:
        return {
            "status": "preview",
            "preview": True,
            "action": action,
            "reason": reason,
            "caseId": case.id,
            "automationKey": case.automation_key,
            "caseStatus": case_status,
            "affectedFiles": sorted(impacted_files),
            "removedFiles": sorted(
                relative_path
                for relative_path in obsolete_files
                if (output / relative_path).is_file()
            ),
            "updatedFiles": sorted(control_plans),
            "obsoleteFiles": sorted(obsolete_files),
            "preservedSharedFiles": sorted(control_plans),
            "preservedFiles": sorted(before_files - obsolete_files - set(control_plans)),
            "conflictFiles": [],
            "unaffectedCaseIds": sorted(active_case_ids),
        }

    case.status = case_status
    case.updated_at = datetime.utcnow()
    session.add(case)

    updated_files: set[str] = set()
    for relative_path, (content, origins, automation_keys, primary_origin) in control_plans.items():
        _write_text(output / relative_path, content, updated_files, output)
        _replace_generated_file(
            session,
            project_id=project_id,
            relative_path=relative_path,
            content_path=output / relative_path,
            automation_key=next(iter(automation_keys)) if len(automation_keys) == 1 else None,
            primary_origin=primary_origin,
            origins=origins,
        )

    removed_files: set[str] = set()
    for relative_path in sorted(obsolete_files):
        target = output / relative_path
        if target.is_file():
            target.unlink()
            removed_files.add(relative_path)
        for row in rows_by_path.get(relative_path, []):
            row.status = GeneratedFileStatus.obsolete.value
            row.updated_at = datetime.utcnow()
            session.add(row)

    session.commit()
    return {
        "status": "completed",
        "action": action,
        "reason": reason,
        "caseId": case.id,
        "automationKey": case.automation_key,
        "caseStatus": case.status,
        "affectedFiles": sorted(impacted_files),
        "removedFiles": sorted(removed_files),
        "updatedFiles": sorted(updated_files),
        "obsoleteFiles": sorted(obsolete_files),
        "preservedSharedFiles": sorted(control_plans),
        "preservedFiles": sorted(before_files - removed_files - updated_files),
        "conflictFiles": [],
    }
