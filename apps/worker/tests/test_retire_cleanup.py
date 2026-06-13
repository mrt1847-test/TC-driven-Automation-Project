from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import yaml
from sqlmodel import Session, select

from worker.models.db import (
    ArtifactAsset,
    CaseActionMapping,
    CaseActionMappingAction,
    ExecutionResult,
    ExecutionRun,
    GeneratedFile,
    GeneratedFileOrigin,
    PageObjectMethod,
    Project,
    RawAction,
    StructuredFlow,
    StructuredStep,
    TestCase as DbTestCase,
    WebwrightRun,
)
from worker.services.generated_file_status import hash_file
from worker.services.project_generator import generate_project


def _patch_generator(monkeypatch, tmp_path) -> None:
    import worker.services.project_generator as project_generator

    template = tmp_path / "retire-template"
    (template / "runner").mkdir(parents=True)
    (template / "runner" / "cli.py").write_text("# runtime\n", encoding="utf-8")
    (template / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    monkeypatch.setattr(project_generator, "load_settings", lambda: None)
    monkeypatch.setattr(
        project_generator,
        "resolve_runtime",
        lambda _settings: SimpleNamespace(template_path=str(template)),
    )


def _seed_case(
    session: Session,
    *,
    project_id: str,
    case: DbTestCase,
    suffix: str,
    method_name: str,
) -> tuple[str, str]:
    run_id = f"ww_retire_{suffix}"
    action_id = f"raw_retire_{suffix}"
    mapping_id = f"map_retire_{suffix}"
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
        normalized_step_name=method_name,
        pom_method_name=method_name,
        status="mapped",
    ))
    session.add(CaseActionMappingAction(
        mapping_id=mapping_id,
        raw_action_id=action_id,
        order_index=0,
    ))
    return run_id, action_id


def _origins(session: Session, generated_file_id: str) -> set[tuple[str, str]]:
    return {
        (row.origin_type, row.origin_id)
        for row in session.exec(
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


def _file_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_confirmed_retire_cleans_selected_files_and_preserves_shared_history(
    monkeypatch,
    client,
    tmp_path,
    project_id: str,
    imported_case: dict,
) -> None:
    import worker.core.database as database

    _patch_generator(monkeypatch, tmp_path)
    selected_id = imported_case["id"]
    unrelated_id = "tc_retire_unrelated"
    shared_method = "shared_submit"

    with Session(database.engine) as session:
        selected = session.get(DbTestCase, selected_id)
        unrelated = DbTestCase(
            id=unrelated_id,
            project_id=project_id,
            source_type="excel",
            source_case_id="TC-RETIRE-UNRELATED",
            title="Unrelated retire case",
            automation_key="retire_unrelated",
        )
        selected_run_id, selected_action_id = _seed_case(
            session,
            project_id=project_id,
            case=selected,
            suffix="selected",
            method_name=shared_method,
        )
        _seed_case(
            session,
            project_id=project_id,
            case=unrelated,
            suffix="unrelated",
            method_name=shared_method,
        )
        session.commit()
        project = session.get(Project, project_id)
        generated = generate_project(session, project_id, Path(project.root_path), mode="full")
        output = generated.output
        artifact_file = output / "artifacts" / "runs" / "selected" / "result.json"
        artifact_file.parent.mkdir(parents=True)
        artifact_file.write_text('{"history": true}\n', encoding="utf-8")
        runtime_file = output / "runner" / "custom_runtime.py"
        runtime_file.write_text("# preserve runtime\n", encoding="utf-8")

        selected_key = selected.automation_key
        selected_test = f"tests/test_{selected_key}.py"
        selected_flow_file = f"flows/{selected_key}_flow.py"
        unrelated_test = "tests/test_retire_unrelated.py"
        unrelated_flow_file = "flows/retire_unrelated_flow.py"
        by_path = _generated_by_path(session, project_id)
        unrelated_snapshot = {
            "test": (output / unrelated_test).read_bytes(),
            "flow": (output / unrelated_flow_file).read_bytes(),
            "test_id": by_path[unrelated_test].id,
            "flow_id": by_path[unrelated_flow_file].id,
            "test_origins": _origins(session, by_path[unrelated_test].id),
            "flow_origins": _origins(session, by_path[unrelated_flow_file].id),
        }
        selected_flow = session.exec(
            select(StructuredFlow).where(StructuredFlow.test_case_id == selected_id)
        ).one()
        selected_step = session.exec(
            select(StructuredStep).where(StructuredStep.structured_flow_id == selected_flow.id)
        ).one()
        selected_flow_id = selected_flow.id
        selected_step_id = selected_step.id
        shared_pom_id = selected_step.page_object_method_id
        session.add(ArtifactAsset(
            id="artifact_retire_selected",
            project_id=project_id,
            automation_key=selected_key,
            source_type="webwright_run",
            source_id=selected_run_id,
            artifact_type="final_script",
            file_path="prior/final_script.py",
        ))
        session.add(ExecutionRun(
            id="execution_retire_selected",
            project_id=project_id,
            run_id="run_retire_selected",
            env="stg",
            browser="chromium",
        ))
        session.add(ExecutionResult(
            id="result_retire_selected",
            execution_run_id="execution_retire_selected",
            automation_key=selected_key,
            status="failed",
        ))
        session.commit()

    response = client.post(
        f"/projects/{project_id}/cases/{selected_id}/retire",
        json={"confirmed": True, "action": "retire", "reason": "human confirmed obsolete area"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["action"] == "retire"
    assert body["caseStatus"] == "retired"
    assert body["reason"] == "human confirmed obsolete area"
    assert sorted(body["removedFiles"]) == sorted([selected_test, selected_flow_file])
    assert body["updatedFiles"] == ["mappings/cases.yaml", "pages/generated_page.py"]
    assert body["preservedSharedFiles"] == ["mappings/cases.yaml", "pages/generated_page.py"]
    assert unrelated_test in body["preservedFiles"]
    assert unrelated_flow_file in body["preservedFiles"]
    assert "artifacts/runs/selected/result.json" in body["preservedFiles"]
    assert "runner/custom_runtime.py" in body["preservedFiles"]
    assert not (output / selected_test).exists()
    assert not (output / selected_flow_file).exists()
    assert (output / unrelated_test).read_bytes() == unrelated_snapshot["test"]
    assert (output / unrelated_flow_file).read_bytes() == unrelated_snapshot["flow"]
    assert artifact_file.read_text(encoding="utf-8") == '{"history": true}\n'
    assert runtime_file.read_text(encoding="utf-8") == "# preserve runtime\n"
    assert shared_method in (output / "pages" / "generated_page.py").read_text(encoding="utf-8")
    mapping_entries = yaml.safe_load(
        (output / "mappings" / "cases.yaml").read_text(encoding="utf-8")
    )["cases"]
    assert [entry["automationKey"] for entry in mapping_entries] == ["retire_unrelated"]

    with Session(database.engine) as session:
        assert session.get(DbTestCase, selected_id).status == "retired"
        assert session.get(WebwrightRun, selected_run_id) is not None
        assert session.get(RawAction, selected_action_id) is not None
        assert session.get(ArtifactAsset, "artifact_retire_selected") is not None
        assert session.get(ExecutionRun, "execution_retire_selected") is not None
        assert session.get(ExecutionResult, "result_retire_selected") is not None
        assert session.get(StructuredFlow, selected_flow_id) is not None
        assert session.get(StructuredStep, selected_step_id) is not None
        assert session.get(PageObjectMethod, shared_pom_id) is not None

        by_path = _generated_by_path(session, project_id)
        assert by_path[selected_test].status == "obsolete"
        assert by_path[selected_flow_file].status == "obsolete"
        assert ("test_case", selected_id) in _origins(session, by_path[selected_test].id)
        page_origins = _origins(session, by_path["pages/generated_page.py"].id)
        mapping_origins = _origins(session, by_path["mappings/cases.yaml"].id)
        assert ("test_case", selected_id) not in page_origins
        assert ("test_case", selected_id) not in mapping_origins
        assert ("test_case", unrelated_id) in page_origins
        assert ("test_case", unrelated_id) in mapping_origins
        assert by_path[unrelated_test].id == unrelated_snapshot["test_id"]
        assert by_path[unrelated_flow_file].id == unrelated_snapshot["flow_id"]
        assert _origins(session, by_path[unrelated_test].id) == unrelated_snapshot["test_origins"]
        assert _origins(session, by_path[unrelated_flow_file].id) == unrelated_snapshot["flow_origins"]


def test_retire_cleanup_requires_explicit_confirmation(
    client,
    project_id: str,
    imported_case: dict,
) -> None:
    response = client.post(
        f"/projects/{project_id}/cases/{imported_case['id']}/retire",
        json={"action": "retire"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Retire cleanup requires confirmed=true"
    assert client.get(
        f"/projects/{project_id}/cases/{imported_case['id']}"
    ).json()["status"] == "imported"


def test_retire_preview_reports_impact_without_mutation(
    monkeypatch,
    client,
    tmp_path,
    project_id: str,
    imported_case: dict,
) -> None:
    _patch_generator(monkeypatch, tmp_path)
    generate = client.post(f"/projects/{project_id}/generate", json={"mode": "full"})
    assert generate.status_code == 200

    preview = client.post(
        f"/projects/{project_id}/cases/{imported_case['id']}/retire/preview",
        json={"action": "retire"},
    )
    assert preview.status_code == 200
    body = preview.json()
    assert body["preview"] is True
    assert body["status"] in {"preview", "conflict"}
    assert body["automationKey"] == imported_case["automation_key"]
    assert isinstance(body.get("affectedFiles"), list)
    assert isinstance(body.get("preservedFiles"), list)

    assert client.get(
        f"/projects/{project_id}/cases/{imported_case['id']}"
    ).json()["status"] == "imported"


def test_edited_generated_file_stops_retire_cleanup_without_other_writes(
    monkeypatch,
    client,
    tmp_path,
    project_id: str,
    imported_case: dict,
) -> None:
    import worker.core.database as database

    _patch_generator(monkeypatch, tmp_path)
    case_id = imported_case["id"]
    with Session(database.engine) as session:
        case = session.get(DbTestCase, case_id)
        _seed_case(
            session,
            project_id=project_id,
            case=case,
            suffix="edited",
            method_name="edited_method",
        )
        session.commit()
        project = session.get(Project, project_id)
        output = generate_project(session, project_id, Path(project.root_path), mode="full").output
        selected_test = output / "tests" / f"test_{case.automation_key}.py"
        selected_test.write_text(selected_test.read_text(encoding="utf-8") + "# human edit\n", encoding="utf-8")
        before = _file_snapshot(output)

    response = client.post(
        f"/projects/{project_id}/cases/{case_id}/retire",
        json={"confirmed": True, "action": "retire"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "conflict"
    assert selected_test.relative_to(output).as_posix() in body["conflictFiles"]
    assert body["removedFiles"] == []
    assert body["updatedFiles"] == []
    assert _file_snapshot(output) == before
    with Session(database.engine) as session:
        assert session.get(DbTestCase, case_id).status == "generated"
        row = _generated_by_path(session, project_id)[selected_test.relative_to(output).as_posix()]
        assert row.status == "conflict"


def test_unproven_shared_file_stops_retire_cleanup(
    monkeypatch,
    client,
    tmp_path,
    project_id: str,
    imported_case: dict,
) -> None:
    import worker.core.database as database

    _patch_generator(monkeypatch, tmp_path)
    selected_id = imported_case["id"]
    unrelated_id = "tc_retire_shared_unrelated"
    with Session(database.engine) as session:
        selected = session.get(DbTestCase, selected_id)
        unrelated = DbTestCase(
            id=unrelated_id,
            project_id=project_id,
            source_type="excel",
            source_case_id="TC-RETIRE-SHARED",
            title="Shared cleanup case",
            automation_key="retire_shared_unrelated",
        )
        _seed_case(
            session,
            project_id=project_id,
            case=selected,
            suffix="shared_selected",
            method_name="selected_shared_method",
        )
        _seed_case(
            session,
            project_id=project_id,
            case=unrelated,
            suffix="shared_unrelated",
            method_name="unrelated_shared_method",
        )
        session.commit()
        project = session.get(Project, project_id)
        output = generate_project(session, project_id, Path(project.root_path), mode="full").output
        shared_file = output / "helpers" / "custom_shared.py"
        shared_file.parent.mkdir(parents=True)
        shared_file.write_text("# shared\n", encoding="utf-8")
        shared_row = GeneratedFile(
            id="gf_unproven_shared",
            project_id=project_id,
            relative_path="helpers/custom_shared.py",
            content_hash=hash_file(shared_file),
            status="generated",
        )
        session.add(shared_row)
        session.add(GeneratedFileOrigin(
            generated_file_id=shared_row.id,
            origin_type="test_case",
            origin_id=selected_id,
        ))
        session.add(GeneratedFileOrigin(
            generated_file_id=shared_row.id,
            origin_type="test_case",
            origin_id=unrelated_id,
        ))
        session.commit()
        before = _file_snapshot(output)

    response = client.post(
        f"/projects/{project_id}/cases/{selected_id}/retire",
        json={"confirmed": True, "action": "retire"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "conflict"
    assert "helpers/custom_shared.py" in body["conflictFiles"]
    assert _file_snapshot(output) == before
    with Session(database.engine) as session:
        assert session.get(DbTestCase, selected_id).status == "generated"
        assert session.get(GeneratedFile, "gf_unproven_shared").status == "conflict"


def test_delete_action_is_soft_and_keeps_case_queryable(
    client,
    project_id: str,
    imported_case: dict,
) -> None:
    response = client.post(
        f"/projects/{project_id}/cases/{imported_case['id']}/retire",
        json={"confirmed": True, "action": "delete"},
    )

    assert response.status_code == 200
    assert response.json()["caseStatus"] == "deleted"
    case = client.get(f"/projects/{project_id}/cases/{imported_case['id']}")
    assert case.status_code == 200
    assert case.json()["status"] == "deleted"
