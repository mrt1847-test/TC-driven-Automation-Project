"""E-03 Automation IDE structure E2E against a live Worker on http://127.0.0.1:8765."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx

from e2e_worker_client import worker_client

ROOT = Path(__file__).resolve().parents[1]
EXCEL = ROOT / "fixtures" / "sample_cases.xlsx"
BASE = "http://127.0.0.1:8765"


def main() -> int:
    if not EXCEL.exists():
        print(f"Missing fixture: {EXCEL}", file=sys.stderr)
        return 1

    client = worker_client(BASE, timeout=60)
    client.get("/health").raise_for_status()

    project = client.post("/projects", json={"name": "E2E Automation IDE Structure"}).json()
    project_id = project["id"]

    client.post(f"/projects/{project_id}/cases/import/excel", json={"file_path": str(EXCEL)}).raise_for_status()
    case = client.get(f"/projects/{project_id}/cases").json()[0]
    case_id = case["id"]
    print("case", case["automation_key"])

    queued = client.post(f"/projects/{project_id}/webwright-runs", json={"caseIds": [case_id]}).json()
    print("queued", queued["jobId"])

    run = None
    for _ in range(40):
        runs = client.get(f"/projects/{project_id}/webwright-runs").json()
        run = next((item for item in runs if item.get("test_case_id") == case_id), None)
        if run and run.get("status") in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.25)
    if not run or run["status"] != "completed":
        print(f"Webwright run did not complete: {run}", file=sys.stderr)
        return 1

    actions = client.get(f"/projects/{project_id}/cases/{case_id}/actions").json()
    mappings = client.get(f"/projects/{project_id}/cases/{case_id}/mappings").json()
    if not actions or not mappings:
        print("Missing actions or mappings", file=sys.stderr)
        return 1

    edited_mappings = []
    for index, mapping in enumerate(mappings, start=1):
        edited_mappings.append({
            **mapping,
            "normalized_step_id": mapping.get("normalized_step_id") or f"flow_{index:03d}",
            "normalized_step_name": f"reviewed_step_{index}",
            "pom_method_name": f"perform_reviewed_step_{index}",
            "status": "mapped",
        })

    edited_actions = [{**actions[0], "target": "Automation IDE reviewed target"}]
    client.put(
        f"/projects/{project_id}/cases/{case_id}/mappings",
        json={"mappings": edited_mappings, "actions": edited_actions},
    ).raise_for_status()

    reloaded = client.get(f"/projects/{project_id}/cases/{case_id}/mappings").json()
    assert reloaded[0]["normalized_step_name"] == "reviewed_step_1"
    assert reloaded[0]["pom_method_name"] == "perform_reviewed_step_1"
    print("mappings", len(reloaded), "first", reloaded[0]["normalized_step_name"], reloaded[0]["pom_method_name"])
    print("E-03 Automation IDE structure E2E OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
