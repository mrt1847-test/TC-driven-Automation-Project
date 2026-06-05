from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlmodel import Session, select

from worker.models.db import (
    ArtifactAsset,
    CaseActionMapping,
    CaseActionMappingAction,
    ExecutionResult,
    ExecutionRun,
    GeneratedFile,
    GeneratedFileStatus,
    HealingProposal,
    PageObject,
    PageObjectMethod,
    Project,
    RawAction,
    SelectorCandidate,
    StructuredFlow,
    StructuredStep,
    TestCase as DbTestCase,
    WebwrightRun,
)
from worker.services.project_generator import generate_project


def _seed_failure(
    session: Session,
    project_id: str,
    execution_id: str,
    key: str,
    *,
    error: str = "locator('#old-submit') not found",
    error_category: str = "selector_not_found",
    with_target: bool = True,
    with_candidate: bool = True,
    candidate_confidence: float = 0.96,
    candidate_selector_type: str = "test_id",
    candidate_selector_value: str | None = None,
    extra_candidates: list[dict] | None = None,
    generated_page_target: bool = False,
) -> str:
    case_id = f"case_heal_{key}"
    result_id = f"result_heal_{key}"
    session.add(DbTestCase(
        id=case_id,
        project_id=project_id,
        source_type="excel",
        source_case_id=f"TC-HEAL-{key}",
        title=f"Heal {key}",
        automation_key=key,
        status="generated",
    ))
    session.add(ExecutionResult(
        id=result_id,
        execution_run_id=execution_id,
        automation_key=key,
        source_type="excel",
        source_case_id=f"TC-HEAL-{key}",
        title=f"Heal {key}",
        status="failed",
        error=error,
    ))
    artifact = ArtifactAsset(
        id=f"artifact_heal_{key}",
        project_id=project_id,
        automation_key=key,
        source_type="execution_result",
        source_id=result_id,
        artifact_type="trace",
        file_path=f"artifacts/{key}.zip",
        metadata_json=json.dumps({"error_category": error_category}),
    )
    session.add(artifact)
    if not with_target:
        session.commit()
        return result_id

    run_id = f"ww_heal_{key}"
    raw_id = f"raw_heal_{key}"
    mapping_id = f"mapping_heal_{key}"
    flow_id = f"flow_heal_{key}"
    page_id = f"page_heal_{key}"
    method_id = f"pom_heal_{key}"
    method_name = f"perform_{key}"
    body_plan = [{
        "action": "click",
        "order": 1,
        "requiresReview": False,
        "selector": "page.locator('#old-submit')",
        "sourceMappingId": mapping_id,
        "sourceRawActionId": raw_id,
    }]
    session.add(WebwrightRun(
        id=run_id,
        project_id=project_id,
        test_case_id=case_id,
        automation_key=key,
        status="completed",
    ))
    session.add(RawAction(
        id=raw_id,
        webwright_run_id=run_id,
        automation_key=key,
        order_index=1,
        type="click",
        selector="page.locator('#old-submit')",
    ))
    session.add(CaseActionMapping(
        id=mapping_id,
        test_case_id=case_id,
        raw_action_id=raw_id,
        tc_step_index=1,
        normalized_step_id=f"flow_{key}",
        normalized_step_name=method_name,
        pom_method_name=method_name,
        status="mapped",
    ))
    session.add(CaseActionMappingAction(
        mapping_id=mapping_id,
        raw_action_id=raw_id,
        order_index=0,
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
        name="GeneratedPage" if generated_page_target else f"Page{key.title().replace('_', '')}",
        file_path="pages/generated_page.py" if generated_page_target else f"pages/{key}.py",
    ))
    session.add(PageObjectMethod(
        id=method_id,
        page_object_id=page_id,
        name=method_name,
        method_type="click",
        selector="page.locator('#old-submit')",
        body_plan_json=json.dumps(body_plan, sort_keys=True, separators=(",", ":")),
        source_mapping_id=mapping_id,
        status="approved",
    ))
    session.add(StructuredStep(
        id=f"step_heal_{key}",
        structured_flow_id=flow_id,
        mapping_id=mapping_id,
        order_index=1,
        name=f"perform {key}",
        page_object_method_id=method_id,
    ))
    session.add(GeneratedFile(
        id=f"generated_heal_{key}",
        project_id=project_id,
        relative_path=f"tests/test_{key}.py",
        automation_key=key,
        source_type="structured_flow",
        source_id=flow_id,
    ))
    if with_candidate:
        session.add(SelectorCandidate(
            id=f"candidate_heal_{key}",
            raw_action_id=raw_id,
            page_object_method_id=method_id,
            selector_type=candidate_selector_type,
            selector_value=candidate_selector_value or f"{key}-submit",
            confidence=candidate_confidence,
            source_artifact_id=artifact.id,
            metadata_json=json.dumps({"source": "test"}),
        ))
    for index, candidate_data in enumerate(extra_candidates or [], start=2):
        session.add(SelectorCandidate(
            id=candidate_data.get("id", f"candidate_heal_{key}_{index}"),
            raw_action_id=raw_id,
            page_object_method_id=method_id,
            selector_type=candidate_data.get("selector_type", "test_id"),
            selector_value=candidate_data.get("selector_value", f"{key}-submit-{index}"),
            confidence=candidate_data.get("confidence", 0.96),
            source_artifact_id=candidate_data.get("source_artifact_id", artifact.id),
            metadata_json=json.dumps(candidate_data.get("metadata", {"source": "test"})),
        ))
    session.commit()
    return result_id


def _execution_url(project_id: str, execution_id: str) -> str:
    return f"/projects/{project_id}/executions/{execution_id}/healing-proposals"


def _patch_template(monkeypatch, tmp_path: Path) -> None:
    import worker.services.project_generator as project_generator

    template = tmp_path / "healing-template"
    (template / "runner").mkdir(parents=True)
    (template / "runner" / "cli.py").write_text("# runtime\n", encoding="utf-8")
    (template / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    monkeypatch.setattr(project_generator, "load_settings", lambda: None)
    monkeypatch.setattr(
        project_generator,
        "resolve_runtime",
        lambda _settings: SimpleNamespace(template_path=str(template)),
    )


def _enable_auto_apply(client, project_id: str) -> None:
    settings = client.get("/settings").json()
    settings["self_healing"] = {"autoApplyProjectIds": [project_id]}
    response = client.put("/settings", json=settings)
    assert response.status_code == 200


def _create_selector_proposal(client, project_id: str, execution_id: str, result_id: str) -> dict:
    response = client.post(
        _execution_url(project_id, execution_id),
        json={"executionResultId": result_id},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "created"
    return body["proposal"]


def test_selector_changed_failure_creates_evidence_backed_proposal(
    client,
    project_id: str,
) -> None:
    import worker.core.database as database

    execution_id = "exec_heal_selector"
    with Session(database.engine) as session:
        session.add(ExecutionRun(
            id=execution_id,
            project_id=project_id,
            run_id="run_heal_selector",
            env="stg",
            browser="chromium",
            status="failed",
        ))
        result_id = _seed_failure(session, project_id, execution_id, "selector")

    response = client.post(
        _execution_url(project_id, execution_id),
        json={"executionResultId": result_id},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "created"
    assert body["autoApply"] == {
        "status": "disabled",
        "reason": "project_auto_apply_disabled",
    }
    assert body["diagnosis"]["disposition"] == "selector_changed"
    proposal = body["proposal"]
    assert proposal["automation_key"] == "selector"
    assert proposal["execution_result_id"] == result_id
    assert proposal["page_object_method_id"] == "pom_heal_selector"
    assert proposal["structured_step_id"] == "step_heal_selector"
    assert proposal["kind"] == "selector_replace"
    assert proposal["old_value"] == "page.locator('#old-submit')"
    assert proposal["new_value"] == 'page.get_by_test_id("selector-submit")'
    assert proposal["confidence"] == 0.96
    assert proposal["status"] == "proposed"
    assert proposal["evidence"][0]["selector_candidate_id"] == "candidate_heal_selector"
    assert proposal["evidence"][0]["artifact_id"] == "artifact_heal_selector"

    list_response = client.get(f"/projects/{project_id}/healing-proposals?automation_key=selector")
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [proposal["id"]]

    get_response = client.get(f"/projects/{project_id}/healing-proposals/{proposal['id']}")
    assert get_response.status_code == 200
    assert get_response.json()["new_value"] == proposal["new_value"]

    with Session(database.engine) as session:
        rows = session.exec(select(HealingProposal)).all()
        assert len(rows) == 1
        assert json.loads(rows[0].evidence_json)[0]["selector_candidate_id"] == "candidate_heal_selector"


def test_repeated_selector_proposal_request_returns_existing_row(
    client,
    project_id: str,
) -> None:
    import worker.core.database as database

    execution_id = "exec_heal_duplicate"
    with Session(database.engine) as session:
        session.add(ExecutionRun(
            id=execution_id,
            project_id=project_id,
            run_id="run_heal_duplicate",
            env="stg",
            browser="chromium",
            status="failed",
        ))
        result_id = _seed_failure(session, project_id, execution_id, "duplicate")

    first = client.post(_execution_url(project_id, execution_id), json={"resultId": result_id})
    second = client.post(_execution_url(project_id, execution_id), json={"resultId": result_id})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["status"] == "created"
    assert second.json()["status"] == "existing"
    assert second.json()["proposal"]["id"] == first.json()["proposal"]["id"]
    with Session(database.engine) as session:
        assert len(session.exec(select(HealingProposal)).all()) == 1


def test_non_selector_or_unresolved_failures_do_not_create_proposals(
    client,
    project_id: str,
) -> None:
    import worker.core.database as database

    execution_id = "exec_heal_not_applicable"
    with Session(database.engine) as session:
        session.add(ExecutionRun(
            id=execution_id,
            project_id=project_id,
            run_id="run_heal_not_applicable",
            env="stg",
            browser="chromium",
            status="failed",
        ))
        raw_refresh_result = _seed_failure(
            session,
            project_id,
            execution_id,
            "raw_refresh",
            error="workflow changed and reached unexpected page",
            error_category="flow_changed",
        )
        unresolved_result = _seed_failure(
            session,
            project_id,
            execution_id,
            "unresolved",
            with_target=False,
        )

    raw_refresh_response = client.post(
        _execution_url(project_id, execution_id),
        json={"executionResultId": raw_refresh_result},
    )
    unresolved_response = client.post(
        _execution_url(project_id, execution_id),
        json={"executionResultId": unresolved_result},
    )

    assert raw_refresh_response.status_code == 200
    assert raw_refresh_response.json()["status"] == "not_applicable"
    assert raw_refresh_response.json()["diagnosis"]["disposition"] == "raw_refresh_required"
    assert raw_refresh_response.json()["proposal"] is None
    assert unresolved_response.status_code == 200
    assert unresolved_response.json()["status"] == "not_applicable"
    assert unresolved_response.json()["diagnosis"]["disposition"] == "unknown"
    assert unresolved_response.json()["proposal"] is None
    with Session(database.engine) as session:
        assert session.exec(select(HealingProposal)).all() == []


def test_accept_proposal_is_idempotent_and_preserves_evidence(
    client,
    project_id: str,
) -> None:
    import worker.core.database as database

    execution_id = "exec_heal_accept"
    with Session(database.engine) as session:
        session.add(ExecutionRun(
            id=execution_id,
            project_id=project_id,
            run_id="run_heal_accept",
            env="stg",
            browser="chromium",
            status="failed",
        ))
        result_id = _seed_failure(session, project_id, execution_id, "accept")

    proposal = _create_selector_proposal(client, project_id, execution_id, result_id)
    proposal_id = proposal["id"]
    evidence = proposal["evidence"]

    first = client.post(f"/projects/{project_id}/healing-proposals/{proposal_id}/accept")
    second = client.post(f"/projects/{project_id}/healing-proposals/{proposal_id}/accept")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["status"] == "accepted"
    assert second.json()["status"] == "accepted"
    assert first.json()["proposal"]["evidence"] == evidence
    assert second.json()["proposal"]["evidence"] == evidence
    with Session(database.engine) as session:
        row = session.get(HealingProposal, proposal_id)
        assert row.status == "accepted"
        assert json.loads(row.evidence_json) == evidence


def test_rejected_proposal_is_idempotent_and_never_applies(
    client,
    project_id: str,
) -> None:
    import worker.core.database as database

    execution_id = "exec_heal_reject"
    with Session(database.engine) as session:
        session.add(ExecutionRun(
            id=execution_id,
            project_id=project_id,
            run_id="run_heal_reject",
            env="stg",
            browser="chromium",
            status="failed",
        ))
        result_id = _seed_failure(session, project_id, execution_id, "reject")

    proposal = _create_selector_proposal(client, project_id, execution_id, result_id)
    proposal_id = proposal["id"]

    first = client.post(f"/projects/{project_id}/healing-proposals/{proposal_id}/reject")
    second = client.post(f"/projects/{project_id}/healing-proposals/{proposal_id}/reject")
    apply_response = client.post(f"/projects/{project_id}/healing-proposals/{proposal_id}/apply")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["status"] == "rejected"
    assert second.json()["status"] == "rejected"
    assert apply_response.status_code == 400
    assert "must be accepted" in apply_response.json()["detail"]
    with Session(database.engine) as session:
        proposal_row = session.get(HealingProposal, proposal_id)
        method = session.get(PageObjectMethod, "pom_heal_reject")
        assert proposal_row.status == "rejected"
        assert method.selector == "page.locator('#old-submit')"


def test_apply_accepted_selector_proposal_updates_pom_and_regenerates_selected_files(
    monkeypatch,
    tmp_path,
    client,
    project_id: str,
) -> None:
    import worker.core.database as database

    _patch_template(monkeypatch, tmp_path)
    execution_id = "exec_heal_apply"
    with Session(database.engine) as session:
        session.add(ExecutionRun(
            id=execution_id,
            project_id=project_id,
            run_id="run_heal_apply",
            env="stg",
            browser="chromium",
            status="failed",
        ))
        result_id = _seed_failure(
            session,
            project_id,
            execution_id,
            "apply",
            generated_page_target=True,
        )
        project = session.get(Project, project_id)
        generated = generate_project(session, project_id, Path(project.root_path), mode="full")
        page_path = generated.output / "pages" / "generated_page.py"
        assert "locator('#old-submit')" in page_path.read_text(encoding="utf-8")

    proposal = _create_selector_proposal(client, project_id, execution_id, result_id)
    proposal_id = proposal["id"]
    accept_response = client.post(f"/projects/{project_id}/healing-proposals/{proposal_id}/accept")
    apply_response = client.post(f"/projects/{project_id}/healing-proposals/{proposal_id}/apply")
    second_apply = client.post(f"/projects/{project_id}/healing-proposals/{proposal_id}/apply")

    assert accept_response.status_code == 200
    assert accept_response.json()["status"] == "accepted"
    assert apply_response.status_code == 200
    body = apply_response.json()
    assert body["status"] == "applied"
    assert body["alreadyApplied"] is False
    assert body["mutation"] == {
        "pageObjectMethodId": "pom_heal_apply",
        "oldSelector": "page.locator('#old-submit')",
        "newSelector": 'page.get_by_test_id("apply-submit")',
        "bodyPlanSelectorIndexes": [0],
    }
    assert body["generation"]["generationMode"] == "incremental"
    assert body["generation"]["selectedCaseIds"] == ["case_heal_apply"]
    assert "pages/generated_page.py" in body["generation"]["affectedFiles"]
    assert body["rerun"]["status"] == "ready"
    assert second_apply.status_code == 200
    assert second_apply.json()["alreadyApplied"] is True

    with Session(database.engine) as session:
        proposal_row = session.get(HealingProposal, proposal_id)
        method = session.get(PageObjectMethod, "pom_heal_apply")
        plan = json.loads(method.body_plan_json)
        project = session.get(Project, project_id)
        page_content = (Path(project.root_path) / "generated" / "pages" / "generated_page.py").read_text(
            encoding="utf-8",
        )
        assert proposal_row.status == "applied"
        assert method.selector == 'page.get_by_test_id("apply-submit")'
        assert plan[0]["selector"] == 'page.get_by_test_id("apply-submit")'
        assert "get_by_test_id('apply-submit')" in page_content


def test_apply_blocks_on_generated_file_conflict_before_persisting_mutation(
    monkeypatch,
    tmp_path,
    client,
    project_id: str,
) -> None:
    import worker.core.database as database

    _patch_template(monkeypatch, tmp_path)
    execution_id = "exec_heal_conflict"
    with Session(database.engine) as session:
        session.add(ExecutionRun(
            id=execution_id,
            project_id=project_id,
            run_id="run_heal_conflict",
            env="stg",
            browser="chromium",
            status="failed",
        ))
        result_id = _seed_failure(
            session,
            project_id,
            execution_id,
            "conflict",
            generated_page_target=True,
        )
        project = session.get(Project, project_id)
        generated = generate_project(session, project_id, Path(project.root_path), mode="full")
        page_path = generated.output / "pages" / "generated_page.py"
        edited_content = page_path.read_text(encoding="utf-8") + "\n# user edit\n"
        page_path.write_text(edited_content, encoding="utf-8")

    proposal = _create_selector_proposal(client, project_id, execution_id, result_id)
    proposal_id = proposal["id"]
    accept_response = client.post(f"/projects/{project_id}/healing-proposals/{proposal_id}/accept")
    apply_response = client.post(f"/projects/{project_id}/healing-proposals/{proposal_id}/apply")

    assert accept_response.status_code == 200
    assert apply_response.status_code == 409
    detail = apply_response.json()["detail"]
    assert "pages/generated_page.py" in detail["conflictFiles"]
    assert page_path.read_text(encoding="utf-8") == edited_content

    with Session(database.engine) as session:
        proposal_row = session.get(HealingProposal, proposal_id)
        method = session.get(PageObjectMethod, "pom_heal_conflict")
        row = session.exec(
            select(GeneratedFile).where(
                GeneratedFile.project_id == project_id,
                GeneratedFile.relative_path == "pages/generated_page.py",
            )
        ).first()
        assert proposal_row.status == "accepted"
        assert method.selector == "page.locator('#old-submit')"
        assert json.loads(method.body_plan_json)[0]["selector"] == "page.locator('#old-submit')"
        assert row.status == GeneratedFileStatus.conflict.value


def test_auto_apply_applies_eligible_selector_proposal_through_existing_apply_path(
    monkeypatch,
    tmp_path,
    client,
    project_id: str,
) -> None:
    import worker.core.database as database

    _patch_template(monkeypatch, tmp_path)
    _enable_auto_apply(client, project_id)
    execution_id = "exec_heal_auto_apply"
    with Session(database.engine) as session:
        session.add(ExecutionRun(
            id=execution_id,
            project_id=project_id,
            run_id="run_heal_auto_apply",
            env="stg",
            browser="chromium",
            status="failed",
        ))
        result_id = _seed_failure(
            session,
            project_id,
            execution_id,
            "auto_apply",
            generated_page_target=True,
        )
        project = session.get(Project, project_id)
        generated = generate_project(session, project_id, Path(project.root_path), mode="full")
        assert "locator('#old-submit')" in (
            generated.output / "pages" / "generated_page.py"
        ).read_text(encoding="utf-8")

    response = client.post(_execution_url(project_id, execution_id), json={"executionResultId": result_id})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "auto_applied"
    assert body["autoApply"]["status"] == "applied"
    assert body["apply"]["status"] == "applied"
    assert body["apply"]["mutation"]["newSelector"] == 'page.get_by_test_id("auto_apply-submit")'
    assert body["proposal"]["status"] == "applied"
    assert any(
        item["type"] == "auto_apply_decision" and item["status"] == "applied"
        for item in body["proposal"]["evidence"]
    )

    with Session(database.engine) as session:
        proposal = session.get(HealingProposal, body["proposal"]["id"])
        method = session.get(PageObjectMethod, "pom_heal_auto_apply")
        project = session.get(Project, project_id)
        page_content = (Path(project.root_path) / "generated" / "pages" / "generated_page.py").read_text(
            encoding="utf-8",
        )
        assert proposal.status == "applied"
        assert method.selector == 'page.get_by_test_id("auto_apply-submit")'
        assert "get_by_test_id('auto_apply-submit')" in page_content


def test_auto_apply_blocks_low_confidence_and_ambiguous_candidates(
    client,
    project_id: str,
) -> None:
    import worker.core.database as database

    _enable_auto_apply(client, project_id)
    execution_id = "exec_heal_auto_candidate_blocks"
    with Session(database.engine) as session:
        session.add(ExecutionRun(
            id=execution_id,
            project_id=project_id,
            run_id="run_heal_auto_candidate_blocks",
            env="stg",
            browser="chromium",
            status="failed",
        ))
        low_result = _seed_failure(
            session,
            project_id,
            execution_id,
            "low_confidence",
            candidate_confidence=0.94,
        )
        ambiguous_result = _seed_failure(
            session,
            project_id,
            execution_id,
            "ambiguous",
            extra_candidates=[{
                "id": "candidate_heal_ambiguous_alt",
                "selector_value": "ambiguous-submit-alt",
                "confidence": 0.96,
            }],
        )

    low_response = client.post(_execution_url(project_id, execution_id), json={"resultId": low_result})
    ambiguous_response = client.post(_execution_url(project_id, execution_id), json={"resultId": ambiguous_result})

    assert low_response.status_code == 200
    assert low_response.json()["status"] == "blocked"
    assert low_response.json()["reason"] == "low_confidence_candidate"
    assert low_response.json()["proposal"]["status"] == "proposed"
    assert ambiguous_response.status_code == 200
    assert ambiguous_response.json()["status"] == "blocked"
    assert ambiguous_response.json()["reason"] == "ambiguous_selector_candidates"
    assert ambiguous_response.json()["proposal"]["status"] == "proposed"

    with Session(database.engine) as session:
        assert session.get(PageObjectMethod, "pom_heal_low_confidence").selector == "page.locator('#old-submit')"
        assert session.get(PageObjectMethod, "pom_heal_ambiguous").selector == "page.locator('#old-submit')"


def test_auto_apply_blocks_stale_proposal_target_without_mutation(
    client,
    project_id: str,
) -> None:
    import worker.core.database as database

    execution_id = "exec_heal_auto_stale"
    with Session(database.engine) as session:
        session.add(ExecutionRun(
            id=execution_id,
            project_id=project_id,
            run_id="run_heal_auto_stale",
            env="stg",
            browser="chromium",
            status="failed",
        ))
        result_id = _seed_failure(session, project_id, execution_id, "stale_target")

    created = client.post(_execution_url(project_id, execution_id), json={"executionResultId": result_id})
    assert created.status_code == 200
    assert created.json()["status"] == "created"

    _enable_auto_apply(client, project_id)
    with Session(database.engine) as session:
        method = session.get(PageObjectMethod, "pom_heal_stale_target")
        method.selector = "page.locator('#manual-change')"
        session.add(method)
        session.commit()

    stale_response = client.post(_execution_url(project_id, execution_id), json={"executionResultId": result_id})

    assert stale_response.status_code == 200
    assert stale_response.json()["status"] == "blocked"
    assert stale_response.json()["reason"] == "proposal_target_stale"
    assert stale_response.json()["proposal"]["status"] == "proposed"
    with Session(database.engine) as session:
        method = session.get(PageObjectMethod, "pom_heal_stale_target")
        proposal = session.get(HealingProposal, stale_response.json()["proposal"]["id"])
        assert method.selector == "page.locator('#manual-change')"
        assert proposal.status == "proposed"


def test_auto_apply_blocks_generation_conflicts_without_selector_mutation(
    monkeypatch,
    tmp_path,
    client,
    project_id: str,
) -> None:
    import worker.core.database as database

    _patch_template(monkeypatch, tmp_path)
    _enable_auto_apply(client, project_id)
    execution_id = "exec_heal_auto_conflict"
    with Session(database.engine) as session:
        session.add(ExecutionRun(
            id=execution_id,
            project_id=project_id,
            run_id="run_heal_auto_conflict",
            env="stg",
            browser="chromium",
            status="failed",
        ))
        result_id = _seed_failure(
            session,
            project_id,
            execution_id,
            "auto_conflict",
            generated_page_target=True,
        )
        project = session.get(Project, project_id)
        generated = generate_project(session, project_id, Path(project.root_path), mode="full")
        page_path = generated.output / "pages" / "generated_page.py"
        edited_content = page_path.read_text(encoding="utf-8") + "\n# user edit\n"
        page_path.write_text(edited_content, encoding="utf-8")

    response = client.post(_execution_url(project_id, execution_id), json={"executionResultId": result_id})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "blocked"
    assert body["reason"] == "generated_file_conflict"
    assert "pages/generated_page.py" in body["autoApply"]["conflictFiles"]
    assert body["proposal"]["status"] == "proposed"
    assert page_path.read_text(encoding="utf-8") == edited_content

    with Session(database.engine) as session:
        proposal = session.get(HealingProposal, body["proposal"]["id"])
        method = session.get(PageObjectMethod, "pom_heal_auto_conflict")
        row = session.exec(
            select(GeneratedFile).where(
                GeneratedFile.project_id == project_id,
                GeneratedFile.relative_path == "pages/generated_page.py",
            )
        ).first()
        assert proposal.status == "proposed"
        assert method.selector == "page.locator('#old-submit')"
        assert json.loads(method.body_plan_json)[0]["selector"] == "page.locator('#old-submit')"
        assert row.status == GeneratedFileStatus.conflict.value
