"""E-09 live Webwright runtime E2E against a live Worker on http://127.0.0.1:8765."""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

import httpx

from e2e_worker_client import worker_client

ROOT = Path(__file__).resolve().parents[1]
EXCEL = ROOT / "fixtures" / "sample_cases.xlsx"
BASE = "http://127.0.0.1:8765"


def _live_env_config(output_root: Path) -> dict | None:
    root = os.environ.get("TC_LIVE_WEBWRIGHT_ROOT", "").strip()
    if not root:
        return None
    python = (
        os.environ.get("TC_LIVE_WEBWRIGHT_PYTHON", "").strip()
        or os.environ.get("TC_STUDIO_PYTHON", "").strip()
        or sys.executable
    )
    runtime: dict[str, str] = {
        "mode": "custom",
        "python": python,
        "webwrightPython": python,
    }
    browsers_path = os.environ.get("TC_LIVE_PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if browsers_path:
        runtime["playwrightBrowsersPath"] = browsers_path
    webwright: dict[str, str] = {
        "executionMode": "native",
        "root": root,
        "python": python,
        "baseConfig": os.environ.get("TC_LIVE_WEBWRIGHT_BASE_CONFIG", "base.yaml"),
        "modelConfig": os.environ.get("TC_LIVE_WEBWRIGHT_MODEL_CONFIG", "model_openai.yaml"),
        "outputRoot": str(output_root),
    }
    model_name = os.environ.get("TC_LIVE_WEBWRIGHT_MODEL_NAME", "").strip()
    if model_name:
        webwright["modelName"] = model_name
    shell = os.environ.get("TC_LIVE_WEBWRIGHT_SHELL", "").strip()
    if shell:
        webwright["shell"] = shell

    return {
        "runtime": runtime,
        "webwright": webwright,
    }


def _wait_for_run(client: httpx.Client, project_id: str, case_id: str, timeout_s: float = 120.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        runs = client.get(f"/projects/{project_id}/webwright-runs").json()
        for run in runs:
            if run.get("test_case_id") == case_id and run.get("status") in {"completed", "failed", "cancelled"}:
                return run
        time.sleep(0.25)
    raise AssertionError("Timed out waiting for live Webwright run to finish")


def _assert_live_validation(validation: dict) -> None:
    for key in ["webwrightCli", "webwrightConfig", "webwrightShell", "mockMode"]:
        if key not in validation:
            raise AssertionError(f"settings validation missing {key}: {validation}")
    if validation["webwrightCli"].get("ok") is not True:
        raise AssertionError(f"webwrightCli is not ready: {validation}")
    if validation["webwrightConfig"].get("ok") is not True:
        raise AssertionError(f"webwrightConfig is not ready: {validation}")
    if validation["webwrightShell"].get("ok") is not True:
        raise AssertionError(f"webwrightShell is not ready: {validation}")
    if validation["mockMode"].get("enabled") is not False:
        raise AssertionError(f"mock mode must be disabled for E-09: {validation}")


def main() -> int:
    if not EXCEL.exists():
        print(f"Missing fixture: {EXCEL}", file=sys.stderr)
        return 1

    client = worker_client(BASE, timeout=60)
    original_settings = None
    try:
        client.get("/health").raise_for_status()
        original_settings = client.get("/settings").json()

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "live-webwright-runs"
            env_config = _live_env_config(output_root)
            if env_config is not None:
                updated = {
                    **original_settings,
                    "runtime": {**original_settings.get("runtime", {}), **env_config["runtime"]},
                    "webwright": {**original_settings.get("webwright", {}), **env_config["webwright"]},
                }
                client.put("/settings", json=updated).raise_for_status()

            validation = client.post("/settings/validate").json()
            _assert_live_validation(validation)

            project = client.post("/projects", json={"name": "E2E Live Webwright Runtime"}).json()
            project_id = project["id"]
            client.post(
                f"/projects/{project_id}/cases/import/excel",
                json={"file_path": str(EXCEL)},
            ).raise_for_status()
            case = client.get(f"/projects/{project_id}/cases").json()[0]
            case_id = case["id"]

            queued = client.post(
                f"/projects/{project_id}/webwright-runs",
                json={"caseIds": [case_id]},
            ).json()
            print("queued", queued["jobId"], "case", case["automation_key"])

            run = _wait_for_run(client, project_id, case_id)
            print("run status", run["status"])
            if run["status"] != "completed":
                raise AssertionError(run)

            final_script = Path(run["final_script_path"])
            output_path = Path(run["output_path"])
            if not final_script.exists():
                raise AssertionError(f"missing final script: {final_script}")
            stdout = output_path / "stdout.log"
            if not stdout.exists():
                raise AssertionError(f"missing stdout log: {stdout}")
            if "[mock]" in stdout.read_text(encoding="utf-8").lower():
                raise AssertionError("live run stdout contains mock marker")

            actions = client.get(f"/projects/{project_id}/cases/{case_id}/actions").json()
            if not actions:
                raise AssertionError("live Webwright run did not index RawAction rows")

        print("E-09 live Webwright runtime E2E OK")
        return 0
    finally:
        if original_settings is not None:
            try:
                client.put("/settings", json=original_settings)
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
