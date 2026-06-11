from __future__ import annotations

import json
from types import SimpleNamespace

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
from worker.services.mapping import get_mappings
from worker.services.structuring_service import (
    get_flow_steps,
    get_latest_flow,
    merge_refreshed_raw_actions,
    sync_structured_entities,
)


def _add_actions(
    session: Session,
    *,
    run_id: str,
    automation_key: str,
    suffix: str,
    specs: list[dict],
) -> list[str]:
    action_ids: list[str] = []
    for order_index, spec in enumerate(specs, start=1):
        action_id = f"act_{suffix}_{order_index}"
        action_ids.append(action_id)
        session.add(RawAction(
            id=action_id,
            webwright_run_id=run_id,
            automation_key=automation_key,
            order_index=order_index,
            type=spec["type"],
            selector=spec.get("selector"),
            target=spec.get("target"),
            value=spec.get("value"),
        ))
    return action_ids


def _seed_structure(
    session: Session,
    *,
    project_id: str,
    case: DbTestCase,
    suffix: str,
    method_name: str,
    specs: list[dict],
) -> dict:
    run = WebwrightRun(
        id=f"ww_{suffix}_old",
        project_id=project_id,
        test_case_id=case.id,
        automation_key=case.automation_key,
        status="completed",
    )
    session.add(run)
    action_ids = _add_actions(
        session,
        run_id=run.id,
        automation_key=case.automation_key,
        suffix=f"{suffix}_old",
        specs=specs,
    )
    mapping = CaseActionMapping(
        id=f"map_{suffix}",
        test_case_id=case.id,
        raw_action_id=action_ids[0],
        tc_step_index=1,
        normalized_step_id=f"flow_{suffix}",
        normalized_step_name=f"reviewed_{suffix}_step",
        pom_method_name=method_name,
        status="mapped",
    )
    session.add(mapping)
    for order_index, action_id in enumerate(action_ids):
        session.add(CaseActionMappingAction(
            mapping_id=mapping.id,
            raw_action_id=action_id,
            order_index=order_index,
        ))
    case.status = "mapped"
    session.add(case)
    session.commit()

    flow = sync_structured_entities(session, project_id, case, run)
    session.commit()
    step = get_flow_steps(session, flow.id)[0]
    method = session.get(PageObjectMethod, step.page_object_method_id)
    return {
        "run": run,
        "action_ids": action_ids,
        "mapping": mapping,
        "flow": flow,
        "step": step,
        "method": method,
    }


def _add_refresh_run(
    session: Session,
    *,
    project_id: str,
    case: DbTestCase,
    suffix: str,
    specs: list[dict],
) -> tuple[WebwrightRun, list[str]]:
    run = WebwrightRun(
        id=f"ww_{suffix}_new",
        project_id=project_id,
        test_case_id=case.id,
        automation_key=case.automation_key,
        status="completed",
    )
    session.add(run)
    action_ids = _add_actions(
        session,
        run_id=run.id,
        automation_key=case.automation_key,
        suffix=f"{suffix}_new",
        specs=specs,
    )
    session.commit()
    return run, action_ids


def test_equivalent_raw_refresh_updates_links_and_body_plan_in_place(
    project_id: str,
    imported_case: dict,
) -> None:
    import worker.core.database as database

    with Session(database.engine) as session:
        case = session.get(DbTestCase, imported_case["id"])
        seeded = _seed_structure(
            session,
            project_id=project_id,
            case=case,
            suffix="equivalent",
            method_name="reviewed_checkout",
            specs=[
                {"type": "goto", "target": "https://old.example", "value": "https://old.example"},
                {"type": "click", "selector": "page.locator('#old')", "target": "click target"},
            ],
        )
        old_plan = json.loads(seeded["method"].body_plan_json)
        run, new_action_ids = _add_refresh_run(
            session,
            project_id=project_id,
            case=case,
            suffix="equivalent",
            specs=[
                {"type": "goto", "target": "https://new.example", "value": "https://new.example"},
                {"type": "click", "selector": "page.get_by_role('button', name='Continue')", "target": "click target"},
            ],
        )

        result = merge_refreshed_raw_actions(session, project_id, case, run)

        mappings = get_mappings(session, case.id)
        flow = get_latest_flow(session, case.id)
        steps = get_flow_steps(session, flow.id)
        method = session.get(PageObjectMethod, seeded["method"].id)
        plan = json.loads(method.body_plan_json)

        assert result["status"] == "merged"
        assert mappings[0].id == seeded["mapping"].id
        assert mappings[0].normalized_step_name == "reviewed_equivalent_step"
        assert mappings[0].pom_method_name == "reviewed_checkout"
        assert mappings[0].action_ids == new_action_ids
        assert flow.id == seeded["flow"].id
        assert steps[0].id == seeded["step"].id
        assert steps[0].name == "reviewed_equivalent_step"
        assert method.id == seeded["method"].id
        assert method.name.endswith("__step_1_reviewed_checkout")
        assert [entry["sourceRawActionId"] for entry in plan] == new_action_ids
        assert plan[0]["value"] == "https://new.example"
        assert plan[1]["selector"] == "page.get_by_role('button', name='Continue')"
        assert plan != old_plan
        assert session.get(DbTestCase, case.id).status == "structured"


def test_raw_refresh_merge_replaces_new_credential_literal_before_plan_persist(
    project_id: str,
    imported_case: dict,
) -> None:
    import worker.core.database as database

    literal = "N3w-password-value!"
    with Session(database.engine) as session:
        case = session.get(DbTestCase, imported_case["id"])
        seeded = _seed_structure(
            session,
            project_id=project_id,
            case=case,
            suffix="credential",
            method_name="enter_password",
            specs=[
                {
                    "type": "fill",
                    "selector": "page.get_by_label('Password')",
                    "target": "old-password-value",
                    "value": "old-password-value",
                },
            ],
        )
        run, new_action_ids = _add_refresh_run(
            session,
            project_id=project_id,
            case=case,
            suffix="credential",
            specs=[
                {
                    "type": "fill",
                    "selector": "page.get_by_label('Password')",
                    "target": f"typed {literal}",
                    "value": literal,
                },
            ],
        )

        result = merge_refreshed_raw_actions(session, project_id, case, run)

        method = session.get(PageObjectMethod, seeded["method"].id)
        plan = json.loads(method.body_plan_json)

        assert result["status"] == "needs_review"
        assert result["reason"] == "planner_review_required"
        assert [entry["sourceRawActionId"] for entry in plan] == new_action_ids
        assert plan[0]["value"] == "${env.credentials.password}"
        assert plan[0]["target"] == "typed ${env.credentials.password}"
        assert plan[0]["requiresReview"] is True
        assert plan[0]["reviewReason"] == "credential_value_placeholder"
        assert literal not in method.body_plan_json
        assert method.value_template == "${env.credentials.password}"
        assert method.status == "draft"


def test_changed_raw_sequence_marks_review_and_preserves_existing_structure(
    project_id: str,
    imported_case: dict,
) -> None:
    import worker.core.database as database

    with Session(database.engine) as session:
        case = session.get(DbTestCase, imported_case["id"])
        seeded = _seed_structure(
            session,
            project_id=project_id,
            case=case,
            suffix="inserted",
            method_name="reviewed_inserted_flow",
            specs=[
                {"type": "goto", "target": "https://example.test", "value": "https://example.test"},
                {"type": "click", "selector": "page.locator('#submit')", "target": "click target"},
            ],
        )
        old_plan = seeded["method"].body_plan_json
        run, new_action_ids = _add_refresh_run(
            session,
            project_id=project_id,
            case=case,
            suffix="inserted",
            specs=[
                {"type": "goto", "target": "https://example.test", "value": "https://example.test"},
                {"type": "fill", "selector": "page.locator('#email')", "value": "user@example.test"},
                {"type": "click", "selector": "page.locator('#submit')", "target": "click target"},
            ],
        )

        result = merge_refreshed_raw_actions(session, project_id, case, run)

        mappings = get_mappings(session, case.id)
        flow = get_latest_flow(session, case.id)
        step = get_flow_steps(session, flow.id)[0]
        method = session.get(PageObjectMethod, seeded["method"].id)
        refresh = json.loads(step.metadata_json)["raw_refresh"]

        assert result["status"] == "needs_review"
        assert result["reason"] == "action_count_changed"
        assert mappings[0].id == seeded["mapping"].id
        assert mappings[0].status == "needs_review"
        assert mappings[0].action_ids == seeded["action_ids"]
        assert flow.id == seeded["flow"].id
        assert step.id == seeded["step"].id
        assert method.id == seeded["method"].id
        assert method.body_plan_json == old_plan
        assert refresh["status"] == "conflict"
        assert refresh["reason"] == "action_count_changed"
        assert refresh["unmatched_new_action_ids"] == [new_action_ids[1]]
        assert session.get(DbTestCase, case.id).status == "needs_review"


def test_ambiguous_refresh_preserves_reviewed_structure_and_unrelated_case(
    project_id: str,
    imported_case: dict,
) -> None:
    import worker.core.database as database

    with Session(database.engine) as session:
        selected_case = session.get(DbTestCase, imported_case["id"])
        selected = _seed_structure(
            session,
            project_id=project_id,
            case=selected_case,
            suffix="ambiguous",
            method_name="reviewed_ambiguous_clicks",
            specs=[
                {"type": "click", "selector": "page.locator('#first')", "target": "click target"},
                {"type": "click", "selector": "page.locator('#second')", "target": "click target"},
            ],
        )
        unrelated_case = DbTestCase(
            id="tc_unrelated_refresh",
            project_id=project_id,
            source_type="excel",
            source_case_id="TC-UNRELATED",
            title="Unrelated case",
            automation_key="unrelated_refresh",
        )
        session.add(unrelated_case)
        unrelated = _seed_structure(
            session,
            project_id=project_id,
            case=unrelated_case,
            suffix="unrelated",
            method_name="reviewed_unrelated_fill",
            specs=[
                {"type": "fill", "selector": "page.locator('#stable')", "value": "stable"},
            ],
        )
        unrelated_snapshot = {
            "mapping": get_mappings(session, unrelated_case.id)[0].model_dump(),
            "flow_status": unrelated["flow"].status,
            "step_metadata": unrelated["step"].metadata_json,
            "method_plan": unrelated["method"].body_plan_json,
        }
        selected_old_plan = selected["method"].body_plan_json
        run, _new_action_ids = _add_refresh_run(
            session,
            project_id=project_id,
            case=selected_case,
            suffix="ambiguous",
            specs=[
                {"type": "click", "selector": "page.locator('#replacement-a')", "target": "click target"},
                {"type": "click", "selector": "page.locator('#replacement-b')", "target": "click target"},
            ],
        )

        result = merge_refreshed_raw_actions(session, project_id, selected_case, run)

        selected_mapping = get_mappings(session, selected_case.id)[0]
        selected_method = session.get(PageObjectMethod, selected["method"].id)
        unrelated_mapping = get_mappings(session, unrelated_case.id)[0]
        unrelated_flow = get_latest_flow(session, unrelated_case.id)
        unrelated_step = get_flow_steps(session, unrelated_flow.id)[0]
        unrelated_method = session.get(PageObjectMethod, unrelated["method"].id)

        assert result["status"] == "needs_review"
        assert result["reason"] == "ambiguous_action_match"
        assert selected_mapping.action_ids == selected["action_ids"]
        assert selected_method.body_plan_json == selected_old_plan
        assert unrelated_mapping.model_dump() == unrelated_snapshot["mapping"]
        assert unrelated_flow.status == unrelated_snapshot["flow_status"]
        assert unrelated_step.metadata_json == unrelated_snapshot["step_metadata"]
        assert unrelated_method.body_plan_json == unrelated_snapshot["method_plan"]


def test_selected_webwright_rerun_uses_merge_for_existing_structure(
    monkeypatch,
    client,
    project_id: str,
    imported_case: dict,
) -> None:
    import worker.core.database as database
    import worker.routers.webwright_runs as webwright_runs

    monkeypatch.setattr(
        webwright_runs,
        "resolve_runtime",
        lambda: SimpleNamespace(
            check_webwright_readiness=lambda: SimpleNamespace(live_ok=False),
        ),
    )
    case_id = imported_case["id"]

    first = client.post(f"/projects/{project_id}/webwright-runs", json={"caseIds": [case_id]})
    assert first.status_code == 200
    first_actions = client.get(f"/projects/{project_id}/cases/{case_id}/actions").json()
    first_mappings = client.get(f"/projects/{project_id}/cases/{case_id}/mappings").json()
    reviewed = []
    for index, mapping in enumerate(first_mappings, start=1):
        if index == 1:
            action_ids = [action["id"] for action in first_actions[:2]]
        else:
            action_ids = [action["id"] for action in first_actions[2:]]
        reviewed.append({
            **mapping,
            "action_ids": action_ids,
            "normalized_step_name": f"reviewed_step_{index}",
            "pom_method_name": f"reviewed_method_{index}",
            "status": "mapped",
        })
    saved = client.put(
        f"/projects/{project_id}/cases/{case_id}/mappings",
        json={"mappings": reviewed},
    )
    assert saved.status_code == 200
    saved_mappings = saved.json()
    synced = client.post(f"/projects/{project_id}/cases/{case_id}/structure/sync")
    assert synced.status_code == 200
    flow_id = synced.json()["flowId"]

    second = client.post(f"/projects/{project_id}/webwright-runs", json={"caseIds": [case_id]})
    assert second.status_code == 200
    refreshed_actions = client.get(f"/projects/{project_id}/cases/{case_id}/actions").json()
    refreshed_mappings = client.get(f"/projects/{project_id}/cases/{case_id}/mappings").json()

    assert [mapping["id"] for mapping in refreshed_mappings] == [mapping["id"] for mapping in saved_mappings]
    assert [mapping["normalized_step_name"] for mapping in refreshed_mappings] == [
        f"reviewed_step_{index}" for index in range(1, len(first_mappings) + 1)
    ]
    assert {action["id"] for action in refreshed_actions}.isdisjoint(
        {action["id"] for action in first_actions}
    )
    assert {
        action_id
        for mapping in refreshed_mappings
        for action_id in mapping["action_ids"]
    } == {action["id"] for action in refreshed_actions}

    with Session(database.engine) as session:
        flows = session.exec(
            select(StructuredFlow).where(StructuredFlow.test_case_id == case_id)
        ).all()
        assert [flow.id for flow in flows] == [flow_id]
        steps = get_flow_steps(session, flow_id)
        assert [step.name for step in steps] == [
            f"reviewed_step_{index}" for index in range(1, len(first_mappings) + 1)
        ]
        assert session.get(DbTestCase, case_id).status == "structured"
