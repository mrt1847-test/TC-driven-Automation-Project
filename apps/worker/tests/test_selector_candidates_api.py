from __future__ import annotations

import json

from sqlmodel import Session

from worker.models.db import (
    ArtifactAsset,
    ArtifactAssetSourceType,
    ArtifactAssetType,
    CaseActionMapping,
    PageObject,
    PageObjectMethod,
    RawAction,
    SelectorCandidate,
    StructuredFlow,
    StructuredStep,
    TestCase as DbTestCase,
    WebwrightRun,
)


def _seed_selector_candidate_graph(project_id: str, foreign_project_id: str, tmp_path) -> dict[str, str]:
    import worker.core.database as database

    output_dir = tmp_path / "webwright" / "selector-api"
    output_dir.mkdir(parents=True)
    trajectory = output_dir / "trajectory.json"
    trajectory.write_text(json.dumps({"actions": []}), encoding="utf-8")

    with Session(database.engine) as session:
        case = DbTestCase(
            id="tc_selector_api",
            project_id=project_id,
            source_type="excel",
            source_case_id="TC-SELECTOR-API",
            title="Selector API",
            steps_json=json.dumps([{"index": 1, "action": "Log in"}]),
            automation_key="selector_api",
            status="structured",
        )
        other_case = DbTestCase(
            id="tc_selector_api_other_case",
            project_id=project_id,
            source_type="excel",
            source_case_id="TC-SELECTOR-OTHER",
            title="Other selector case",
            steps_json="[]",
            automation_key="selector_api_other",
        )
        foreign_case = DbTestCase(
            id="tc_selector_api_foreign_project",
            project_id=foreign_project_id,
            source_type="excel",
            source_case_id="TC-SELECTOR-FOREIGN",
            title="Foreign selector case",
            steps_json="[]",
            automation_key="selector_api_foreign",
        )
        run = WebwrightRun(
            id="ww_selector_api",
            project_id=project_id,
            test_case_id=case.id,
            automation_key=case.automation_key,
            status="completed",
            output_path=str(output_dir),
            trajectory_path=str(trajectory),
        )
        other_run = WebwrightRun(
            id="ww_selector_api_other_case",
            project_id=project_id,
            test_case_id=other_case.id,
            automation_key=other_case.automation_key,
            status="completed",
        )
        foreign_run = WebwrightRun(
            id="ww_selector_api_foreign_project",
            project_id=foreign_project_id,
            test_case_id=foreign_case.id,
            automation_key=foreign_case.automation_key,
            status="completed",
        )
        raw_click = RawAction(
            id="raw_selector_api_click",
            webwright_run_id=run.id,
            automation_key=case.automation_key,
            order_index=1,
            type="click",
            target="Login button",
            selector="page.locator('#login')",
            source_line=12,
        )
        raw_fill = RawAction(
            id="raw_selector_api_fill",
            webwright_run_id=run.id,
            automation_key=case.automation_key,
            order_index=2,
            type="fill",
            target="Email",
            selector="page.locator('#email')",
            value="user@example.test",
            source_line=13,
        )
        other_raw = RawAction(
            id="raw_selector_api_other_case",
            webwright_run_id=other_run.id,
            automation_key=other_case.automation_key,
            order_index=1,
            type="click",
            selector="page.locator('#other')",
        )
        foreign_raw = RawAction(
            id="raw_selector_api_foreign_project",
            webwright_run_id=foreign_run.id,
            automation_key=foreign_case.automation_key,
            order_index=1,
            type="click",
            selector="page.locator('#foreign')",
        )
        mapping = CaseActionMapping(
            id="map_selector_api",
            test_case_id=case.id,
            raw_action_id=raw_click.id,
            tc_step_index=1,
            normalized_step_id="flow_001",
            normalized_step_name="log_in",
            pom_method_name="log_in",
            status="mapped",
        )
        page = PageObject(
            id="po_selector_api",
            project_id=project_id,
            name="LoginPage",
            file_path="pages/login_page.py",
        )
        method = PageObjectMethod(
            id="pom_selector_api_log_in",
            page_object_id=page.id,
            name="selector_api__step_1_log_in",
            method_type="click",
            selector="page.locator('#login')",
            source_mapping_id=mapping.id,
            status="approved",
        )
        flow = StructuredFlow(
            id="flow_selector_api",
            project_id=project_id,
            test_case_id=case.id,
            automation_key=case.automation_key,
            name="Selector API",
            status="approved",
        )
        step = StructuredStep(
            id="step_selector_api",
            structured_flow_id=flow.id,
            mapping_id=mapping.id,
            order_index=1,
            name="Log in",
            page_object_method_id=method.id,
            metadata_json=json.dumps({"raw_action_ids": [raw_click.id, raw_fill.id]}),
        )
        artifact = ArtifactAsset(
            id="art_selector_api_trajectory",
            project_id=project_id,
            automation_key=case.automation_key,
            source_type=ArtifactAssetSourceType.webwright_run.value,
            source_id=run.id,
            artifact_type=ArtifactAssetType.trajectory.value,
            file_path=str(trajectory),
            content_hash="sha256:selector-api-trajectory",
            metadata_json=json.dumps({
                "file_name": "trajectory.json",
                "relative_path": "trajectory.json",
                "title": "Selector trajectory",
            }),
        )
        session.add_all([
            case,
            other_case,
            foreign_case,
            run,
            other_run,
            foreign_run,
            raw_click,
            raw_fill,
            other_raw,
            foreign_raw,
            mapping,
            page,
            method,
            flow,
            step,
            artifact,
            SelectorCandidate(
                id="sel_api_raw_role",
                raw_action_id=raw_click.id,
                selector_type="role",
                selector_value="button[name='Log in']",
                confidence=0.91,
                source_artifact_id=artifact.id,
                metadata_json=json.dumps({"source": "trajectory", "rank": 1}),
            ),
            SelectorCandidate(
                id="sel_api_pom_text",
                page_object_method_id=method.id,
                selector_type="text",
                selector_value="Log in",
                confidence=0.83,
                source_artifact_id=artifact.id,
                metadata_json=json.dumps({"source": "healing"}),
            ),
            SelectorCandidate(
                id="sel_api_both_test_id",
                raw_action_id=raw_fill.id,
                page_object_method_id=method.id,
                selector_type="test_id",
                selector_value="login-email",
                confidence=0.95,
                source_artifact_id=artifact.id,
            ),
            SelectorCandidate(
                id="sel_api_other_case_raw",
                raw_action_id=other_raw.id,
                selector_type="css",
                selector_value="#other",
                confidence=0.8,
            ),
            SelectorCandidate(
                id="sel_api_foreign_project_raw",
                raw_action_id=foreign_raw.id,
                selector_type="css",
                selector_value="#foreign",
                confidence=0.8,
            ),
        ])
        session.commit()

    return {
        "case_id": "tc_selector_api",
        "other_case_id": "tc_selector_api_other_case",
        "foreign_case_id": "tc_selector_api_foreign_project",
    }


def test_selector_candidates_api_returns_mixed_raw_action_and_pom_candidates(
    client,
    project_id: str,
    tmp_path,
) -> None:
    foreign_project_id = client.post("/projects", json={"name": "Foreign"}).json()["id"]
    seeded = _seed_selector_candidate_graph(project_id, foreign_project_id, tmp_path)

    response = client.get(
        f"/projects/{project_id}/cases/{seeded['case_id']}/selector-candidates"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["projectId"] == project_id
    assert payload["caseId"] == seeded["case_id"]
    assert payload["automationKey"] == "selector_api"
    assert payload["candidateCount"] == 3
    candidate_by_id = {candidate["id"]: candidate for candidate in payload["candidates"]}
    assert set(candidate_by_id) == {
        "sel_api_raw_role",
        "sel_api_pom_text",
        "sel_api_both_test_id",
    }

    raw_candidate = candidate_by_id["sel_api_raw_role"]
    assert raw_candidate["selectorType"] == "role"
    assert raw_candidate["selectorValue"] == "button[name='Log in']"
    assert raw_candidate["type"] == "role"
    assert raw_candidate["value"] == "button[name='Log in']"
    assert raw_candidate["confidence"] == 0.91
    assert raw_candidate["metadata"] == {"source": "trajectory", "rank": 1}
    assert raw_candidate["sourceArtifactId"] == "art_selector_api_trajectory"
    assert raw_candidate["sourceArtifact"]["filePath"].endswith("trajectory.json")
    assert raw_candidate["sourceArtifact"]["pathAvailable"] is True
    assert raw_candidate["rawAction"]["id"] == "raw_selector_api_click"
    assert raw_candidate["rawAction"]["webwrightRunId"] == "ww_selector_api"
    assert raw_candidate["rawAction"]["orderIndex"] == 1
    assert raw_candidate["pageObjectMethod"] is None

    pom_candidate = candidate_by_id["sel_api_pom_text"]
    assert pom_candidate["rawAction"] is None
    assert pom_candidate["pageObjectMethod"]["id"] == "pom_selector_api_log_in"
    assert pom_candidate["pageObjectMethod"]["pageObjectName"] == "LoginPage"
    assert pom_candidate["pageObjectMethod"]["mapping"]["tcStepIndex"] == 1
    assert pom_candidate["pageObjectMethod"]["structuredSteps"][0]["id"] == "step_selector_api"

    both_candidate = candidate_by_id["sel_api_both_test_id"]
    assert both_candidate["rawAction"]["id"] == "raw_selector_api_fill"
    assert both_candidate["rawAction"]["value"] == "user@example.test"
    assert both_candidate["pageObjectMethod"]["id"] == "pom_selector_api_log_in"

    raw_groups = {
        group["rawAction"]["id"]: set(group["candidateIds"])
        for group in payload["groups"]["rawActions"]
    }
    assert raw_groups == {
        "raw_selector_api_click": {"sel_api_raw_role"},
        "raw_selector_api_fill": {"sel_api_both_test_id"},
    }
    method_groups = {
        group["pageObjectMethod"]["id"]: set(group["candidateIds"])
        for group in payload["groups"]["pageObjectMethods"]
    }
    assert method_groups == {
        "pom_selector_api_log_in": {"sel_api_pom_text", "sel_api_both_test_id"},
    }


def test_selector_candidates_api_scopes_candidates_to_selected_case(
    client,
    project_id: str,
    tmp_path,
) -> None:
    foreign_project_id = client.post("/projects", json={"name": "Foreign"}).json()["id"]
    seeded = _seed_selector_candidate_graph(project_id, foreign_project_id, tmp_path)

    selected_response = client.get(
        f"/projects/{project_id}/cases/{seeded['case_id']}/selector-candidates"
    )
    other_response = client.get(
        f"/projects/{project_id}/cases/{seeded['other_case_id']}/selector-candidates"
    )

    assert selected_response.status_code == 200
    assert "sel_api_other_case_raw" not in {
        candidate["id"] for candidate in selected_response.json()["candidates"]
    }
    assert other_response.status_code == 200
    assert {
        candidate["id"] for candidate in other_response.json()["candidates"]
    } == {"sel_api_other_case_raw"}


def test_selector_candidates_api_rejects_case_from_another_project(
    client,
    project_id: str,
    tmp_path,
) -> None:
    foreign_project_id = client.post("/projects", json={"name": "Foreign"}).json()["id"]
    seeded = _seed_selector_candidate_graph(project_id, foreign_project_id, tmp_path)

    response = client.get(
        f"/projects/{project_id}/cases/{seeded['foreign_case_id']}/selector-candidates"
    )

    assert response.status_code == 404
