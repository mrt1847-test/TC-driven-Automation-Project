"""A2-08: CaseActionMappingAction stores ordered multi-action mappings."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from worker.models.db import CaseActionMapping, CaseActionMappingAction, RawAction, TestCase as DbTestCase, WebwrightRun


def test_case_action_mapping_action_join_persists_ordered_actions(
    client: TestClient,
    project_id: str,
    imported_case: dict,
) -> None:
    case_id = imported_case["id"]
    automation_key = imported_case["automation_key"]

    import worker.core.database as database

    with Session(database.engine) as session:
        session.add(WebwrightRun(
            id="wwr_join_001",
            project_id=project_id,
            test_case_id=case_id,
            automation_key=automation_key,
            status="completed",
        ))
        session.add(RawAction(
            id="raw_join_first",
            webwright_run_id="wwr_join_001",
            automation_key=automation_key,
            order_index=1,
            type="fill",
            target="Username",
            selector="page.get_by_label('Username')",
            value="tester",
        ))
        session.add(RawAction(
            id="raw_join_second",
            webwright_run_id="wwr_join_001",
            automation_key=automation_key,
            order_index=2,
            type="click",
            target="Submit",
            selector="page.get_by_role('button', name='Submit')",
        ))
        session.commit()

    payload = {
        "mappings": [
            {
                "tc_step_index": 1,
                "action_ids": ["raw_join_second", "raw_join_first"],
                "normalized_step_id": "flow_001",
                "normalized_step_name": "submit_login",
                "pom_method_name": "submit_login",
                "status": "mapped",
            }
        ]
    }
    response = client.put(f"/projects/{project_id}/cases/{case_id}/mappings", json=payload)
    assert response.status_code == 200

    reloaded = client.get(f"/projects/{project_id}/cases/{case_id}/mappings")
    assert reloaded.status_code == 200
    mappings = reloaded.json()
    assert len(mappings) == 1
    assert mappings[0]["action_ids"] == ["raw_join_second", "raw_join_first"]

    with Session(database.engine) as session:
        mapping = session.exec(
            select(CaseActionMapping).where(
                CaseActionMapping.test_case_id == case_id,
                CaseActionMapping.tc_step_index == 1,
            )
        ).one()
        assert mapping.raw_action_id == "raw_join_second"

        links = session.exec(
            select(CaseActionMappingAction)
            .where(CaseActionMappingAction.mapping_id == mapping.id)
            .order_by(CaseActionMappingAction.order_index)
        ).all()
        assert [(link.raw_action_id, link.order_index) for link in links] == [
            ("raw_join_second", 0),
            ("raw_join_first", 1),
        ]


def test_mapping_update_replaces_and_removes_join_rows(
    client: TestClient,
    project_id: str,
    imported_case: dict,
) -> None:
    case_id = imported_case["id"]
    automation_key = imported_case["automation_key"]

    import worker.core.database as database

    with Session(database.engine) as session:
        session.add(WebwrightRun(
            id="wwr_join_replace",
            project_id=project_id,
            test_case_id=case_id,
            automation_key=automation_key,
            status="completed",
        ))
        for order_index, action_id in enumerate(
            ["raw_join_replace_first", "raw_join_replace_second", "raw_join_replace_third"],
            start=1,
        ):
            session.add(RawAction(
                id=action_id,
                webwright_run_id="wwr_join_replace",
                automation_key=automation_key,
                order_index=order_index,
                type="click",
            ))
        session.commit()

    endpoint = f"/projects/{project_id}/cases/{case_id}/mappings"
    initial = client.put(endpoint, json={
        "mappings": [{
            "tc_step_index": 1,
            "action_ids": ["raw_join_replace_first", "raw_join_replace_second"],
            "status": "mapped",
        }]
    })
    assert initial.status_code == 200
    initial_mapping_id = initial.json()[0]["id"]

    replaced = client.put(endpoint, json={
        "mappings": [{
            "tc_step_index": 1,
            "action_ids": ["raw_join_replace_third"],
            "status": "mapped",
        }]
    })
    assert replaced.status_code == 200
    assert replaced.json()[0]["action_ids"] == ["raw_join_replace_third"]
    replacement_mapping_id = replaced.json()[0]["id"]

    with Session(database.engine) as session:
        mappings = session.exec(
            select(CaseActionMapping).where(CaseActionMapping.test_case_id == case_id)
        ).all()
        assert len(mappings) == 1
        assert mappings[0].raw_action_id == "raw_join_replace_third"
        assert session.exec(
            select(CaseActionMappingAction).where(CaseActionMappingAction.mapping_id == initial_mapping_id)
        ).all() == []

    removed = client.put(endpoint, json={
        "mappings": [{
            "tc_step_index": 1,
            "action_ids": [],
            "status": "unmapped",
        }]
    })
    assert removed.status_code == 200
    assert removed.json()[0]["action_ids"] == []

    with Session(database.engine) as session:
        mapping = session.exec(
            select(CaseActionMapping).where(CaseActionMapping.test_case_id == case_id)
        ).one()
        assert mapping.raw_action_id is None
        assert session.exec(
            select(CaseActionMappingAction).where(
                CaseActionMappingAction.mapping_id.in_([replacement_mapping_id, mapping.id])
            )
        ).all() == []


def test_mapping_update_rejects_foreign_and_invalid_actions_without_partial_rewrite(
    client: TestClient,
    project_id: str,
    imported_case: dict,
) -> None:
    case_id = imported_case["id"]
    automation_key = imported_case["automation_key"]

    import worker.core.database as database

    with Session(database.engine) as session:
        session.add(DbTestCase(
            id="case_join_foreign",
            project_id=project_id,
            source_type="excel",
            source_case_id="TC-JOIN-FOREIGN",
            title="Foreign mapping case",
            automation_key=automation_key,
        ))
        session.add(WebwrightRun(
            id="wwr_join_valid",
            project_id=project_id,
            test_case_id=case_id,
            automation_key=automation_key,
            status="completed",
        ))
        session.add(WebwrightRun(
            id="wwr_join_foreign",
            project_id=project_id,
            test_case_id="case_join_foreign",
            automation_key=automation_key,
            status="completed",
        ))
        session.add(RawAction(
            id="raw_join_valid",
            webwright_run_id="wwr_join_valid",
            automation_key=automation_key,
            order_index=1,
            type="click",
        ))
        session.add(RawAction(
            id="raw_join_foreign",
            webwright_run_id="wwr_join_foreign",
            automation_key=automation_key,
            order_index=1,
            type="click",
        ))
        session.commit()

    endpoint = f"/projects/{project_id}/cases/{case_id}/mappings"
    original = client.put(endpoint, json={
        "mappings": [{
            "tc_step_index": 1,
            "action_ids": ["raw_join_valid"],
            "normalized_step_name": "keep_me",
            "status": "mapped",
        }]
    })
    assert original.status_code == 200
    original_body = original.json()

    for rejected_action_id in ["raw_join_foreign", "raw_join_missing"]:
        rejected = client.put(endpoint, json={
            "mappings": [{
                "tc_step_index": 1,
                "action_ids": [rejected_action_id],
                "normalized_step_name": "must_not_persist",
                "status": "mapped",
            }]
        })
        assert rejected.status_code == 400
        assert rejected_action_id in rejected.json()["detail"]
        assert client.get(endpoint).json() == original_body

    with Session(database.engine) as session:
        mapping = session.exec(
            select(CaseActionMapping).where(CaseActionMapping.test_case_id == case_id)
        ).one()
        assert mapping.raw_action_id == "raw_join_valid"
        assert mapping.normalized_step_name == "keep_me"
        links = session.exec(
            select(CaseActionMappingAction).where(CaseActionMappingAction.mapping_id == mapping.id)
        ).all()
        assert [link.raw_action_id for link in links] == ["raw_join_valid"]
