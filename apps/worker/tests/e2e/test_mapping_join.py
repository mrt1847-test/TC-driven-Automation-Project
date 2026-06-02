"""A2-08: CaseActionMappingAction stores ordered multi-action mappings."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from worker.models.db import CaseActionMapping, CaseActionMappingAction, RawAction, WebwrightRun


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
