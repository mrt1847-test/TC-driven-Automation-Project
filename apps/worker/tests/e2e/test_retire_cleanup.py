"""E-12: Feature-removed TC diagnosis-bound retire cleanup E2E."""
from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from worker.models.db import (
    ArtifactAsset,
    ExecutionResult,
    ExecutionRun,
    GeneratedFile,
    GeneratedFileOrigin,
    StructuredFlow,
    TestCase as DbTestCase,
)


def _wait_for_run(client: TestClient, project_id: str, case_id: str, timeout_s: float = 5.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        runs = client.get(f"/projects/{project_id}/webwright-runs").json()
        for run in runs:
            if run.get("test_case_id") == case_id and run.get("status") in {"completed", "failed", "cancelled"}:
                return run
        time.sleep(0.05)
    pytest.fail(f"Timed out waiting for Webwright run for case {case_id}")


def _review_mappings(client: TestClient, project_id: str, case_id: str, prefix: str) -> list[dict]:
    mappings = client.get(f"/projects/{project_id}/cases/{case_id}/mappings").json()
    assert mappings

    reviewed = []
    for index, mapping in enumerate(mappings, start=1):
        reviewed.append({
            **mapping,
            "normalized_step_id": mapping.get("normalized_step_id") or f"flow_{index:03d}",
            "normalized_step_name": f"{prefix}_step_{index}",
            "pom_method_name": f"perform_{prefix}_step_{index}",
            "status": "mapped",
        })
    response = client.put(
        f"/projects/{project_id}/cases/{case_id}/mappings",
        json={"mappings": reviewed},
    )
    assert response.status_code == 200
    return reviewed


def _prepare_structured_case(
    client: TestClient,
    project_id: str,
    case_id: str,
    prefix: str,
    *,
    consolidate_actions: bool = False,
) -> list[dict]:
    queued = client.post(f"/projects/{project_id}/webwright-runs", json={"caseIds": [case_id]})
    assert queued.status_code == 200
    run = _wait_for_run(client, project_id, case_id)
    assert run["status"] == "completed"

    if consolidate_actions:
        actions = client.get(f"/projects/{project_id}/cases/{case_id}/actions").json()
        mappings = client.get(f"/projects/{project_id}/cases/{case_id}/mappings").json()
        assert mappings
        reviewed = [{
            **mappings[0],
            "action_ids": [action["id"] for action in actions],
            "normalized_step_id": mappings[0].get("normalized_step_id") or "flow_001",
            "normalized_step_name": f"{prefix}_step_1",
            "pom_method_name": f"perform_{prefix}_step_1",
            "status": "mapped",
        }]
        response = client.put(
            f"/projects/{project_id}/cases/{case_id}/mappings",
            json={"mappings": reviewed},
        )
        assert response.status_code == 200
        reviewed = response.json()
    else:
        reviewed = _review_mappings(client, project_id, case_id, prefix)

    synced = client.post(f"/projects/{project_id}/cases/{case_id}/structure/sync")
    assert synced.status_code == 200
    return reviewed


def _add_peer_case(
    session: Session,
    project_id: str,
    *,
    case_id: str,
    automation_key: str,
    title: str,
    source_case_id: str,
) -> DbTestCase:
    case = DbTestCase(
        id=case_id,
        project_id=project_id,
        source_type="excel",
        source_case_id=source_case_id,
        title=title,
        automation_key=automation_key,
        steps_json=json.dumps([{"index": 1, "action": "More information link click"}]),
        start_url="https://example.com",
    )
    session.add(case)
    session.commit()
    session.refresh(case)
    return case


def _origins(session: Session, generated_file_id: str) -> set[tuple[str, str]]:
    return {
        (origin.origin_type, origin.origin_id)
        for origin in session.exec(
            select(GeneratedFileOrigin).where(GeneratedFileOrigin.generated_file_id == generated_file_id)
        ).all()
    }


def _force_mock_webwright(monkeypatch) -> None:
    import worker.routers.webwright_runs as webwright_runs

    monkeypatch.setattr(
        webwright_runs,
        "resolve_runtime",
        lambda: SimpleNamespace(
            check_webwright_readiness=lambda: SimpleNamespace(live_ok=False),
        ),
    )


def _seed_feature_removed_failure(
    session: Session,
    project_id: str,
    case: DbTestCase,
    *,
    execution_id: str = "execution_e12_retire",
    result_id: str = "result_e12_retire",
    artifact_id: str = "artifact_e12_retire",
) -> dict:
    session.add(ExecutionRun(
        id=execution_id,
        project_id=project_id,
        run_id="run_e12_retire",
        env="stg",
        browser="chromium",
        status="failed",
    ))
    session.add(ExecutionResult(
        id=result_id,
        execution_run_id=execution_id,
        automation_key=case.automation_key,
        source_type=case.source_type,
        source_case_id=case.source_case_id,
        title=case.title,
        status="failed",
        error="feature removed and no longer exists",
    ))
    session.add(ArtifactAsset(
        id=artifact_id,
        project_id=project_id,
        automation_key=case.automation_key,
        source_type="execution_result",
        source_id=result_id,
        artifact_type="trace",
        file_path="artifacts/e12/feature-removed.zip",
        metadata_json=json.dumps({"error_category": "feature_removed"}),
    ))
    session.commit()
    return {
        "execution_id": execution_id,
        "result_id": result_id,
        "artifact_id": artifact_id,
    }


def test_feature_removed_retire_cleanup_e2e(
    monkeypatch,
    client: TestClient,
    project_id: str,
    imported_case: dict,
) -> None:
    import worker.core.database as database

    _force_mock_webwright(monkeypatch)
    selected_case_id = imported_case["id"]
    selected_key = imported_case["automation_key"]
    peer_cases = [
        {
            "id": "tc_e12_peer_alpha",
            "automation_key": "e12_peer_alpha",
            "title": "E12 peer alpha",
            "source_case_id": "TC-E12-ALPHA",
            "prefix": "e12_alpha",
        },
        {
            "id": "tc_e12_peer_beta",
            "automation_key": "e12_peer_beta",
            "title": "E12 peer beta",
            "source_case_id": "TC-E12-BETA",
            "prefix": "e12_beta",
        },
    ]

    with Session(database.engine) as session:
        for peer in peer_cases:
            _add_peer_case(
                session,
                project_id,
                case_id=peer["id"],
                automation_key=peer["automation_key"],
                title=peer["title"],
                source_case_id=peer["source_case_id"],
            )

    _prepare_structured_case(
        client,
        project_id,
        selected_case_id,
        "e12_selected",
        consolidate_actions=True,
    )
    for peer in peer_cases:
        _prepare_structured_case(client, project_id, peer["id"], peer["prefix"])

    generated = client.post(f"/projects/{project_id}/generate", json={"mode": "full"})
    assert generated.status_code == 200
    generated_path = Path(generated.json()["generatedProjectPath"])
    assert generated_path.exists()

    stable_artifact = generated_path / "artifacts" / "runs" / "e12_stable" / "result.json"
    stable_artifact.parent.mkdir(parents=True, exist_ok=True)
    stable_artifact.write_text('{"stable": true}\n', encoding="utf-8")

    selected_test = f"tests/test_{selected_key}.py"
    selected_flow = f"flows/{selected_key}_flow.py"
    peer_snapshots: dict[str, dict[str, bytes]] = {}
    for peer in peer_cases:
        peer_key = peer["automation_key"]
        peer_snapshots[peer_key] = {
            "test": (generated_path / "tests" / f"test_{peer_key}.py").read_bytes(),
            "flow": (generated_path / "flows" / f"{peer_key}_flow.py").read_bytes(),
        }

    with Session(database.engine) as session:
        selected_case = session.get(DbTestCase, selected_case_id)
        failure = _seed_feature_removed_failure(session, project_id, selected_case)
        peer_rows_before = {
            peer["automation_key"]: {
                "flow_status": session.exec(
                    select(StructuredFlow)
                    .where(StructuredFlow.test_case_id == peer["id"])
                    .order_by(StructuredFlow.version.desc())
                ).first().status,
                "test_origins": _origins(
                    session,
                    session.exec(
                        select(GeneratedFile).where(
                            GeneratedFile.project_id == project_id,
                            GeneratedFile.relative_path == f"tests/test_{peer['automation_key']}.py",
                        )
                    ).one().id,
                ),
            }
            for peer in peer_cases
        }
        selected_test_before = (generated_path / selected_test).read_bytes()
        selected_flow_before_exists = (generated_path / selected_flow).exists()

    diagnose = client.post(
        f"/projects/{project_id}/executions/{failure['execution_id']}/diagnose",
    )
    assert diagnose.status_code == 200
    diagnosis = next(
        item for item in diagnose.json()["diagnoses"]
        if item["execution_result_id"] == failure["result_id"]
    )
    assert diagnosis["disposition"] == "feature_removed_retire_tc"
    assert diagnosis["reason"] == "linked_feature_removed_evidence"
    assert diagnosis["confidence"] == 0.85
    assert failure["artifact_id"] in diagnosis["evidence_artifact_ids"]
    assert diagnosis["target"]["test_case_ids"] == [selected_case_id]

    preview = client.post(
        f"/projects/{project_id}/executions/{failure['execution_id']}"
        f"/results/{failure['result_id']}/retire/preview",
        json={"caseId": selected_case_id, "action": "retire"},
    )
    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["preview"] is True
    assert preview_body["diagnosis"]["disposition"] == "feature_removed_retire_tc"
    assert preview_body["cleanup"]["preview"] is True
    assert selected_test in preview_body["cleanup"]["removedFiles"]
    assert selected_flow in preview_body["cleanup"]["removedFiles"]
    for peer in peer_cases:
        assert f"tests/test_{peer['automation_key']}.py" in preview_body["cleanup"]["preservedFiles"]
    assert (generated_path / selected_test).read_bytes() == selected_test_before
    assert (generated_path / selected_flow).exists() == selected_flow_before_exists

    unconfirmed = client.post(
        f"/projects/{project_id}/executions/{failure['execution_id']}"
        f"/results/{failure['result_id']}/retire",
        json={"caseId": selected_case_id, "action": "retire"},
    )
    assert unconfirmed.status_code == 400
    assert unconfirmed.json()["detail"] == "Retire disposition action requires confirmed=true"
    assert (generated_path / selected_test).exists()

    retire = client.post(
        f"/projects/{project_id}/executions/{failure['execution_id']}"
        f"/results/{failure['result_id']}/retire",
        json={"caseId": selected_case_id, "confirmed": True, "action": "retire"},
    )
    assert retire.status_code == 200
    body = retire.json()
    assert body["status"] == "completed"
    assert body["caseId"] == selected_case_id
    assert body["diagnosis"]["disposition"] == "feature_removed_retire_tc"
    assert body["cleanup"]["status"] == "completed"
    assert body["cleanup"]["caseStatus"] == "retired"
    assert sorted(body["cleanup"]["removedFiles"]) == sorted([selected_test, selected_flow])
    assert body["cleanup"]["updatedFiles"] == ["mappings/cases.yaml", "pages/generated_page.py"]
    for peer in peer_cases:
        peer_test = f"tests/test_{peer['automation_key']}.py"
        peer_flow = f"flows/{peer['automation_key']}_flow.py"
        assert peer_test in body["cleanup"]["preservedFiles"]
        assert peer_flow in body["cleanup"]["preservedFiles"]
    assert "artifacts/runs/e12_stable/result.json" in body["cleanup"]["preservedFiles"]

    assert not (generated_path / selected_test).exists()
    assert not (generated_path / selected_flow).exists()
    for peer in peer_cases:
        peer_key = peer["automation_key"]
        assert (
            generated_path / "tests" / f"test_{peer_key}.py"
        ).read_bytes() == peer_snapshots[peer_key]["test"]
        assert (
            generated_path / "flows" / f"{peer_key}_flow.py"
        ).read_bytes() == peer_snapshots[peer_key]["flow"]
    assert stable_artifact.read_text(encoding="utf-8") == '{"stable": true}\n'

    page_content = (generated_path / "pages" / "generated_page.py").read_text(encoding="utf-8")
    assert "perform_e12_selected_step_1" not in page_content
    assert "perform_e12_alpha_step_1" in page_content
    assert "perform_e12_beta_step_1" in page_content
    mapping_entries = yaml.safe_load(
        (generated_path / "mappings" / "cases.yaml").read_text(encoding="utf-8")
    )["cases"]
    assert {entry["automationKey"] for entry in mapping_entries} == {
        peer["automation_key"] for peer in peer_cases
    }

    with Session(database.engine) as session:
        assert session.get(DbTestCase, selected_case_id).status == "retired"
        selected_row = session.exec(
            select(GeneratedFile).where(
                GeneratedFile.project_id == project_id,
                GeneratedFile.relative_path == selected_test,
            )
        ).one()
        assert selected_row.status == "obsolete"
        assert session.get(ExecutionResult, failure["result_id"]) is not None
        assert session.get(ArtifactAsset, failure["artifact_id"]) is not None

        for peer in peer_cases:
            flow = session.exec(
                select(StructuredFlow)
                .where(StructuredFlow.test_case_id == peer["id"])
                .order_by(StructuredFlow.version.desc())
            ).first()
            assert flow.status == peer_rows_before[peer["automation_key"]]["flow_status"]
            test_row = session.exec(
                select(GeneratedFile).where(
                    GeneratedFile.project_id == project_id,
                    GeneratedFile.relative_path == f"tests/test_{peer['automation_key']}.py",
                )
            ).one()
            assert _origins(session, test_row.id) == peer_rows_before[peer["automation_key"]]["test_origins"]
