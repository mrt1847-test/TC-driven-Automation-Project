"""A2-15: HealingProposal metadata is durable for self-healing review."""

from __future__ import annotations

import json

from sqlalchemy import inspect
from sqlmodel import Session, select

from worker.models.db import (
    ArtifactAsset,
    ArtifactAssetSourceType,
    ArtifactAssetType,
    ExecutionResult,
    ExecutionRun,
    HealingProposal,
    HealingProposalKind,
    HealingProposalStatus,
    PageObject,
    PageObjectMethod,
    RawAction,
    SelectorCandidate,
    SelectorCandidateType,
    StructuredFlow,
    StructuredStep,
    TestCase as DbTestCase,
    WebwrightRun,
)


def test_healing_proposals_persist_targets_status_and_evidence(project_id: str, tmp_path) -> None:
    import worker.core.database as database

    inspector = inspect(database.engine)
    assert "healing_proposals" in inspector.get_table_names()
    columns = {column["name"] for column in inspector.get_columns(HealingProposal.__tablename__)}
    assert {
        "project_id",
        "automation_key",
        "execution_result_id",
        "page_object_method_id",
        "structured_step_id",
        "kind",
        "old_value",
        "new_value",
        "confidence",
        "status",
        "evidence_json",
        "created_at",
        "updated_at",
    }.issubset(columns)

    index_names = {index["name"] for index in inspector.get_indexes(HealingProposal.__tablename__)}
    assert "idx_healing_proposals_key_status" in index_names

    automation_key = "healing_login"
    with Session(database.engine) as session:
        test_case = DbTestCase(
            id="tc_healing_proposal",
            project_id=project_id,
            source_type="excel",
            source_case_id="TC-HEALING",
            title="Healing proposal case",
            steps_json="[]",
            automation_key=automation_key,
        )
        webwright_run = WebwrightRun(
            id="ww_healing_proposal",
            project_id=project_id,
            test_case_id=test_case.id,
            automation_key=automation_key,
            status="completed",
        )
        raw_action = RawAction(
            id="act_healing_proposal",
            webwright_run_id=webwright_run.id,
            automation_key=automation_key,
            order_index=1,
            type="click",
            target="Login button",
            selector="page.locator('#login')",
        )
        structured_flow = StructuredFlow(
            id="sf_healing_proposal",
            project_id=project_id,
            test_case_id=test_case.id,
            automation_key=automation_key,
            name="login_flow",
            status="approved",
            version=1,
        )
        structured_step = StructuredStep(
            id="ss_healing_proposal",
            structured_flow_id=structured_flow.id,
            order_index=1,
            name="submit_login",
            kind="interaction",
        )
        page_object = PageObject(
            id="po_healing_login",
            project_id=project_id,
            name="HealingLoginPage",
            file_path="pages/healing_login_page.py",
        )
        page_object_method = PageObjectMethod(
            id="pom_healing_login",
            page_object_id=page_object.id,
            name="submit_login",
            method_type="click",
            selector="page.locator('#login')",
            body_plan_json="[]",
            status="approved",
        )
        execution_run = ExecutionRun(
            id="exec_healing_proposal",
            project_id=project_id,
            run_id="runner_healing_proposal",
            env="stg",
            browser="chromium",
            headed=False,
            status="failed",
            result_path=str(tmp_path / "results.json"),
        )
        execution_result = ExecutionResult(
            id="res_healing_proposal",
            execution_run_id=execution_run.id,
            automation_key=automation_key,
            source_type="excel",
            source_case_id="TC-HEALING",
            title="Healing proposal case",
            status="failed",
            error="locator('#login') not found",
            screenshot_path=str(tmp_path / "failed.png"),
            trace_path=str(tmp_path / "trace.zip"),
        )
        artifact = ArtifactAsset(
            id="art_healing_trace",
            project_id=project_id,
            automation_key=automation_key,
            source_type=ArtifactAssetSourceType.execution_result.value,
            source_id=execution_result.id,
            artifact_type=ArtifactAssetType.trace.value,
            file_path=str(tmp_path / "trace.zip"),
            content_hash="sha256:trace",
            metadata_json=json.dumps({"error_category": "selector_not_found"}),
        )
        selector_candidate = SelectorCandidate(
            id="sel_healing_role",
            raw_action_id=raw_action.id,
            page_object_method_id=page_object_method.id,
            selector_type=SelectorCandidateType.role.value,
            selector_value="button[name='Login']",
            confidence=0.91,
            source_artifact_id=artifact.id,
        )
        evidence = [
            {
                "artifact_id": artifact.id,
                "selector_candidate_id": selector_candidate.id,
                "note": "trace shows accessible login button",
            },
        ]
        session.add(test_case)
        session.add(webwright_run)
        session.add(raw_action)
        session.add(structured_flow)
        session.add(structured_step)
        session.add(page_object)
        session.add(page_object_method)
        session.add(execution_run)
        session.add(execution_result)
        session.add(artifact)
        session.add(selector_candidate)
        session.add(HealingProposal(
            id="heal_selector_login",
            project_id=project_id,
            automation_key=automation_key,
            execution_result_id=execution_result.id,
            page_object_method_id=page_object_method.id,
            structured_step_id=structured_step.id,
            kind=HealingProposalKind.selector_replace.value,
            old_value="page.locator('#login')",
            new_value="page.get_by_role('button', name='Login')",
            confidence=0.88,
            evidence_json=json.dumps(evidence),
        ))
        session.commit()

    with Session(database.engine) as session:
        proposal = session.exec(
            select(HealingProposal)
            .where(HealingProposal.project_id == project_id)
            .where(HealingProposal.automation_key == automation_key)
            .where(HealingProposal.status == HealingProposalStatus.proposed.value)
        ).one()

    assert proposal.execution_result_id == "res_healing_proposal"
    assert proposal.page_object_method_id == "pom_healing_login"
    assert proposal.structured_step_id == "ss_healing_proposal"
    assert proposal.kind == HealingProposalKind.selector_replace.value
    assert proposal.status == HealingProposalStatus.proposed.value
    assert proposal.old_value == "page.locator('#login')"
    assert proposal.new_value == "page.get_by_role('button', name='Login')"
    assert proposal.confidence == 0.88
    assert proposal.created_at is not None
    assert proposal.updated_at is not None

    saved_evidence = json.loads(proposal.evidence_json)
    assert saved_evidence == [
        {
            "artifact_id": "art_healing_trace",
            "selector_candidate_id": "sel_healing_role",
            "note": "trace shows accessible login button",
        },
    ]
