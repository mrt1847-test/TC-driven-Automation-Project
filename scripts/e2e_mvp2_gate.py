"""H-02 MVP 2 gate E2E against a live Worker on http://127.0.0.1:8765."""
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


def read_file(client: httpx.Client, project_id: str, path: str) -> str:
    return client.get(f"/projects/{project_id}/generated-files/content", params={"path": path}).json()["content"]


def write_file(client: httpx.Client, project_id: str, path: str, content: str) -> None:
    client.put(f"/projects/{project_id}/generated-files/content", json={"path": path, "content": content}).raise_for_status()


def save_mappings(client: httpx.Client, project_id: str, case_id: str, prefix: str) -> list[dict]:
    mappings = client.get(f"/projects/{project_id}/cases/{case_id}/mappings").json()
    reviewed = []
    for index, mapping in enumerate(mappings, start=1):
        reviewed.append({
            **mapping,
            "normalized_step_id": mapping.get("normalized_step_id") or f"flow_{index:03d}",
            "normalized_step_name": f"{prefix}_step_{index}",
            "pom_method_name": f"perform_{prefix}_step_{index}",
            "status": "mapped",
        })
    client.put(f"/projects/{project_id}/cases/{case_id}/mappings", json={"mappings": reviewed}).raise_for_status()
    return reviewed


def main() -> int:
    if not EXCEL.exists():
        print(f"Missing fixture: {EXCEL}", file=sys.stderr)
        return 1

    client = worker_client(BASE, timeout=60)
    client.get("/health").raise_for_status()

    project = client.post("/projects", json={"name": "E2E MVP 2 Gate"}).json()
    project_id = project["id"]

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

    save_mappings(client, project_id, case_id, "mvp2")
    generated = client.post(f"/projects/{project_id}/generate", json={"caseIds": [case_id]}).json()
    print("generated", generated["generatedProjectPath"])

    page_path = "pages/generated_page.py"
    page_content = read_file(client, project_id, page_path)
    marker = f"# mvp2 manual edit for {automation_key}"
    write_file(client, project_id, page_path, f"{page_content.rstrip()}\n{marker}\n")
    if marker not in read_file(client, project_id, page_path):
        print("IDE save did not persist", file=sys.stderr)
        return 1

    if not client.get(f"/projects/{project_id}/search", params={"q": automation_key}).json():
        print("Search did not return TC context", file=sys.stderr)
        return 1

    regenerated_mappings = save_mappings(client, project_id, case_id, "mvp2_regenerated")
    client.post(f"/projects/{project_id}/generate", json={"caseIds": [case_id]}).raise_for_status()
    regenerated_page = read_file(client, project_id, page_path)
    if "perform_mvp2_regenerated_step_1" not in regenerated_page or marker in regenerated_page:
        print("Regeneration baseline did not refresh generated output", file=sys.stderr)
        return 1

    failure_message = f"mvp2 debug failure for {automation_key}"
    failure_page = ["class GeneratedPage:", "    def __init__(self, page):", "        self.page = page", ""]
    for mapping in regenerated_mappings:
        failure_page.extend([
            f"    def {mapping['pom_method_name']}(self):",
            f"        raise AssertionError({failure_message!r})",
            "",
        ])
    write_file(client, project_id, page_path, "\n".join(failure_page))

    module_key = automation_key.lower().replace("-", "_").replace(" ", "_")
    flow_class = "".join(part.capitalize() for part in automation_key.split("_")) + "Flow"
    write_file(
        client,
        project_id,
        f"tests/test_{module_key}.py",
        "\n".join([
            f"from flows.{module_key}_flow import {flow_class}",
            "",
            "class FakePage:",
            "    pass",
            "",
            f"def test_{module_key}():",
            f"    flow = {flow_class}(FakePage())",
            "    flow.execute()",
            "",
        ]),
    )
    write_file(
        client,
        project_id,
        "conftest.py",
        "\n".join([
            "def pytest_addoption(parser):",
            "    parser.addoption('--browser', action='store', default='chromium')",
            "    parser.addoption('--headed', action='store', default='false')",
            "",
        ]),
    )

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
    result = next((item for item in detail["results"] if item["automation_key"] == automation_key), None)
    if not result or result["status"] != "failed" or failure_message not in (result.get("error") or ""):
        print(f"Missing traceable debug failure: {result}", file=sys.stderr)
        return 1

    print("diagnosis", {"automation_key": automation_key, "kind": "generated_step_failure", "status": "proposed"})
    print("H-02 MVP 2 gate E2E OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
