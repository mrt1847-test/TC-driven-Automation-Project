"""E-06 Result Export E2E against a live Worker on http://127.0.0.1:8765."""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
EXCEL = ROOT / "fixtures" / "sample_cases.xlsx"
DATA = ROOT / ".data"
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
    DATA.mkdir(parents=True, exist_ok=True)
    export_source = DATA / f"e2e_export_cases_{int(time.time())}.xlsx"
    shutil.copy2(EXCEL, export_source)

    client = httpx.Client(base_url=BASE, timeout=60)
    client.get("/health").raise_for_status()

    project = client.post("/projects", json={"name": "E2E Result Export"}).json()
    project_id = project["id"]

    client.post(f"/projects/{project_id}/cases/import/excel", json={"file_path": str(export_source)}).raise_for_status()
    case = client.get(f"/projects/{project_id}/cases").json()[0]
    case_id = case["id"]
    automation_key = case["automation_key"]
    print("case", automation_key)

    client.post(f"/projects/{project_id}/webwright-runs", json={"caseIds": [case_id]}).raise_for_status()
    ww_run = wait_for_first(client, f"/projects/{project_id}/webwright-runs", {"completed", "failed", "cancelled"})
    if not ww_run or ww_run["status"] != "completed":
        print(f"Webwright run did not complete: {ww_run}", file=sys.stderr)
        return 1

    mappings = client.get(f"/projects/{project_id}/cases/{case_id}/mappings").json()
    reviewed = []
    for index, mapping in enumerate(mappings, start=1):
        reviewed.append({
            **mapping,
            "normalized_step_id": mapping.get("normalized_step_id") or f"flow_{index:03d}",
            "normalized_step_name": f"export_step_{index}",
            "pom_method_name": f"perform_export_step_{index}",
            "status": "mapped",
        })
    client.put(f"/projects/{project_id}/cases/{case_id}/mappings", json={"mappings": reviewed}).raise_for_status()
    client.post(f"/projects/{project_id}/generate", json={"caseIds": [case_id]}).raise_for_status()

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
    if not execution:
        print("No execution completed", file=sys.stderr)
        return 1

    preview = client.post(
        f"/projects/{project_id}/executions/{execution['id']}/export/excel",
        json={"preview": True},
    ).json()
    if not preview.get("updates"):
        print(f"No export preview updates: {preview}", file=sys.stderr)
        return 1

    exported = client.post(
        f"/projects/{project_id}/executions/{execution['id']}/export/excel",
        json={"preview": False},
    ).json()
    if exported.get("updated") != 1:
        print(f"Unexpected export response: {exported}", file=sys.stderr)
        return 1

    print("preview updates", len(preview["updates"]))
    print("exported", exported["updated"], "file", export_source)
    print("E-06 Result Export E2E OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
