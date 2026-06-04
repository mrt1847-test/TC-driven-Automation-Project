from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, select

from worker.models.db import (
    ArtifactAsset,
    CaseActionMapping,
    CaseActionMappingAction,
    ExecutionResult,
    ExecutionRun,
    GeneratedFile,
    GeneratedFileOrigin,
    PageObject,
    PageObjectMethod,
    RawAction,
    StructuredFlow,
    StructuredStep,
    WebwrightRun,
)
from worker.services.failure_target_resolver import resolve_failure_target


def _add_failed_result(
    session: Session,
    project_id: str,
    prefix: str,
    automation_key: str,
    error: str,
) -> ExecutionResult:
    execution_run = ExecutionRun(
        id=f"exec_{prefix}",
        project_id=project_id,
        run_id=f"runner_{prefix}",
        env="stg",
        browser="chromium",
        status="failed",
    )
    execution_result = ExecutionResult(
        id=f"result_{prefix}",
        execution_run_id=execution_run.id,
        automation_key=automation_key,
        source_type="excel",
        source_case_id=f"TC-{prefix}",
        status="failed",
        error=error,
    )
    session.add(execution_run)
    session.add(execution_result)
    return execution_result


def test_resolver_links_failed_result_to_unique_structured_target_and_evidence(
    project_id: str,
) -> None:
    import worker.core.database as database

    automation_key = "resolver_unique"
    with Session(database.engine) as session:
        result = _add_failed_result(
            session,
            project_id,
            "resolver_unique",
            automation_key,
            "submit_login failed: selector not found",
        )
        webwright_run = WebwrightRun(
            id="ww_resolver_unique",
            project_id=project_id,
            test_case_id="case_resolver_unique",
            automation_key=automation_key,
            status="completed",
        )
        raw_action = RawAction(
            id="raw_resolver_unique",
            webwright_run_id=webwright_run.id,
            automation_key=automation_key,
            order_index=1,
            type="click",
        )
        mapping = CaseActionMapping(
            id="mapping_resolver_unique",
            test_case_id="case_resolver_unique",
            raw_action_id=raw_action.id,
            tc_step_index=1,
        )
        mapping_action = CaseActionMappingAction(
            mapping_id=mapping.id,
            raw_action_id=raw_action.id,
            order_index=1,
        )
        other_raw_action = RawAction(
            id="raw_resolver_other",
            webwright_run_id=webwright_run.id,
            automation_key=automation_key,
            order_index=2,
            type="click",
        )
        other_mapping = CaseActionMapping(
            id="mapping_resolver_other",
            test_case_id="case_resolver_unique",
            raw_action_id=other_raw_action.id,
            tc_step_index=2,
        )
        foreign_webwright_run = WebwrightRun(
            id="ww_resolver_foreign",
            project_id="other_project",
            test_case_id="case_resolver_foreign",
            automation_key=automation_key,
            status="completed",
        )
        foreign_raw_action = RawAction(
            id="raw_resolver_foreign",
            webwright_run_id=foreign_webwright_run.id,
            automation_key=automation_key,
            order_index=1,
            type="click",
        )
        flow = StructuredFlow(
            id="flow_resolver_unique",
            project_id=project_id,
            test_case_id="case_resolver_unique",
            automation_key=automation_key,
            name="login_flow",
        )
        old_flow = StructuredFlow(
            id="flow_resolver_old",
            project_id=project_id,
            test_case_id="case_resolver_old",
            automation_key=automation_key,
            name="old_login_flow",
        )
        page_object = PageObject(
            id="page_resolver_unique",
            project_id=project_id,
            name="ResolverLoginPage",
            file_path="pages/resolver_login.py",
        )
        method = PageObjectMethod(
            id="pom_resolver_unique",
            page_object_id=page_object.id,
            name="submit_login",
            method_type="click",
            source_mapping_id=mapping.id,
        )
        other_method = PageObjectMethod(
            id="pom_resolver_other",
            page_object_id=page_object.id,
            name="cancel_login",
            method_type="click",
            source_mapping_id=other_mapping.id,
        )
        step = StructuredStep(
            id="step_resolver_unique",
            structured_flow_id=flow.id,
            mapping_id=mapping.id,
            order_index=1,
            name="submit login",
            page_object_method_id=method.id,
        )
        other_step = StructuredStep(
            id="step_resolver_other",
            structured_flow_id=flow.id,
            mapping_id=other_mapping.id,
            order_index=2,
            name="cancel login",
            page_object_method_id=other_method.id,
        )
        old_file = GeneratedFile(
            id="generated_resolver_old",
            project_id=project_id,
            relative_path="tests/test_resolver_unique.py",
            automation_key=automation_key,
            source_type="structured_flow",
            source_id=old_flow.id,
            created_at=datetime(2026, 1, 1),
            updated_at=datetime(2026, 1, 1),
        )
        generated_file = GeneratedFile(
            id="generated_resolver_unique",
            project_id=project_id,
            relative_path="tests/test_resolver_unique.py",
            automation_key=automation_key,
            source_type="structured_flow",
            source_id=flow.id,
            created_at=datetime(2026, 1, 2),
            updated_at=datetime(2026, 1, 2),
        )
        origin = GeneratedFileOrigin(
            generated_file_id=generated_file.id,
            origin_type="page_object_method",
            origin_id=method.id,
        )
        foreign_origin = GeneratedFileOrigin(
            generated_file_id=generated_file.id,
            origin_type="raw_action",
            origin_id=foreign_raw_action.id,
        )
        artifacts = [
            ArtifactAsset(
                id="artifact_resolver_result",
                project_id=project_id,
                automation_key=automation_key,
                source_type="execution_result",
                source_id=result.id,
                artifact_type="trace",
                file_path="artifacts/resolver-trace.zip",
            ),
            ArtifactAsset(
                id="artifact_resolver_generated",
                project_id=project_id,
                automation_key=automation_key,
                source_type="generated_file",
                source_id=generated_file.id,
                artifact_type="metadata",
                file_path="artifacts/resolver-generated.json",
            ),
            ArtifactAsset(
                id="artifact_resolver_raw",
                project_id=project_id,
                automation_key=automation_key,
                source_type="raw_action",
                source_id=raw_action.id,
                artifact_type="screenshot",
                file_path="artifacts/resolver-action.png",
            ),
        ]
        session.add_all(
            [
                webwright_run,
                raw_action,
                other_raw_action,
                foreign_webwright_run,
                foreign_raw_action,
                mapping,
                other_mapping,
                mapping_action,
                flow,
                old_flow,
                page_object,
                method,
                other_method,
                step,
                other_step,
                old_file,
                generated_file,
                origin,
                foreign_origin,
                *artifacts,
            ]
        )
        session.commit()

        resolution = resolve_failure_target(session, result.id)

    assert resolution.status == "resolved"
    assert resolution.reason == "unique_structured_target"
    assert resolution.execution_result_id == result.id
    assert resolution.source_case_id == "TC-resolver_unique"
    assert resolution.test_case_ids == [flow.test_case_id]
    assert resolution.structured_step_id == step.id
    assert resolution.page_object_method_id == method.id
    assert resolution.structured_step_ids == sorted([step.id, other_step.id])
    assert resolution.page_object_method_ids == sorted([method.id, other_method.id])
    assert resolution.generated_file_ids == [generated_file.id]
    assert resolution.structured_flow_ids == [flow.id]
    assert resolution.mapping_ids == [mapping.id]
    assert resolution.raw_action_ids == [raw_action.id]
    assert resolution.webwright_run_ids == [webwright_run.id]
    assert resolution.artifact_ids == sorted(artifact.id for artifact in artifacts)


def test_resolver_returns_missing_without_mutating_when_generation_link_is_absent(
    project_id: str,
) -> None:
    import worker.core.database as database

    with Session(database.engine) as session:
        result = _add_failed_result(
            session,
            project_id,
            "resolver_missing",
            "resolver_missing",
            "selector not found",
        )
        artifact = ArtifactAsset(
            id="artifact_resolver_missing",
            project_id=project_id,
            automation_key="resolver_missing",
            source_type="execution_result",
            source_id=result.id,
            artifact_type="trace",
            file_path="artifacts/resolver-missing-trace.zip",
        )
        session.add(artifact)
        session.commit()

        resolution = resolve_failure_target(session, result.id)
        saved_result = session.get(ExecutionResult, result.id)
        generated_files = session.exec(select(GeneratedFile)).all()

    assert resolution.status == "missing"
    assert resolution.reason == "generated_files_missing"
    assert resolution.structured_step_id is None
    assert resolution.page_object_method_id is None
    assert resolution.artifact_ids == [artifact.id]
    assert saved_result is not None
    assert saved_result.error == "selector not found"
    assert generated_files == []


def test_resolver_returns_ambiguous_without_guessing_between_structured_targets(
    project_id: str,
) -> None:
    import worker.core.database as database

    automation_key = "resolver_ambiguous"
    with Session(database.engine) as session:
        result = _add_failed_result(
            session,
            project_id,
            "resolver_ambiguous",
            automation_key,
            "interaction failed",
        )
        flow = StructuredFlow(
            id="flow_resolver_ambiguous",
            project_id=project_id,
            test_case_id="case_resolver_ambiguous",
            automation_key=automation_key,
            name="ambiguous_flow",
        )
        page_object = PageObject(
            id="page_resolver_ambiguous",
            project_id=project_id,
            name="ResolverAmbiguousPage",
            file_path="pages/resolver_ambiguous.py",
        )
        methods = [
            PageObjectMethod(
                id="pom_resolver_first",
                page_object_id=page_object.id,
                name="click_first",
                method_type="click",
            ),
            PageObjectMethod(
                id="pom_resolver_second",
                page_object_id=page_object.id,
                name="click_second",
                method_type="click",
            ),
        ]
        steps = [
            StructuredStep(
                id="step_resolver_first",
                structured_flow_id=flow.id,
                order_index=1,
                name="click first",
                page_object_method_id=methods[0].id,
            ),
            StructuredStep(
                id="step_resolver_second",
                structured_flow_id=flow.id,
                order_index=2,
                name="click second",
                page_object_method_id=methods[1].id,
            ),
        ]
        generated_file = GeneratedFile(
            id="generated_resolver_ambiguous",
            project_id=project_id,
            relative_path="tests/test_resolver_ambiguous.py",
            automation_key=automation_key,
            source_type="structured_flow",
            source_id=flow.id,
        )
        session.add_all([flow, page_object, *methods, *steps, generated_file])
        session.commit()

        resolution = resolve_failure_target(session, result.id)

    assert resolution.status == "ambiguous"
    assert resolution.reason == "multiple_structured_targets"
    assert resolution.structured_step_id is None
    assert resolution.page_object_method_id is None
    assert resolution.structured_step_ids == sorted(step.id for step in steps)
    assert resolution.page_object_method_ids == sorted(method.id for method in methods)
