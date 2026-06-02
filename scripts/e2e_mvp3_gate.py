"""H-03 MVP 3 gate E2E against a live Worker on http://127.0.0.1:8765."""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import time
from urllib.parse import parse_qs, urlparse

import httpx

BASE = "http://127.0.0.1:8765"

CASES = [
    {
        "caseId": "CLONE-100",
        "title": "Clone login succeeds",
        "automationKey": "mvp3_clone_login",
        "expectedResult": "User is logged in",
        "steps": [{"action": "Open login page", "expected": "Login page is visible"}],
    },
    {
        "caseId": "CLONE-200",
        "title": "Clone checkout succeeds",
        "automationKey": "mvp3_clone_checkout",
        "expectedResult": "Order is created",
        "steps": [{"action": "Open checkout page", "expected": "Checkout page is visible"}],
    },
]

POSTS: list[dict] = []


def start_clone_server() -> tuple[ThreadingHTTPServer, str]:
    class Handler(BaseHTTPRequestHandler):
        def json_response(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != "/api/automation/cases":
                self.json_response(404, {"error": "not found"})
                return
            query = parse_qs(parsed.query)
            self.json_response(200, {"projectId": query.get("projectId", [""])[0], "cases": CASES})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != "/api/automation/results/bulk":
                self.json_response(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            POSTS.append(payload)
            self.json_response(
                200,
                {
                    "ok": True,
                    "received": len(payload.get("results", [])),
                    "sourceCaseIds": [item.get("sourceCaseId") for item in payload.get("results", [])],
                },
            )

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}"


def wait_for_count(client: httpx.Client, path: str, expected_count: int, timeout_s: float = 20.0) -> list[dict] | None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        items = client.get(path).json()
        terminal = [item for item in items if item.get("status") in {"completed", "failed", "cancelled"}]
        if len(terminal) >= expected_count:
            return terminal
        time.sleep(0.25)
    return None


def wait_for_first(client: httpx.Client, path: str, timeout_s: float = 20.0) -> dict | None:
    items = wait_for_count(client, path, 1, timeout_s)
    return items[0] if items else None


def save_mappings(client: httpx.Client, project_id: str, case_id: str) -> None:
    mappings = client.get(f"/projects/{project_id}/cases/{case_id}/mappings").json()
    reviewed = []
    for index, mapping in enumerate(mappings, start=1):
        reviewed.append({
            **mapping,
            "normalized_step_id": mapping.get("normalized_step_id") or f"flow_{index:03d}",
            "normalized_step_name": f"mvp3_clone_step_{index}",
            "pom_method_name": f"perform_mvp3_clone_step_{index}",
            "status": "mapped",
        })
    client.put(f"/projects/{project_id}/cases/{case_id}/mappings", json={"mappings": reviewed}).raise_for_status()


def write_fake_pytest_fixture(client: httpx.Client, project_id: str) -> None:
    content = "\n".join([
        "import pytest",
        "",
        "def pytest_addoption(parser):",
        "    parser.addoption('--browser', action='store', default='chromium')",
        "    parser.addoption('--headed', action='store', default='false')",
        "",
        "class FakeLocator:",
        "    def click(self):",
        "        return None",
        "    def fill(self, value):",
        "        return None",
        "",
        "class FakePage:",
        "    def goto(self, url):",
        "        return None",
        "    def locator(self, selector):",
        "        return FakeLocator()",
        "    def get_by_role(self, *args, **kwargs):",
        "        return FakeLocator()",
        "",
        "@pytest.fixture",
        "def page():",
        "    return FakePage()",
        "",
    ])
    client.put(
        f"/projects/{project_id}/generated-files/content",
        json={"path": "conftest.py", "content": content},
    ).raise_for_status()


def main() -> int:
    server, clone_url = start_clone_server()
    client = httpx.Client(base_url=BASE, timeout=60)
    original_settings = None
    try:
        client.get("/health").raise_for_status()
        original_settings = client.get("/settings").json()
        settings = json.loads(json.dumps(original_settings))
        settings["integrations"]["testrailClone"] = {"baseUrl": clone_url, "enabled": True}
        settings["webwright"]["root"] = ""
        client.put("/settings", json=settings).raise_for_status()

        project = client.post("/projects", json={"name": "E2E MVP 3 Gate"}).json()
        project_id = project["id"]

        preview = client.post(
            f"/projects/{project_id}/cases/import/testrail-clone/preview",
            json={"project_id": "clone-project", "suite_id": "suite-a"},
        ).json()
        if [case["source_id"] for case in preview] != ["CLONE-100", "CLONE-200"]:
            print(f"Unexpected preview cases: {preview}", file=sys.stderr)
            return 1

        cases = client.post(
            f"/projects/{project_id}/cases/import/testrail-clone",
            json={"project_id": "clone-project", "suite_id": "suite-a"},
        ).json()
        case_ids = [case["id"] for case in cases]
        print("imported", [case["automation_key"] for case in cases])

        client.post(f"/projects/{project_id}/webwright-runs", json={"caseIds": case_ids}).raise_for_status()
        runs = wait_for_count(client, f"/projects/{project_id}/webwright-runs", 2)
        if not runs:
            print("Webwright mock runs did not complete", file=sys.stderr)
            return 1

        for case_id in case_ids:
            save_mappings(client, project_id, case_id)

        generated = client.post(f"/projects/{project_id}/generate", json={"caseIds": case_ids}).json()
        if not Path(generated["generatedProjectPath"]).exists():
            print("Generated path missing", file=sys.stderr)
            return 1
        write_fake_pytest_fixture(client, project_id)

        client.post(
            f"/projects/{project_id}/executions",
            json={
                "env": "stg",
                "browser": "chromium",
                "headed": False,
                "target_type": "all",
                "result_target": "testrail-clone",
            },
        ).raise_for_status()
        execution = wait_for_first(client, f"/projects/{project_id}/executions")
        if not execution or not execution.get("result_path"):
            print(f"Execution did not produce results: {execution}", file=sys.stderr)
            return 1

        preview_export = client.post(
            f"/projects/{project_id}/executions/{execution['id']}/export/testrail-clone",
            json={"preview": True},
        ).json()
        source_ids = {item["sourceCaseId"] for item in preview_export["payload"]["results"]}
        if source_ids != {"CLONE-100", "CLONE-200"}:
            print(f"Export preview lost source IDs: {preview_export}", file=sys.stderr)
            return 1

        export = client.post(
            f"/projects/{project_id}/executions/{execution['id']}/export/testrail-clone",
            json={"preview": False},
        ).json()
        if export.get("received") != 2 or len(POSTS) != 1:
            print(f"Bulk upload failed: {export}, posts={POSTS}", file=sys.stderr)
            return 1

        print("bulk upload source ids", sorted(source_ids))
        print("H-03 MVP 3 gate E2E OK")
        return 0
    finally:
        if original_settings is not None:
            try:
                client.put("/settings", json=original_settings)
            except Exception:
                pass
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
