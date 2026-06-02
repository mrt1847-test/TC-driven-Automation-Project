"""A2-13: ArtifactAsset metadata is durable for self-healing evidence."""

from __future__ import annotations

import json

from sqlalchemy import inspect
from sqlmodel import Session, select

from worker.models.db import (
    ArtifactAsset,
    ArtifactAssetSourceType,
    ArtifactAssetType,
    ExecutionRun,
    TestCase as DbTestCase,
    WebwrightRun,
)


def test_artifact_assets_persist_source_links_and_metadata(project_id: str, tmp_path) -> None:
    import worker.core.database as database

    inspector = inspect(database.engine)
    assert "artifact_assets" in inspector.get_table_names()
    columns = {column["name"] for column in inspector.get_columns(ArtifactAsset.__tablename__)}
    assert {
        "project_id",
        "automation_key",
        "source_type",
        "source_id",
        "artifact_type",
        "file_path",
        "content_hash",
        "metadata_json",
        "created_at",
    }.issubset(columns)
    assert "file_bytes" not in columns

    index_names = {index["name"] for index in inspector.get_indexes(ArtifactAsset.__tablename__)}
    assert {"idx_artifact_assets_key", "idx_artifact_assets_source"}.issubset(index_names)

    automation_key = "artifact_login"
    final_script_path = tmp_path / "webwright" / "final_script.py"
    trace_path = tmp_path / "execution" / "trace.zip"

    with Session(database.engine) as session:
        test_case = DbTestCase(
            id="tc_artifact_asset",
            project_id=project_id,
            source_type="excel",
            source_case_id="TC-ARTIFACT",
            title="Artifact evidence case",
            steps_json="[]",
            automation_key=automation_key,
        )
        webwright_run = WebwrightRun(
            id="ww_artifact_asset",
            project_id=project_id,
            test_case_id=test_case.id,
            automation_key=automation_key,
            status="completed",
            output_path=str(final_script_path.parent),
            final_script_path=str(final_script_path),
        )
        execution_run = ExecutionRun(
            id="exec_artifact_asset",
            project_id=project_id,
            run_id="runner_artifact_asset",
            env="stg",
            browser="chromium",
            headed=False,
            status="failed",
            result_path=str(trace_path.parent / "results.json"),
        )
        session.add(test_case)
        session.add(webwright_run)
        session.add(execution_run)
        session.add(ArtifactAsset(
            id="art_webwright_final_script",
            project_id=project_id,
            automation_key=automation_key,
            source_type=ArtifactAssetSourceType.webwright_run.value,
            source_id=webwright_run.id,
            artifact_type=ArtifactAssetType.final_script.value,
            file_path=str(final_script_path),
            content_hash="sha256:final-script",
            metadata_json=json.dumps({"url": "https://example.test/login", "viewport": {"width": 1280, "height": 720}}),
        ))
        session.add(ArtifactAsset(
            id="art_execution_trace",
            project_id=project_id,
            automation_key=automation_key,
            source_type=ArtifactAssetSourceType.execution_run.value,
            source_id=execution_run.id,
            artifact_type=ArtifactAssetType.trace.value,
            file_path=str(trace_path),
            content_hash="sha256:trace",
            metadata_json=json.dumps({"error_category": "selector_not_found"}),
        ))
        session.commit()

    with Session(database.engine) as session:
        webwright_artifact = session.exec(
            select(ArtifactAsset)
            .where(ArtifactAsset.source_type == ArtifactAssetSourceType.webwright_run.value)
            .where(ArtifactAsset.source_id == "ww_artifact_asset")
        ).one()
        execution_artifact = session.exec(
            select(ArtifactAsset)
            .where(ArtifactAsset.source_type == ArtifactAssetSourceType.execution_run.value)
            .where(ArtifactAsset.source_id == "exec_artifact_asset")
        ).one()

    assert webwright_artifact.project_id == project_id
    assert webwright_artifact.automation_key == automation_key
    assert webwright_artifact.artifact_type == ArtifactAssetType.final_script.value
    assert webwright_artifact.file_path == str(final_script_path)
    assert json.loads(webwright_artifact.metadata_json or "{}")["viewport"]["width"] == 1280

    assert execution_artifact.project_id == project_id
    assert execution_artifact.automation_key == automation_key
    assert execution_artifact.artifact_type == ArtifactAssetType.trace.value
    assert execution_artifact.file_path == str(trace_path)
    assert json.loads(execution_artifact.metadata_json or "{}")["error_category"] == "selector_not_found"
