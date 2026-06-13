"""E-07 reverse handoff rerun E2E against a live Worker on http://127.0.0.1:8765."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx

from e2e_worker_client import worker_client

ROOT = Path(__file__).resolve().parents[1]
EXCEL = ROOT / "fixtures" / "sample_cases.xlsx"
BASE = "http://127.0.0.1:8765"


def runs_for_case(client: httpx.Client, project_id: str, case_id: str) -> list[dict]:
    runs = client.get(f"/projects/{project_id}/webwright-runs").json()
    return [run for run in runs if run.get("test_case_id") == case_id]


def wait_for_run_count(client: httpx.Client, project_id: str, case_id: str, expected_count: int) -> list[dict]:
    for _ in range(80):
        runs = runs_for_case(client, project_id, case_id)
        terminal = [run for run in runs if run.get("status") in {"completed", "failed", "cancelled"}]
        if len(terminal) >= expected_count:
            return terminal
        time.sleep(0.25)
    return []


def main() -> int:
    if not EXCEL.exists():
        print(f"Missing fixture: {EXCEL}", file=sys.stderr)
        return 1

    client = worker_client(BASE, timeout=60)
    client.get("/health").raise_for_status()

    project = client.post("/projects", json={"name": "E2E Reverse Handoff"}).json()
    project_id = project["id"]

    client.post(f"/projects/{project_id}/cases/import/excel", json={"file_path": str(EXCEL)}).raise_for_status()
    case = client.get(f"/projects/{project_id}/cases").json()[0]
    case_id = case["id"]
    automation_key = case["automation_key"]
    print("case", automation_key)

    client.post(f"/projects/{project_id}/webwright-runs", json={"caseIds": [case_id]}).raise_for_status()
    first_runs = wait_for_run_count(client, project_id, case_id, 1)
    if not first_runs or first_runs[0]["status"] != "completed":
        print(f"Initial Webwright run failed: {first_runs}", file=sys.stderr)
        return 1
    first_run = first_runs[0]

    mappings = client.get(f"/projects/{project_id}/cases/{case_id}/mappings").json()
    actions = client.get(f"/projects/{project_id}/cases/{case_id}/actions").json()
    if not mappings or not actions:
        print("Missing initial mappings/actions", file=sys.stderr)
        return 1

    gap_payload = {
        "mappings": [{**mapping, "action_ids": [], "status": "unmapped"} for mapping in mappings]
    }
    client.put(f"/projects/{project_id}/cases/{case_id}/mappings", json=gap_payload).raise_for_status()
    print("mapping gap", client.get(f"/projects/{project_id}/cases/{case_id}").json()["status"])

    retry = client.post(f"/projects/{project_id}/webwright-runs/{first_run['id']}/retry").json()
    print("retry", retry["jobId"])
    runs = wait_for_run_count(client, project_id, case_id, 2)
    if len({run["id"] for run in runs}) < 2:
        print(f"Retry did not create a second run: {runs}", file=sys.stderr)
        return 1

    refreshed_actions = client.get(f"/projects/{project_id}/cases/{case_id}/actions").json()
    refreshed_mappings = client.get(f"/projects/{project_id}/cases/{case_id}/mappings").json()
    if not refreshed_actions or not refreshed_mappings or not refreshed_mappings[0].get("action_ids"):
        print("Refreshed Mapping view missing actions/mappings", file=sys.stderr)
        return 1

    print("runs", len(runs), "actions", len(refreshed_actions), "mappings", len(refreshed_mappings))
    print("E-07 reverse handoff rerun E2E OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
