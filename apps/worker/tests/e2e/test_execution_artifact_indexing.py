"""C12-03: failed execution artifacts are indexed as ArtifactAsset evidence."""

from __future__ import annotations

import json
from pathlib import Path
import time

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from worker.models.db import ArtifactAsset, ArtifactAssetSourceType, ArtifactAssetType, ExecutionResult, ExecutionRun
from worker.services.artifact_indexing import index_execution_failure_artifacts


def _wait_for_webwright_run(client: TestClient, project_id: str, case_id: str, timeout_s: float = 5.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        runs = client.get(f"/projects/{project_id}/webwright-runs").json()
        for run in runs:
            if run.get("test_case_id") == case_id and run.get("status") in {"completed", "failed", "cancelled"}:
                return run
        time.sleep(0.05)
    pytest.fail("Timed out waiting for Webwright run to finish")


def _wait_for_execution(client: TestClient, project_id: str, timeout_s: float = 8.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        executions = client.get(f"/projects/{project_id}/executions").json()
        for execution in executions:
            if execution.get("status") in {"completed", "failed", "cancelled"}:
                return execution
        time.sleep(0.05)
    pytest.fail("Timed out waiting for execution to finish")


def _save_reviewed_mappings(client: TestClient, project_id: str, case_id: str) -> list[dict]:
    mappings = client.get(f"/projects/{project_id}/cases/{case_id}/mappings").json()
    assert mappings

    reviewed = []
    for index, mapping in enumerate(mappings, start=1):
        reviewed.append({
            **mapping,
            "normalized_step_id": mapping.get("normalized_step_id") or f"flow_{index:03d}",
            "normalized_step_name": f"execution_artifact_step_{index}",
            "pom_method_name": f"perform_execution_artifact_step_{index}",
            "status": "mapped",
        })
    response = client.put(f"/projects/{project_id}/cases/{case_id}/mappings", json={"mappings": reviewed})
    assert response.status_code == 200
    return reviewed


def _write_generated_file(client: TestClient, project_id: str, path: str, content: str) -> None:
    response = client.put(f"/projects/{project_id}/generated-files/content", json={"path": path, "content": content})
    assert response.status_code == 200


def _execution_assets(source_type: str, source_id: str) -> list[ArtifactAsset]:
    import worker.core.database as database

    with Session(database.engine) as session:
        return session.exec(
            select(ArtifactAsset)
            .where(ArtifactAsset.source_type == source_type)
            .where(ArtifactAsset.source_id == source_id)
            .order_by(ArtifactAsset.artifact_type, ArtifactAsset.file_path)
        ).all()


def test_execution_failure_artifacts_index_results_logs_and_failed_result_assets(project_id: str, tmp_path) -> None:
    import worker.core.database as database

    automation_key = "execution_artifact_login"
    run_dir = tmp_path / "generated" / "artifacts" / "runs" / "run_failed_artifacts"
    run_dir.mkdir(parents=True)
    results_path = run_dir / "results.json"
    stdout_path = run_dir / "stdout.log"
    stderr_path = run_dir / "stderr.log"
    screenshot_path = run_dir / "failed.png"
    trace_path = run_dir / "trace.zip"
    passed_screenshot_path = run_dir / "passed.png"

    results_path.write_text(json.dumps({"summary": {"failed": 1}, "cases": []}), encoding="utf-8")
    stdout_path.write_text("pytest failed output", encoding="utf-8")
    stderr_path.write_text("assertion stack", encoding="utf-8")
    screenshot_path.write_bytes(b"fake screenshot")
    trace_path.write_bytes(b"fake trace")
    passed_screenshot_path.write_bytes(b"passed screenshot should not index")

    with Session(database.engine) as session:
        run = ExecutionRun(
            id="exec_failure_artifacts",
            project_id=project_id,
            run_id="run_failed_artifacts",
            env="stg",
            browser="chromium",
            headed=False,
            status="failed",
            result_path=str(results_path),
        )
        failed_result = ExecutionResult(
            id="er_failed_artifacts",
            execution_run_id=run.id,
            automation_key=automation_key,
            title="Failed artifact case",
            status="failed",
            error="missing selector",
            screenshot_path=str(screenshot_path),
            trace_path="trace.zip",
        )
        passed_result = ExecutionResult(
            id="er_passed_artifacts",
            execution_run_id=run.id,
            automation_key="execution_artifact_passed",
            title="Passed artifact case",
            status="passed",
            screenshot_path=str(passed_screenshot_path),
        )
        session.add(run)
        session.add(failed_result)
        session.add(passed_result)
        session.commit()
        session.refresh(run)

        first_assets = index_execution_failure_artifacts(session, run)
        refreshed_run = session.get(ExecutionRun, run.id)
        assert refreshed_run is not None
        second_assets = index_execution_failure_artifacts(session, refreshed_run)

        assert len(first_assets) == len(second_assets)

    run_assets = _execution_assets(ArtifactAssetSourceType.execution_run.value, "exec_failure_artifacts")
    failed_assets = _execution_assets(ArtifactAssetSourceType.execution_result.value, "er_failed_artifacts")
    passed_assets = _execution_assets(ArtifactAssetSourceType.execution_result.value, "er_passed_artifacts")

    assert [asset.artifact_type for asset in run_assets].count(ArtifactAssetType.metadata.value) == 1
    assert [asset.artifact_type for asset in run_assets].count(ArtifactAssetType.log.value) == 2
    assert {asset.artifact_type for asset in failed_assets} == {
        ArtifactAssetType.screenshot.value,
        ArtifactAssetType.trace.value,
    }
    assert passed_assets == []

    for asset in [*run_assets, *failed_assets]:
        assert asset.project_id == project_id
        assert asset.content_hash and asset.content_hash.startswith("sha256:")
        assert Path(asset.file_path).exists()
        metadata = json.loads(asset.metadata_json or "{}")
        assert metadata["execution_id"] == "exec_failure_artifacts"
        assert metadata["run_id"] == "run_failed_artifacts"
        assert metadata["relative_path"]
        assert metadata["size_bytes"] >= 0

    assert all(asset.automation_key is None for asset in run_assets)
    assert all(asset.automation_key == automation_key for asset in failed_assets)


def test_failed_execution_artifact_indexing_does_not_disrupt_execution_api(
    client: TestClient,
    project_id: str,
    imported_case: dict,
) -> None:
    case_id = imported_case["id"]
    automation_key = imported_case["automation_key"]

    queued = client.post(f"/projects/{project_id}/webwright-runs", json={"caseIds": [case_id]})
    assert queued.status_code == 200
    run = _wait_for_webwright_run(client, project_id, case_id)
    assert run["status"] == "completed"

    reviewed = _save_reviewed_mappings(client, project_id, case_id)
    generated = client.post(f"/projects/{project_id}/generate", json={"caseIds": [case_id]})
    assert generated.status_code == 200

    failure_message = f"execution artifact failure for {automation_key}"
    page_lines = [
        "class GeneratedPage:",
        "    def __init__(self, page):",
        "        self.page = page",
        "",
    ]
    for mapping in reviewed:
        page_lines.extend([
            f"    def {mapping['pom_method_name']}(self):",
            f"        raise AssertionError({failure_message!r})",
            "",
        ])
    _write_generated_file(client, project_id, "pages/generated_page.py", "\n".join(page_lines))

    safe_key = automation_key.lower().replace("-", "_").replace(" ", "_")
    flow_class = "".join(part.capitalize() for part in automation_key.split("_")) + "Flow"
    _write_generated_file(
        client,
        project_id,
        f"tests/test_{safe_key}.py",
        "\n".join([
            f"from flows.{safe_key}_flow import {flow_class}",
            "",
            "",
            "class FakePage:",
            "    pass",
            "",
            "",
            f"def test_{safe_key}():",
            f"    flow = {flow_class}(FakePage())",
            "    flow.execute()",
            "",
        ]),
    )
    _write_generated_file(
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

    queued_execution = client.post(
        f"/projects/{project_id}/executions",
        json={
            "env": "stg",
            "browser": "chromium",
            "headed": False,
            "target_type": "case",
            "automation_key": automation_key,
            "result_target": "local",
        },
    )
    assert queued_execution.status_code == 200

    execution = _wait_for_execution(client, project_id)
    assert execution["status"] == "failed"
    assert execution["result_path"]
    assert Path(execution["result_path"]).exists()

    listed = client.get(f"/projects/{project_id}/executions")
    assert listed.status_code == 200
    assert any(item["id"] == execution["id"] for item in listed.json())

    detail_response = client.get(f"/projects/{project_id}/executions/{execution['id']}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    failed_result = next(result for result in detail["results"] if result["automation_key"] == automation_key)
    assert failed_result["status"] == "failed"
    assert failure_message in (failed_result["error"] or "")

    run_assets = _execution_assets(ArtifactAssetSourceType.execution_run.value, execution["id"])
    assert ArtifactAssetType.metadata.value in {asset.artifact_type for asset in run_assets}
    assert [asset.artifact_type for asset in run_assets].count(ArtifactAssetType.log.value) >= 2
    for asset in run_assets:
        assert asset.source_id == execution["id"]
        assert asset.source_type == ArtifactAssetSourceType.execution_run.value
        assert Path(asset.file_path).exists()
        metadata = json.loads(asset.metadata_json or "{}")
        assert metadata["execution_id"] == execution["id"]
        assert metadata["status"] == "failed"
