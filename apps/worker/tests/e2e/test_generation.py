"""E-04: Project Generation - reviewed mappings to generated project files and metadata."""
from __future__ import annotations

from pathlib import Path
import time

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from worker.models.db import GeneratedFile, Project, TestCase as DbTestCase


def _wait_for_run(client: TestClient, project_id: str, case_id: str, timeout_s: float = 5.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        runs = client.get(f"/projects/{project_id}/webwright-runs").json()
        for run in runs:
            if run.get("test_case_id") == case_id and run.get("status") in {"completed", "failed", "cancelled"}:
                return run
        time.sleep(0.05)
    pytest.fail("Timed out waiting for Webwright run to finish")


def _review_mappings(client: TestClient, project_id: str, case_id: str) -> list[dict]:
    mappings = client.get(f"/projects/{project_id}/cases/{case_id}/mappings").json()
    assert mappings

    reviewed = []
    for index, mapping in enumerate(mappings, start=1):
        reviewed.append({
            **mapping,
            "normalized_step_id": mapping.get("normalized_step_id") or f"flow_{index:03d}",
            "normalized_step_name": f"project_generation_step_{index}",
            "pom_method_name": f"perform_project_generation_step_{index}",
            "status": "mapped",
        })

    response = client.put(f"/projects/{project_id}/cases/{case_id}/mappings", json={"mappings": reviewed})
    assert response.status_code == 200
    return reviewed


def test_project_generation_workflow(client: TestClient, project_id: str, imported_case: dict) -> None:
    case_id = imported_case["id"]
    automation_key = imported_case["automation_key"]

    queued = client.post(f"/projects/{project_id}/webwright-runs", json={"caseIds": [case_id]})
    assert queued.status_code == 200
    run = _wait_for_run(client, project_id, case_id)
    assert run["status"] == "completed"

    reviewed = _review_mappings(client, project_id, case_id)

    generated_response = client.post(f"/projects/{project_id}/generate", json={"caseIds": [case_id]})
    assert generated_response.status_code == 200
    generated_path = Path(generated_response.json()["generatedProjectPath"])
    assert generated_path.exists()

    files_response = client.get(f"/projects/{project_id}/generated-files")
    assert files_response.status_code == 200
    file_paths = {item["path"] for item in files_response.json()}

    expected_paths = {
        "mappings/cases.yaml",
        "pages/generated_page.py",
        f"flows/{automation_key}_flow.py",
        f"tests/test_{automation_key}.py",
        "fixtures/browser_fixture.py",
        "fixtures/env_fixture.py",
        "runner/cli.py",
        "requirements.txt",
    }
    assert expected_paths.issubset(file_paths)

    cases_yaml = client.get(f"/projects/{project_id}/generated-files/content", params={"path": "mappings/cases.yaml"}).json()["content"]
    assert automation_key in cases_yaml
    assert f"tests/test_{automation_key}.py" in cases_yaml

    flow_content = client.get(
        f"/projects/{project_id}/generated-files/content",
        params={"path": f"flows/{automation_key}_flow.py"},
    ).json()["content"]
    assert "perform_project_generation_step_1" in flow_content

    page_content = client.get(
        f"/projects/{project_id}/generated-files/content",
        params={"path": "pages/generated_page.py"},
    ).json()["content"]
    assert "perform_project_generation_step_1" in page_content
    assert "self.page.get_by_role('link', name='More information').click()" in page_content
    assert ".click().click()" not in page_content

    import worker.core.database as database

    with Session(database.engine) as session:
        project = session.get(Project, project_id)
        assert project is not None
        assert project.generated_project_path == str(generated_path)

        case = session.get(DbTestCase, case_id)
        assert case is not None
        assert case.status == "generated"

        rows = session.exec(
            select(GeneratedFile).where(
                GeneratedFile.project_id == project_id,
                GeneratedFile.automation_key == automation_key,
            )
        ).all()
        metadata_paths = {row.relative_path for row in rows}

    assert {
        "mappings/cases.yaml",
        "pages/generated_page.py",
        f"flows/{automation_key}_flow.py",
        f"tests/test_{automation_key}.py",
    }.issubset(metadata_paths)
    assert reviewed[0]["pom_method_name"] == "perform_project_generation_step_1"
