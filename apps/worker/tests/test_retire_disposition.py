from __future__ import annotations

import json
from pathlib import Path

from sqlmodel import Session

from worker.models.db import (
    ArtifactAsset,
    CaseActionMapping,
    ExecutionResult,
    ExecutionRun,
    GeneratedFile,
    GeneratedFileOrigin,
    PageObject,
    PageObjectMethod,
    Project,
    RawAction,
    StructuredFlow,
    StructuredStep,
    TestCase as DbTestCase,
    WebwrightRun,
)
from worker.services.generated_file_status import hash_file


def _seed_failure(
    session: Session,
    project_id: str,
    key: str,
    *,
    error: str = "feature removed and no longer exists",
    error_category: str = "feature_removed",
    with_target: bool = True,
) -> dict:
    project = session.get(Project, project_id)
    output = Path(project.generated_project_path)
    execution_id = f"exec_disposition_{key}"
    result_id = f"result_disposition_{key}"
    case_id = f"case_disposition_{key}"
    artifact_id = f"artifact_disposition_{key}"
    case = DbTestCase(
        id=case_id,
        project_id=project_id,
        source_type="excel",
        source_case_id=f"TC-{key}",
        title=f"Disposition {key}",
        automation_key=key,
        status="generated",
    )
    session.add(case)
    session.add(ExecutionRun(
        id=execution_id,
        project_id=project_id,
        run_id=f"run_disposition_{key}",
        env="stg",
        browser="chromium",
        status="failed",
    ))
    session.add(ExecutionResult(
        id=result_id,
        execution_run_id=execution_id,
        automation_key=key,
        source_type=case.source_type,
        source_case_id=case.source_case_id,
        title=case.title,
        status="failed",
        error=error,
    ))
    session.add(ArtifactAsset(
        id=artifact_id,
        project_id=project_id,
        automation_key=key,
        source_type="execution_result",
        source_id=result_id,
        artifact_type="trace",
        file_path=f"artifacts/{key}.zip",
        metadata_json=json.dumps({"error_category": error_category}),
    ))

    generated_path = None
    generated_file_id = None
    if with_target:
        webwright_id = f"ww_disposition_{key}"
        raw_id = f"raw_disposition_{key}"
        mapping_id = f"mapping_disposition_{key}"
        flow_id = f"flow_disposition_{key}"
        page_id = f"page_disposition_{key}"
        method_id = f"method_disposition_{key}"
        generated_file_id = f"generated_disposition_{key}"
        session.add(WebwrightRun(
            id=webwright_id,
            project_id=project_id,
            test_case_id=case_id,
            automation_key=key,
            status="completed",
        ))
        session.add(RawAction(
            id=raw_id,
            webwright_run_id=webwright_id,
            automation_key=key,
            order_index=1,
            type="click",
            selector="page.locator('#retired-feature')",
        ))
        session.add(CaseActionMapping(
            id=mapping_id,
            test_case_id=case_id,
            raw_action_id=raw_id,
            tc_step_index=1,
        ))
        session.add(StructuredFlow(
            id=flow_id,
            project_id=project_id,
            test_case_id=case_id,
            automation_key=key,
            name=f"flow_{key}",
        ))
        session.add(PageObject(
            id=page_id,
            project_id=project_id,
            name=f"Page{key.title().replace('_', '')}",
            file_path=f"pages/{key}.py",
        ))
        session.add(PageObjectMethod(
            id=method_id,
            page_object_id=page_id,
            name=f"perform_{key}",
            method_type="click",
            selector="page.locator('#retired-feature')",
            source_mapping_id=mapping_id,
        ))
        session.add(StructuredStep(
            id=f"step_disposition_{key}",
            structured_flow_id=flow_id,
            mapping_id=mapping_id,
            order_index=1,
            name=f"perform {key}",
            page_object_method_id=method_id,
        ))
        relative_path = f"tests/test_{key}.py"
        generated_path = output / relative_path
        generated_path.parent.mkdir(parents=True, exist_ok=True)
        generated_path.write_text(f"# generated {key}\n", encoding="utf-8")
        session.add(GeneratedFile(
            id=generated_file_id,
            project_id=project_id,
            relative_path=relative_path,
            automation_key=key,
            source_type="structured_flow",
            source_id=flow_id,
            content_hash=hash_file(generated_path),
        ))
        session.add(GeneratedFileOrigin(
            generated_file_id=generated_file_id,
            origin_type="test_case",
            origin_id=case_id,
        ))

    session.commit()
    return {
        "case_id": case_id,
        "execution_id": execution_id,
        "result_id": result_id,
        "artifact_id": artifact_id,
        "generated_file_id": generated_file_id,
        "generated_path": generated_path,
    }


def _retire_url(project_id: str, seeded: dict) -> str:
    return (
        f"/projects/{project_id}/executions/{seeded['execution_id']}"
        f"/results/{seeded['result_id']}/retire"
    )


def _retire_preview_url(project_id: str, seeded: dict) -> str:
    return (
        f"/projects/{project_id}/executions/{seeded['execution_id']}"
        f"/results/{seeded['result_id']}/retire/preview"
    )


def test_feature_removed_disposition_preview_reports_cleanup_without_mutation(
    client,
    project_id: str,
) -> None:
    import worker.core.database as database

    with Session(database.engine) as session:
        seeded = _seed_failure(session, project_id, "preview_retire")

    response = client.post(
        _retire_preview_url(project_id, seeded),
        json={"caseId": seeded["case_id"], "action": "retire"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["preview"] is True
    assert body["cleanup"]["preview"] is True
    assert body["cleanup"]["status"] == "preview"
    assert body["cleanup"]["removedFiles"] == ["tests/test_preview_retire.py"]
    assert seeded["generated_path"].exists()

    with Session(database.engine) as session:
        assert session.get(DbTestCase, seeded["case_id"]).status == "generated"


def test_feature_removed_disposition_invokes_confirmed_cleanup(
    client,
    project_id: str,
) -> None:
    import worker.core.database as database

    with Session(database.engine) as session:
        seeded = _seed_failure(session, project_id, "confirmed_retire")

    response = client.post(
        _retire_url(project_id, seeded),
        json={"caseId": seeded["case_id"], "confirmed": True, "action": "retire"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["caseId"] == seeded["case_id"]
    assert body["diagnosis"]["disposition"] == "feature_removed_retire_tc"
    assert body["diagnosis"]["reason"] == "linked_feature_removed_evidence"
    assert body["diagnosis"]["confidence"] == 0.85
    assert body["diagnosis"]["evidence_artifact_ids"] == [seeded["artifact_id"]]
    assert body["diagnosis"]["target"]["test_case_ids"] == [seeded["case_id"]]
    assert body["cleanup"]["status"] == "completed"
    assert body["cleanup"]["caseStatus"] == "retired"
    assert body["cleanup"]["reason"] == body["diagnosis"]["reason"]
    assert body["cleanup"]["removedFiles"] == ["tests/test_confirmed_retire.py"]
    assert not seeded["generated_path"].exists()

    with Session(database.engine) as session:
        assert session.get(DbTestCase, seeded["case_id"]).status == "retired"
        assert session.get(GeneratedFile, seeded["generated_file_id"]).status == "obsolete"
        assert session.get(ExecutionResult, seeded["result_id"]) is not None
        assert session.get(ArtifactAsset, seeded["artifact_id"]) is not None


def test_retire_disposition_rejections_leave_cases_and_files_unchanged(
    client,
    project_id: str,
) -> None:
    import worker.core.database as database

    with Session(database.engine) as session:
        unconfirmed = _seed_failure(session, project_id, "unconfirmed_retire")
        non_feature = _seed_failure(
            session,
            project_id,
            "raw_refresh_retire",
            error="workflow changed and reached unexpected page",
            error_category="flow_changed",
        )
        mismatch = _seed_failure(session, project_id, "mismatched_retire")
        mismatch_case_id = "case_disposition_other"
        mismatch_case = DbTestCase(
            id=mismatch_case_id,
            project_id=project_id,
            source_type="excel",
            source_case_id="TC-other",
            title="Other case",
            automation_key="other_case",
            status="generated",
        )
        session.add(mismatch_case)
        session.commit()
        unresolved = _seed_failure(
            session,
            project_id,
            "unresolved_retire",
            with_target=False,
        )
        before = {
            item["case_id"]: item["generated_path"].read_bytes()
            for item in [unconfirmed, non_feature, mismatch]
        }

    unconfirmed_response = client.post(
        _retire_url(project_id, unconfirmed),
        json={"caseId": unconfirmed["case_id"], "action": "retire"},
    )
    non_feature_response = client.post(
        _retire_url(project_id, non_feature),
        json={"caseId": non_feature["case_id"], "confirmed": True, "action": "retire"},
    )
    mismatch_response = client.post(
        _retire_url(project_id, mismatch),
        json={"caseId": mismatch_case_id, "confirmed": True, "action": "retire"},
    )
    unresolved_response = client.post(
        _retire_url(project_id, unresolved),
        json={"caseId": unresolved["case_id"], "confirmed": True, "action": "retire"},
    )

    assert unconfirmed_response.status_code == 400
    assert unconfirmed_response.json()["detail"] == (
        "Retire disposition action requires confirmed=true"
    )
    assert non_feature_response.status_code == 400
    assert "raw_refresh_required" in non_feature_response.json()["detail"]
    assert mismatch_response.status_code == 400
    assert mismatch_response.json()["detail"] == (
        "Failure diagnosis automation key does not match selected case"
    )
    assert unresolved_response.status_code == 400
    assert unresolved_response.json()["detail"] == "Failure target is not resolved: missing"

    with Session(database.engine) as session:
        for item in [unconfirmed, non_feature, mismatch, unresolved]:
            assert session.get(DbTestCase, item["case_id"]).status == "generated"
        assert session.get(DbTestCase, mismatch_case_id).status == "generated"
        for item in [unconfirmed, non_feature, mismatch]:
            assert item["generated_path"].read_bytes() == before[item["case_id"]]
            assert session.get(GeneratedFile, item["generated_file_id"]).status == "generated"
