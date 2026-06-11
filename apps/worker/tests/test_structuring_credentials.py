from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from sqlmodel import Session, select

from worker.models.db import (
    CaseActionMapping,
    CaseActionMappingAction,
    PageObjectMethod,
    Project,
    RawAction,
    StructuredFlow,
    StructuredStep,
    TestCase as DbTestCase,
    WebwrightRun,
)
from worker.services.project_generator import generate_project
from worker.services.structuring_service import sync_structured_entities


def _seed_credential_case(
    session: Session,
    *,
    project_id: str,
    case_id: str,
    automation_key: str,
    action_id: str,
    selector: str,
    value: str,
    target: str | None = None,
    method_name: str = "submit_credentials",
) -> DbTestCase:
    case = DbTestCase(
        id=case_id,
        project_id=project_id,
        source_type="manual",
        source_case_id=case_id,
        title=f"{automation_key} case",
        steps_json=json.dumps([{"index": 1, "action": method_name}]),
        automation_key=automation_key,
        status="mapped",
    )
    run = WebwrightRun(
        id=f"ww_{case_id}",
        project_id=project_id,
        test_case_id=case_id,
        automation_key=automation_key,
        status="completed",
    )
    mapping = CaseActionMapping(
        id=f"map_{case_id}",
        test_case_id=case_id,
        raw_action_id=action_id,
        tc_step_index=1,
        normalized_step_id=f"flow_{case_id}",
        normalized_step_name=method_name,
        pom_method_name=method_name,
        status="mapped",
    )
    session.add(case)
    session.add(run)
    session.add(RawAction(
        id=action_id,
        webwright_run_id=run.id,
        automation_key=automation_key,
        order_index=1,
        type="fill",
        selector=selector,
        value=value,
        target=target or value,
    ))
    session.add(mapping)
    session.add(CaseActionMappingAction(
        mapping_id=mapping.id,
        raw_action_id=action_id,
        order_index=0,
    ))
    session.commit()
    return case


def _sync_and_plan(session: Session, project_id: str, case: DbTestCase) -> tuple[PageObjectMethod, list[dict]]:
    run = session.exec(select(WebwrightRun).where(WebwrightRun.test_case_id == case.id)).one()
    sync_structured_entities(session, project_id, case, run)
    session.commit()
    pom = session.exec(
        select(PageObjectMethod).where(PageObjectMethod.source_mapping_id == f"map_{case.id}")
    ).one()
    return pom, json.loads(pom.body_plan_json)


def test_password_field_fill_value_becomes_reviewed_env_placeholder(
    project_id: str,
) -> None:
    import worker.core.database as database

    literal = "tiny"
    with Session(database.engine) as session:
        case = _seed_credential_case(
            session,
            project_id=project_id,
            case_id="tc_password_placeholder",
            automation_key="password_placeholder",
            action_id="act_password_placeholder",
            selector="page.get_by_label('Password')",
            value=literal,
        )

        pom, plan = _sync_and_plan(session, project_id, case)
        flow = session.exec(select(StructuredFlow).where(StructuredFlow.test_case_id == case.id)).one()
        step = session.exec(
            select(StructuredStep).where(StructuredStep.structured_flow_id == flow.id)
        ).one()

        assert plan[0]["value"] == "${env.credentials.password}"
        assert plan[0]["target"] == "${env.credentials.password}"
        assert plan[0]["requiresReview"] is True
        assert plan[0]["reviewReason"] == "credential_value_placeholder"
        assert plan[0]["credentialPlaceholder"] == {
            "placeholder": "${env.credentials.password}",
            "source": "credential_field",
        }
        assert literal not in pom.body_plan_json
        assert pom.value_template == "${env.credentials.password}"
        assert pom.status == "draft"
        assert flow.status == "needs_review"
        assert json.loads(step.metadata_json)["requires_review"] is True


def test_fill_value_matching_secret_env_uses_env_secret_placeholder(
    monkeypatch,
    project_id: str,
) -> None:
    import worker.core.database as database

    literal = "value-visible-only-via-env-123456789"
    monkeypatch.setenv("PAYMENT_API_TOKEN", literal)
    with Session(database.engine) as session:
        case = _seed_credential_case(
            session,
            project_id=project_id,
            case_id="tc_env_secret_placeholder",
            automation_key="env_secret_placeholder",
            action_id="act_env_secret_placeholder",
            selector="page.get_by_label('Invite code')",
            value=literal,
            target=f"token={literal}",
        )

        pom, plan = _sync_and_plan(session, project_id, case)

        assert plan[0]["value"] == "${env.secrets.payment_api_token}"
        assert plan[0]["target"] == "token=${env.secrets.payment_api_token}"
        assert plan[0]["credentialPlaceholder"]["source"] == "secret_env_value"
        assert literal not in pom.body_plan_json
        assert pom.value_template == "${env.secrets.payment_api_token}"


def test_secret_looking_fill_value_is_placeholdered_without_literal_leak(
    project_id: str,
) -> None:
    import worker.core.database as database

    literal = "sk-test-1234567890abcdef"
    with Session(database.engine) as session:
        case = _seed_credential_case(
            session,
            project_id=project_id,
            case_id="tc_secret_literal_placeholder",
            automation_key="secret_literal_placeholder",
            action_id="act_secret_literal_placeholder",
            selector="page.get_by_label('Invitation code')",
            value=literal,
        )

        pom, plan = _sync_and_plan(session, project_id, case)

        assert plan[0]["value"] == "${env.credentials.secret}"
        assert plan[0]["credentialPlaceholder"]["source"] == "secret_literal"
        assert plan[0]["requiresReview"] is True
        assert literal not in pom.body_plan_json


def test_credential_literal_does_not_reach_generated_source(
    monkeypatch,
    tmp_path: Path,
    project_id: str,
) -> None:
    import worker.core.database as database
    import worker.services.project_generator as project_generator

    literal = "P@ssw0rd-value-123456"
    template = tmp_path / "credential-template"
    (template / "runner").mkdir(parents=True)
    (template / "runner" / "cli.py").write_text("# runtime\n", encoding="utf-8")
    (template / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    monkeypatch.setattr(project_generator, "load_settings", lambda: None)
    monkeypatch.setattr(
        project_generator,
        "resolve_runtime",
        lambda _settings: SimpleNamespace(template_path=str(template)),
    )

    with Session(database.engine) as session:
        project = session.get(Project, project_id)
        case = _seed_credential_case(
            session,
            project_id=project_id,
            case_id="tc_generated_secret_absent",
            automation_key="generated_secret_absent",
            action_id="act_generated_secret_absent",
            selector="page.get_by_placeholder('Password')",
            value=literal,
        )

        generated = generate_project(session, project_id, Path(project.root_path), mode="full")
        page_source = (generated.output / "pages" / "generated_page.py").read_text(encoding="utf-8")

        assert literal not in page_source
        assert literal not in (generated.output / "flows" / "generated_secret_absent_flow.py").read_text(
            encoding="utf-8"
        )
        assert literal not in (generated.output / "tests" / "test_generated_secret_absent.py").read_text(
            encoding="utf-8"
        )
        assert "review required (credential_value_placeholder)" in page_source
