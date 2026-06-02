"""H-03: MVP 3 gate - testrail-clone import to result bulk upload."""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import time
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from worker.models.db import ExportLog


CLONE_CASES = [
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


class _CloneState:
    posts: list[dict] = []
    get_queries: list[dict] = []


def _start_clone_server() -> tuple[ThreadingHTTPServer, str]:
    class Handler(BaseHTTPRequestHandler):
        def _json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != "/api/automation/cases":
                self._json(404, {"error": "not found"})
                return
            _CloneState.get_queries.append(parse_qs(parsed.query))
            self._json(200, {"cases": CLONE_CASES})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != "/api/automation/results/bulk":
                self._json(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            _CloneState.posts.append(payload)
            self._json(
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


@pytest.fixture()
def clone_server(client: TestClient):
    _CloneState.posts = []
    _CloneState.get_queries = []
    server, base_url = _start_clone_server()

    settings = client.get("/settings").json()
    settings["integrations"]["testrailClone"] = {"baseUrl": base_url, "enabled": True}
    settings["webwright"]["root"] = ""
    response = client.put("/settings", json=settings)
    assert response.status_code == 200

    try:
        yield base_url
    finally:
        server.shutdown()
        server.server_close()


def _wait_for_runs(client: TestClient, project_id: str, expected_count: int, timeout_s: float = 5.0) -> list[dict]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        runs = client.get(f"/projects/{project_id}/webwright-runs").json()
        terminal = [run for run in runs if run.get("status") in {"completed", "failed", "cancelled"}]
        if len(terminal) >= expected_count:
            return terminal
        time.sleep(0.05)
    pytest.fail(f"Timed out waiting for {expected_count} Webwright runs")


def _wait_for_execution(client: TestClient, project_id: str, timeout_s: float = 8.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        executions = client.get(f"/projects/{project_id}/executions").json()
        for execution in executions:
            if execution.get("status") in {"completed", "failed", "cancelled"}:
                return execution
        time.sleep(0.05)
    pytest.fail("Timed out waiting for execution to finish")


def _save_mvp3_mappings(client: TestClient, project_id: str, case_id: str) -> None:
    mappings = client.get(f"/projects/{project_id}/cases/{case_id}/mappings").json()
    assert mappings
    reviewed = []
    for index, mapping in enumerate(mappings, start=1):
        reviewed.append({
            **mapping,
            "normalized_step_id": mapping.get("normalized_step_id") or f"flow_{index:03d}",
            "normalized_step_name": f"mvp3_clone_step_{index}",
            "pom_method_name": f"perform_mvp3_clone_step_{index}",
            "status": "mapped",
        })
    save = client.put(f"/projects/{project_id}/cases/{case_id}/mappings", json={"mappings": reviewed})
    assert save.status_code == 200


def _write_fake_pytest_fixture(client: TestClient, project_id: str) -> None:
    content = "\n".join([
        "import pytest",
        "",
        "",
        "def pytest_addoption(parser):",
        "    parser.addoption('--browser', action='store', default='chromium')",
        "    parser.addoption('--headed', action='store', default='false')",
        "",
        "",
        "class FakeLocator:",
        "    def click(self):",
        "        return None",
        "    def fill(self, value):",
        "        return None",
        "",
        "",
        "class FakePage:",
        "    def goto(self, url):",
        "        return None",
        "    def locator(self, selector):",
        "        return FakeLocator()",
        "    def get_by_role(self, *args, **kwargs):",
        "        return FakeLocator()",
        "",
        "",
        "@pytest.fixture",
        "def page():",
        "    return FakePage()",
        "",
    ])
    response = client.put(
        f"/projects/{project_id}/generated-files/content",
        json={"path": "conftest.py", "content": content},
    )
    assert response.status_code == 200


def test_mvp3_testrail_clone_import_to_bulk_upload_gate(
    client: TestClient,
    project_id: str,
    clone_server: str,
) -> None:
    preview = client.post(
        f"/projects/{project_id}/cases/import/testrail-clone/preview",
        json={"project_id": "clone-project", "suite_id": "suite-a"},
    )
    assert preview.status_code == 200
    preview_cases = preview.json()
    assert [case["source_id"] for case in preview_cases] == ["CLONE-100", "CLONE-200"]
    assert all(case["source_type"] == "testrail-clone" for case in preview_cases)
    assert _CloneState.get_queries[-1]["projectId"] == ["clone-project"]

    imported = client.post(
        f"/projects/{project_id}/cases/import/testrail-clone",
        json={"project_id": "clone-project", "suite_id": "suite-a"},
    )
    assert imported.status_code == 200
    cases = imported.json()
    case_ids = [case["id"] for case in cases]
    automation_keys = [case["automation_key"] for case in cases]
    assert automation_keys == ["mvp3_clone_login", "mvp3_clone_checkout"]

    listed = client.get(f"/projects/{project_id}/cases").json()
    assert {case["source_case_id"] for case in listed} >= {"CLONE-100", "CLONE-200"}

    queued = client.post(f"/projects/{project_id}/webwright-runs", json={"caseIds": case_ids})
    assert queued.status_code == 200
    runs = _wait_for_runs(client, project_id, 2)
    assert {run["automation_key"] for run in runs} == set(automation_keys)

    for case_id in case_ids:
        _save_mvp3_mappings(client, project_id, case_id)

    generated = client.post(f"/projects/{project_id}/generate", json={"caseIds": case_ids})
    assert generated.status_code == 200
    generated_path = Path(generated.json()["generatedProjectPath"])
    assert generated_path.exists()
    _write_fake_pytest_fixture(client, project_id)

    execution_queue = client.post(
        f"/projects/{project_id}/executions",
        json={
            "env": "stg",
            "browser": "chromium",
            "headed": False,
            "target_type": "all",
            "result_target": "testrail-clone",
        },
    )
    assert execution_queue.status_code == 200
    execution = _wait_for_execution(client, project_id)
    assert execution["result_path"]

    detail = client.get(f"/projects/{project_id}/executions/{execution['id']}").json()
    results_by_key = {result["automation_key"]: result for result in detail["results"]}
    assert set(results_by_key) == set(automation_keys)
    assert results_by_key["mvp3_clone_login"]["source_case_id"] == "CLONE-100"
    assert results_by_key["mvp3_clone_checkout"]["source_case_id"] == "CLONE-200"

    preview_export = client.post(
        f"/projects/{project_id}/executions/{execution['id']}/export/testrail-clone",
        json={"preview": True},
    )
    assert preview_export.status_code == 200
    preview_payload = preview_export.json()["payload"]
    assert preview_payload["runId"] == execution["run_id"]
    assert {item["sourceCaseId"] for item in preview_payload["results"]} == {"CLONE-100", "CLONE-200"}
    assert all(item["sourceType"] == "testrail-clone" for item in preview_payload["results"])

    export = client.post(
        f"/projects/{project_id}/executions/{execution['id']}/export/testrail-clone",
        json={"preview": False},
    )
    assert export.status_code == 200
    assert export.json()["received"] == 2
    assert len(_CloneState.posts) == 1
    assert {item["sourceCaseId"] for item in _CloneState.posts[0]["results"]} == {"CLONE-100", "CLONE-200"}

    import worker.core.database as database

    with Session(database.engine) as session:
        logs = session.exec(
            select(ExportLog).where(
                ExportLog.execution_run_id == execution["id"],
                ExportLog.target == "testrail-clone",
            )
        ).all()

    assert len(logs) == 1
    assert logs[0].status == "success"
    assert "CLONE-100" in (logs[0].message or "")
    assert "CLONE-200" in (logs[0].message or "")
