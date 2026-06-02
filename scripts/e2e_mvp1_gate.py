"""H-01 MVP 1 gate E2E against a live Worker on http://127.0.0.1:8765."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx

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

    client = httpx.Client(base_url=BASE, timeout=60)
    client.get("/health").raise_for_status()

    project = client.post("/projects", json={"name": "E2E MVP 1 Gate"}).json()
    project_id = project["id"]

    preview = client.post(f"/projects/{project_id}/cases/import/excel/preview", json={"file_path": str(EXCEL)}).json()
    print("preview rows", preview["totalRows"])

    client.post(f"/projects/{project_id}/cases/import/excel", json={"file_path": str(EXCEL)}).raise_for_status()
    case = client.get(f"/projects/{project_id}/cases").json()[0]
    case_id = case["id"]
    automation_key = case["automation_key"]
    print("case", automation_key)

    client.post(f"/projects/{project_id}/webwright-runs", json={"caseIds": [case_id]}).raise_for_status()
    webwright_run = wait_for_first(client, f"/projects/{project_id}/webwright-runs", {"completed", "failed", "cancelled"})
    if not webwright_run or webwright_run["status"] != "completed":
        print(f"Webwright run did not complete: {webwright_run}", file=sys.stderr)
        return 1

    mappings = client.get(f"/projects/{project_id}/cases/{case_id}/mappings").json()
    if not mappings:
        print("Missing mappings", file=sys.stderr)
        return 1
    reviewed = []
    for index, mapping in enumerate(mappings, start=1):
        reviewed.append({
            **mapping,
            "normalized_step_id": mapping.get("normalized_step_id") or f"flow_{index:03d}",
            "normalized_step_name": f"mvp1_step_{index}",
            "pom_method_name": f"perform_mvp1_step_{index}",
            "status": "mapped",
        })
    client.put(f"/projects/{project_id}/cases/{case_id}/mappings", json={"mappings": reviewed}).raise_for_status()

    generated = client.post(f"/projects/{project_id}/generate", json={"caseIds": [case_id]}).json()
    print("generated", generated["generatedProjectPath"])

    client.post(
        f"/projects/{project_id}/executions",
        json={
            "env": "stg",
            "browser": "chromium",
            "headed": False,
            "target_type": "case",
            "automation_key": automation_key,
            "result_target": "local",
        },
    ).raise_for_status()
    execution = wait_for_first(client, f"/projects/{project_id}/executions", {"completed", "failed", "cancelled"})
    if not execution or not execution.get("result_path"):
        print(f"Execution did not produce results: {execution}", file=sys.stderr)
        return 1
    detail = client.get(f"/projects/{project_id}/executions/{execution['id']}").json()
    if not any(result["automation_key"] == automation_key for result in detail["results"]):
        print("Missing traceable execution result row", file=sys.stderr)
        return 1

    print("execution", execution["status"], execution["run_id"])
    print("H-01 MVP 1 gate E2E OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
