from __future__ import annotations

import json

from sqlmodel import Session, select

from worker.models.db import (
    CaseActionMapping,
    CaseActionMappingAction,
    PageObjectMethod,
    RawAction,
    StructuredFlow,
    StructuredStep,
    TestCase as DbTestCase,
    WebwrightRun,
)
from worker.services.structuring_service import sync_structured_entities, validate_structure


def _add_action(
    session: Session,
    *,
    action_id: str,
    run_id: str,
    automation_key: str,
    order_index: int,
    action_type: str,
    selector: str | None = None,
    value: str | None = None,
    target: str | None = None,
) -> None:
    session.add(RawAction(
        id=action_id,
        webwright_run_id=run_id,
        automation_key=automation_key,
        order_index=order_index,
        type=action_type,
        selector=selector,
        value=value,
        target=target,
    ))


def _add_mapping(
    session: Session,
    *,
    mapping_id: str,
    case_id: str,
    action_ids: list[str],
    method_name: str,
) -> None:
    session.add(CaseActionMapping(
        id=mapping_id,
        test_case_id=case_id,
        tc_step_index=1,
        normalized_step_id="flow_001",
        normalized_step_name=method_name,
        pom_method_name=method_name,
        raw_action_id=action_ids[0] if action_ids else None,
        status="mapped",
    ))
    for order_index, action_id in enumerate(action_ids):
        session.add(CaseActionMappingAction(
            mapping_id=mapping_id,
            raw_action_id=action_id,
            order_index=order_index,
        ))


def test_structuring_planner_compiles_ordered_multi_action_plan(
    project_id: str,
    imported_case: dict,
) -> None:
    import worker.core.database as database

    case_id = imported_case["id"]
    automation_key = imported_case["automation_key"]
    action_ids = [
        "plan_fill",
        "plan_select",
        "plan_check",
        "plan_upload",
        "plan_wait",
        "plan_assert",
    ]

    with Session(database.engine) as session:
        old_run = WebwrightRun(
            id="wwr_plan_old",
            project_id=project_id,
            test_case_id=case_id,
            automation_key=automation_key,
            status="completed",
        )
        latest_run = WebwrightRun(
            id="wwr_plan_latest",
            project_id=project_id,
            test_case_id=case_id,
            automation_key=automation_key,
            status="completed",
        )
        session.add(old_run)
        session.add(latest_run)
        _add_action(
            session,
            action_id="plan_fill",
            run_id=old_run.id,
            automation_key=automation_key,
            order_index=1,
            action_type="fill",
            selector="page.get_by_label('Email')",
            value="${env.user.email}",
        )
        _add_action(
            session,
            action_id="plan_select",
            run_id=old_run.id,
            automation_key=automation_key,
            order_index=2,
            action_type="select",
            selector="page.locator('#role')",
            value="${data.role}",
        )
        _add_action(
            session,
            action_id="plan_check",
            run_id=old_run.id,
            automation_key=automation_key,
            order_index=3,
            action_type="check",
            selector="page.locator('#terms')",
        )
        _add_action(
            session,
            action_id="plan_upload",
            run_id=latest_run.id,
            automation_key=automation_key,
            order_index=4,
            action_type="set_input_files",
            selector="page.locator('#avatar')",
            value="${data.avatar_path}",
        )
        _add_action(
            session,
            action_id="plan_wait",
            run_id=latest_run.id,
            automation_key=automation_key,
            order_index=5,
            action_type="wait",
            value="networkidle",
        )
        _add_action(
            session,
            action_id="plan_assert",
            run_id=latest_run.id,
            automation_key=automation_key,
            order_index=6,
            action_type="assert_visible",
            selector="page.get_by_text('Dashboard')",
        )
        _add_mapping(
            session,
            mapping_id="map_ordered_plan",
            case_id=case_id,
            action_ids=action_ids,
            method_name="complete_login",
        )
        session.commit()

        case = session.get(DbTestCase, case_id)
        sync_structured_entities(session, project_id, case, latest_run)
        session.commit()

        pom = session.exec(
            select(PageObjectMethod).where(PageObjectMethod.source_mapping_id == "map_ordered_plan")
        ).one()
        first_body_plan_json = pom.body_plan_json
        plan = json.loads(first_body_plan_json)
        flow = session.exec(
            select(StructuredFlow)
            .where(StructuredFlow.test_case_id == case_id)
            .order_by(StructuredFlow.version.desc())
        ).first()
        step = session.exec(
            select(StructuredStep).where(StructuredStep.structured_flow_id == flow.id)
        ).one()

        assert pom.method_type == "composite"
        assert pom.status == "approved"
        assert [entry["action"] for entry in plan] == [
            "fill",
            "select",
            "check",
            "set_input_files",
            "wait",
            "assert_visible",
        ]
        assert [entry["sourceRawActionId"] for entry in plan] == action_ids
        assert all(entry["sourceMappingId"] == "map_ordered_plan" for entry in plan)
        assert all(entry["requiresReview"] is False for entry in plan)
        assert plan[0]["value"] == "${env.user.email}"
        assert plan[1]["value"] == "${data.role}"
        assert plan[3]["value"] == "${data.avatar_path}"
        assert plan[4]["value"] == "networkidle"
        assert plan[5]["selector"] == "page.get_by_text('Dashboard')"
        assert flow.status == "approved"
        assert step.kind == "interaction"
        assert json.loads(step.metadata_json)["raw_action_ids"] == action_ids

        sync_structured_entities(session, project_id, case, latest_run)
        session.commit()
        session.refresh(pom)
        assert pom.body_plan_json == first_body_plan_json


def test_structuring_planner_preserves_unsupported_actions_and_forces_review(
    project_id: str,
    imported_case: dict,
) -> None:
    import worker.core.database as database

    case_id = imported_case["id"]
    automation_key = imported_case["automation_key"]

    with Session(database.engine) as session:
        run = WebwrightRun(
            id="wwr_plan_review",
            project_id=project_id,
            test_case_id=case_id,
            automation_key=automation_key,
            status="completed",
        )
        session.add(run)
        _add_action(
            session,
            action_id="plan_hard_wait",
            run_id=run.id,
            automation_key=automation_key,
            order_index=1,
            action_type="wait",
            value="250",
            target="page.wait_for_timeout(250)",
        )
        _add_action(
            session,
            action_id="plan_custom",
            run_id=run.id,
            automation_key=automation_key,
            order_index=2,
            action_type="custom_code",
            target="page.locator('#thing').dblclick()",
        )
        _add_mapping(
            session,
            mapping_id="map_review_plan",
            case_id=case_id,
            action_ids=["plan_hard_wait", "plan_custom"],
            method_name="review_required",
        )
        session.commit()

        case = session.get(DbTestCase, case_id)
        sync_structured_entities(session, project_id, case, run)
        session.commit()

        pom = session.exec(
            select(PageObjectMethod).where(PageObjectMethod.source_mapping_id == "map_review_plan")
        ).one()
        plan = json.loads(pom.body_plan_json)
        flow = session.exec(
            select(StructuredFlow).where(StructuredFlow.test_case_id == case_id)
        ).one()
        step = session.exec(
            select(StructuredStep).where(StructuredStep.structured_flow_id == flow.id)
        ).one()

        assert pom.method_type == "composite"
        assert pom.status == "draft"
        assert plan[0]["reviewReason"] == "hard_wait"
        assert plan[0]["requiresReview"] is True
        assert plan[1]["reviewReason"] == "unsupported_action"
        assert plan[1]["requiresReview"] is True
        assert plan[1]["target"] == "page.locator('#thing').dblclick()"
        assert flow.status == "needs_review"
        assert step.kind == "custom_code"
        assert json.loads(step.metadata_json)["requires_review"] is True
        assert session.get(DbTestCase, case_id).status == "needs_review"
        assert validate_structure(session, project_id, case_id) == {
            "ok": False,
            "issues": ["flow_needs_review"],
            "flowId": flow.id,
        }
