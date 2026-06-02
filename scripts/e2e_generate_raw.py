"""E-02 Generate Raw E2E — run against a live Worker on http://127.0.0.1:8765."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
EXCEL = ROOT / "fixtures" / "sample_cases.xlsx"
BASE = "http://127.0.0.1:8765"


def main() -> int:
    if not EXCEL.exists():
        print(f"Missing fixture: {EXCEL}", file=sys.stderr)
        return 1

    client = httpx.Client(base_url=BASE, timeout=60)
    client.get("/health").raise_for_status()

    project = client.post("/projects", json={"name": "E2E Generate Raw"}).json()
    project_id = project["id"]

    client.post(
        f"/projects/{project_id}/cases/import/excel",
        json={"file_path": str(EXCEL)},
    ).raise_for_status()
    case = client.get(f"/projects/{project_id}/cases").json()[0]
    case_id = case["id"]
    print("case", case["automation_key"])

    queued = client.post(
        f"/projects/{project_id}/webwright-runs",
        json={"caseIds": [case_id]},
    ).json()
    job_id = queued["jobId"]
    print("queued", job_id)

    run = None
    for _ in range(40):
        runs = client.get(f"/projects/{project_id}/webwright-runs").json()
        run = next((item for item in runs if item.get("test_case_id") == case_id), None)
        if run and run.get("status") in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.25)
    if not run:
        print("No Webwright run found", file=sys.stderr)
        return 1

    print("run status", run["status"])
    assert run["status"] == "completed", run

    actions = client.get(f"/projects/{project_id}/cases/{case_id}/actions").json()
    mappings = client.get(f"/projects/{project_id}/cases/{case_id}/mappings").json()
    case_detail = client.get(f"/projects/{project_id}/cases/{case_id}").json()
    print("actions", len(actions), "mappings", len(mappings), "case status", case_detail.get("status"))
    assert actions and mappings and case_detail.get("status") == "webwright_completed"

    print("E-02 Generate Raw E2E OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
