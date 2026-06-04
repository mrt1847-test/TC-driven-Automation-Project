from __future__ import annotations

from types import SimpleNamespace

from sqlmodel import Session, select

from worker.models.db import (
    CaseActionMapping,
    CaseActionMappingAction,
    GeneratedFile,
    GeneratedFileOrigin,
    RawAction,
    TestCase as DbTestCase,
    WebwrightRun,
)
from worker.services.project_generator import generate_project


def _seed_mapped_case(
    session: Session,
    *,
    project_id: str,
    case: DbTestCase,
    suffix: str,
) -> tuple[str, str, str]:
    run_id = f"wwr_origin_{suffix}"
    action_id = f"raw_origin_{suffix}"
    mapping_id = f"map_origin_{suffix}"
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
        normalized_step_id="flow_001",
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
    rows = session.exec(
        select(GeneratedFileOrigin).where(GeneratedFileOrigin.generated_file_id == generated_file_id)
    ).all()
    return {(row.origin_type, row.origin_id) for row in rows}


def test_generation_persists_complete_origins_and_replaces_stale_shared_links(
    monkeypatch,
    tmp_path,
    project_id: str,
    imported_case: dict,
) -> None:
    import worker.core.database as database
    import worker.services.project_generator as project_generator

    template = tmp_path / "template"
    template.mkdir()
    monkeypatch.setattr(project_generator, "load_settings", lambda: None)
    monkeypatch.setattr(
        project_generator,
        "resolve_runtime",
        lambda _settings: SimpleNamespace(template_path=str(template)),
    )

    first_case_id = imported_case["id"]
    second_case_id = "tc_origin_second"
    second_automation_key = "origin_second_case"
    project_root = tmp_path / "origin-project"

    with Session(database.engine) as session:
        first_case = session.get(DbTestCase, first_case_id)
        second_case = DbTestCase(
            id=second_case_id,
            project_id=project_id,
            source_type="excel",
            source_case_id="TC-ORIGIN-SECOND",
            title="Second origin case",
            automation_key=second_automation_key,
        )
        first_run_id, first_action_id, first_mapping_id = _seed_mapped_case(
            session,
            project_id=project_id,
            case=first_case,
            suffix="first",
        )
        second_run_id, second_action_id, second_mapping_id = _seed_mapped_case(
            session,
            project_id=project_id,
            case=second_case,
            suffix="second",
        )
        session.commit()

        generate_project(session, project_id, project_root)

        generated_files = session.exec(
            select(GeneratedFile).where(GeneratedFile.project_id == project_id)
        ).all()
        by_path = {row.relative_path: row for row in generated_files}
        assert len(by_path) == len(generated_files) == 6

        first_key = imported_case["automation_key"]
        first_test = by_path[f"tests/test_{first_key}.py"]
        first_test_origins = _origins(session, first_test.id)
        assert (first_test.source_type, first_test.source_id) in first_test_origins
        assert {
            ("test_case", first_case_id),
            ("mapping", first_mapping_id),
            ("raw_action", first_action_id),
            ("webwright_run", first_run_id),
        }.issubset(first_test_origins)
        assert {origin_type for origin_type, _origin_id in first_test_origins}.issuperset({
            "page_object",
            "page_object_method",
            "structured_flow",
            "structured_step",
        })

        shared_page = by_path["pages/generated_page.py"]
        shared_origins = _origins(session, shared_page.id)
        assert {
            ("test_case", first_case_id),
            ("test_case", second_case_id),
            ("mapping", first_mapping_id),
            ("mapping", second_mapping_id),
            ("raw_action", first_action_id),
            ("raw_action", second_action_id),
            ("webwright_run", first_run_id),
            ("webwright_run", second_run_id),
        }.issubset(shared_origins)
        assert shared_page.automation_key is None
        assert (shared_page.source_type, shared_page.source_id) in shared_origins
        old_flow_origins = {
            origin_id for origin_type, origin_id in shared_origins if origin_type == "structured_flow"
        }
        assert len(old_flow_origins) == 2

        shared_mappings = _origins(session, by_path["mappings/cases.yaml"].id)
        assert {
            ("test_case", first_case_id),
            ("test_case", second_case_id),
            ("mapping", first_mapping_id),
            ("mapping", second_mapping_id),
        }.issubset(shared_mappings)

        session.add(GeneratedFileOrigin(
            generated_file_id=shared_page.id,
            origin_type="raw_action",
            origin_id="stale_raw_action",
        ))
        duplicate = GeneratedFile(
            id="gf_duplicate_shared_page",
            project_id=project_id,
            relative_path="pages/generated_page.py",
            source_type="structured_flow",
            source_id="stale_flow",
        )
        session.add(duplicate)
        session.add(GeneratedFileOrigin(
            generated_file_id=duplicate.id,
            origin_type="structured_flow",
            origin_id="stale_flow",
        ))
        session.commit()

        generate_project(session, project_id, project_root)

        shared_rows = session.exec(
            select(GeneratedFile).where(
                GeneratedFile.project_id == project_id,
                GeneratedFile.relative_path == "pages/generated_page.py",
            )
        ).all()
        assert len(shared_rows) == 1
        refreshed_origins = _origins(session, shared_rows[0].id)
        assert ("raw_action", "stale_raw_action") not in refreshed_origins
        assert ("structured_flow", "stale_flow") not in refreshed_origins
        assert old_flow_origins.isdisjoint({
            origin_id for origin_type, origin_id in refreshed_origins if origin_type == "structured_flow"
        })
        assert {
            ("test_case", first_case_id),
            ("test_case", second_case_id),
            ("raw_action", first_action_id),
            ("raw_action", second_action_id),
        }.issubset(refreshed_origins)
