"""E-05 Automation IDE runner E2E against a live Worker on http://127.0.0.1:8765."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx

from e2e_worker_client import worker_client

ROOT = Path(__file__).resolve().parents[1]
EXCEL = ROOT / "fixtures" / "sample_cases.xlsx"
BASE = "http://127.0.0.1:8765"


def wait_for_first(client: httpx.Client, path: str, terminal: set[str], timeout_s: float = 20.0) -> dict | None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        items = client.get(path).json()
        for item in items:
            if item.get("status") in terminal:
                return item
        time.sleep(0.25)
    return None


def main() -> int:
    if not EXCEL.exists():
        print(f"Missing fixture: {EXCEL}", file=sys.stderr)
        return 1

    client = worker_client(BASE, timeout=60)
    client.get("/health").raise_for_status()

    project = client.post("/projects", json={"name": "E2E Automation IDE Runner"}).json()
    project_id = project["id"]

    client.post(f"/projects/{project_id}/cases/import/excel", json={"file_path": str(EXCEL)}).raise_for_status()
    case = client.get(f"/projects/{project_id}/cases").json()[0]
    case_id = case["id"]
    automation_key = case["automation_key"]
    print("case", automation_key)

    client.post(f"/projects/{project_id}/webwright-runs", json={"caseIds": [case_id]}).raise_for_status()
    ww_run = wait_for_first(
        client,
        f"/projects/{project_id}/webwright-runs",
        {"completed", "failed", "cancelled"},
    )
    if not ww_run or ww_run["status"] != "completed":
        print(f"Webwright run did not complete: {ww_run}", file=sys.stderr)
        return 1

    mappings = client.get(f"/projects/{project_id}/cases/{case_id}/mappings").json()
    reviewed = []
    for index, mapping in enumerate(mappings, start=1):
        reviewed.append({
            **mapping,
            "normalized_step_id": mapping.get("normalized_step_id") or f"flow_{index:03d}",
            "normalized_step_name": f"runner_step_{index}",
            "pom_method_name": f"perform_runner_step_{index}",
            "status": "mapped",
        })
    client.put(f"/projects/{project_id}/cases/{case_id}/mappings", json={"mappings": reviewed}).raise_for_status()

    generated = client.post(f"/projects/{project_id}/generate", json={"caseIds": [case_id]}).json()
    print("generated", generated["generatedProjectPath"])

    queued = client.post(
        f"/projects/{project_id}/executions",
        json={
            "env": "stg",
            "browser": "chromium",
            "headed": False,
            "target_type": "case",
            "automation_key": automation_key,
            "result_target": "local",
        },
    ).json()
    print("queued", queued["jobId"])

    execution = wait_for_first(
        client,
        f"/projects/{project_id}/executions",
        {"completed", "failed", "cancelled"},
    )
    if not execution:
        print("No execution completed", file=sys.stderr)
        return 1

    detail = client.get(f"/projects/{project_id}/executions/{execution['id']}").json()
    if not detail.get("results"):
        print("Execution produced no result rows", file=sys.stderr)
        return 1
    if not execution.get("result_path") or not Path(execution["result_path"]).exists():
        print(f"Missing result artifact: {execution.get('result_path')}", file=sys.stderr)
        return 1

    print("execution", execution["status"], execution["run_id"])
    print("results", len(detail["results"]), "summary", detail["summary"]["summary"])
    print("E-05 Automation IDE runner E2E OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
