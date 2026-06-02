"""I-03: Smoke test - setup/settings health validation baseline."""
from __future__ import annotations

from pathlib import Path
import sys

from fastapi.testclient import TestClient


def _make_generated_project(root: Path) -> Path:
    generated = root / "generated-smoke"
    (generated / "runner").mkdir(parents=True)
    (generated / "mappings").mkdir(parents=True)
    (generated / "requirements.txt").write_text("pytest>=8.3.0\n", encoding="utf-8")
    (generated / "runner" / "cli.py").write_text("def main():\n    return 0\n", encoding="utf-8")
    (generated / "mappings" / "cases.yaml").write_text("cases: []\n", encoding="utf-8")
    return generated


def _assert_health_shape(payload: dict) -> None:
    for key in [
        "worker",
        "settings",
        "python",
        "webwrightRoot",
        "templatePath",
        "playwright",
        "playwrightBrowser",
        "allOk",
    ]:
        assert key in payload
    assert payload["worker"]["ok"] is True
    assert payload["settings"]["ok"] is True
    assert isinstance(payload["allOk"], bool)


def test_setup_settings_smoke_validation_baseline(
    client: TestClient,
    project_id: str,
    tmp_path: Path,
) -> None:
    root = client.get("/")
    assert root.status_code == 200
    assert root.json()["status"] == "ok"

    health = client.get("/health")
    assert health.status_code == 200
    _assert_health_shape(health.json())

    settings = client.get("/settings")
    assert settings.status_code == 200
    body = settings.json()
    assert Path(body["generator"]["templatePath"]).exists()

    webwright_root = tmp_path / "webwright-root"
    output_root = tmp_path / "webwright-runs"
    project_root = tmp_path / "automation-projects"
    for path in [webwright_root, output_root, project_root]:
        path.mkdir(parents=True, exist_ok=True)

    updated = body.copy()
    updated["webwright"] = {
        **updated["webwright"],
        "executionMode": "native",
        "root": str(webwright_root),
        "python": sys.executable,
        "baseConfig": "base.yaml",
        "modelConfig": "model_openai.yaml",
        "outputRoot": str(output_root),
    }
    updated["generator"] = {
        **updated["generator"],
        "projectRoot": str(project_root),
        "defaultFramework": "playwright-pytest",
        "defaultLanguage": "python",
    }
    updated["runner"] = {
        **updated["runner"],
        "defaultBrowser": "chromium",
        "defaultEnv": "stg",
        "headless": True,
    }
    updated["integrations"] = {
        **updated["integrations"],
        "testrailClone": {"baseUrl": "http://127.0.0.1:3000", "enabled": False},
        "testrail": {"baseUrl": "http://127.0.0.1:3001", "enabled": False},
        "googleSheets": {"enabled": False, "spreadsheetId": "smoke-sheet"},
    }

    saved = client.put("/settings", json=updated)
    assert saved.status_code == 200
    saved_body = saved.json()
    assert saved_body["webwright"]["root"] == str(webwright_root)
    assert saved_body["webwright"]["python"] == sys.executable
    assert saved_body["generator"]["projectRoot"] == str(project_root)
    assert saved_body["runner"]["defaultBrowser"] == "chromium"
    assert saved_body["integrations"]["googleSheets"]["spreadsheetId"] == "smoke-sheet"

    reloaded = client.get("/settings")
    assert reloaded.status_code == 200
    assert reloaded.json()["webwright"]["outputRoot"] == str(output_root)
    assert reloaded.json()["generator"]["projectRoot"] == str(project_root)

    validation = client.post("/settings/validate")
    assert validation.status_code == 200
    validation_body = validation.json()
    _assert_health_shape(validation_body)
    assert validation_body["webwrightRoot"]["ok"] is True
    assert validation_body["webwrightRoot"]["path"] == str(webwright_root)
    assert validation_body["python"]["ok"] is True
    assert validation_body["settings"]["path"].endswith("settings.json")

    missing_generated = client.post(
        f"/projects/{project_id}/health",
        params={"generated_path": str(tmp_path / "missing-generated")},
    )
    assert missing_generated.status_code == 200
    assert missing_generated.json()["allOk"] is False

    generated = _make_generated_project(tmp_path)
    project_health = client.post(
        f"/projects/{project_id}/health",
        params={"generated_path": str(generated)},
    )
    assert project_health.status_code == 200
    assert project_health.json() == {
        "exists": True,
        "requirements": True,
        "runner": True,
        "mappings": True,
        "allOk": True,
    }
