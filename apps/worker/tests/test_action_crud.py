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
        steps_json=json.dumps([{"index": 1, "action": "review action"}]),
        automation_key=automation_key,
    )
    session.add(case)
    return case


def _seed_run(
    session: Session,
    *,
    project_id: str,
    case: DbTestCase,
    run_id: str,
) -> WebwrightRun:
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
) -> RawAction:
    action = RawAction(
        id=action_id,
        webwright_run_id=run_id,
        automation_key=automation_key,
        order_index=order_index,
        type=action_type,
        selector=selector,
        value=value,
        target=target,
    )
    session.add(action)
    return action


def _seed_mapping(
    session: Session,
    *,
    mapping_id: str,
    case_id: str,
    action_ids: list[str],
) -> CaseActionMapping:
    mapping = CaseActionMapping(
        id=mapping_id,
        test_case_id=case_id,
        raw_action_id=action_ids[0] if action_ids else None,
        tc_step_index=1,
        normalized_step_id="flow_001",
        normalized_step_name="review_action",
        pom_method_name="review_action",
        status="mapped",
    )
    session.add(mapping)
    for order_index, action_id in enumerate(action_ids):
        session.add(CaseActionMappingAction(
            mapping_id=mapping_id,
            raw_action_id=action_id,
            order_index=order_index,
        ))
    return mapping


def test_action_crud_create_update_and_structure_handoff(
    client: TestClient,
    project_id: str,
) -> None:
    import worker.core.database as database

    case_id = "tc_action_crud_handoff"
    with Session(database.engine) as session:
        case = _seed_case(session, project_id=project_id, case_id=case_id, automation_key="crud_handoff")
        run = _seed_run(session, project_id=project_id, case=case, run_id="ww_crud_handoff")
        _seed_action(
            session,
            action_id="act_crud_goto",
            run_id=run.id,
            automation_key=case.automation_key,
            order_index=1,
            action_type="goto",
            target="https://example.test/login",
            value="https://example.test/login",
        )
        session.commit()

    created = client.post(
        f"/projects/{project_id}/cases/{case_id}/actions",
        json={
            "type": "fill",
            "selector": "page.locator('#email')",
            "value": "draft@example.test",
        },
    )
    assert created.status_code == 201
    created_action = created.json()
    assert created_action["order_index"] == 2
    created_id = created_action["id"]

    patched = client.patch(
        f"/projects/{project_id}/cases/{case_id}/actions/{created_id}",
        json={
            "selector": "page.get_by_label('Email')",
            "value": "${env.user.email}",
            "target": "reviewed email field",
        },
    )
    assert patched.status_code == 200
    assert patched.json()["selector"] == "page.get_by_label('Email')"

    saved = client.put(
        f"/projects/{project_id}/cases/{case_id}/mappings",
        json={
            "mappings": [
                {
                    "tc_step_index": 1,
                    "action_ids": ["act_crud_goto", created_id],
                    "normalized_step_id": "flow_001",
                    "normalized_step_name": "review_action",
                    "pom_method_name": "review_action",
                    "status": "mapped",
                }
            ]
        },
    )
    assert saved.status_code == 200
    mapping_id = saved.json()[0]["id"]

    synced = client.post(f"/projects/{project_id}/cases/{case_id}/structure/sync")
    assert synced.status_code == 200

    actions = client.get(f"/projects/{project_id}/cases/{case_id}/actions").json()
    assert [action["id"] for action in actions] == ["act_crud_goto", created_id]
    assert actions[1]["target"] == "reviewed email field"

    with Session(database.engine) as session:
        pom = session.exec(
            select(PageObjectMethod).where(PageObjectMethod.source_mapping_id == mapping_id)
        ).one()
        plan = json.loads(pom.body_plan_json)
        assert [entry["sourceRawActionId"] for entry in plan] == ["act_crud_goto", created_id]
        assert plan[1]["selector"] == "page.get_by_label('Email')"
        assert plan[1]["value"] == "${env.user.email}"


def test_action_delete_updates_ordered_join_and_legacy_first_action(
    client: TestClient,
    project_id: str,
) -> None:
    import worker.core.database as database

    case_id = "tc_action_crud_delete"
    with Session(database.engine) as session:
        case = _seed_case(session, project_id=project_id, case_id=case_id, automation_key="crud_delete")
        run = _seed_run(session, project_id=project_id, case=case, run_id="ww_crud_delete")
        for index, action_id in enumerate(["act_delete_first", "act_delete_middle", "act_delete_last"], start=1):
            _seed_action(
                session,
                action_id=action_id,
                run_id=run.id,
                automation_key=case.automation_key,
                order_index=index,
            )
        _seed_mapping(
            session,
            mapping_id="map_crud_delete",
            case_id=case_id,
            action_ids=["act_delete_first", "act_delete_middle", "act_delete_last"],
        )
        session.commit()

    removed_middle = client.delete(
        f"/projects/{project_id}/cases/{case_id}/actions/act_delete_middle"
    )
    assert removed_middle.status_code == 200
    assert removed_middle.json()["affectedMappingIds"] == ["map_crud_delete"]

    mappings = client.get(f"/projects/{project_id}/cases/{case_id}/mappings").json()
    assert mappings[0]["action_ids"] == ["act_delete_first", "act_delete_last"]
    with Session(database.engine) as session:
        mapping = session.get(CaseActionMapping, "map_crud_delete")
        assert mapping.raw_action_id == "act_delete_first"
        assert session.get(RawAction, "act_delete_middle") is None

    removed_first = client.delete(
        f"/projects/{project_id}/cases/{case_id}/actions/act_delete_first"
    )
    assert removed_first.status_code == 200
    mappings = client.get(f"/projects/{project_id}/cases/{case_id}/mappings").json()
    assert mappings[0]["action_ids"] == ["act_delete_last"]
    with Session(database.engine) as session:
        mapping = session.get(CaseActionMapping, "map_crud_delete")
        assert mapping.raw_action_id == "act_delete_last"

    removed_last = client.delete(
        f"/projects/{project_id}/cases/{case_id}/actions/act_delete_last"
    )
    assert removed_last.status_code == 200
    mappings = client.get(f"/projects/{project_id}/cases/{case_id}/mappings").json()
    assert mappings[0]["action_ids"] == []
    assert mappings[0]["status"] == "unmapped"
    assert client.get(f"/projects/{project_id}/cases/{case_id}").json()["status"] == "needs_review"


def test_action_crud_rejects_foreign_action_mutation_without_partial_write(
    client: TestClient,
    project_id: str,
) -> None:
    import worker.core.database as database

    selected_case_id = "tc_action_crud_selected"
    foreign_case_id = "tc_action_crud_foreign"
    with Session(database.engine) as session:
        selected = _seed_case(
            session,
            project_id=project_id,
            case_id=selected_case_id,
            automation_key="crud_selected",
        )
        foreign = _seed_case(
            session,
            project_id=project_id,
            case_id=foreign_case_id,
            automation_key="crud_foreign",
        )
        selected_run = _seed_run(
            session,
            project_id=project_id,
            case=selected,
            run_id="ww_crud_selected",
        )
        foreign_run = _seed_run(
            session,
            project_id=project_id,
            case=foreign,
            run_id="ww_crud_foreign",
        )
        _seed_action(
            session,
            action_id="act_crud_selected",
            run_id=selected_run.id,
            automation_key=selected.automation_key,
            order_index=1,
            selector="page.locator('#selected')",
        )
        _seed_action(
            session,
            action_id="act_crud_foreign",
            run_id=foreign_run.id,
            automation_key=foreign.automation_key,
            order_index=1,
            selector="page.locator('#foreign')",
        )
        _seed_mapping(
            session,
            mapping_id="map_crud_selected",
            case_id=selected_case_id,
            action_ids=["act_crud_selected"],
        )
        session.commit()

    patched = client.patch(
        f"/projects/{project_id}/cases/{selected_case_id}/actions/act_crud_foreign",
        json={"selector": "page.locator('#mutated')"},
    )
    assert patched.status_code == 400
    removed = client.delete(
        f"/projects/{project_id}/cases/{selected_case_id}/actions/act_crud_foreign"
    )
    assert removed.status_code == 400

    with Session(database.engine) as session:
        foreign_action = session.get(RawAction, "act_crud_foreign")
        selected_action = session.get(RawAction, "act_crud_selected")
        mapping = session.get(CaseActionMapping, "map_crud_selected")
        links = session.exec(
            select(CaseActionMappingAction).where(
                CaseActionMappingAction.mapping_id == "map_crud_selected"
            )
        ).all()

        assert foreign_action is not None
        assert foreign_action.selector == "page.locator('#foreign')"
        assert selected_action is not None
        assert mapping.raw_action_id == "act_crud_selected"
        assert [link.raw_action_id for link in links] == ["act_crud_selected"]
