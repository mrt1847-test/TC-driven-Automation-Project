from __future__ import annotations

import json

from sqlmodel import Session

from worker.models.db import (
    ArtifactAsset,
    ArtifactAssetSourceType,
    ArtifactAssetType,
    ExecutionResult,
    ExecutionRun,
    TestCase as DbTestCase,
    WebwrightRun,
)


def _seed_artifact_graph(project_id: str, tmp_path) -> dict[str, str]:
    import worker.core.database as database

    automation_key = "artifact_login"
    webwright_dir = tmp_path / "webwright" / "artifact_login"
    execution_dir = tmp_path / "execution" / "artifact_login"
    outside_dir = tmp_path / "outside"
    webwright_dir.mkdir(parents=True)
    execution_dir.mkdir(parents=True)
    outside_dir.mkdir(parents=True)

    final_script = webwright_dir / "final_script.py"
    trajectory = webwright_dir / "trajectory.json"
    results_json = execution_dir / "results.json"
    stdout_log = execution_dir / "stdout.log"
    trace = execution_dir / "trace.zip"
    unsafe_trace = outside_dir / "unsafe-trace.zip"
    for path in [final_script, trajectory, results_json, stdout_log, trace, unsafe_trace]:
        path.write_text(path.name, encoding="utf-8")

    with Session(database.engine) as session:
        case = DbTestCase(
            id="tc_artifact_login",
            project_id=project_id,
            source_type="excel",
            source_case_id="TC-ARTIFACT-LOGIN",
            title="Artifact login",
            steps_json="[]",
            automation_key=automation_key,
        )
        webwright_run = WebwrightRun(
            id="ww_artifact_login",
            project_id=project_id,
            test_case_id=case.id,
            automation_key=automation_key,
            status="completed",
            output_path=str(webwright_dir),
            final_script_path=str(final_script),
            trajectory_path=str(trajectory),
        )
        execution_run = ExecutionRun(
            id="exec_artifact_login",
            project_id=project_id,
            run_id="runner_artifact_login",
            env="stg",
            browser="chromium",
            status="failed",
            result_path=str(results_json),
        )
        failed_result = ExecutionResult(
            id="er_artifact_login",
            execution_run_id=execution_run.id,
            automation_key=automation_key,
            source_type="excel",
            source_case_id="TC-ARTIFACT-LOGIN",
            title="Artifact login",
            status="failed",
            error="selector not found",
            trace_path=str(trace),
        )
        session.add_all([case, webwright_run, execution_run, failed_result])
        session.add_all([
            ArtifactAsset(
                id="art_artifact_webwright_script",
                project_id=project_id,
                automation_key=automation_key,
                source_type=ArtifactAssetSourceType.webwright_run.value,
                source_id=webwright_run.id,
                artifact_type=ArtifactAssetType.final_script.value,
                file_path=str(final_script),
                content_hash="sha256:script",
                metadata_json=json.dumps({
                    "file_name": "final_script.py",
                    "relative_path": "final_script.py",
                    "size_bytes": final_script.stat().st_size,
                }),
            ),
            ArtifactAsset(
                id="art_artifact_webwright_trajectory",
                project_id=project_id,
                automation_key=automation_key,
                source_type=ArtifactAssetSourceType.webwright_run.value,
                source_id=webwright_run.id,
                artifact_type=ArtifactAssetType.trajectory.value,
                file_path=str(trajectory),
                content_hash="sha256:trajectory",
                metadata_json=json.dumps({
                    "file_name": "trajectory.json",
                    "relative_path": "trajectory.json",
                    "size_bytes": trajectory.stat().st_size,
                }),
            ),
            ArtifactAsset(
                id="art_artifact_execution_results",
                project_id=project_id,
                automation_key=None,
                source_type=ArtifactAssetSourceType.execution_run.value,
                source_id=execution_run.id,
                artifact_type=ArtifactAssetType.metadata.value,
                file_path=str(results_json),
                content_hash="sha256:results",
                metadata_json=json.dumps({
                    "file_name": "results.json",
                    "relative_path": "results.json",
                    "size_bytes": results_json.stat().st_size,
                }),
            ),
            ArtifactAsset(
                id="art_artifact_execution_log",
                project_id=project_id,
                automation_key=None,
                source_type=ArtifactAssetSourceType.execution_run.value,
                source_id=execution_run.id,
                artifact_type=ArtifactAssetType.log.value,
                file_path=str(stdout_log),
                content_hash="sha256:log",
                metadata_json=json.dumps({
                    "file_name": "stdout.log",
                    "relative_path": "stdout.log",
                    "size_bytes": stdout_log.stat().st_size,
                }),
            ),
            ArtifactAsset(
                id="art_artifact_execution_trace",
                project_id=project_id,
                automation_key=automation_key,
                source_type=ArtifactAssetSourceType.execution_result.value,
                source_id=failed_result.id,
                artifact_type=ArtifactAssetType.trace.value,
                file_path=str(trace),
                content_hash="sha256:trace",
                metadata_json=json.dumps({
                    "file_name": "trace.zip",
                    "relative_path": "trace.zip",
                    "size_bytes": trace.stat().st_size,
                }),
            ),
            ArtifactAsset(
                id="art_artifact_other_key",
                project_id=project_id,
                automation_key="other_case",
                source_type=ArtifactAssetSourceType.webwright_run.value,
                source_id=webwright_run.id,
                artifact_type=ArtifactAssetType.log.value,
                file_path=str(webwright_dir / "other.log"),
            ),
            ArtifactAsset(
                id="art_artifact_unsafe_trace",
                project_id=project_id,
                automation_key=automation_key,
                source_type=ArtifactAssetSourceType.execution_result.value,
                source_id=failed_result.id,
                artifact_type=ArtifactAssetType.trace.value,
                file_path=str(unsafe_trace),
                content_hash="sha256:unsafe",
                metadata_json=json.dumps({"file_name": "unsafe-trace.zip"}),
            ),
        ])
        session.commit()

    return {
        "automation_key": automation_key,
        "execution_id": "exec_artifact_login",
        "webwright_run_id": "ww_artifact_login",
        "unsafe_path": str(unsafe_trace),
    }


def test_artifacts_api_filters_by_project_and_automation_key(client, project_id: str, tmp_path) -> None:
    import worker.core.database as database

    seeded = _seed_artifact_graph(project_id, tmp_path)
    other_project = client.post("/projects", json={"name": "Other"}).json()["id"]
    with Session(database.engine) as session:
        session.add(ArtifactAsset(
            id="art_artifact_foreign",
            project_id=other_project,
            automation_key=seeded["automation_key"],
            source_type=ArtifactAssetSourceType.webwright_run.value,
            source_id="ww_foreign",
            artifact_type=ArtifactAssetType.log.value,
            file_path=str(tmp_path / "foreign.log"),
        ))
        session.commit()

    response = client.get(
        f"/projects/{project_id}/artifacts",
        params={"automation_key": seeded["automation_key"]},
    )

    assert response.status_code == 200
    body = response.json()
    ids = {artifact["id"] for artifact in body["artifacts"]}
    assert body["projectId"] == project_id
    assert "art_artifact_webwright_script" in ids
    assert "art_artifact_execution_trace" in ids
    assert "art_artifact_execution_results" not in ids
    assert "art_artifact_other_key" not in ids
    assert "art_artifact_foreign" not in ids
    script = next(artifact for artifact in body["artifacts"] if artifact["id"] == "art_artifact_webwright_script")
    assert script["sourceType"] == ArtifactAssetSourceType.webwright_run.value
    assert script["kind"] == ArtifactAssetType.final_script.value
    assert script["filePath"].endswith("final_script.py")
    assert script["fileName"] == "final_script.py"
    assert script["relativePath"] == "final_script.py"
    assert script["pathAvailable"] is True


def test_artifacts_api_filters_by_source_and_run_ids(client, project_id: str, tmp_path) -> None:
    seeded = _seed_artifact_graph(project_id, tmp_path)

    webwright_response = client.get(
        f"/projects/{project_id}/artifacts",
        params={"sourceType": "webwright_run", "sourceId": seeded["webwright_run_id"]},
    )
    assert webwright_response.status_code == 200
    assert {artifact["id"] for artifact in webwright_response.json()["artifacts"]} == {
        "art_artifact_webwright_script",
        "art_artifact_webwright_trajectory",
        "art_artifact_other_key",
    }

    execution_response = client.get(
        f"/projects/{project_id}/artifacts",
        params={"executionId": seeded["execution_id"]},
    )
    assert execution_response.status_code == 200
    assert {artifact["id"] for artifact in execution_response.json()["artifacts"]} == {
        "art_artifact_execution_results",
        "art_artifact_execution_log",
        "art_artifact_execution_trace",
        "art_artifact_unsafe_trace",
    }

    webwright_run_response = client.get(
        f"/projects/{project_id}/artifacts",
        params={"webwright_run_id": seeded["webwright_run_id"]},
    )
    assert webwright_run_response.status_code == 200
    assert {artifact["id"] for artifact in webwright_run_response.json()["artifacts"]} == {
        "art_artifact_webwright_script",
        "art_artifact_webwright_trajectory",
        "art_artifact_other_key",
    }


def test_artifacts_api_suppresses_paths_outside_runtime_artifact_roots(client, project_id: str, tmp_path) -> None:
    seeded = _seed_artifact_graph(project_id, tmp_path)

    response = client.get(
        f"/projects/{project_id}/artifacts",
        params={"automationKey": seeded["automation_key"]},
    )

    assert response.status_code == 200
    unsafe = next(artifact for artifact in response.json()["artifacts"] if artifact["id"] == "art_artifact_unsafe_trace")
    assert unsafe["filePath"] is None
    assert unsafe["pathAvailable"] is False
    assert seeded["unsafe_path"] not in response.text
