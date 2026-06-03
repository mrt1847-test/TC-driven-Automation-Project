"""E-09: live Webwright runtime E2E gate.

This test is intentionally opt-in. It should be enabled only when a real,
pinned Webwright checkout/package is available locally.
"""

from __future__ import annotations

import os
import json
from pathlib import Path
import sys
import time

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from worker.models.db import ArtifactAsset, ArtifactAssetSourceType, ArtifactAssetType


def _repo_settings() -> dict:
    settings_path = Path(__file__).resolve().parents[4] / ".data" / "settings.json"
    if not settings_path.exists():
        return {}
    return json.loads(settings_path.read_text(encoding="utf-8-sig"))


def _repo_dotenv() -> dict[str, str]:
    env_path = Path(__file__).resolve().parents[4] / ".env"
    if not env_path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def _effective_env() -> dict[str, str]:
    return {**_repo_dotenv(), **os.environ}


def _model_config_for_available_key(default_config: str) -> str:
    env = _effective_env()
    if env.get("OPENAI_API_KEY"):
        return "model_openai.yaml"
    if env.get("ANTHROPIC_API_KEY"):
        return "model_claude.yaml"
    if env.get("OPENROUTER_API_KEY"):
        return "model_openrouter.yaml"
    return default_config


def _required_key_for_model_config(model_config: str) -> str | None:
    if model_config == "model_openai.yaml":
        return "OPENAI_API_KEY"
    if model_config == "model_claude.yaml":
        return "ANTHROPIC_API_KEY"
    if model_config == "model_openrouter.yaml":
        return "OPENROUTER_API_KEY"
    return None


def _live_webwright_config_or_skip(settings: dict, tmp_path: Path) -> dict[str, str]:
    repo_settings = _repo_settings()
    webwright_settings = settings.get("webwright", {})
    repo_webwright_settings = repo_settings.get("webwright", {})
    runtime_settings = settings.get("runtime", {})
    repo_runtime_settings = repo_settings.get("runtime", {})

    env_root = os.environ.get("TC_LIVE_WEBWRIGHT_ROOT", "").strip()
    settings_root = webwright_settings.get("root", "").strip()
    repo_root = repo_webwright_settings.get("root", "").strip()
    root = env_root or settings_root or repo_root
    if not root:
        pytest.skip("E-09 requires TC_LIVE_WEBWRIGHT_ROOT or settings.webwright.root pointing at a real pinned Webwright root")

    python = os.environ.get("TC_LIVE_WEBWRIGHT_PYTHON", "").strip() or os.environ.get("TC_STUDIO_PYTHON", "").strip()
    if not python and env_root:
        python = webwright_settings.get("python", "").strip() or runtime_settings.get("webwrightPython", "").strip()
    if not python and settings_root:
        python = webwright_settings.get("python", "").strip() or runtime_settings.get("webwrightPython", "").strip()
    if not python and repo_root:
        python = repo_webwright_settings.get("python", "").strip() or repo_runtime_settings.get("webwrightPython", "").strip()
    if not python:
        python = runtime_settings.get("python", "").strip() or repo_runtime_settings.get("python", "").strip() or sys.executable
    if env_root:
        default_model_config = webwright_settings.get("modelConfig") or repo_webwright_settings.get("modelConfig") or "model_openai.yaml"
    elif settings_root:
        default_model_config = webwright_settings.get("modelConfig") or repo_webwright_settings.get("modelConfig") or "model_openai.yaml"
    else:
        default_model_config = repo_webwright_settings.get("modelConfig") or webwright_settings.get("modelConfig") or "model_openai.yaml"
    model_config = os.environ.get("TC_LIVE_WEBWRIGHT_MODEL_CONFIG", _model_config_for_available_key(default_model_config))
    required_key = _required_key_for_model_config(model_config)
    effective_env = _effective_env()
    if required_key and not effective_env.get(required_key) and not effective_env.get("API_KEY"):
        pytest.skip(f"E-09 requires {required_key} for {model_config}")

    return {
        "root": root,
        "python": python,
        "base_config": os.environ.get(
            "TC_LIVE_WEBWRIGHT_BASE_CONFIG",
            webwright_settings.get("baseConfig") or repo_webwright_settings.get("baseConfig") or "base.yaml",
        ),
        "model_config": model_config,
        "model_name": os.environ.get(
            "TC_LIVE_WEBWRIGHT_MODEL_NAME",
            webwright_settings.get("modelName") or repo_webwright_settings.get("modelName") or "",
        ),
        "shell": os.environ.get(
            "TC_LIVE_WEBWRIGHT_SHELL",
            webwright_settings.get("shell") or repo_webwright_settings.get("shell") or "",
        ).strip(),
        "output_root": str(tmp_path / "live-webwright-runs"),
        "browsers_path": os.environ.get("TC_LIVE_PLAYWRIGHT_BROWSERS_PATH", "").strip()
        or runtime_settings.get("playwrightBrowsersPath", "").strip()
        or repo_runtime_settings.get("playwrightBrowsersPath", "").strip(),
    }


def _wait_for_run(client: TestClient, project_id: str, case_id: str, timeout_s: float = 120.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        runs = client.get(f"/projects/{project_id}/webwright-runs").json()
        for run in runs:
            if run.get("test_case_id") == case_id and run.get("status") in {"completed", "failed", "cancelled"}:
                return run
        time.sleep(0.25)
    pytest.fail("Timed out waiting for live Webwright run to finish")


def _assets_for_run(run_id: str) -> list[ArtifactAsset]:
    import worker.core.database as database

    with Session(database.engine) as session:
        return session.exec(
            select(ArtifactAsset)
            .where(ArtifactAsset.source_type == ArtifactAssetSourceType.webwright_run.value)
            .where(ArtifactAsset.source_id == run_id)
            .order_by(ArtifactAsset.artifact_type, ArtifactAsset.file_path)
        ).all()


def test_live_webwright_runtime_generates_raw_without_mock_mode(
    client: TestClient,
    project_id: str,
    imported_case: dict,
    tmp_path: Path,
) -> None:
    settings = client.get("/settings").json()
    live = _live_webwright_config_or_skip(settings, tmp_path)

    settings["runtime"] = {
        **settings.get("runtime", {}),
        "mode": "custom",
        "python": live["python"],
        "webwrightPython": live["python"],
    }
    if live["browsers_path"]:
        settings["runtime"]["playwrightBrowsersPath"] = live["browsers_path"]

    settings["webwright"] = {
        **settings.get("webwright", {}),
        "executionMode": "native",
        "root": live["root"],
        "python": live["python"],
        "baseConfig": live["base_config"],
        "modelConfig": live["model_config"],
        "outputRoot": live["output_root"],
    }
    if live["model_name"]:
        settings["webwright"]["modelName"] = live["model_name"]
    if live["shell"]:
        settings["webwright"]["shell"] = live["shell"]
    response = client.put("/settings", json=settings)
    assert response.status_code == 200, response.text

    validation = client.post("/settings/validate").json()
    assert validation["webwrightCli"]["ok"] is True, validation
    assert validation["webwrightConfig"]["ok"] is True, validation
    assert validation["webwrightShell"]["ok"] is True, validation
    assert validation["mockMode"]["enabled"] is False, validation

    case_id = imported_case["id"]
    queued = client.post(
        f"/projects/{project_id}/webwright-runs",
        json={"caseIds": [case_id], "modelConfig": live["model_config"]},
    )
    assert queued.status_code == 200, queued.text

    run = _wait_for_run(client, project_id, case_id)
    assert run["status"] == "completed", run
    assert run["final_script_path"], run

    final_script = Path(run["final_script_path"])
    output_path = Path(run["output_path"])
    assert final_script.exists()
    assert (output_path / "stdout.log").exists()
    assert (output_path / "stderr.log").exists()
    assert (output_path / "metadata.json").exists()
    assert "[mock]" not in (output_path / "stdout.log").read_text(encoding="utf-8").lower()

    actions = client.get(f"/projects/{project_id}/cases/{case_id}/actions")
    assert actions.status_code == 200, actions.text
    assert actions.json(), "live Webwright final_script.py should produce indexed RawAction rows"

    assets = _assets_for_run(run["id"])
    artifact_types = {asset.artifact_type for asset in assets}
    assert ArtifactAssetType.final_script.value in artifact_types
    assert ArtifactAssetType.metadata.value in artifact_types
    assert ArtifactAssetType.log.value in artifact_types
    for asset in assets:
        assert asset.source_type == ArtifactAssetSourceType.webwright_run.value
        assert asset.source_id == run["id"]
        assert Path(asset.file_path).exists()
