"""E-11: Selected TC Webwright refresh -> safe raw merge -> incremental regeneration E2E."""
from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from worker.models.db import (
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
) -> list[dict]:
    queued = client.post(f"/projects/{project_id}/webwright-runs", json={"caseIds": [case_id]})
    assert queued.status_code == 200
    run = _wait_for_run(client, project_id, case_id)
    assert run["status"] == "completed"

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


def _patch_refresh_mock_script(monkeypatch) -> None:
    import worker.services.raw_refresh_regeneration as refresh_service

    async def refreshed_mock_run(session, project_id, case, job_id, **kwargs):
        import worker.services.webwright_adapter as webwright_adapter

        run = await webwright_adapter.create_mock_run(session, project_id, case, job_id, **kwargs)
        script = (
            "from playwright.sync_api import sync_playwright, expect\n\n"
            "def run():\n"
            "    with sync_playwright() as p:\n"
            "        browser = p.chromium.launch(headless=True)\n"
            "        page = browser.new_page()\n"
            "        page.goto('https://example.com')\n"
            "        page.get_by_role('button', name='Refreshed').click()\n"
            "        browser.close()\n"
        )
        script_path = Path(run.final_script_path or "")
        if script_path.exists():
            script_path.write_text(script, encoding="utf-8")
        return run

    monkeypatch.setattr(
        refresh_service,
        "resolve_runtime",
        lambda: SimpleNamespace(
            check_webwright_readiness=lambda: SimpleNamespace(live_ok=False),
        ),
    )
    monkeypatch.setattr(refresh_service, "create_mock_run", refreshed_mock_run)


def test_selected_raw_refresh_incremental_regeneration_e2e(
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
            "id": "tc_e11_peer_alpha",
            "automation_key": "e11_peer_alpha",
            "title": "E11 peer alpha",
            "source_case_id": "TC-E11-ALPHA",
            "prefix": "e11_alpha",
        },
        {
            "id": "tc_e11_peer_beta",
            "automation_key": "e11_peer_beta",
            "title": "E11 peer beta",
            "source_case_id": "TC-E11-BETA",
            "prefix": "e11_beta",
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

    all_case_ids = [selected_case_id, *(peer["id"] for peer in peer_cases)]
    for case_id, prefix in [
        (selected_case_id, "e11_selected"),
        *((peer["id"], peer["prefix"]) for peer in peer_cases),
    ]:
        _prepare_structured_case(client, project_id, case_id, prefix)

    generated = client.post(f"/projects/{project_id}/generate", json={"mode": "full"})
    assert generated.status_code == 200
    generated_path = Path(generated.json()["generatedProjectPath"])
    assert generated_path.exists()
    assert generated.json()["generationMode"] == "full"
    assert set(generated.json()["selectedCaseIds"]) == set(all_case_ids)

    stable_artifact = generated_path / "artifacts" / "runs" / "e11_stable" / "result.json"
    stable_artifact.parent.mkdir(parents=True, exist_ok=True)
    stable_artifact.write_text('{"stable": true}\n', encoding="utf-8")

    peer_snapshots: dict[str, dict[str, bytes]] = {}
    for peer in peer_cases:
        peer_key = peer["automation_key"]
        peer_snapshots[peer_key] = {
            "test": (generated_path / "tests" / f"test_{peer_key}.py").read_bytes(),
            "flow": (generated_path / "flows" / f"{peer_key}_flow.py").read_bytes(),
        }

    with Session(database.engine) as session:
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
        selected_test_path = f"tests/test_{selected_key}.py"
        selected_test_row = session.exec(
            select(GeneratedFile).where(
                GeneratedFile.project_id == project_id,
                GeneratedFile.relative_path == selected_test_path,
            )
        ).one()
        selected_origins_before = _origins(session, selected_test_row.id)
        selected_page_before = (
            generated_path / "pages" / "generated_page.py"
        ).read_text(encoding="utf-8")

    preview = client.post(
        f"/projects/{project_id}/cases/{selected_case_id}/refresh-webwright-and-regenerate/preview",
    )
    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["preview"] is True
    assert preview_body["action"] == "raw_refresh_regenerate"
    assert preview_body["caseId"] == selected_case_id
    assert preview_body["generation"]["generationMode"] == "incremental"
    for peer in peer_cases:
        assert f"tests/test_{peer['automation_key']}.py" in preview_body["generation"]["preservedFiles"]

    _patch_refresh_mock_script(monkeypatch)
    refresh = client.post(
        f"/projects/{project_id}/cases/{selected_case_id}/refresh-webwright-and-regenerate",
        json={"modelConfig": "model_openai.yaml"},
    )
    assert refresh.status_code == 200
    body = refresh.json()
    assert body["status"] == "completed"
    assert body["merge"]["status"] == "merged"
    assert body["generation"]["mode"] == "incremental"
    assert body["generation"]["selectedCaseIds"] == [selected_case_id]
    assert body["previousRunIds"]
    assert body["run"]["mode"] == "mock"

    selected_affected = sorted([
        f"flows/{selected_key}_flow.py",
        "mappings/cases.yaml",
        "pages/generated_page.py",
        f"tests/test_{selected_key}.py",
    ])
    assert body["generation"]["affectedFiles"] == selected_affected
    for peer in peer_cases:
        peer_test = f"tests/test_{peer['automation_key']}.py"
        peer_flow = f"flows/{peer['automation_key']}_flow.py"
        assert peer_test in body["generation"]["preservedFiles"]
        assert peer_flow in body["generation"]["preservedFiles"]
    assert "artifacts/runs/e11_stable/result.json" in body["generation"]["preservedFiles"]

    selected_page_after = (
        generated_path / "pages" / "generated_page.py"
    ).read_text(encoding="utf-8")
    assert "Refreshed" in selected_page_after
    assert selected_page_after != selected_page_before

    for peer in peer_cases:
        peer_key = peer["automation_key"]
        assert (
            generated_path / "tests" / f"test_{peer_key}.py"
        ).read_bytes() == peer_snapshots[peer_key]["test"]
        assert (
            generated_path / "flows" / f"{peer_key}_flow.py"
        ).read_bytes() == peer_snapshots[peer_key]["flow"]
    assert stable_artifact.read_text(encoding="utf-8") == '{"stable": true}\n'

    with Session(database.engine) as session:
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

        selected_test_row = session.exec(
            select(GeneratedFile).where(
                GeneratedFile.project_id == project_id,
                GeneratedFile.relative_path == selected_test_path,
            )
        ).one()
        selected_origins_after = _origins(session, selected_test_row.id)
        assert selected_origins_after != selected_origins_before
        assert body["run"]["id"] in {
            origin_id
            for origin_type, origin_id in selected_origins_after
            if origin_type == "webwright_run"
        }

        merge_metadata = session.exec(
            select(StructuredFlow)
            .where(StructuredFlow.test_case_id == selected_case_id)
            .order_by(StructuredFlow.version.desc())
        ).first()
        assert merge_metadata.status in {"approved", "structured", "generated"}
