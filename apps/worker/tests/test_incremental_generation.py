from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from sqlmodel import Session, select

from worker.models.db import (
    CaseActionMapping,
    CaseActionMappingAction,
    GeneratedFile,
    GeneratedFileOrigin,
    PageObjectMethod,
    RawAction,
    StructuredFlow,
    StructuredStep,
    TestCase as DbTestCase,
    WebwrightRun,
)
from worker.services.project_generator import generate_project


def _seed_case(
    session: Session,
    *,
    project_id: str,
    case: DbTestCase,
    suffix: str,
) -> tuple[str, str, str]:
    run_id = f"ww_incremental_{suffix}"
    action_id = f"raw_incremental_{suffix}"
    mapping_id = f"map_incremental_{suffix}"
    case.status = "mapped"
    session.add(case)
    session.add(WebwrightRun(
        id=run_id,
        project_id=project_id,
        test_case_id=case.id,
        automation_key=case.automation_key,
        status="completed",
    ))
    session.add(RawAction(
        id=action_id,
        webwright_run_id=run_id,
        automation_key=case.automation_key,
        order_index=1,
        type="click",
        selector=f"page.locator('#{suffix}')",
    ))
    session.add(CaseActionMapping(
        id=mapping_id,
        test_case_id=case.id,
        raw_action_id=action_id,
        tc_step_index=1,
        normalized_step_id=f"flow_{suffix}",
        normalized_step_name=f"click_{suffix}",
        pom_method_name=f"click_{suffix}",
        status="mapped",
    ))
    session.add(CaseActionMappingAction(
        mapping_id=mapping_id,
        raw_action_id=action_id,
        order_index=0,
    ))
    return run_id, action_id, mapping_id


def _origins(session: Session, generated_file_id: str) -> set[tuple[str, str]]:
    return {
        (origin.origin_type, origin.origin_id)
        for origin in session.exec(
            select(GeneratedFileOrigin).where(GeneratedFileOrigin.generated_file_id == generated_file_id)
        ).all()
    }


def _generated_by_path(session: Session, project_id: str) -> dict[str, GeneratedFile]:
    return {
        row.relative_path: row
        for row in session.exec(
            select(GeneratedFile).where(GeneratedFile.project_id == project_id)
        ).all()
    }


def test_selected_incremental_generation_preserves_unrelated_files_and_replaces_origins(
    monkeypatch,
    tmp_path,
    project_id: str,
    imported_case: dict,
) -> None:
    import worker.core.database as database
    import worker.services.project_generator as project_generator

    template = tmp_path / "template"
    (template / "runner").mkdir(parents=True)
    (template / "runner" / "cli.py").write_text("# runtime\n", encoding="utf-8")
    (template / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    monkeypatch.setattr(project_generator, "load_settings", lambda: None)
    monkeypatch.setattr(
        project_generator,
        "resolve_runtime",
        lambda _settings: SimpleNamespace(template_path=str(template)),
    )

    selected_case_id = imported_case["id"]
    unrelated_case_id = "tc_incremental_unrelated"
    project_root = tmp_path / "incremental-project"

    with Session(database.engine) as session:
        selected_case = session.get(DbTestCase, selected_case_id)
        unrelated_case = DbTestCase(
            id=unrelated_case_id,
            project_id=project_id,
            source_type="excel",
            source_case_id="TC-INCREMENTAL-UNRELATED",
            title="Unrelated case",
            automation_key="incremental_unrelated",
        )
        _selected_run_id, selected_old_action_id, selected_mapping_id = _seed_case(
            session,
            project_id=project_id,
            case=selected_case,
            suffix="selected",
        )
        _seed_case(
            session,
            project_id=project_id,
            case=unrelated_case,
            suffix="unrelated",
        )
        session.commit()

        full = generate_project(session, project_id, project_root, mode="full")
        assert full.mode == "full"
        output = full.output
        artifact = output / "artifacts" / "runs" / "stable" / "result.json"
        artifact.parent.mkdir(parents=True)
        artifact.write_text('{"stable": true}\n', encoding="utf-8")
        custom_runtime = output / "runner" / "custom_runtime.py"
        custom_runtime.write_text("# preserve me\n", encoding="utf-8")

        selected_key = selected_case.automation_key
        unrelated_key = unrelated_case.automation_key
        selected_test = f"tests/test_{selected_key}.py"
        selected_flow = f"flows/{selected_key}_flow.py"
        unrelated_test = f"tests/test_{unrelated_key}.py"
        unrelated_flow = f"flows/{unrelated_key}_flow.py"
        by_path_before = _generated_by_path(session, project_id)
        unrelated_snapshot = {
            "test": (output / unrelated_test).read_bytes(),
            "flow": (output / unrelated_flow).read_bytes(),
            "test_row_id": by_path_before[unrelated_test].id,
            "flow_row_id": by_path_before[unrelated_flow].id,
            "test_origins": _origins(session, by_path_before[unrelated_test].id),
            "flow_origins": _origins(session, by_path_before[unrelated_flow].id),
        }

        replacement_run_id = "ww_incremental_selected_refresh"
        replacement_action_id = "raw_incremental_selected_refresh"
        session.add(WebwrightRun(
            id=replacement_run_id,
            project_id=project_id,
            test_case_id=selected_case_id,
            automation_key=selected_key,
            status="completed",
        ))
        session.add(RawAction(
            id=replacement_action_id,
            webwright_run_id=replacement_run_id,
            automation_key=selected_key,
            order_index=1,
            type="click",
            selector="page.get_by_role('button', name='Refreshed')",
        ))
        link = session.exec(
            select(CaseActionMappingAction).where(CaseActionMappingAction.mapping_id == selected_mapping_id)
        ).one()
        session.delete(link)
        mapping = session.get(CaseActionMapping, selected_mapping_id)
        mapping.raw_action_id = replacement_action_id
        session.add(mapping)
        session.add(CaseActionMappingAction(
            mapping_id=selected_mapping_id,
            raw_action_id=replacement_action_id,
            order_index=0,
        ))
        flow = session.exec(
            select(StructuredFlow)
            .where(StructuredFlow.test_case_id == selected_case_id)
            .order_by(StructuredFlow.version.desc())
        ).first()
        step = session.exec(
            select(StructuredStep).where(StructuredStep.structured_flow_id == flow.id)
        ).one()
        method = session.get(PageObjectMethod, step.page_object_method_id)
        method.selector = "page.get_by_role('button', name='Refreshed')"
        method.body_plan_json = json.dumps([{
            "action": "click",
            "order": 1,
            "requiresReview": False,
            "selector": method.selector,
            "sourceMappingId": selected_mapping_id,
            "sourceRawActionId": replacement_action_id,
        }], sort_keys=True, separators=(",", ":"))
        selected_case.title = "Selected case refreshed"
        session.add(method)
        session.add(selected_case)
        session.commit()

        result = generate_project(
            session,
            project_id,
            project_root,
            [selected_case_id],
        )

        assert result.mode == "incremental"
        assert result.selected_case_ids == [selected_case_id]
        assert result.affected_files == sorted([
            selected_flow,
            selected_test,
            "mappings/cases.yaml",
            "pages/generated_page.py",
        ])
        assert "pages/generated_page.py" in result.changed_files
        assert "mappings/cases.yaml" in result.changed_files
        assert unrelated_test in result.preserved_files
        assert unrelated_flow in result.preserved_files
        assert "artifacts/runs/stable/result.json" in result.preserved_files
        assert "runner/custom_runtime.py" in result.preserved_files
        assert artifact.read_text(encoding="utf-8") == '{"stable": true}\n'
        assert custom_runtime.read_text(encoding="utf-8") == "# preserve me\n"
        assert (output / unrelated_test).read_bytes() == unrelated_snapshot["test"]
        assert (output / unrelated_flow).read_bytes() == unrelated_snapshot["flow"]

        page_content = (output / "pages" / "generated_page.py").read_text(encoding="utf-8")
        assert "click_selected" in page_content
        assert "click_unrelated" in page_content
        assert "Refreshed" in page_content
        mapping_entries = yaml.safe_load(
            (output / "mappings" / "cases.yaml").read_text(encoding="utf-8")
        )["cases"]
        assert {entry["automationKey"] for entry in mapping_entries} == {selected_key, unrelated_key}
        assert next(entry for entry in mapping_entries if entry["automationKey"] == selected_key)["title"] == "Selected case refreshed"

        by_path_after = _generated_by_path(session, project_id)
        assert by_path_after[unrelated_test].id == unrelated_snapshot["test_row_id"]
        assert by_path_after[unrelated_flow].id == unrelated_snapshot["flow_row_id"]
        assert _origins(session, by_path_after[unrelated_test].id) == unrelated_snapshot["test_origins"]
        assert _origins(session, by_path_after[unrelated_flow].id) == unrelated_snapshot["flow_origins"]
        selected_origins = _origins(session, by_path_after[selected_test].id)
        page_origins = _origins(session, by_path_after["pages/generated_page.py"].id)
        assert ("raw_action", selected_old_action_id) not in selected_origins
        assert ("raw_action", selected_old_action_id) not in page_origins
        assert ("raw_action", replacement_action_id) in selected_origins
        assert ("raw_action", replacement_action_id) in page_origins


def test_selected_generation_api_returns_deterministic_affected_summary(
    monkeypatch,
    client,
    project_id: str,
    imported_case: dict,
    tmp_path,
) -> None:
    import worker.core.database as database
    import worker.routers.generation as generation_router
    import worker.services.project_generator as project_generator

    template = tmp_path / "api-template"
    (template / "runner").mkdir(parents=True)
    (template / "runner" / "cli.py").write_text("# runtime\n", encoding="utf-8")
    (template / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    monkeypatch.setattr(project_generator, "load_settings", lambda: None)
    monkeypatch.setattr(
        project_generator,
        "resolve_runtime",
        lambda _settings: SimpleNamespace(template_path=str(template)),
    )
    monkeypatch.setattr(generation_router, "ensure_generated_runtime", lambda _path, install, **_kwargs: {"ok": True})

    unrelated_case_id = "tc_incremental_api_unrelated"
    with Session(database.engine) as session:
        selected_case = session.get(DbTestCase, imported_case["id"])
        unrelated_case = DbTestCase(
            id=unrelated_case_id,
            project_id=project_id,
            source_type="excel",
            source_case_id="TC-INCREMENTAL-API",
            title="API unrelated case",
            automation_key="incremental_api_unrelated",
        )
        _seed_case(session, project_id=project_id, case=selected_case, suffix="api_selected")
        _seed_case(session, project_id=project_id, case=unrelated_case, suffix="api_unrelated")
        session.commit()

    full = client.post(
        f"/projects/{project_id}/generate",
        json={"caseIds": [imported_case["id"]], "mode": "full"},
    )
    assert full.status_code == 200
    assert full.json()["generationMode"] == "full"
    assert unrelated_case_id in full.json()["selectedCaseIds"]

    generated_path = full.json()["generatedProjectPath"]
    unrelated_test = Path(generated_path) / "tests" / "test_incremental_api_unrelated.py"
    unrelated_before_empty_selection = unrelated_test.read_bytes()
    empty_selection = client.post(
        f"/projects/{project_id}/generate",
        json={"caseIds": []},
    )
    assert empty_selection.status_code == 400
    assert unrelated_test.read_bytes() == unrelated_before_empty_selection

    artifact = Path(generated_path) / "artifacts" / "runs" / "api" / "result.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("{}\n", encoding="utf-8")

    selected = client.post(
        f"/projects/{project_id}/generate/selected",
        json={"caseIds": [imported_case["id"]]},
    )
    assert selected.status_code == 200
    body = selected.json()
    selected_key = imported_case["automation_key"]
    assert body["generationMode"] == "incremental"
    assert body["selectedCaseIds"] == [imported_case["id"]]
    assert body["affectedFiles"] == sorted([
        f"flows/{selected_key}_flow.py",
        "mappings/cases.yaml",
        "pages/generated_page.py",
        f"tests/test_{selected_key}.py",
    ])
    assert "artifacts/runs/api/result.json" in body["preservedFiles"]
    assert f"tests/test_incremental_api_unrelated.py" in body["preservedFiles"]


def test_selected_incremental_generation_stops_when_structure_needs_review(
    monkeypatch,
    tmp_path,
    project_id: str,
    imported_case: dict,
) -> None:
    import worker.core.database as database
    import worker.services.project_generator as project_generator

    template = tmp_path / "review-template"
    template.mkdir()
    monkeypatch.setattr(project_generator, "load_settings", lambda: None)
    monkeypatch.setattr(
        project_generator,
        "resolve_runtime",
        lambda _settings: SimpleNamespace(template_path=str(template)),
    )

    project_root = tmp_path / "review-project"
    with Session(database.engine) as session:
        case = session.get(DbTestCase, imported_case["id"])
        _seed_case(session, project_id=project_id, case=case, suffix="review")
        session.commit()
        generate_project(session, project_id, project_root, mode="full")
        generated_page = project_root / "generated" / "pages" / "generated_page.py"
        previous_page = generated_page.read_bytes()
        case.status = "needs_review"
        flow = session.exec(
            select(StructuredFlow)
            .where(StructuredFlow.test_case_id == case.id)
            .order_by(StructuredFlow.version.desc())
        ).first()
        flow.status = "needs_review"
        session.add(case)
        session.add(flow)
        session.commit()

        with pytest.raises(ValueError, match="requires structure review"):
            generate_project(session, project_id, project_root, [case.id])

        assert generated_page.read_bytes() == previous_page
