from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlmodel import Session, select

from worker.models.db import (
    CaseActionMapping,
    CaseActionMappingAction,
    PageObjectMethod,
    Project,
    RawAction,
    SelectorCandidate,
    SelectorCandidateType,
    TestCase as DbTestCase,
    WebwrightRun,
)
from worker.services.project_generator import generate_project
from worker.services.structuring_service import merge_refreshed_raw_actions, sync_structured_entities


def _seed_case(
    session: Session,
    *,
    project_id: str,
    suffix: str,
    actions: list[dict[str, Any]],
) -> tuple[DbTestCase, WebwrightRun, list[str], str]:
    case = DbTestCase(
        id=f"tc_selector_rank_{suffix}",
        project_id=project_id,
        source_type="excel",
        source_case_id=f"TC-SELECTOR-{suffix.upper()}",
        title=f"Selector rank {suffix}",
        automation_key=f"selector_rank_{suffix}",
        steps_json=json.dumps([{"index": 1, "action": "Click submit"}]),
        status="mapped",
    )
    run = WebwrightRun(
        id=f"ww_selector_rank_{suffix}",
        project_id=project_id,
        test_case_id=case.id,
        automation_key=case.automation_key,
        status="completed",
    )
    session.add(case)
    session.add(run)

    action_ids: list[str] = []
    for order_index, spec in enumerate(actions, start=1):
        action_id = f"act_selector_rank_{suffix}_{order_index}"
        action_ids.append(action_id)
        session.add(RawAction(
            id=action_id,
            webwright_run_id=run.id,
            automation_key=case.automation_key,
            order_index=order_index,
            type=spec.get("type", "click"),
            selector=spec.get("selector"),
            target=spec.get("target", "Submit"),
            value=spec.get("value"),
        ))

    mapping_id = f"map_selector_rank_{suffix}"
    session.add(CaseActionMapping(
        id=mapping_id,
        test_case_id=case.id,
        raw_action_id=action_ids[0],
        tc_step_index=1,
        normalized_step_id="flow_001",
        normalized_step_name="submit",
        pom_method_name="submit",
        status="mapped",
    ))
    for order_index, action_id in enumerate(action_ids):
        session.add(CaseActionMappingAction(
            mapping_id=mapping_id,
            raw_action_id=action_id,
            order_index=order_index,
        ))
    session.commit()
    session.refresh(case)
    session.refresh(run)
    return case, run, action_ids, mapping_id


def _add_candidate(
    session: Session,
    *,
    candidate_id: str,
    action_id: str,
    selector_type: str,
    selector_value: str,
    confidence: float,
) -> None:
    session.add(SelectorCandidate(
        id=candidate_id,
        raw_action_id=action_id,
        selector_type=selector_type,
        selector_value=selector_value,
        confidence=confidence,
        metadata_json=json.dumps({"test": "selector_ranking"}),
    ))


def _method_for_mapping(session: Session, mapping_id: str) -> PageObjectMethod:
    return session.exec(
        select(PageObjectMethod).where(PageObjectMethod.source_mapping_id == mapping_id)
    ).one()


def test_selector_ranking_prefers_test_id_and_generated_code_uses_ranked_selector(
    monkeypatch,
    tmp_path: Path,
    project_id: str,
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

    with Session(database.engine) as session:
        project = session.get(Project, project_id)
        project.root_path = str(tmp_path / "ranked-project")
        project.generated_project_path = str(Path(project.root_path) / "generated")
        session.add(project)

        case, run, action_ids, mapping_id = _seed_case(
            session,
            project_id=project_id,
            suffix="test_id",
            actions=[{"selector": "page.locator('[data-testid=\"checkout\"]')"}],
        )
        _add_candidate(
            session,
            candidate_id="sel_rank_test_id",
            action_id=action_ids[0],
            selector_type=SelectorCandidateType.test_id.value,
            selector_value="checkout",
            confidence=0.9,
        )
        _add_candidate(
            session,
            candidate_id="sel_rank_css",
            action_id=action_ids[0],
            selector_type=SelectorCandidateType.css.value,
            selector_value="[data-testid=\"checkout\"]",
            confidence=0.99,
        )
        session.commit()

        sync_structured_entities(session, project_id, case, run)
        session.commit()

        method = _method_for_mapping(session, mapping_id)
        plan = json.loads(method.body_plan_json)
        metadata = plan[0]["selectorCandidate"]

        assert plan[0]["selector"] == 'page.get_by_test_id("checkout")'
        assert method.selector == 'page.get_by_test_id("checkout")'
        assert metadata["rawSelector"] == "page.locator('[data-testid=\"checkout\"]')"
        assert metadata["selectedCandidateId"] == "sel_rank_test_id"
        assert metadata["selectedType"] == "test_id"
        assert metadata["selectedConfidence"] == 0.9
        assert metadata["runnerUpCandidateIds"] == ["sel_rank_css"]
        assert session.get(SelectorCandidate, "sel_rank_test_id").page_object_method_id == method.id

        generated = generate_project(session, project_id, Path(project.root_path), mode="full")
        page_source = (generated.output / "pages" / "generated_page.py").read_text(encoding="utf-8")
        assert "self.page.get_by_test_id('checkout').click()" in page_source


def test_selector_ranking_prefers_role_over_text_candidate(project_id: str) -> None:
    import worker.core.database as database

    with Session(database.engine) as session:
        case, run, action_ids, mapping_id = _seed_case(
            session,
            project_id=project_id,
            suffix="role_text",
            actions=[{"selector": "page.locator('#submit')"}],
        )
        _add_candidate(
            session,
            candidate_id="sel_rank_text",
            action_id=action_ids[0],
            selector_type=SelectorCandidateType.text.value,
            selector_value="Submit",
            confidence=0.99,
        )
        _add_candidate(
            session,
            candidate_id="sel_rank_role",
            action_id=action_ids[0],
            selector_type=SelectorCandidateType.role.value,
            selector_value="button[name='Submit']",
            confidence=0.8,
        )
        session.commit()

        sync_structured_entities(session, project_id, case, run)
        session.commit()

        plan = json.loads(_method_for_mapping(session, mapping_id).body_plan_json)
        assert plan[0]["selector"] == 'page.get_by_role("button", name="Submit")'
        assert plan[0]["selectorCandidate"]["selectedCandidateId"] == "sel_rank_role"
        assert plan[0]["selectorCandidate"]["runnerUpCandidateIds"] == ["sel_rank_text"]


def test_selector_ranking_falls_back_for_low_confidence_and_ambiguity(project_id: str) -> None:
    import worker.core.database as database

    with Session(database.engine) as session:
        case, run, action_ids, mapping_id = _seed_case(
            session,
            project_id=project_id,
            suffix="fallback",
            actions=[
                {"selector": "page.locator('#low-confidence')"},
                {"selector": "page.locator('#ambiguous')"},
            ],
        )
        _add_candidate(
            session,
            candidate_id="sel_rank_low",
            action_id=action_ids[0],
            selector_type=SelectorCandidateType.test_id.value,
            selector_value="low-confidence",
            confidence=0.55,
        )
        _add_candidate(
            session,
            candidate_id="sel_rank_amb_a",
            action_id=action_ids[1],
            selector_type=SelectorCandidateType.test_id.value,
            selector_value="submit-primary",
            confidence=0.91,
        )
        _add_candidate(
            session,
            candidate_id="sel_rank_amb_b",
            action_id=action_ids[1],
            selector_type=SelectorCandidateType.test_id.value,
            selector_value="submit-secondary",
            confidence=0.91,
        )
        session.commit()

        sync_structured_entities(session, project_id, case, run)
        session.commit()

        plan = json.loads(_method_for_mapping(session, mapping_id).body_plan_json)
        assert plan[0]["selector"] == "page.locator('#low-confidence')"
        assert plan[0]["selectorCandidate"]["selectedCandidateId"] is None
        assert plan[0]["selectorCandidate"]["fallbackReason"] == "low_confidence"
        assert plan[1]["selector"] == "page.locator('#ambiguous')"
        assert plan[1]["selectorCandidate"]["selectedCandidateId"] is None
        assert plan[1]["selectorCandidate"]["fallbackReason"] == "ambiguous_candidate"
        assert plan[1]["selectorCandidate"]["runnerUpCandidateIds"] == [
            "sel_rank_amb_a",
            "sel_rank_amb_b",
        ]


def test_selector_ranking_is_reused_by_selected_raw_refresh_merge(project_id: str) -> None:
    import worker.core.database as database

    with Session(database.engine) as session:
        case, run, _action_ids, mapping_id = _seed_case(
            session,
            project_id=project_id,
            suffix="refresh_initial",
            actions=[{"selector": "page.locator('#old-submit')", "target": "Submit"}],
        )
        sync_structured_entities(session, project_id, case, run)
        session.commit()
        method_id = _method_for_mapping(session, mapping_id).id

        refresh_run = WebwrightRun(
            id="ww_selector_rank_refresh_new",
            project_id=project_id,
            test_case_id=case.id,
            automation_key=case.automation_key,
            status="completed",
        )
        refresh_action = RawAction(
            id="act_selector_rank_refresh_new",
            webwright_run_id=refresh_run.id,
            automation_key=case.automation_key,
            order_index=1,
            type="click",
            selector="page.locator('#new-submit')",
            target="Submit",
        )
        session.add(refresh_run)
        session.add(refresh_action)
        _add_candidate(
            session,
            candidate_id="sel_rank_refresh_role",
            action_id=refresh_action.id,
            selector_type=SelectorCandidateType.role.value,
            selector_value="button[name='Submit']",
            confidence=0.94,
        )
        session.commit()

        result = merge_refreshed_raw_actions(session, project_id, case, refresh_run)

        method = session.get(PageObjectMethod, method_id)
        plan = json.loads(method.body_plan_json)
        assert result["status"] == "merged"
        assert plan[0]["sourceRawActionId"] == "act_selector_rank_refresh_new"
        assert plan[0]["selector"] == 'page.get_by_role("button", name="Submit")'
        assert plan[0]["selectorCandidate"]["selectedCandidateId"] == "sel_rank_refresh_role"
        assert session.get(SelectorCandidate, "sel_rank_refresh_role").page_object_method_id == method.id
