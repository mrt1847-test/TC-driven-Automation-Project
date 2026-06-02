"""C12-02: RawAction selectors produce persisted SelectorCandidate rows."""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from worker.models.db import (
    ArtifactAsset,
    ArtifactAssetSourceType,
    ArtifactAssetType,
    RawAction,
    SelectorCandidate,
    SelectorCandidateType,
    TestCase as DbTestCase,
    WebwrightRun,
)
from worker.services.selector_candidates import extract_selector_candidates_for_run


def _wait_for_run(client: TestClient, project_id: str, case_id: str, timeout_s: float = 5.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        runs = client.get(f"/projects/{project_id}/webwright-runs").json()
        for run in runs:
            if run.get("test_case_id") == case_id and run.get("status") in {"completed", "failed", "cancelled"}:
                return run
        time.sleep(0.05)
    pytest.fail("Timed out waiting for Webwright run to finish")


def test_selector_candidate_extraction_handles_common_selector_shapes(project_id: str, tmp_path) -> None:
    import worker.core.database as database

    automation_key = "selector_candidate_extraction"
    with Session(database.engine) as session:
        test_case = DbTestCase(
            id="tc_selector_extraction",
            project_id=project_id,
            source_type="excel",
            source_case_id="TC-CANDIDATES",
            title="Selector candidate extraction",
            steps_json="[]",
            automation_key=automation_key,
        )
        run = WebwrightRun(
            id="ww_selector_extraction",
            project_id=project_id,
            test_case_id=test_case.id,
            automation_key=automation_key,
            status="completed",
        )
        session.add(test_case)
        session.add(run)
        session.add(ArtifactAsset(
            id="art_selector_run_trajectory",
            project_id=project_id,
            automation_key=automation_key,
            source_type=ArtifactAssetSourceType.webwright_run.value,
            source_id=run.id,
            artifact_type=ArtifactAssetType.trajectory.value,
            file_path=str(tmp_path / "trajectory.json"),
            content_hash="sha256:trajectory",
            metadata_json=json.dumps({"source": "test"}),
        ))
        selectors = [
            ("act_role", "click", "page.get_by_role('button', name='Submit')"),
            ("act_text", "click", "page.get_by_text('Continue')"),
            ("act_test_id", "click", "page.get_by_test_id('login-submit')"),
            ("act_css", "click", "page.locator('#login')"),
            ("act_xpath", "click", "page.locator(\"//button[@id='login']\")"),
            ("act_data_testid", "click", "page.locator(\"[data-testid='checkout']\")"),
        ]
        for order, (action_id, action_type, selector) in enumerate(selectors, start=1):
            session.add(RawAction(
                id=action_id,
                webwright_run_id=run.id,
                automation_key=automation_key,
                order_index=order,
                type=action_type,
                target=selector,
                selector=selector,
                source_line=order,
            ))
        session.commit()

        first_pass = extract_selector_candidates_for_run(session, run.id)
        second_pass = extract_selector_candidates_for_run(session, run.id)
        assert len(first_pass) == len(second_pass)

    with Session(database.engine) as session:
        candidates = session.exec(
            select(SelectorCandidate).order_by(SelectorCandidate.raw_action_id, SelectorCandidate.selector_type)
        ).all()

    by_action = {candidate.raw_action_id: candidate for candidate in candidates}
    assert by_action["act_role"].selector_type == SelectorCandidateType.role.value
    assert by_action["act_role"].selector_value == "button[name='Submit']"
    assert by_action["act_text"].selector_type == SelectorCandidateType.text.value
    assert by_action["act_text"].selector_value == "Continue"
    assert by_action["act_test_id"].selector_type == SelectorCandidateType.test_id.value
    assert by_action["act_test_id"].selector_value == "login-submit"
    assert by_action["act_css"].selector_type == SelectorCandidateType.css.value
    assert by_action["act_css"].selector_value == "#login"
    assert by_action["act_xpath"].selector_type == SelectorCandidateType.xpath.value
    assert by_action["act_xpath"].selector_value == "//button[@id='login']"
    assert by_action["act_data_testid"].selector_type == SelectorCandidateType.test_id.value
    assert by_action["act_data_testid"].selector_value == "checkout"

    for candidate in by_action.values():
        assert candidate.source_artifact_id == "art_selector_run_trajectory"
        metadata = json.loads(candidate.metadata_json or "{}")
        assert metadata["run_id"] == "ww_selector_extraction"
        assert metadata["source_selector"]
        assert metadata["reason"]


def test_webwright_action_extraction_persists_selector_candidates(
    client: TestClient,
    project_id: str,
    imported_case: dict,
) -> None:
    case_id = imported_case["id"]

    queued = client.post(f"/projects/{project_id}/webwright-runs", json={"caseIds": [case_id]})
    assert queued.status_code == 200

    run = _wait_for_run(client, project_id, case_id)
    assert run["status"] == "completed"

    import worker.core.database as database

    with Session(database.engine) as session:
        candidates = session.exec(
            select(SelectorCandidate)
            .where(SelectorCandidate.selector_type == SelectorCandidateType.role.value)
            .order_by(SelectorCandidate.confidence.desc())
        ).all()
        assert candidates
        candidate = candidates[0]
        assert candidate.raw_action_id is not None
        assert candidate.selector_value == "link[name='More information']"
        assert candidate.source_artifact_id is not None
        artifact = session.get(ArtifactAsset, candidate.source_artifact_id)
        assert artifact is not None
        assert artifact.source_type == ArtifactAssetSourceType.webwright_run.value
        assert artifact.source_id == run["id"]
