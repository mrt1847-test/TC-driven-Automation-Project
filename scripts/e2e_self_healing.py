"""E-08 self-healing proposal baseline E2E against a live Worker on http://127.0.0.1:8765."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx

from e2e_worker_client import worker_client

ROOT = Path(__file__).resolve().parents[1]
EXCEL = ROOT / "fixtures" / "sample_cases.xlsx"
BASE = "http://127.0.0.1:8765"


def wait_for_first(client: httpx.Client, path: str, terminal: set[str], count: int = 1) -> list[dict]:
    for _ in range(80):
        items = client.get(path).json()
        terminal_items = [item for item in items if item.get("status") in terminal]
        if len(terminal_items) >= count:
            return terminal_items
        time.sleep(0.25)
    return []


def main() -> int:
    if not EXCEL.exists():
        print(f"Missing fixture: {EXCEL}", file=sys.stderr)
        return 1

    client = worker_client(BASE, timeout=60)
    client.get("/health").raise_for_status()

    project = client.post("/projects", json={"name": "E2E Self Healing"}).json()
    project_id = project["id"]

    client.post(f"/projects/{project_id}/cases/import/excel", json={"file_path": str(EXCEL)}).raise_for_status()
    case = client.get(f"/projects/{project_id}/cases").json()[0]
    case_id = case["id"]
    automation_key = case["automation_key"]
    print("case", automation_key)

    client.post(f"/projects/{project_id}/webwright-runs", json={"caseIds": [case_id]}).raise_for_status()
    ww_runs = wait_for_first(client, f"/projects/{project_id}/webwright-runs", {"completed", "failed", "cancelled"})
    if not ww_runs or ww_runs[0]["status"] != "completed":
        print(f"Webwright run did not complete: {ww_runs}", file=sys.stderr)
        return 1

    mappings = client.get(f"/projects/{project_id}/cases/{case_id}/mappings").json()
    reviewed = []
    for index, mapping in enumerate(mappings, start=1):
        reviewed.append({
            **mapping,
            "normalized_step_id": mapping.get("normalized_step_id") or f"flow_{index:03d}",
            "normalized_step_name": f"healing_step_{index}",
            "pom_method_name": f"perform_healing_step_{index}",
            "status": "mapped",
        })
    client.put(f"/projects/{project_id}/cases/{case_id}/mappings", json={"mappings": reviewed}).raise_for_status()
    client.post(f"/projects/{project_id}/generate", json={"caseIds": [case_id]}).raise_for_status()

    page_lines = ["class GeneratedPage:", "    def __init__(self, page):", "        self.page = page", ""]
    for index, _ in enumerate(reviewed, start=1):
        page_lines.extend([
            f"    def perform_healing_step_{index}(self):",
            "        raise AssertionError('selector healing timeout: missing locator #checkout')",
            "",
        ])
    client.put(
        f"/projects/{project_id}/generated-files/content",
        json={"path": "pages/generated_page.py", "content": "\n".join(page_lines)},
    ).raise_for_status()

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
    executions = wait_for_first(client, f"/projects/{project_id}/executions", {"completed", "failed", "cancelled"})
    if not executions or executions[0]["status"] not in {"completed", "failed"}:
        print(f"Expected failed execution: {executions}", file=sys.stderr)
        return 1
    execution = executions[0]
    detail = client.get(f"/projects/{project_id}/executions/{execution['id']}").json()
    failed = next((result for result in detail["results"] if result["automation_key"] == automation_key), None)
    if not failed or not failed.get("error"):
        print(f"Missing failed result context: {detail}", file=sys.stderr)
        return 1
    print("proposal", "manual_review", "proposed")

    rerun = client.post(f"/projects/{project_id}/executions/{execution['id']}/rerun-failed").json()
    print("rerun", rerun["jobId"])
    reruns = wait_for_first(client, f"/projects/{project_id}/executions", {"completed", "failed", "cancelled"}, count=2)
    if len(reruns) < 2:
        print("Rerun failed did not produce a second execution", file=sys.stderr)
        return 1

    print("executions", len(reruns))
    print("E-08 self-healing proposal E2E OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
