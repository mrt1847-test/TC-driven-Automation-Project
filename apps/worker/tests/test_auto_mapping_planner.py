from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from worker.models.db import (
    CaseActionMapping,
    CaseActionMappingAction,
    PageObjectMethod,
    RawAction,
    TestCase as DbTestCase,
    WebwrightRun,
)
from worker.services.mapping import auto_map_case, get_mappings
from worker.services.structuring_service import get_flow_steps, merge_refreshed_raw_actions, sync_structured_entities


def _add_case(
    session: Session,
    project_id: str,
    suffix: str,
    steps: list[dict[str, Any]],
) -> DbTestCase:
    case = DbTestCase(
        id=f"tc_auto_map_{suffix}",
        project_id=project_id,
        source_type="excel",
        source_case_id=f"TC-AUTO-{suffix.upper()}",
        title=f"Auto map {suffix}",
        automation_key=f"auto_map_{suffix}",
        steps_json=json.dumps(steps),
    )
    session.add(case)
    session.commit()
    session.refresh(case)
    return case


def _write_trajectory(
    tmp_path: Path,
    suffix: str,
    payload: Any | None,
) -> str | None:
    if payload is None:
        return None
    path = tmp_path / f"{suffix}_trajectory.json"
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _add_run(
    session: Session,
    tmp_path: Path,
    *,
    project_id: str,
    case: DbTestCase,
    suffix: str,
    actions: list[dict[str, Any]],
    trajectory: Any | None = None,
) -> tuple[WebwrightRun, list[str]]:
    run = WebwrightRun(
        id=f"ww_auto_map_{suffix}",
        project_id=project_id,
        test_case_id=case.id,
        automation_key=case.automation_key,
        status="completed",
        trajectory_path=_write_trajectory(tmp_path, suffix, trajectory),
    )
    session.add(run)
    action_ids: list[str] = []
    for order_index, spec in enumerate(actions, start=1):
        action_id = f"act_auto_map_{suffix}_{order_index}"
        action_ids.append(action_id)
        session.add(RawAction(
            id=action_id,
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
    return run, action_ids


def _ordered_links(session: Session, mapping_id: str) -> list[str]:
    return [
        link.raw_action_id
        for link in session.exec(
            select(CaseActionMappingAction)
            .where(CaseActionMappingAction.mapping_id == mapping_id)
            .order_by(CaseActionMappingAction.order_index)
        ).all()
    ]


def test_auto_map_groups_login_style_trajectory_actions(project_id: str, tmp_path: Path) -> None:
    import worker.core.database as database

    with Session(database.engine) as session:
        case = _add_case(
            session,
            project_id,
            "login_group",
            [{"index": 1, "action": "Log in with valid credentials", "expected": "Dashboard is shown"}],
        )
        run, action_ids = _add_run(
            session,
            tmp_path,
            project_id=project_id,
            case=case,
            suffix="login_group",
            actions=[
                {"type": "goto", "target": "https://app.example/login", "value": "https://app.example/login"},
                {"type": "fill", "selector": "page.locator('#user')", "value": "alice@example.test"},
                {"type": "fill", "selector": "page.locator('#pass')", "value": "letmein"},
                {"type": "click", "selector": "page.locator('#primary')", "target": "Sign in"},
            ],
            trajectory={
                "actions": [
                    {"orderIndex": 1, "url": "https://app.example/login", "pageTitle": "Login"},
                    {"orderIndex": 2, "accessibility": {"label": "Email address"}},
                    {"orderIndex": 3, "accessibility": {"label": "Password"}},
                    {"orderIndex": 4, "text": "Sign in", "pageTitle": "Login"},
                ]
            },
        )

        mappings, status = auto_map_case(session, case, run.id)

        assert status == "mapped"
        assert len(mappings) == 1
        assert mappings[0].status == "mapped"
        assert mappings[0].action_ids == action_ids
        assert session.get(DbTestCase, case.id).status == "mapped"

        row = session.exec(select(CaseActionMapping).where(CaseActionMapping.test_case_id == case.id)).one()
        assert row.raw_action_id == action_ids[0]
        assert _ordered_links(session, row.id) == action_ids


def test_auto_map_marks_extra_and_missing_actions_for_review(project_id: str, tmp_path: Path) -> None:
    import worker.core.database as database

    with Session(database.engine) as session:
        case = _add_case(
            session,
            project_id,
            "extra_missing",
            [
                {"index": 1, "action": "Open login page"},
                {"index": 2, "action": "Submit login"},
                {"index": 3, "action": "Verify dashboard", "expected": "Dashboard"},
                {"index": 4, "action": "Sign out"},
            ],
        )
        run, action_ids = _add_run(
            session,
            tmp_path,
            project_id=project_id,
            case=case,
            suffix="extra_missing",
            actions=[
                {"type": "goto", "target": "https://app.example/login", "value": "https://app.example/login"},
                {"type": "click", "selector": "page.get_by_role('button', name='Sign in')", "target": "Sign in"},
                {"type": "hover", "selector": "page.locator('#promo')", "target": "Marketing banner"},
                {"type": "assert_visible", "selector": "page.get_by_text('Dashboard')", "target": "Dashboard"},
            ],
        )

        mappings, status = auto_map_case(session, case, run.id)

        assert status == "needs_review"
        assert [mapping.tc_step_index for mapping in mappings] == [1, 2, 3, 4]
        assert mappings[-1].status == "unmapped"
        assert mappings[-1].action_ids == []
        extra_mapping = next(mapping for mapping in mappings if action_ids[2] in mapping.action_ids)
        assert extra_mapping.status == "needs_review"
        assert session.get(DbTestCase, case.id).status == "needs_review"


def test_auto_map_maps_assertion_only_step(project_id: str, tmp_path: Path) -> None:
    import worker.core.database as database

    with Session(database.engine) as session:
        case = _add_case(
            session,
            project_id,
            "assertion",
            [{"index": 1, "action": "Verify dashboard is visible", "expected": "Dashboard"}],
        )
        run, action_ids = _add_run(
            session,
            tmp_path,
            project_id=project_id,
            case=case,
            suffix="assertion",
            actions=[
                {"type": "assert_visible", "selector": "page.get_by_text('Dashboard')", "target": "Dashboard"},
            ],
        )

        mappings, status = auto_map_case(session, case, run.id)

        assert status == "mapped"
        assert mappings[0].status == "mapped"
        assert mappings[0].action_ids == action_ids


def test_auto_map_uses_raw_order_when_trajectory_is_malformed(project_id: str, tmp_path: Path) -> None:
    import worker.core.database as database

    with Session(database.engine) as session:
        case = _add_case(
            session,
            project_id,
            "malformed_trajectory",
            [{"index": 1, "action": "Search for invoice 123"}],
        )
        run, action_ids = _add_run(
            session,
            tmp_path,
            project_id=project_id,
            case=case,
            suffix="malformed_trajectory",
            actions=[
                {"type": "fill", "selector": "page.get_by_placeholder('Search')", "value": "invoice 123"},
                {"type": "press", "selector": "page.get_by_placeholder('Search')", "value": "Enter"},
            ],
            trajectory="{malformed",
        )

        mappings, _status = auto_map_case(session, case, run.id)

        assert len(mappings) == 1
        assert mappings[0].action_ids == action_ids
        assert get_mappings(session, case.id)[0].action_ids == action_ids


def test_auto_mapped_multi_action_chunks_survive_raw_refresh_merge(project_id: str, tmp_path: Path) -> None:
    import worker.core.database as database

    with Session(database.engine) as session:
        case = _add_case(
            session,
            project_id,
            "refresh",
            [{"index": 1, "action": "Log in with valid credentials", "expected": "Dashboard"}],
        )
        initial_run, initial_ids = _add_run(
            session,
            tmp_path,
            project_id=project_id,
            case=case,
            suffix="refresh_initial",
            actions=[
                {"type": "goto", "target": "https://app.example/login", "value": "https://app.example/login"},
                {"type": "fill", "selector": "page.get_by_label('Email')", "value": "alice@example.test"},
                {"type": "fill", "selector": "page.get_by_label('Password')", "value": "${env.credentials.password}"},
                {"type": "click", "selector": "page.get_by_role('button', name='Sign in')", "target": "Sign in"},
            ],
        )
        auto_map_case(session, case, initial_run.id)
        initial_mapping = get_mappings(session, case.id)[0]
        assert initial_mapping.action_ids == initial_ids

        flow = sync_structured_entities(session, project_id, case, initial_run)
        session.commit()
        method_id = get_flow_steps(session, flow.id)[0].page_object_method_id

        refresh_run, refresh_ids = _add_run(
            session,
            tmp_path,
            project_id=project_id,
            case=case,
            suffix="refresh_new",
            actions=[
                {"type": "goto", "target": "https://app.example/login", "value": "https://app.example/login"},
                {"type": "fill", "selector": "page.locator('[name=email]')", "value": "alice@example.test"},
                {"type": "fill", "selector": "page.locator('[name=password]')", "value": "${env.credentials.password}"},
                {"type": "click", "selector": "page.locator('button[type=submit]')", "target": "Sign in"},
            ],
        )

        result = merge_refreshed_raw_actions(session, project_id, case, refresh_run)

        assert result["status"] == "merged"
        refreshed_mapping = get_mappings(session, case.id)[0]
        assert refreshed_mapping.id == initial_mapping.id
        assert refreshed_mapping.action_ids == refresh_ids
        method = session.get(PageObjectMethod, method_id)
        plan = json.loads(method.body_plan_json)
        assert [entry["sourceRawActionId"] for entry in plan] == refresh_ids
