"""C12-01: Webwright run artifacts are indexed as ArtifactAsset rows."""

from __future__ import annotations

import json
from pathlib import Path
import time

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from worker.models.db import ArtifactAsset, ArtifactAssetSourceType, ArtifactAssetType, WebwrightRun
from worker.services.artifact_indexing import index_webwright_run_artifacts


def _wait_for_run(client: TestClient, project_id: str, case_id: str, timeout_s: float = 5.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        runs = client.get(f"/projects/{project_id}/webwright-runs").json()
        for run in runs:
            if run.get("test_case_id") == case_id and run.get("status") in {"completed", "failed", "cancelled"}:
                return run
        time.sleep(0.05)
    pytest.fail("Timed out waiting for Webwright run to finish")


def _assets_for_run(run_id: str) -> list[ArtifactAsset]:
    import worker.core.database as database

    with Session(database.engine) as session:
        return session.exec(
            select(ArtifactAsset)
            .where(ArtifactAsset.source_type == ArtifactAssetSourceType.webwright_run.value)
            .where(ArtifactAsset.source_id == run_id)
            .order_by(ArtifactAsset.artifact_type, ArtifactAsset.file_path)
        ).all()


def test_webwright_run_artifacts_are_indexed_without_disrupting_run_api(
    client: TestClient,
    project_id: str,
    imported_case: dict,
) -> None:
    case_id = imported_case["id"]
    automation_key = imported_case["automation_key"]

    queued = client.post(f"/projects/{project_id}/webwright-runs", json={"caseIds": [case_id]})
    assert queued.status_code == 200

    run = _wait_for_run(client, project_id, case_id)
    assert run["status"] == "completed"

    run_detail = client.get(f"/projects/{project_id}/webwright-runs/{run['id']}")
    assert run_detail.status_code == 200
    assert run_detail.json()["id"] == run["id"]

    listed_runs = client.get(f"/projects/{project_id}/webwright-runs")
    assert listed_runs.status_code == 200
    assert any(item["id"] == run["id"] for item in listed_runs.json())

    assets = _assets_for_run(run["id"])
    artifact_types = [asset.artifact_type for asset in assets]
    assert ArtifactAssetType.final_script.value in artifact_types
    assert ArtifactAssetType.trajectory.value in artifact_types
    assert ArtifactAssetType.metadata.value in artifact_types
    assert artifact_types.count(ArtifactAssetType.log.value) >= 2

    for asset in assets:
        assert asset.project_id == project_id
        assert asset.automation_key == automation_key
        assert asset.source_type == ArtifactAssetSourceType.webwright_run.value
        assert asset.source_id == run["id"]
        assert asset.content_hash and asset.content_hash.startswith("sha256:")
        assert Path(asset.file_path).exists()
        metadata = json.loads(asset.metadata_json or "{}")
        assert metadata["run_id"] == run["id"]
        assert metadata["test_case_id"] == case_id
        assert metadata["relative_path"]
        assert metadata["size_bytes"] >= 0

    screenshot_path = Path(run["output_path"]) / "screenshots" / "login.png"
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    screenshot_path.write_bytes(b"fake screenshot")

    import worker.core.database as database

    with Session(database.engine) as session:
        db_run = session.get(WebwrightRun, run["id"])
        assert db_run is not None
        index_webwright_run_artifacts(session, db_run)

    refreshed_assets = _assets_for_run(run["id"])
    refreshed_paths = [asset.file_path for asset in refreshed_assets]
    assert len(refreshed_paths) == len(set(refreshed_paths))
    assert any(
        asset.artifact_type == ArtifactAssetType.screenshot.value
        and Path(asset.file_path) == screenshot_path
        for asset in refreshed_assets
    )
