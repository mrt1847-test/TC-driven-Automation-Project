"""A2-14: SelectorCandidate metadata is durable for self-healing evidence."""

from __future__ import annotations

import json

from sqlalchemy import inspect
from sqlmodel import Session, select

from worker.models.db import (
    ArtifactAsset,
    ArtifactAssetSourceType,
    ArtifactAssetType,
    PageObject,
    PageObjectMethod,
    RawAction,
    SelectorCandidate,
    SelectorCandidateType,
    TestCase as DbTestCase,
    WebwrightRun,
)


def test_selector_candidates_persist_action_method_and_artifact_links(project_id: str, tmp_path) -> None:
    import worker.core.database as database

    inspector = inspect(database.engine)
    assert "selector_candidates" in inspector.get_table_names()
    columns = {column["name"] for column in inspector.get_columns(SelectorCandidate.__tablename__)}
    assert {
        "raw_action_id",
        "page_object_method_id",
        "selector_type",
        "selector_value",
        "confidence",
        "source_artifact_id",
        "metadata_json",
        "created_at",
    }.issubset(columns)

    index_names = {index["name"] for index in inspector.get_indexes(SelectorCandidate.__tablename__)}
    assert {"idx_selector_candidates_raw_action", "idx_selector_candidates_method"}.issubset(index_names)

    automation_key = "selector_login"
    with Session(database.engine) as session:
        test_case = DbTestCase(
            id="tc_selector_candidate",
            project_id=project_id,
            source_type="excel",
            source_case_id="TC-SELECTOR",
            title="Selector evidence case",
            steps_json="[]",
            automation_key=automation_key,
        )
        webwright_run = WebwrightRun(
            id="ww_selector_candidate",
            project_id=project_id,
            test_case_id=test_case.id,
            automation_key=automation_key,
            status="completed",
        )
        raw_action = RawAction(
            id="act_selector_candidate",
            webwright_run_id=webwright_run.id,
            automation_key=automation_key,
            order_index=1,
            type="click",
            target="Sign in button",
            selector="page.locator('#login')",
        )
        page_object = PageObject(
            id="po_selector_login",
            project_id=project_id,
            name="SelectorLoginPage",
            file_path="pages/selector_login_page.py",
        )
        page_object_method = PageObjectMethod(
            id="pom_selector_login",
            page_object_id=page_object.id,
            name="submit_login",
            method_type="click",
            selector="page.locator('#login')",
            body_plan_json="[]",
            status="draft",
        )
        artifact = ArtifactAsset(
            id="art_selector_trajectory",
            project_id=project_id,
            automation_key=automation_key,
            source_type=ArtifactAssetSourceType.raw_action.value,
            source_id=raw_action.id,
            artifact_type=ArtifactAssetType.trajectory.value,
            file_path=str(tmp_path / "trajectory.json"),
            content_hash="sha256:trajectory",
            metadata_json=json.dumps({"dom_snapshot": "button#login"}),
        )
        session.add(test_case)
        session.add(webwright_run)
        session.add(raw_action)
        session.add(page_object)
        session.add(page_object_method)
        session.add(artifact)
        session.add(SelectorCandidate(
            id="sel_role_login",
            raw_action_id=raw_action.id,
            page_object_method_id=page_object_method.id,
            selector_type=SelectorCandidateType.role.value,
            selector_value="button[name='Sign in']",
            confidence=0.92,
            source_artifact_id=artifact.id,
            metadata_json=json.dumps({"reason": "accessible role matched"}),
        ))
        session.add(SelectorCandidate(
            id="sel_css_login",
            raw_action_id=raw_action.id,
            page_object_method_id=page_object_method.id,
            selector_type=SelectorCandidateType.css.value,
            selector_value="button[type='submit']",
            confidence=0.64,
            source_artifact_id=artifact.id,
            metadata_json=json.dumps({"reason": "fallback css"}),
        ))
        session.commit()

    with Session(database.engine) as session:
        candidates = session.exec(
            select(SelectorCandidate)
            .where(SelectorCandidate.raw_action_id == "act_selector_candidate")
            .order_by(SelectorCandidate.confidence.desc())
        ).all()

    assert [candidate.id for candidate in candidates] == ["sel_role_login", "sel_css_login"]
    assert candidates[0].page_object_method_id == "pom_selector_login"
    assert candidates[0].source_artifact_id == "art_selector_trajectory"
    assert candidates[0].selector_type == SelectorCandidateType.role.value
    assert candidates[0].selector_value == "button[name='Sign in']"
    assert candidates[0].confidence == 0.92
    assert json.loads(candidates[0].metadata_json or "{}")["reason"] == "accessible role matched"
