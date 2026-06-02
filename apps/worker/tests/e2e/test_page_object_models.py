"""A2-10: PageObject and PageObjectMethod models are durable."""

from __future__ import annotations

import json

from sqlalchemy import inspect
from sqlmodel import Session, select

from worker.models.db import CaseActionMapping, PageObject, PageObjectMethod


def test_page_object_and_method_models_persist_typed_mapping_origin(
    project_id: str,
    imported_case: dict,
) -> None:
    import worker.core.database as database

    case_id = imported_case["id"]

    inspector = inspect(database.engine)
    assert "page_objects" in inspector.get_table_names()
    assert "page_object_methods" in inspector.get_table_names()

    with Session(database.engine) as session:
        mapping = CaseActionMapping(
            id="map_page_object_001",
            test_case_id=case_id,
            tc_step_index=1,
            normalized_step_id="flow_001",
            normalized_step_name="submit_login",
            pom_method_name="submit_login",
            status="mapped",
        )
        page_object = PageObject(
            id="po_login_page",
            project_id=project_id,
            name="LoginPage",
            file_path="pages/login_page.py",
            url_pattern="/login",
            description="Login page object plan",
        )
        session.add(mapping)
        session.add(page_object)
        session.add(PageObjectMethod(
            id="pom_fill_username",
            page_object_id=page_object.id,
            name="fill_username",
            method_type="fill",
            selector="page.get_by_label('Username')",
            value_template="{username}",
            return_type="None",
            body_plan_json=json.dumps([
                {"order": 1, "action": "fill", "selector": "page.get_by_label('Username')"},
            ]),
            source_mapping_id=mapping.id,
            status="approved",
        ))
        session.add(PageObjectMethod(
            id="pom_submit_login",
            page_object_id=page_object.id,
            name="submit_login",
            method_type="composite",
            return_type="None",
            body_plan_json=json.dumps([
                {"order": 1, "action": "fill", "method": "fill_username"},
                {"order": 2, "action": "click", "selector": "page.get_by_role('button', name='Sign in')"},
            ]),
            source_mapping_id=mapping.id,
            status="draft",
        ))
        session.commit()

    with Session(database.engine) as session:
        saved_page = session.get(PageObject, "po_login_page")
        assert saved_page is not None
        assert saved_page.project_id == project_id
        assert saved_page.file_path == "pages/login_page.py"

        methods = session.exec(
            select(PageObjectMethod)
            .where(PageObjectMethod.page_object_id == saved_page.id)
            .order_by(PageObjectMethod.name)
        ).all()

    by_name = {method.name: method for method in methods}
    assert set(by_name) == {"fill_username", "submit_login"}
    assert by_name["fill_username"].method_type == "fill"
    assert by_name["fill_username"].source_mapping_id == "map_page_object_001"
    assert by_name["submit_login"].method_type == "composite"
    assert by_name["submit_login"].source_mapping_id == "map_page_object_001"
    assert json.loads(by_name["submit_login"].body_plan_json) == [
        {"order": 1, "action": "fill", "method": "fill_username"},
        {"order": 2, "action": "click", "selector": "page.get_by_role('button', name='Sign in')"},
    ]
