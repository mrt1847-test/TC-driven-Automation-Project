"""A2-09: StructuredFlow and StructuredStep models are durable."""

from __future__ import annotations

from sqlalchemy import inspect
from sqlmodel import Session, select

from worker.models.db import CaseActionMapping, StructuredFlow, StructuredStep


def test_structured_flow_and_step_models_persist_ordered_steps(
    project_id: str,
    imported_case: dict,
) -> None:
    import worker.core.database as database

    case_id = imported_case["id"]
    automation_key = imported_case["automation_key"]

    inspector = inspect(database.engine)
    assert "structured_flows" in inspector.get_table_names()
    assert "structured_steps" in inspector.get_table_names()

    with Session(database.engine) as session:
        first_mapping = CaseActionMapping(
            id="map_structured_first",
            test_case_id=case_id,
            tc_step_index=1,
            normalized_step_id="flow_001",
            normalized_step_name="enter_username",
            pom_method_name="enter_username",
            status="mapped",
        )
        second_mapping = CaseActionMapping(
            id="map_structured_second",
            test_case_id=case_id,
            tc_step_index=2,
            normalized_step_id="flow_002",
            normalized_step_name="submit_login",
            pom_method_name="submit_login",
            status="mapped",
        )
        flow = StructuredFlow(
            id="sf_login_001",
            project_id=project_id,
            test_case_id=case_id,
            automation_key=automation_key,
            name="LoginFlow",
            status="draft",
            version=1,
        )
        session.add(first_mapping)
        session.add(second_mapping)
        session.add(flow)
        session.add(StructuredStep(
            id="ss_login_002",
            structured_flow_id=flow.id,
            mapping_id=second_mapping.id,
            order_index=2,
            name="submit_login",
            kind="interaction",
            metadata_json='{"source":"reviewed_mapping"}',
        ))
        session.add(StructuredStep(
            id="ss_login_001",
            structured_flow_id=flow.id,
            mapping_id=first_mapping.id,
            order_index=1,
            name="enter_username",
            kind="interaction",
        ))
        session.commit()

    with Session(database.engine) as session:
        saved_flow = session.get(StructuredFlow, "sf_login_001")
        assert saved_flow is not None
        assert saved_flow.project_id == project_id
        assert saved_flow.test_case_id == case_id
        assert saved_flow.automation_key == automation_key
        assert saved_flow.version == 1

        steps = session.exec(
            select(StructuredStep)
            .where(StructuredStep.structured_flow_id == saved_flow.id)
            .order_by(StructuredStep.order_index)
        ).all()

    assert [(step.name, step.mapping_id, step.order_index) for step in steps] == [
        ("enter_username", "map_structured_first", 1),
        ("submit_login", "map_structured_second", 2),
    ]
    assert steps[1].metadata_json == '{"source":"reviewed_mapping"}'
