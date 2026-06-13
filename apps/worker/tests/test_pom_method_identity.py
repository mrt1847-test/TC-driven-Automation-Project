from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from sqlmodel import Session, select

from worker.models.db import (
    CaseActionMapping,
    CaseActionMappingAction,
    GeneratedFile,
    GeneratedFileOrigin,
    PageObject,
    PageObjectMethod,
    RawAction,
    StructuredFlow,
    StructuredStep,
    TestCase as DbTestCase,
    WebwrightRun,
)
from worker.services.project_generator import generate_project, retire_generated_case
from worker.services.structuring_service import merge_refreshed_raw_actions, sync_structured_entities


def _patch_generator(monkeypatch, tmp_path: Path) -> None:
    import worker.services.project_generator as project_generator

    template = tmp_path / "identity-template"
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
    case_id: str,
    automation_key: str,
    method_name: str,
    selector: str,
) -> DbTestCase:
    case = DbTestCase(
        id=case_id,
        project_id=project_id,
        source_type="manual",
        source_case_id=case_id,
        title=f"{automation_key} case",
        steps_json=json.dumps([{"index": 1, "action": method_name}]),
        automation_key=automation_key,
        status="mapped",
    )
    run = WebwrightRun(
        id=f"ww_{case_id}",
        project_id=project_id,
        test_case_id=case_id,
        automation_key=automation_key,
        status="completed",
    )
    action = RawAction(
        id=f"act_{case_id}",
        webwright_run_id=run.id,
        automation_key=automation_key,
        order_index=1,
        type="click",
        selector=selector,
        target="click target",
    )
    mapping = CaseActionMapping(
        id=f"map_{case_id}",
        test_case_id=case_id,
        raw_action_id=action.id,
        tc_step_index=1,
        normalized_step_id=f"flow_{case_id}",
        normalized_step_name=method_name,
        pom_method_name=method_name,
        status="mapped",
    )
    session.add(case)
    session.add(run)
    session.add(action)
    session.add(mapping)
    session.add(CaseActionMappingAction(
        mapping_id=mapping.id,
        raw_action_id=action.id,
        order_index=0,
    ))
    return case


def _sync_method(session: Session, project_id: str, case: DbTestCase) -> PageObjectMethod:
    run = session.exec(select(WebwrightRun).where(WebwrightRun.test_case_id == case.id)).one()
    sync_structured_entities(session, project_id, case, run)
    session.commit()
    return session.exec(
        select(PageObjectMethod).where(PageObjectMethod.source_mapping_id == f"map_{case.id}")
    ).one()


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
        for row in session.exec(select(GeneratedFile).where(GeneratedFile.project_id == project_id)).all()
    }


def _replace_protected_region(content: str, name: str, body: str) -> str:
    begin = f'# <tc-protected name="{name}">'
    end = "# </tc-protected>"
    begin_index = content.index(begin)
    body_start = content.index("\n", begin_index) + 1
    end_index = content.index(end, body_start)
    end_line_start = content.rfind("\n", 0, end_index) + 1
    return content[:body_start] + body + content[end_line_start:]


def test_same_method_text_across_cases_creates_case_scoped_poms(project_id: str) -> None:
    import worker.core.database as database

    with Session(database.engine) as session:
        first = _seed_case(
            session,
            project_id=project_id,
            case_id="tc_identity_first",
            automation_key="identity_first",
            method_name="submit_login",
            selector="page.locator('#first-submit')",
        )
        second = _seed_case(
            session,
            project_id=project_id,
            case_id="tc_identity_second",
            automation_key="identity_second",
            method_name="submit_login",
            selector="page.locator('#second-submit')",
        )
        session.commit()

        first_method = _sync_method(session, project_id, first)
        second_method = _sync_method(session, project_id, second)

        assert first_method.id != second_method.id
        assert first_method.name == "identity_first__step_1_submit_login"
        assert second_method.name == "identity_second__step_1_submit_login"
        assert "first-submit" in first_method.body_plan_json
        assert "second-submit" in second_method.body_plan_json
        assert "second-submit" not in first_method.body_plan_json
        assert "first-submit" not in second_method.body_plan_json


def test_identical_body_plans_do_not_share_cross_case_identity(project_id: str) -> None:
    import worker.core.database as database

    with Session(database.engine) as session:
        first = _seed_case(
            session,
            project_id=project_id,
            case_id="tc_identity_same_first",
            automation_key="identity_same_first",
            method_name="open_details",
            selector="page.get_by_role('link', name='Details')",
        )
        second = _seed_case(
            session,
            project_id=project_id,
            case_id="tc_identity_same_second",
            automation_key="identity_same_second",
            method_name="open_details",
            selector="page.get_by_role('link', name='Details')",
        )
        session.commit()

        first_method = _sync_method(session, project_id, first)
        second_method = _sync_method(session, project_id, second)

        assert first_method.id != second_method.id
        assert first_method.name.endswith("__step_1_open_details")
        assert second_method.name.endswith("__step_1_open_details")
        assert json.loads(first_method.body_plan_json)[0]["selector"] == json.loads(second_method.body_plan_json)[0]["selector"]


def test_raw_refresh_repairs_legacy_shared_method_before_merge(project_id: str) -> None:
    import worker.core.database as database

    with Session(database.engine) as session:
        selected = _seed_case(
            session,
            project_id=project_id,
            case_id="tc_identity_refresh_selected",
            automation_key="identity_refresh_selected",
            method_name="submit_login",
            selector="page.locator('#legacy-selected')",
        )
        unrelated = _seed_case(
            session,
            project_id=project_id,
            case_id="tc_identity_refresh_unrelated",
            automation_key="identity_refresh_unrelated",
            method_name="submit_login",
            selector="page.locator('#legacy-unrelated')",
        )
        page = PageObject(
            id="po_identity_legacy",
            project_id=project_id,
            name="GeneratedPage",
            file_path="pages/generated_page.py",
        )
        shared_method = PageObjectMethod(
            id="pom_identity_legacy_shared",
            page_object_id=page.id,
            name="submit_login",
            method_type="click",
            selector="page.locator('#legacy-selected')",
            body_plan_json=json.dumps([{
                "action": "click",
                "order": 1,
                "requiresReview": False,
                "selector": "page.locator('#legacy-selected')",
                "sourceMappingId": "map_tc_identity_refresh_selected",
                "sourceRawActionId": "act_tc_identity_refresh_selected",
            }], sort_keys=True, separators=(",", ":")),
            source_mapping_id="map_tc_identity_refresh_selected",
            status="approved",
        )
        selected_flow = StructuredFlow(
            id="sf_identity_refresh_selected",
            project_id=project_id,
            test_case_id=selected.id,
            automation_key=selected.automation_key,
            name="IdentityRefreshSelectedFlow",
            status="approved",
            version=1,
        )
        unrelated_flow = StructuredFlow(
            id="sf_identity_refresh_unrelated",
            project_id=project_id,
            test_case_id=unrelated.id,
            automation_key=unrelated.automation_key,
            name="IdentityRefreshUnrelatedFlow",
            status="approved",
            version=1,
        )
        session.add(page)
        session.add(shared_method)
        session.add(selected_flow)
        session.add(unrelated_flow)
        session.add(StructuredStep(
            id="ss_identity_refresh_selected",
            structured_flow_id=selected_flow.id,
            mapping_id="map_tc_identity_refresh_selected",
            order_index=1,
            name="submit_login",
            page_object_method_id=shared_method.id,
        ))
        session.add(StructuredStep(
            id="ss_identity_refresh_unrelated",
            structured_flow_id=unrelated_flow.id,
            mapping_id="map_tc_identity_refresh_unrelated",
            order_index=1,
            name="submit_login",
            page_object_method_id=shared_method.id,
        ))
        refresh_run = WebwrightRun(
            id="ww_identity_refresh_new",
            project_id=project_id,
            test_case_id=selected.id,
            automation_key=selected.automation_key,
            status="completed",
        )
        refresh_action = RawAction(
            id="act_identity_refresh_new",
            webwright_run_id=refresh_run.id,
            automation_key=selected.automation_key,
            order_index=1,
            type="click",
            selector="page.get_by_role('button', name='Continue')",
            target="click target",
        )
        session.add(refresh_run)
        session.add(refresh_action)
        session.commit()

        result = merge_refreshed_raw_actions(session, project_id, selected, refresh_run)

        selected_step = session.get(StructuredStep, "ss_identity_refresh_selected")
        unrelated_step = session.get(StructuredStep, "ss_identity_refresh_unrelated")
        repaired = session.get(PageObjectMethod, selected_step.page_object_method_id)
        legacy = session.get(PageObjectMethod, shared_method.id)

        assert result["status"] == "merged"
        assert repaired.id != legacy.id
        assert repaired.name == "identity_refresh_selected__step_1_submit_login"
        assert "Continue" in repaired.body_plan_json
        assert selected_step.page_object_method_id == repaired.id
        assert unrelated_step.page_object_method_id == legacy.id


def test_scoped_methods_survive_selected_generation_and_retire_cleanup(
    monkeypatch,
    tmp_path: Path,
    project_id: str,
) -> None:
    import worker.core.database as database

    _patch_generator(monkeypatch, tmp_path)
    project_root = tmp_path / "identity-project"
    with Session(database.engine) as session:
        selected = _seed_case(
            session,
            project_id=project_id,
            case_id="tc_identity_retire_selected",
            automation_key="identity_retire_selected",
            method_name="shared_submit",
            selector="page.locator('#selected-submit')",
        )
        unrelated = _seed_case(
            session,
            project_id=project_id,
            case_id="tc_identity_retire_unrelated",
            automation_key="identity_retire_unrelated",
            method_name="shared_submit",
            selector="page.locator('#unrelated-submit')",
        )
        session.commit()

        generated = generate_project(session, project_id, project_root, mode="full")
        page_path = generated.output / "pages" / "generated_page.py"
        page_source = page_path.read_text(encoding="utf-8")
        assert "def identity_retire_selected__step_1_shared_submit" in page_source
        assert "def identity_retire_unrelated__step_1_shared_submit" in page_source

        selected_result = generate_project(session, project_id, project_root, [selected.id])
        assert selected_result.mode == "incremental"
        page_source = page_path.read_text(encoding="utf-8")
        assert "def identity_retire_selected__step_1_shared_submit" in page_source
        assert "def identity_retire_unrelated__step_1_shared_submit" in page_source
        helper_body = (
            "    def manual_retire_helper(self):\n"
            "        return \"preserved during retire\"\n"
        )
        page_path.write_text(
            _replace_protected_region(
                page_source,
                "generated-page-helpers",
                helper_body,
            ),
            encoding="utf-8",
        )

        retire_result = retire_generated_case(
            session,
            project_id,
            generated.output,
            selected.id,
            action="retire",
        )
        page_source = page_path.read_text(encoding="utf-8")
        by_path = _generated_by_path(session, project_id)
        page_origins = _origins(session, by_path["pages/generated_page.py"].id)

        assert retire_result["status"] == "completed"
        assert "pages/generated_page.py" in retire_result["updatedFiles"]
        assert "def identity_retire_selected__step_1_shared_submit" not in page_source
        assert "def identity_retire_unrelated__step_1_shared_submit" in page_source
        assert helper_body in page_source
        assert ("test_case", selected.id) not in page_origins
        assert ("test_case", unrelated.id) in page_origins
