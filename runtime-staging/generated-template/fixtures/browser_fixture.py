from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() not in {"0", "false", "no", "off"}


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _resolve_project_path(value: str | None) -> str | None:
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = _project_root() / path
    return str(path)


def _storage_state(env_config: dict[str, Any]) -> str | None:
    configured = os.environ.get("TC_STORAGE_STATE") or env_config.get("storageState") or env_config.get("storage_state")
    resolved = _resolve_project_path(configured)
    if not resolved:
        return None
    return resolved if Path(resolved).exists() else None


def _viewport(env_config: dict[str, Any]) -> dict[str, int]:
    viewport = env_config.get("viewport") if isinstance(env_config.get("viewport"), dict) else {}
    return {
        "width": _env_int("TC_VIEWPORT_WIDTH", int(viewport.get("width", 1280))),
        "height": _env_int("TC_VIEWPORT_HEIGHT", int(viewport.get("height", 720))),
    }


def _artifact_policy(name: str, default: str) -> str:
    return os.environ.get(name, default).lower()


@pytest.fixture(scope="session")
def browser_type_launch_args() -> dict[str, Any]:
    headless_env = os.environ.get("TC_HEADLESS", "true").lower()
    headless = headless_env not in {"0", "false", "no", "off"}
    return {"headless": headless}


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args, env_config: dict[str, Any], base_url: str, artifact_dir: Path) -> dict[str, Any]:
    args = {
        **browser_context_args,
        "ignore_https_errors": _env_bool("TC_IGNORE_HTTPS_ERRORS", True),
        "viewport": _viewport(env_config),
    }
    if base_url:
        args["base_url"] = base_url
    storage_state = _storage_state(env_config)
    if storage_state:
        args["storage_state"] = storage_state
    if env_config.get("locale"):
        args["locale"] = env_config["locale"]
    if env_config.get("timezoneId"):
        args["timezone_id"] = env_config["timezoneId"]
    if env_config.get("permissions"):
        args["permissions"] = env_config["permissions"]
    if _artifact_policy("TC_VIDEO", "retain-on-failure") != "off":
        args["record_video_dir"] = str(artifact_dir / "videos")
    return args


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    setattr(item, f"rep_{report.when}", report)


@pytest.fixture(autouse=True)
def artifact_capture(request, artifact_dir: Path):
    if "page" not in request.fixturenames or "context" not in request.fixturenames:
        yield
        return

    page = request.getfixturevalue("page")
    context = request.getfixturevalue("context")
    trace_policy = _artifact_policy("TC_TRACE", "retain-on-failure")
    screenshot_policy = _artifact_policy("TC_SCREENSHOT", "only-on-failure")
    trace_started = trace_policy != "off"
    if trace_started:
        context.tracing.start(screenshots=True, snapshots=True, sources=True)

    yield

    failed = getattr(request.node, "rep_call", None) is not None and request.node.rep_call.failed
    test_name = request.node.nodeid.replace("::", "__").replace("/", "_").replace("\\", "_")
    if screenshot_policy == "all" or (screenshot_policy in {"only-on-failure", "retain-on-failure"} and failed):
        page.screenshot(path=str(artifact_dir / f"{test_name}.png"), full_page=True)
    if trace_started:
        if trace_policy == "all" or (trace_policy == "retain-on-failure" and failed):
            context.tracing.stop(path=str(artifact_dir / f"{test_name}.zip"))
        else:
            context.tracing.stop()
