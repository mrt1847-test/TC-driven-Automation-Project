"""I-03 smoke test against a live Worker on http://127.0.0.1:8765."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8765"


def make_generated_project(root: Path) -> Path:
    generated = root / "generated-smoke"
    (generated / "runner").mkdir(parents=True)
    (generated / "mappings").mkdir(parents=True)
    (generated / "requirements.txt").write_text("pytest>=8.3.0\n", encoding="utf-8")
    (generated / "runner" / "cli.py").write_text("def main():\n    return 0\n", encoding="utf-8")
    (generated / "mappings" / "cases.yaml").write_text("cases: []\n", encoding="utf-8")
    return generated


def assert_health_shape(payload: dict) -> None:
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
        if key not in payload:
            raise AssertionError(f"missing health key: {key}")
    if payload["worker"]["ok"] is not True or payload["settings"]["ok"] is not True:
        raise AssertionError(f"worker/settings health failed: {payload}")


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=60)
    original_settings = None
    try:
        root = client.get("/")
        root.raise_for_status()
        if root.json().get("status") != "ok":
            print(f"Unexpected root response: {root.json()}", file=sys.stderr)
            return 1

        health = client.get("/health").json()
        assert_health_shape(health)
        print("health allOk", health["allOk"])

        original_settings = client.get("/settings").json()
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            webwright_root = temp / "webwright-root"
            output_root = temp / "webwright-runs"
            project_root = temp / "automation-projects"
            for path in [webwright_root, output_root, project_root]:
                path.mkdir(parents=True, exist_ok=True)

            updated = {
                **original_settings,
                "webwright": {
                    **original_settings["webwright"],
                    "executionMode": "native",
                    "root": str(webwright_root),
                    "python": sys.executable,
                    "baseConfig": "base.yaml",
                    "modelConfig": "model_openai.yaml",
                    "outputRoot": str(output_root),
                },
                "generator": {
                    **original_settings["generator"],
                    "projectRoot": str(project_root),
                    "defaultFramework": "playwright-pytest",
                    "defaultLanguage": "python",
                },
                "runner": {
                    **original_settings["runner"],
                    "defaultBrowser": "chromium",
                    "defaultEnv": "stg",
                    "headless": True,
                },
                "integrations": {
                    **original_settings["integrations"],
                    "testrailClone": {"baseUrl": "http://127.0.0.1:3000", "enabled": False},
                    "testrail": {"baseUrl": "http://127.0.0.1:3001", "enabled": False},
                    "googleSheets": {"enabled": False, "spreadsheetId": "smoke-sheet"},
                },
            }
            client.put("/settings", json=updated).raise_for_status()
            reloaded = client.get("/settings").json()
            if reloaded["webwright"]["root"] != str(webwright_root):
                print("settings did not persist webwright root", file=sys.stderr)
                return 1

            validation = client.post("/settings/validate").json()
            assert_health_shape(validation)
            if validation["webwrightRoot"]["ok"] is not True or validation["python"]["ok"] is not True:
                print(f"settings validation failed expected checks: {validation}", file=sys.stderr)
                return 1
            print("validate allOk", validation["allOk"])

            project = client.post("/projects", json={"name": "Smoke Project"}).json()
            generated = make_generated_project(temp)
            project_health = client.post(
                f"/projects/{project['id']}/health",
                params={"generated_path": str(generated)},
            ).json()
            if project_health.get("allOk") is not True:
                print(f"project health failed: {project_health}", file=sys.stderr)
                return 1
            missing_health = client.post(
                f"/projects/{project['id']}/health",
                params={"generated_path": str(temp / 'missing-generated')},
            ).json()
            if missing_health.get("allOk") is not False:
                print(f"missing project health should fail: {missing_health}", file=sys.stderr)
                return 1

        print("I-03 smoke E2E OK")
        return 0
    finally:
        if original_settings is not None:
            try:
                client.put("/settings", json=original_settings)
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
