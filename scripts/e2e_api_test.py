"""End-to-end API verification script."""
from __future__ import annotations

import shutil
import time
from pathlib import Path

import httpx

from e2e_worker_client import worker_client

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / ".data"
EXCEL = ROOT / "fixtures" / "sample_cases.xlsx"
BASE = "http://127.0.0.1:8765"


def main() -> None:
    client = worker_client(BASE, timeout=60)
    print("health", client.get("/health").json())

    proj = client.post("/projects", json={"name": "E2E Project"}).json()
    pid = proj["id"]
    print("project", pid)

    client.post(f"/projects/{pid}/cases/import/excel", json={"file_path": str(EXCEL)}).raise_for_status()
    cases = client.get(f"/projects/{pid}/cases").json()
    case_id = cases[0]["id"]
    print("imported", cases[0]["automation_key"])

    client.post(f"/projects/{pid}/webwright-runs", json={"caseIds": [case_id]}).raise_for_status()
    time.sleep(4)
    case = client.get(f"/projects/{pid}/cases/{case_id}").json()
    print("after webwright", case.get("status"))

    client.post(f"/projects/{pid}/generate", json={}).raise_for_status()
    print("generated")

    client.post(
        f"/projects/{pid}/executions",
        json={"env": "stg", "browser": "chromium", "target_type": "all"},
    ).raise_for_status()
    time.sleep(3)
    execs = client.get(f"/projects/{pid}/executions").json()
    print("executions", len(execs))
    if execs:
        detail = client.get(f"/projects/{pid}/executions/{execs[0]['id']}").json()
        summary = detail.get("summary") or {}
        print("summary", summary.get("summary") if isinstance(summary, dict) else summary)

    print("E2E OK")


if __name__ == "__main__":
    main()
