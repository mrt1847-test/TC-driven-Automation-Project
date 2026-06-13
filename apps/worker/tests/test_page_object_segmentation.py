from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import yaml
from sqlmodel import Session, select

from worker.models.db import (
    CaseActionMapping,
    CaseActionMappingAction,
    GeneratedFile,
    GeneratedFileOrigin,
    PageObject,
    PageObjectMethod,
    RawAction,
    StructuredFlow,
    StructuredStep,
    TestCase as DbTestCase,
    WebwrightRun,
)
from worker.services.project_generator import generate_project, retire_generated_case


def _patch_generator(monkeypatch, tmp_path: Path) -> None:
    import worker.services.project_generator as project_generator

    template = tmp_path / "segmented-template"
    (template / "runner").mkdir(parents=True)
    (template / "runner" / "cli.py").write_text("# runtime\n", encoding="utf-8")
    (template / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    monkeypatch.setattr(project_generator, "load_settings", lambda: None)
    monkeypatch.setattr(
        project_generator,
        "resolve_runtime",
        lambda _settings: SimpleNamespace(template_path=str(template)),
    )


def _seed_route_case(
    session: Session,
    tmp_path: Path,
    *,
    project_id: str,
    case_id: str,
    automation_key: str,
    route_url: str,
    selector: str,
    step_name: str,
) -> DbTestCase:
    case = DbTestCase(
        id=case_id,
        project_id=project_id,
        source_type="manual",
        source_case_id=case_id,
        title=f"{automation_key} case",
        steps_json=json.dumps([{"index": 1, "action": step_name}]),
        automation_key=automation_key,
        status="mapped",
    )
    trajectory = tmp_path / f"{automation_key}_trajectory.json"
    trajectory.write_text(
        json.dumps({"actions": [{"orderIndex": 1, "url": route_url, "pageTitle": step_name}]}),
        encoding="utf-8",
    )
    run = WebwrightRun(
        id=f"ww_segmented_{automation_key}",
        project_id=project_id,
        test_case_id=case_id,
        automation_key=automation_key,
        status="completed",
        trajectory_path=str(trajectory),
    )
    action = RawAction(
        id=f"act_segmented_{automation_key}",
        webwright_run_id=run.id,
        automation_key=automation_key,
        order_index=1,
        type="click",
        selector=selector,
        target=step_name,
    )
    mapping = CaseActionMapping(
        id=f"map_segmented_{automation_key}",
        test_case_id=case_id,
        raw_action_id=action.id,
        tc_step_index=1,
        normalized_step_name=step_name,
        status="mapped",
    )
    session.add(case)
    session.add(run)
    session.add(action)
    session.add(mapping)
    session.add(CaseActionMappingAction(
        mapping_id=mapping.id,
        raw_action_id=action.id,
        order_index=0,
    ))
    return case


def _generated_by_path(session: Session, project_id: str) -> dict[str, GeneratedFile]:
    return {
        row.relative_path: row
        for row in session.exec(select(GeneratedFile).where(GeneratedFile.project_id == project_id)).all()
    }


def _origins(session: Session, generated_file_id: str) -> set[tuple[str, str]]:
    return {
        (row.origin_type, row.origin_id)
        for row in session.exec(
            select(GeneratedFileOrigin).where(GeneratedFileOrigin.generated_file_id == generated_file_id)
        ).all()
    }


def _method_for_case(session: Session, case_id: str) -> PageObjectMethod:
    flow = session.exec(select(StructuredFlow).where(StructuredFlow.test_case_id == case_id)).one()
    step = session.exec(select(StructuredStep).where(StructuredStep.structured_flow_id == flow.id)).one()
    return session.get(PageObjectMethod, step.page_object_method_id)


def test_route_trajectory_generates_segmented_page_objects_and_selected_regeneration(
    monkeypatch,
    tmp_path: Path,
    project_id: str,
) -> None:
    import worker.core.database as database

    _patch_generator(monkeypatch, tmp_path)
    project_root = tmp_path / "segmented-project"
    with Session(database.engine) as session:
        login = _seed_route_case(
            session,
            tmp_path,
            project_id=project_id,
            case_id="tc_segmented_login",
            automation_key="segmented_login",
            route_url="https://app.example/login",
            selector="page.locator('#login-submit')",
            step_name="submit login",
        )
        checkout = _seed_route_case(
            session,
            tmp_path,
            project_id=project_id,
            case_id="tc_segmented_checkout",
            automation_key="segmented_checkout",
            route_url="https://app.example/checkout/payment",
            selector="page.locator('#pay-now')",
            step_name="pay now",
        )
        session.commit()

        generated = generate_project(session, project_id, project_root, mode="full")
        login_page = generated.output / "pages" / "login_page.py"
        checkout_page = generated.output / "pages" / "checkout_payment_page.py"
        assert login_page.exists()
        assert checkout_page.exists()
        assert not (generated.output / "pages" / "generated_page.py").exists()
        assert "class LoginPage:" in login_page.read_text(encoding="utf-8")
        assert "class CheckoutPaymentPage:" in checkout_page.read_text(encoding="utf-8")

        login_flow = (generated.output / "flows" / "segmented_login_flow.py").read_text(encoding="utf-8")
        assert "from pages.login_page import LoginPage" in login_flow
        assert "self.login_page.segmented_login__step_1_submit_login()" in login_flow
        checkout_flow = (generated.output / "flows" / "segmented_checkout_flow.py").read_text(encoding="utf-8")
        assert "from pages.checkout_payment_page import CheckoutPaymentPage" in checkout_flow
        assert "self.checkout_payment_page.segmented_checkout__step_1_pay_now()" in checkout_flow

        mapping_entries = yaml.safe_load(
            (generated.output / "mappings" / "cases.yaml").read_text(encoding="utf-8")
        )["cases"]
        by_key = {entry["automationKey"]: entry for entry in mapping_entries}
        assert by_key["segmented_login"]["pageObjects"] == ["pages/login_page.py"]
        assert by_key["segmented_checkout"]["pageObjects"] == ["pages/checkout_payment_page.py"]

        by_path = _generated_by_path(session, project_id)
        login_origins = _origins(session, by_path["pages/login_page.py"].id)
        checkout_origins = _origins(session, by_path["pages/checkout_payment_page.py"].id)
        assert ("test_case", login.id) in login_origins
        assert ("test_case", checkout.id) not in login_origins
        assert ("test_case", checkout.id) in checkout_origins
        assert ("test_case", login.id) not in checkout_origins
        assert session.exec(select(PageObject).where(PageObject.name == "LoginPage")).one().file_path == "pages/login_page.py"

        checkout_snapshot = checkout_page.read_bytes()
        method = _method_for_case(session, login.id)
        plan = json.loads(method.body_plan_json)
        plan[0]["selector"] = "page.locator('#login-submit-v2')"
        method.selector = "page.locator('#login-submit-v2')"
        method.body_plan_json = json.dumps(plan, sort_keys=True, separators=(",", ":"))
        session.add(method)
        session.commit()

        selected = generate_project(session, project_id, project_root, [login.id])
        assert "pages/login_page.py" in selected.changed_files
        assert "pages/checkout_payment_page.py" not in selected.affected_files
        assert "page.locator('#login-submit-v2').click()" in login_page.read_text(encoding="utf-8")
        assert checkout_page.read_bytes() == checkout_snapshot


def test_retire_cleanup_rewrites_shared_segmented_page_file(
    monkeypatch,
    tmp_path: Path,
    project_id: str,
) -> None:
    import worker.core.database as database

    _patch_generator(monkeypatch, tmp_path)
    project_root = tmp_path / "segmented-retire-project"
    with Session(database.engine) as session:
        selected = _seed_route_case(
            session,
            tmp_path,
            project_id=project_id,
            case_id="tc_segmented_retire_selected",
            automation_key="segmented_retire_selected",
            route_url="https://app.example/login",
            selector="page.locator('#selected-login')",
            step_name="selected login",
        )
        unrelated = _seed_route_case(
            session,
            tmp_path,
            project_id=project_id,
            case_id="tc_segmented_retire_unrelated",
            automation_key="segmented_retire_unrelated",
            route_url="https://app.example/login",
            selector="page.locator('#unrelated-login')",
            step_name="unrelated login",
        )
        session.commit()

        generated = generate_project(session, project_id, project_root, mode="full")
        page_path = generated.output / "pages" / "login_page.py"
        page_source = page_path.read_text(encoding="utf-8")
        assert "segmented_retire_selected__step_1_selected_login" in page_source
        assert "segmented_retire_unrelated__step_1_unrelated_login" in page_source

        result = retire_generated_case(
            session,
            project_id,
            generated.output,
            selected.id,
            action="retire",
        )

        page_source = page_path.read_text(encoding="utf-8")
        by_path = _generated_by_path(session, project_id)
        page_origins = _origins(session, by_path["pages/login_page.py"].id)
        assert result["status"] == "completed"
        assert result["updatedFiles"] == ["mappings/cases.yaml", "pages/login_page.py"]
        assert "segmented_retire_selected__step_1_selected_login" not in page_source
        assert "segmented_retire_unrelated__step_1_unrelated_login" in page_source
        assert ("test_case", selected.id) not in page_origins
        assert ("test_case", unrelated.id) in page_origins
