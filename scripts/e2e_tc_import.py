"""E-01 TC Import E2E — run against a live Worker on http://127.0.0.1:8765."""
from __future__ import annotations

import sys
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
    health = client.get("/health")
    health.raise_for_status()
    print("health", health.json())

    project = client.post("/projects", json={"name": "E2E TC Import"}).json()
    project_id = project["id"]
    print("project", project_id)

    preview = client.post(
        f"/projects/{project_id}/cases/import/excel/preview",
        json={"file_path": str(EXCEL)},
    )
    preview.raise_for_status()
    preview_body = preview.json()
    assert preview_body["totalRows"] >= 1, "Excel preview returned no rows"
    print("excel preview rows", preview_body["totalRows"])

    imported = client.post(
        f"/projects/{project_id}/cases/import/excel",
        json={"file_path": str(EXCEL)},
    )
    imported.raise_for_status()
    cases = imported.json()
    assert cases and cases[0].get("automation_key"), "Excel import missing automation_key"
    print("excel imported", cases[0]["automation_key"])

    listed = client.get(f"/projects/{project_id}/cases").json()
    assert any(item.get("automation_key") == cases[0]["automation_key"] for item in listed), "TC list handoff failed"
    print("tc list count", len(listed))

    connector = client.post(
        f"/projects/{project_id}/cases/import/testrail",
        json={"project_id": 12},
    )
    connector.raise_for_status()
    connector_cases = connector.json()
    assert connector_cases and connector_cases[0].get("source_type") == "testrail", "TestRail connector path failed"
    print("testrail connector preview", connector_cases[0]["automation_key"])

    print("E-01 TC Import E2E OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
