from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlmodel import Session, select

from worker.models.db import (
    CaseActionMapping,
    CaseActionMappingAction,
    GeneratedFile,
    PageObjectMethod,
    Project,
    RawAction,
    TestCase as DbTestCase,
    WebwrightRun,
)
from worker.services.generated_file_status import refresh_generated_file_statuses
from worker.services.project_generator import generate_project


def _patch_template(monkeypatch, tmp_path: Path) -> None:
    import worker.services.project_generator as project_generator

    template = tmp_path / "status-template"
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
) -> None:
    run_id = f"ww_status_{suffix}"
    action_id = f"raw_status_{suffix}"
    mapping_id = f"map_status_{suffix}"
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
        target=f"click {suffix}",
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


def _change_planned_page_source(session: Session, selector: str) -> None:
    method = session.exec(select(PageObjectMethod)).first()
    assert method is not None
    plan = json.loads(method.body_plan_json)
    plan[0]["selector"] = selector
    method.body_plan_json = json.dumps(plan, sort_keys=True, separators=(",", ":"))
    session.add(method)


def test_generated_file_hash_mismatch_is_edited_and_visible_in_validation(
    monkeypatch,
    tmp_path,
    client,
    project_id: str,
    imported_case: dict,
) -> None:
    import worker.core.database as database

    _patch_template(monkeypatch, tmp_path)
    project_root = tmp_path / "edited-project"

    with Session(database.engine) as session:
        case = session.get(DbTestCase, imported_case["id"])
        _seed_case(session, project_id=project_id, case=case, suffix="edited")
        session.commit()
        result = generate_project(session, project_id, project_root, mode="full")
        project = session.get(Project, project_id)
        project.generated_project_path = str(result.output)
        session.add(project)
        session.commit()

        selected_path = f"tests/test_{case.automation_key}.py"
        target = result.output / selected_path
        target.write_text(target.read_text(encoding="utf-8") + "\n# user edit\n", encoding="utf-8")

    validation = client.get(
        f"/projects/{project_id}/cases/{imported_case['id']}/structure/validate"
    )
    assert validation.status_code == 200
    assert f"generated_file_edited:{selected_path}" in validation.json()["issues"]

    with Session(database.engine) as session:
        row = session.exec(
            select(GeneratedFile).where(
                GeneratedFile.project_id == project_id,
                GeneratedFile.relative_path == selected_path,
            )
        ).first()
        assert row.status == "edited"


def test_source_changed_untouched_file_is_stale_before_incremental_rewrite(
    monkeypatch,
    tmp_path,
    project_id: str,
    imported_case: dict,
) -> None:
    import worker.core.database as database

    _patch_template(monkeypatch, tmp_path)
    project_root = tmp_path / "stale-project"

    with Session(database.engine) as session:
        case = session.get(DbTestCase, imported_case["id"])
        _seed_case(session, project_id=project_id, case=case, suffix="stale")
        session.commit()
        generate_project(session, project_id, project_root, mode="full")

        _change_planned_page_source(session, "page.locator('#changed-stale')")
        session.commit()

        result = generate_project(session, project_id, project_root, [case.id])

        assert "pages/generated_page.py" in result.stale_files
        page_row = session.exec(
            select(GeneratedFile).where(
                GeneratedFile.project_id == project_id,
                GeneratedFile.relative_path == "pages/generated_page.py",
            )
        ).first()
        assert page_row.status == "generated"


def test_source_changed_edited_file_becomes_conflict_without_overwrite(
    monkeypatch,
    tmp_path,
    project_id: str,
    imported_case: dict,
) -> None:
    import worker.core.database as database

    _patch_template(monkeypatch, tmp_path)
    project_root = tmp_path / "conflict-project"

    with Session(database.engine) as session:
        case = session.get(DbTestCase, imported_case["id"])
        _seed_case(session, project_id=project_id, case=case, suffix="conflict")
        session.commit()
        result = generate_project(session, project_id, project_root, mode="full")
        page_path = result.output / "pages" / "generated_page.py"
        previous_content = page_path.read_text(encoding="utf-8")
        user_content = previous_content + "\n# user edit\n"
        page_path.write_text(user_content, encoding="utf-8")

        _change_planned_page_source(session, "page.locator('#changed-conflict')")
        session.commit()

        with pytest.raises(ValueError, match="Generated files require review"):
            generate_project(session, project_id, project_root, [case.id])

        assert page_path.read_text(encoding="utf-8") == user_content
        page_row = session.exec(
            select(GeneratedFile).where(
                GeneratedFile.project_id == project_id,
                GeneratedFile.relative_path == "pages/generated_page.py",
            )
        ).first()
        assert page_row.status == "conflict"


def test_status_refresh_marks_source_changed_and_edited_as_conflict(
    monkeypatch,
    tmp_path,
    project_id: str,
    imported_case: dict,
) -> None:
    import worker.core.database as database

    _patch_template(monkeypatch, tmp_path)
    project_root = tmp_path / "direct-conflict-project"

    with Session(database.engine) as session:
        case = session.get(DbTestCase, imported_case["id"])
        _seed_case(session, project_id=project_id, case=case, suffix="direct")
        session.commit()
        result = generate_project(session, project_id, project_root, mode="full")
        selected_path = f"tests/test_{case.automation_key}.py"
        target = result.output / selected_path
        target.write_text(target.read_text(encoding="utf-8") + "\n# user edit\n", encoding="utf-8")

        statuses = refresh_generated_file_statuses(
            session,
            project_id,
            result.output,
            planned_contents={selected_path: "def test_changed():\n    pass\n"},
            commit=True,
        )

        assert statuses[selected_path]["status"] == "conflict"
        assert statuses[selected_path]["onDiskChanged"] is True
        assert statuses[selected_path]["sourceChanged"] is True
