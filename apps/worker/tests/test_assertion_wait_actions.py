from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from worker.models.db import (
    CaseActionMapping,
    CaseActionMappingAction,
    PageObjectMethod,
    RawAction,
    TestCase as DbTestCase,
    WebwrightRun,
)


def _seed_case(session: Session, *, project_id: str, case_id: str, automation_key: str) -> DbTestCase:
    case = DbTestCase(
        id=case_id,
        project_id=project_id,
        source_type="manual",
        source_case_id=case_id,
        title=f"{automation_key} case",
        steps_json=json.dumps([{"index": 1, "action": "save profile"}]),
        automation_key=automation_key,
    )
    session.add(case)
    return case


def _seed_run(session: Session, *, project_id: str, case: DbTestCase, run_id: str) -> WebwrightRun:
    run = WebwrightRun(
        id=run_id,
        project_id=project_id,
        test_case_id=case.id,
        automation_key=case.automation_key,
        status="completed",
    )
    session.add(run)
    return run


def _seed_action(
    session: Session,
    *,
    action_id: str,
    run_id: str,
    automation_key: str,
    order_index: int,
    action_type: str = "click",
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


def _seed_mapping(
    session: Session,
    *,
    mapping_id: str,
    case_id: str,
    action_ids: list[str],
) -> None:
    session.add(CaseActionMapping(
        id=mapping_id,
        test_case_id=case_id,
        raw_action_id=action_ids[0] if action_ids else None,
        tc_step_index=1,
        normalized_step_id="flow_001",
        normalized_step_name="save_profile",
        pom_method_name="save_profile",
        status="mapped",
    ))
    for order_index, action_id in enumerate(action_ids):
        session.add(CaseActionMappingAction(
            mapping_id=mapping_id,
            raw_action_id=action_id,
            order_index=order_index,
        ))


def test_step_assertion_and_wait_insertions_flow_into_structure_plan(
    client: TestClient,
    project_id: str,
) -> None:
    import worker.core.database as database

    case_id = "tc_assert_wait_step"
    with Session(database.engine) as session:
        case = _seed_case(
            session,
            project_id=project_id,
            case_id=case_id,
            automation_key="assert_wait_step",
        )
        run = _seed_run(session, project_id=project_id, case=case, run_id="ww_assert_wait_step")
        _seed_action(
            session,
            action_id="act_step_click",
            run_id=run.id,
            automation_key=case.automation_key,
            order_index=1,
            selector="page.get_by_role('button', name='Save')",
        )
        _seed_mapping(
            session,
            mapping_id="map_assert_wait_step",
            case_id=case_id,
            action_ids=["act_step_click"],
        )
        session.commit()

    wait_response = client.post(
        f"/projects/{project_id}/cases/{case_id}/steps/1/actions",
        json={
            "type": "wait_for_response",
            "value": "**/api/profile",
            "insertAfterActionId": "act_step_click",
        },
    )
    assert wait_response.status_code == 201
    wait_action_id = wait_response.json()["action"]["id"]

    assertion_response = client.post(
        f"/projects/{project_id}/cases/{case_id}/steps/1/actions",
        json={
            "type": "assert_visible",
            "selector": "page.get_by_text('Profile saved')",
            "value": "Profile saved",
            "insertAfterActionId": wait_action_id,
        },
    )
    assert assertion_response.status_code == 201
    assertion_action_id = assertion_response.json()["action"]["id"]

    patched_wait = client.patch(
        f"/projects/{project_id}/cases/{case_id}/steps/1/actions/{wait_action_id}",
        json={"value": "**/api/profile/saved"},
    )
    assert patched_wait.status_code == 200
    assert patched_wait.json()["action"]["value"] == "**/api/profile/saved"

    mappings = client.get(f"/projects/{project_id}/cases/{case_id}/mappings").json()
    assert mappings[0]["action_ids"] == [
        "act_step_click",
        wait_action_id,
        assertion_action_id,
    ]

    synced = client.post(f"/projects/{project_id}/cases/{case_id}/structure/sync")
    assert synced.status_code == 200

    with Session(database.engine) as session:
        mapping = session.get(CaseActionMapping, "map_assert_wait_step")
        pom = session.exec(
            select(PageObjectMethod).where(PageObjectMethod.source_mapping_id == mapping.id)
        ).one()
        plan = json.loads(pom.body_plan_json)

        assert mapping.raw_action_id == "act_step_click"
        assert [entry["action"] for entry in plan] == [
            "click",
            "wait_for_response",
            "assert_visible",
        ]
        assert [entry["sourceRawActionId"] for entry in plan] == [
            "act_step_click",
            wait_action_id,
            assertion_action_id,
        ]
        assert plan[1]["value"] == "**/api/profile/saved"
        assert plan[2]["selector"] == "page.get_by_text('Profile saved')"


def test_step_review_action_insert_creates_missing_step_mapping(
    client: TestClient,
    project_id: str,
) -> None:
    import worker.core.database as database

    case_id = "tc_assert_wait_unmapped"
    with Session(database.engine) as session:
        case = _seed_case(
            session,
            project_id=project_id,
            case_id=case_id,
            automation_key="assert_wait_unmapped",
        )
        _seed_run(session, project_id=project_id, case=case, run_id="ww_assert_wait_unmapped")
        session.commit()

    inserted = client.post(
        f"/projects/{project_id}/cases/{case_id}/steps/1/actions",
        json={
            "type": "assert_text",
            "selector": "page.locator('#status')",
            "value": "Ready",
        },
    )
    assert inserted.status_code == 201
    action_id = inserted.json()["action"]["id"]
    mapping = inserted.json()["mapping"]
    assert mapping["tc_step_index"] == 1
    assert mapping["action_ids"] == [action_id]
    assert mapping["status"] == "mapped"

    synced = client.post(f"/projects/{project_id}/cases/{case_id}/structure/sync")
    assert synced.status_code == 200
    with Session(database.engine) as session:
        pom = session.exec(select(PageObjectMethod)).one()
        plan = json.loads(pom.body_plan_json)
        assert pom.method_type == "assert"
        assert plan[0]["action"] == "assert_text"
        assert plan[0]["sourceRawActionId"] == action_id


def test_step_review_action_rejects_invalid_or_foreign_mutations_without_partial_write(
    client: TestClient,
    project_id: str,
) -> None:
    import worker.core.database as database

    selected_case_id = "tc_assert_wait_selected"
    foreign_case_id = "tc_assert_wait_foreign"
    with Session(database.engine) as session:
        selected = _seed_case(
            session,
            project_id=project_id,
            case_id=selected_case_id,
            automation_key="assert_wait_selected",
        )
        foreign = _seed_case(
            session,
            project_id=project_id,
            case_id=foreign_case_id,
            automation_key="assert_wait_foreign",
        )
        selected_run = _seed_run(
            session,
            project_id=project_id,
            case=selected,
            run_id="ww_assert_wait_selected",
        )
        foreign_run = _seed_run(
            session,
            project_id=project_id,
            case=foreign,
            run_id="ww_assert_wait_foreign",
        )
        _seed_action(
            session,
            action_id="act_assert_wait_selected",
            run_id=selected_run.id,
            automation_key=selected.automation_key,
            order_index=1,
        )
        _seed_action(
            session,
            action_id="act_assert_wait_unlinked",
            run_id=selected_run.id,
            automation_key=selected.automation_key,
            order_index=2,
        )
        _seed_action(
            session,
            action_id="act_assert_wait_foreign",
            run_id=foreign_run.id,
            automation_key=foreign.automation_key,
            order_index=1,
            selector="page.locator('#foreign')",
        )
        _seed_mapping(
            session,
            mapping_id="map_assert_wait_selected",
            case_id=selected_case_id,
            action_ids=["act_assert_wait_selected"],
        )
        session.commit()

    invalid_type = client.post(
        f"/projects/{project_id}/cases/{selected_case_id}/steps/1/actions",
        json={"type": "click", "selector": "page.locator('#bad')"},
    )
    assert invalid_type.status_code == 400

    invalid_after = client.post(
        f"/projects/{project_id}/cases/{selected_case_id}/steps/1/actions",
        json={
            "type": "assert_visible",
            "selector": "page.locator('#good')",
            "insertAfterActionId": "act_assert_wait_foreign",
        },
    )
    assert invalid_after.status_code == 400

    foreign_update = client.patch(
        f"/projects/{project_id}/cases/{selected_case_id}/steps/1/actions/act_assert_wait_foreign",
        json={"type": "assert_visible", "selector": "page.locator('#mutated')"},
    )
    assert foreign_update.status_code == 400

    unlinked_update = client.patch(
        f"/projects/{project_id}/cases/{selected_case_id}/steps/1/actions/act_assert_wait_unlinked",
        json={"type": "assert_visible", "selector": "page.locator('#mutated')"},
    )
    assert unlinked_update.status_code == 400

    with Session(database.engine) as session:
        actions = session.exec(
            select(RawAction).where(RawAction.webwright_run_id == "ww_assert_wait_selected")
        ).all()
        mapping = session.get(CaseActionMapping, "map_assert_wait_selected")
        links = session.exec(
            select(CaseActionMappingAction).where(
                CaseActionMappingAction.mapping_id == "map_assert_wait_selected"
            )
        ).all()
        foreign_action = session.get(RawAction, "act_assert_wait_foreign")

        assert {action.id for action in actions} == {
            "act_assert_wait_selected",
            "act_assert_wait_unlinked",
        }
        assert mapping.raw_action_id == "act_assert_wait_selected"
        assert [link.raw_action_id for link in links] == ["act_assert_wait_selected"]
        assert foreign_action.selector == "page.locator('#foreign')"
