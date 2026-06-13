"""E-04 Project Generation E2E against a live Worker on http://127.0.0.1:8765."""
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

    project = client.post("/projects", json={"name": "E2E Project Generation"}).json()
    project_id = project["id"]

    client.post(f"/projects/{project_id}/cases/import/excel", json={"file_path": str(EXCEL)}).raise_for_status()
    case = client.get(f"/projects/{project_id}/cases").json()[0]
    case_id = case["id"]
    automation_key = case["automation_key"]
    print("case", automation_key)

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

    mappings = client.get(f"/projects/{project_id}/cases/{case_id}/mappings").json()
    if not mappings:
        print("Missing mappings", file=sys.stderr)
        return 1

    reviewed = []
    for index, mapping in enumerate(mappings, start=1):
        reviewed.append({
            **mapping,
            "normalized_step_id": mapping.get("normalized_step_id") or f"flow_{index:03d}",
            "normalized_step_name": f"project_generation_step_{index}",
            "pom_method_name": f"perform_project_generation_step_{index}",
            "status": "mapped",
        })
    client.put(f"/projects/{project_id}/cases/{case_id}/mappings", json={"mappings": reviewed}).raise_for_status()

    generated = client.post(f"/projects/{project_id}/generate", json={"caseIds": [case_id]}).json()
    generated_path = Path(generated["generatedProjectPath"])
    if not generated_path.exists():
        print(f"Generated path missing: {generated_path}", file=sys.stderr)
        return 1

    files = {item["path"] for item in client.get(f"/projects/{project_id}/generated-files").json()}
    required = {
        "mappings/cases.yaml",
        "pages/generated_page.py",
        f"flows/{automation_key}_flow.py",
        f"tests/test_{automation_key}.py",
        "fixtures/browser_fixture.py",
        "runner/cli.py",
    }
    missing = sorted(required - files)
    if missing:
        print(f"Missing generated files: {missing}", file=sys.stderr)
        return 1

    page = client.get(
        f"/projects/{project_id}/generated-files/content",
        params={"path": "pages/generated_page.py"},
    ).json()["content"]
    assert "perform_project_generation_step_1" in page

    print("generated", generated_path)
    print("E-04 Project Generation E2E OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
