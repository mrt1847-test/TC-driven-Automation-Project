from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from worker.models.db import (
    ArtifactAsset,
    CaseActionMapping,
    ExecutionResult,
    ExecutionRun,
    GeneratedFile,
    HealingProposal,
    PageObject,
    PageObjectMethod,
    RawAction,
    SelectorCandidate,
    StructuredFlow,
    StructuredStep,
    TestCase as DbTestCase,
    WebwrightRun,
)


def _add_resolved_failure(
    session: Session,
    project_id: str,
    execution_id: str,
    key: str,
    error: str,
    error_category: str | None,
    *,
    selector_context: bool = True,
) -> tuple[ExecutionResult, ArtifactAsset]:
    test_case = DbTestCase(
        id=f"case_{key}",
        project_id=project_id,
        source_type="excel",
        source_case_id=f"TC-{key}",
        title=f"Disposition {key}",
        automation_key=key,
    )
    webwright_run = WebwrightRun(
        id=f"ww_{key}",
        project_id=project_id,
        test_case_id=test_case.id,
        automation_key=key,
        status="completed",
    )
    raw_action = RawAction(
        id=f"raw_{key}",
        webwright_run_id=webwright_run.id,
        automation_key=key,
        order_index=1,
        type="click",
        selector="page.locator('#submit')" if selector_context else None,
    )
    mapping = CaseActionMapping(
        id=f"mapping_{key}",
        test_case_id=test_case.id,
        raw_action_id=raw_action.id,
        tc_step_index=1,
    )
    flow = StructuredFlow(
        id=f"flow_{key}",
        project_id=project_id,
        test_case_id=test_case.id,
        automation_key=key,
        name=f"flow_{key}",
    )
    page_object = PageObject(
        id=f"page_{key}",
        project_id=project_id,
        name=f"Page{key.title().replace('_', '')}",
        file_path=f"pages/{key}.py",
    )
    method = PageObjectMethod(
        id=f"pom_{key}",
        page_object_id=page_object.id,
        name=f"perform_{key}",
        method_type="click",
        selector="page.locator('#submit')" if selector_context else None,
        source_mapping_id=mapping.id,
    )
    step = StructuredStep(
        id=f"step_{key}",
        structured_flow_id=flow.id,
        mapping_id=mapping.id,
        order_index=1,
        name=f"perform {key}",
        page_object_method_id=method.id,
    )
    generated_file = GeneratedFile(
        id=f"generated_{key}",
        project_id=project_id,
        relative_path=f"tests/test_{key}.py",
        automation_key=key,
        source_type="structured_flow",
        source_id=flow.id,
    )
    result = ExecutionResult(
        id=f"result_{key}",
        execution_run_id=execution_id,
        automation_key=key,
        source_type="excel",
        source_case_id=test_case.source_case_id,
        title=test_case.title,
        status="failed",
        error=error,
    )
    metadata = {"error_category": error_category} if error_category else {}
    artifact = ArtifactAsset(
        id=f"artifact_{key}",
        project_id=project_id,
        automation_key=key,
        source_type="execution_result",
        source_id=result.id,
        artifact_type="trace",
        file_path=f"artifacts/{key}.zip",
        metadata_json=json.dumps(metadata),
    )
    values = [
        test_case,
        webwright_run,
        raw_action,
        mapping,
        flow,
        page_object,
        method,
        step,
        generated_file,
        result,
        artifact,
    ]
    if selector_context:
        values.append(
            SelectorCandidate(
                id=f"candidate_{key}",
                raw_action_id=raw_action.id,
                page_object_method_id=method.id,
                selector_type="test_id",
                selector_value="submit",
                confidence=0.97,
                source_artifact_id=artifact.id,
            )
        )
    session.add_all(values)
    return result, artifact


def test_execution_diagnosis_classifies_each_failed_case_and_falls_back_conservatively(
    client: TestClient,
    project_id: str,
) -> None:
    import worker.core.database as database

    execution_id = "exec_disposition"
    with Session(database.engine) as session:
        session.add(
            ExecutionRun(
                id=execution_id,
                project_id=project_id,
                run_id="runner_disposition",
                env="stg",
                browser="chromium",
                status="failed",
            )
        )
        selector_result, selector_artifact = _add_resolved_failure(
            session,
            project_id,
            execution_id,
            "selector",
            "locator('#submit') not found",
            "selector_not_found",
        )
        raw_result, raw_artifact = _add_resolved_failure(
            session,
            project_id,
            execution_id,
            "raw_refresh",
            "workflow changed and reached unexpected page",
            "flow_changed",
        )
        retire_result, retire_artifact = _add_resolved_failure(
            session,
            project_id,
            execution_id,
            "retire",
            "feature removed and no longer exists",
            "feature_removed",
        )
        mixed_result, mixed_artifact = _add_resolved_failure(
            session,
            project_id,
            execution_id,
            "mixed",
            "locator('#submit') not found",
            "feature_removed",
        )
        no_selector_result, no_selector_artifact = _add_resolved_failure(
            session,
            project_id,
            execution_id,
            "no_selector",
            "selector not found",
            "selector_not_found",
            selector_context=False,
        )
        missing_result = ExecutionResult(
            id="result_missing_target",
            execution_run_id=execution_id,
            automation_key="missing_target",
            source_type="excel",
            source_case_id="TC-missing-target",
            status="failed",
            error="locator('#missing') not found",
        )
        missing_artifact = ArtifactAsset(
            id="artifact_missing_target",
            project_id=project_id,
            automation_key="missing_target",
            source_type="execution_result",
            source_id=missing_result.id,
            artifact_type="trace",
            file_path="artifacts/missing-target.zip",
            metadata_json=json.dumps({"error_category": "selector_not_found"}),
        )
        session.add(missing_result)
        session.add(missing_artifact)
        session.add(
            ExecutionResult(
                id="result_passed",
                execution_run_id=execution_id,
                automation_key="passed_case",
                status="passed",
            )
        )
        result_ids = {
            "selector": selector_result.id,
            "raw_refresh": raw_result.id,
            "retire": retire_result.id,
            "mixed": mixed_result.id,
            "no_selector": no_selector_result.id,
            "missing": missing_result.id,
        }
        artifact_ids = {
            "selector": selector_artifact.id,
            "raw_refresh": raw_artifact.id,
            "retire": retire_artifact.id,
            "mixed": mixed_artifact.id,
            "no_selector": no_selector_artifact.id,
            "missing": missing_artifact.id,
        }
        session.commit()

    response = client.post(f"/projects/{project_id}/executions/{execution_id}/diagnose")
    assert response.status_code == 200
    payload = response.json()
    assert payload["project_id"] == project_id
    assert payload["execution_id"] == execution_id
    by_result = {item["execution_result_id"]: item for item in payload["diagnoses"]}
    assert len(by_result) == 6
    assert "result_passed" not in by_result

    selector = by_result[result_ids["selector"]]
    assert selector["disposition"] == "selector_changed"
    assert selector["reason"] == "linked_selector_failure_evidence"
    assert selector["confidence"] == 0.9
    assert selector["selector_candidate_ids"] == ["candidate_selector"]
    assert selector["evidence_artifact_ids"] == [artifact_ids["selector"]]
    assert selector["target"]["structured_step_id"] == "step_selector"
    assert selector["target"]["page_object_method_id"] == "pom_selector"

    raw_refresh = by_result[result_ids["raw_refresh"]]
    assert raw_refresh["disposition"] == "raw_refresh_required"
    assert raw_refresh["reason"] == "linked_flow_change_evidence"
    assert raw_refresh["confidence"] == 0.8
    assert raw_refresh["evidence_artifact_ids"] == [artifact_ids["raw_refresh"]]

    retire = by_result[result_ids["retire"]]
    assert retire["disposition"] == "feature_removed_retire_tc"
    assert retire["reason"] == "linked_feature_removed_evidence"
    assert retire["confidence"] == 0.85
    assert retire["evidence_artifact_ids"] == [artifact_ids["retire"]]

    mixed = by_result[result_ids["mixed"]]
    assert mixed["disposition"] == "unknown"
    assert mixed["reason"] == "mixed_failure_signals"
    assert mixed["evidence_artifact_ids"] == [artifact_ids["mixed"]]

    no_selector = by_result[result_ids["no_selector"]]
    assert no_selector["disposition"] == "unknown"
    assert no_selector["reason"] == "selector_signal_without_linked_selector_evidence"
    assert no_selector["evidence_artifact_ids"] == [artifact_ids["no_selector"]]

    missing = by_result[result_ids["missing"]]
    assert missing["disposition"] == "unknown"
    assert missing["reason"] == "target_missing:generated_files_missing"
    assert missing["evidence_artifact_ids"] == [artifact_ids["missing"]]

    with Session(database.engine) as session:
        assert session.exec(select(HealingProposal)).all() == []
        assert all(
            generated_file.status == "generated"
            for generated_file in session.exec(select(GeneratedFile)).all()
        )


def test_execution_diagnosis_rejects_an_execution_from_another_project(
    client: TestClient,
    project_id: str,
) -> None:
    import worker.core.database as database

    with Session(database.engine) as session:
        session.add(
            ExecutionRun(
                id="exec_other_project",
                project_id=project_id,
                run_id="runner_other_project",
                env="stg",
                browser="chromium",
                status="failed",
            )
        )
        session.commit()

    response = client.post("/projects/not-the-project/executions/exec_other_project/diagnose")
    assert response.status_code == 404
