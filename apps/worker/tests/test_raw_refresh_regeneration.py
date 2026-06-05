from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sqlmodel import Session, select

from worker.models.db import (
    ArtifactAsset,
    CaseActionMapping,
    CaseActionMappingAction,
    Project,
    RawAction,
    StructuredFlow,
    TestCase as DbTestCase,
    WebwrightRun,
)
from worker.services.mapping import get_mappings
from worker.services.project_generator import generate_project


def _seed_case(
    session: Session,
    *,
    project_id: str,
    case: DbTestCase,
    suffix: str,
    specs: list[dict],
) -> tuple[str, list[str]]:
    run_id = f"ww_refresh_{suffix}_old"
    mapping_id = f"map_refresh_{suffix}"
    action_ids: list[str] = []
    case.status = "mapped"
    session.add(case)
    session.add(WebwrightRun(
        id=run_id,
        project_id=project_id,
        test_case_id=case.id,
        automation_key=case.automation_key,
        status="completed",
    ))
    for order_index, spec in enumerate(specs, start=1):
        action_id = f"raw_refresh_{suffix}_old_{order_index}"
        action_ids.append(action_id)
        session.add(RawAction(
            id=action_id,
            webwright_run_id=run_id,
            automation_key=case.automation_key,
            order_index=order_index,
            type=spec["type"],
            selector=spec.get("selector"),
            target=spec.get("target"),
            value=spec.get("value"),
        ))
    session.add(CaseActionMapping(
        id=mapping_id,
        test_case_id=case.id,
        raw_action_id=action_ids[0],
        tc_step_index=1,
        normalized_step_id=f"flow_{suffix}",
        normalized_step_name=f"reviewed_{suffix}",
        pom_method_name=f"reviewed_{suffix}",
        status="mapped",
    ))
    for order_index, action_id in enumerate(action_ids):
        session.add(CaseActionMappingAction(
            mapping_id=mapping_id,
            raw_action_id=action_id,
            order_index=order_index,
        ))
    return run_id, action_ids


def _patch_generator(monkeypatch, tmp_path) -> None:
    import worker.services.project_generator as project_generator

    template = tmp_path / "refresh-template"
    (template / "runner").mkdir(parents=True)
    (template / "runner" / "cli.py").write_text("# runtime\n", encoding="utf-8")
    monkeypatch.setattr(project_generator, "load_settings", lambda: None)
    monkeypatch.setattr(
        project_generator,
        "resolve_runtime",
        lambda _settings: SimpleNamespace(template_path=str(template)),
    )


def _patch_refresh_run(monkeypatch, specs: list[dict]) -> str:
    import worker.services.raw_refresh_regeneration as refresh_service

    run_id = "ww_refresh_selected_new"

    async def create_refresh_run(session, project_id, case, job_id):
        run = WebwrightRun(
            id=run_id,
            project_id=project_id,
            test_case_id=case.id,
            automation_key=case.automation_key,
            status="completed",
            final_script_path="mock://final_script.py",
            trajectory_path="mock://trajectory.json",
        )
        session.add(run)
        for order_index, spec in enumerate(specs, start=1):
            session.add(RawAction(
                id=f"raw_refresh_selected_new_{order_index}",
                webwright_run_id=run.id,
                automation_key=case.automation_key,
                order_index=order_index,
                type=spec["type"],
                selector=spec.get("selector"),
                target=spec.get("target"),
                value=spec.get("value"),
            ))
        session.commit()
        session.refresh(run)
        return run

    def extracted_actions(_path, _automation_key, selected_run_id, session):
        return list(session.exec(
            select(RawAction)
            .where(RawAction.webwright_run_id == selected_run_id)
            .order_by(RawAction.order_index)
        ).all())

    monkeypatch.setattr(
        refresh_service,
        "resolve_runtime",
        lambda: SimpleNamespace(
            check_webwright_readiness=lambda: SimpleNamespace(live_ok=False),
        ),
    )
    monkeypatch.setattr(refresh_service, "create_mock_run", create_refresh_run)
    monkeypatch.setattr(refresh_service, "extract_actions_from_script", extracted_actions)
    monkeypatch.setattr(refresh_service, "enrich_from_trajectory", lambda _actions, _path: None)
    monkeypatch.setattr(refresh_service, "extract_selector_candidates_for_run", lambda _session, _run_id: [])
    return run_id


def _file_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_selected_raw_refresh_safely_merges_and_incrementally_regenerates(
    monkeypatch,
    client,
    tmp_path,
    project_id: str,
    imported_case: dict,
) -> None:
    import worker.core.database as database

    _patch_generator(monkeypatch, tmp_path)
    new_run_id = _patch_refresh_run(monkeypatch, [
        {"type": "click", "selector": "page.get_by_role('button', name='Refreshed')", "target": "click target"},
    ])
    selected_case_id = imported_case["id"]
    unrelated_case_id = "tc_refresh_unrelated"

    with Session(database.engine) as session:
        project = session.get(Project, project_id)
        selected_case = session.get(DbTestCase, selected_case_id)
        unrelated_case = DbTestCase(
            id=unrelated_case_id,
            project_id=project_id,
            source_type="excel",
            source_case_id="TC-REFRESH-UNRELATED",
            title="Unrelated refresh case",
            automation_key="refresh_unrelated",
        )
        previous_run_id, previous_action_ids = _seed_case(
            session,
            project_id=project_id,
            case=selected_case,
            suffix="selected",
            specs=[{"type": "click", "selector": "page.locator('#old')", "target": "click target"}],
        )
        session.add(ArtifactAsset(
            id="artifact_refresh_previous",
            project_id=project_id,
            automation_key=selected_case.automation_key,
            source_type="webwright_run",
            source_id=previous_run_id,
            artifact_type="final_script",
            file_path="prior/final_script.py",
        ))
        _seed_case(
            session,
            project_id=project_id,
            case=unrelated_case,
            suffix="unrelated",
            specs=[{"type": "fill", "selector": "page.locator('#stable')", "value": "stable"}],
        )
        session.commit()
        generated = generate_project(session, project_id, Path(project.root_path), mode="full")
        project.generated_project_path = str(generated.output)
        session.add(project)
        session.commit()
        artifact = generated.output / "artifacts" / "runs" / "prior" / "result.json"
        artifact.parent.mkdir(parents=True)
        artifact.write_text('{"preserved": true}\n', encoding="utf-8")
        unrelated_mapping = get_mappings(session, unrelated_case_id)[0].model_dump()
        unrelated_flow = session.exec(
            select(StructuredFlow).where(StructuredFlow.test_case_id == unrelated_case_id)
        ).one()
        unrelated_status = unrelated_flow.status
        unrelated_test = generated.output / "tests" / "test_refresh_unrelated.py"
        unrelated_flow_file = generated.output / "flows" / "refresh_unrelated_flow.py"
        unrelated_files = (unrelated_test.read_bytes(), unrelated_flow_file.read_bytes())

    response = client.post(
        f"/projects/{project_id}/cases/{selected_case_id}/refresh-webwright-and-regenerate",
        json={"modelConfig": "model_openai.yaml"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["jobId"].startswith("refresh_")
    assert body["caseId"] == selected_case_id
    assert body["automationKey"] == imported_case["automation_key"]
    assert body["previousRunIds"] == [previous_run_id]
    assert body["run"]["id"] == new_run_id
    assert body["run"]["mode"] == "mock"
    assert body["merge"]["status"] == "merged"
    assert body["generation"]["mode"] == "incremental"
    assert body["generation"]["selectedCaseIds"] == [selected_case_id]
    assert "tests/test_refresh_unrelated.py" in body["generation"]["preservedFiles"]
    assert "artifacts/runs/prior/result.json" in body["generation"]["preservedFiles"]

    with Session(database.engine) as session:
        assert session.get(WebwrightRun, previous_run_id) is not None
        assert all(session.get(RawAction, action_id) is not None for action_id in previous_action_ids)
        assert session.get(ArtifactAsset, "artifact_refresh_previous") is not None
        assert session.get(WebwrightRun, new_run_id) is not None
        assert get_mappings(session, unrelated_case_id)[0].model_dump() == unrelated_mapping
        unrelated_flow = session.exec(
            select(StructuredFlow).where(StructuredFlow.test_case_id == unrelated_case_id)
        ).one()
        assert unrelated_flow.status == unrelated_status
        assert unrelated_test.read_bytes() == unrelated_files[0]
        assert unrelated_flow_file.read_bytes() == unrelated_files[1]
        assert artifact.read_text(encoding="utf-8") == '{"preserved": true}\n'


def test_review_required_refresh_stops_before_generated_files_are_rewritten(
    monkeypatch,
    client,
    tmp_path,
    project_id: str,
    imported_case: dict,
) -> None:
    import worker.core.database as database

    _patch_generator(monkeypatch, tmp_path)
    _patch_refresh_run(monkeypatch, [
        {"type": "click", "selector": "page.locator('#replacement-a')", "target": "click target"},
        {"type": "click", "selector": "page.locator('#replacement-b')", "target": "click target"},
    ])
    case_id = imported_case["id"]

    with Session(database.engine) as session:
        project = session.get(Project, project_id)
        case = session.get(DbTestCase, case_id)
        previous_run_id, previous_action_ids = _seed_case(
            session,
            project_id=project_id,
            case=case,
            suffix="selected",
            specs=[
                {"type": "click", "selector": "page.locator('#old-a')", "target": "click target"},
                {"type": "click", "selector": "page.locator('#old-b')", "target": "click target"},
            ],
        )
        session.commit()
        generated = generate_project(session, project_id, Path(project.root_path), mode="full")
        before = _file_snapshot(generated.output)

    response = client.post(
        f"/projects/{project_id}/cases/{case_id}/refresh-webwright-and-regenerate",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "needs_review"
    assert body["previousRunIds"] == [previous_run_id]
    assert body["merge"]["status"] == "needs_review"
    assert body["merge"]["reason"] == "ambiguous_action_match"
    assert body["generation"] is None
    assert _file_snapshot(generated.output) == before

    with Session(database.engine) as session:
        assert session.get(WebwrightRun, previous_run_id) is not None
        assert all(session.get(RawAction, action_id) is not None for action_id in previous_action_ids)


def test_generation_validation_failure_keeps_traceable_run_and_merge_result(
    monkeypatch,
    client,
    tmp_path,
    project_id: str,
    imported_case: dict,
) -> None:
    import worker.core.database as database
    import worker.services.raw_refresh_regeneration as refresh_service

    _patch_generator(monkeypatch, tmp_path)
    new_run_id = _patch_refresh_run(monkeypatch, [
        {"type": "click", "selector": "page.locator('#replacement')", "target": "click target"},
    ])
    case_id = imported_case["id"]

    with Session(database.engine) as session:
        project = session.get(Project, project_id)
        case = session.get(DbTestCase, case_id)
        _seed_case(
            session,
            project_id=project_id,
            case=case,
            suffix="selected",
            specs=[{"type": "click", "selector": "page.locator('#old')", "target": "click target"}],
        )
        session.commit()
        generated = generate_project(session, project_id, Path(project.root_path), mode="full")
        before = _file_snapshot(generated.output)

    def fail_generation(*_args, **_kwargs):
        raise ValueError("incremental validation failed")

    monkeypatch.setattr(refresh_service, "generate_project", fail_generation)

    response = client.post(
        f"/projects/{project_id}/cases/{case_id}/refresh-webwright-and-regenerate",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "generation_failed"
    assert body["run"]["id"] == new_run_id
    assert body["merge"]["status"] == "merged"
    assert body["generation"] == {"error": "incremental validation failed"}
    assert _file_snapshot(generated.output) == before


def test_refresh_regeneration_requires_existing_structure(
    client,
    project_id: str,
    imported_case: dict,
) -> None:
    response = client.post(
        f"/projects/{project_id}/cases/{imported_case['id']}/refresh-webwright-and-regenerate",
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Existing structured flow required for refresh regeneration"
