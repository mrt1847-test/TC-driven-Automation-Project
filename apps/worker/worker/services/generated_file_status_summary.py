from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from worker.models.db import (
    CaseActionMapping,
    GeneratedFile,
    GeneratedFileOrigin,
    GeneratedFileStatus,
    PageObject,
    PageObjectMethod,
    Project,
    RawAction,
    StructuredFlow,
    StructuredStep,
    TestCase,
    WebwrightRun,
)
from worker.services.generated_file_status import (
    hash_file,
    latest_generated_files_by_path,
    refresh_generated_file_statuses,
)


STATUS_ORDER = {
    GeneratedFileStatus.conflict.value: 0,
    GeneratedFileStatus.edited.value: 1,
    GeneratedFileStatus.stale.value: 2,
    GeneratedFileStatus.obsolete.value: 3,
    GeneratedFileStatus.generated.value: 4,
}
SUMMARY_STATUSES = [
    GeneratedFileStatus.generated.value,
    GeneratedFileStatus.edited.value,
    GeneratedFileStatus.stale.value,
    GeneratedFileStatus.conflict.value,
    GeneratedFileStatus.obsolete.value,
]


def _iso(value: object) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def _guidance(status: str) -> dict[str, Any]:
    if status == GeneratedFileStatus.edited.value:
        return {
            "severity": "warning",
            "blocksGeneration": True,
            "action": "review_local_edit",
            "message": "Review the local edit before regeneration overwrites this tracked file.",
        }
    if status == GeneratedFileStatus.stale.value:
        return {
            "severity": "warning",
            "blocksGeneration": False,
            "action": "regenerate",
            "message": "Source data changed; regeneration can refresh this file if it has no local edit.",
        }
    if status == GeneratedFileStatus.conflict.value:
        return {
            "severity": "error",
            "blocksGeneration": True,
            "action": "resolve_conflict",
            "message": "Source data and the file both changed; resolve the conflict before regeneration.",
        }
    if status == GeneratedFileStatus.obsolete.value:
        return {
            "severity": "info",
            "blocksGeneration": False,
            "action": "audit_only",
            "message": "This tracked file has been retired or deleted and is kept for audit history.",
        }
    return {
        "severity": "ok",
        "blocksGeneration": False,
        "action": "none",
        "message": "Tracked file matches the stored generated hash.",
    }


def _case_payload(case: TestCase) -> dict[str, Any]:
    return {
        "type": "test_case",
        "id": case.id,
        "automationKey": case.automation_key,
        "title": case.title,
        "sourceType": case.source_type,
        "sourceCaseId": case.source_case_id,
        "status": case.status,
    }


def _origin_payload(session: Session, project_id: str, origin_type: str | None, origin_id: str | None) -> dict[str, Any] | None:
    if not origin_type or not origin_id:
        return None

    base: dict[str, Any] = {"type": origin_type, "id": origin_id}
    if origin_type == "test_case":
        case = session.get(TestCase, origin_id)
        if case and case.project_id == project_id:
            return _case_payload(case)
        return base

    if origin_type == "structured_flow":
        flow = session.get(StructuredFlow, origin_id)
        if flow and flow.project_id == project_id:
            base.update({
                "automationKey": flow.automation_key,
                "testCaseId": flow.test_case_id,
                "name": flow.name,
                "status": flow.status,
                "version": flow.version,
            })
        return base

    if origin_type == "structured_step":
        step = session.get(StructuredStep, origin_id)
        flow = session.get(StructuredFlow, step.structured_flow_id) if step else None
        if step and flow and flow.project_id == project_id:
            base.update({
                "automationKey": flow.automation_key,
                "testCaseId": flow.test_case_id,
                "structuredFlowId": flow.id,
                "mappingId": step.mapping_id,
                "name": step.name,
                "kind": step.kind,
                "orderIndex": step.order_index,
            })
        return base

    if origin_type == "page_object_method":
        method = session.get(PageObjectMethod, origin_id)
        page_object = session.get(PageObject, method.page_object_id) if method else None
        if method and page_object and page_object.project_id == project_id:
            base.update({
                "pageObjectId": page_object.id,
                "pageObjectName": page_object.name,
                "pageObjectFilePath": page_object.file_path,
                "name": method.name,
                "methodType": method.method_type,
                "sourceMappingId": method.source_mapping_id,
                "status": method.status,
            })
        return base

    if origin_type in {"mapping", "case_action_mapping"}:
        mapping = session.get(CaseActionMapping, origin_id)
        case = session.get(TestCase, mapping.test_case_id) if mapping else None
        if mapping and case and case.project_id == project_id:
            base.update({
                "testCaseId": case.id,
                "automationKey": case.automation_key,
                "tcStepIndex": mapping.tc_step_index,
                "normalizedStepName": mapping.normalized_step_name,
                "pomMethodName": mapping.pom_method_name,
                "status": mapping.status,
            })
        return base

    if origin_type == "raw_action":
        action = session.get(RawAction, origin_id)
        run = session.get(WebwrightRun, action.webwright_run_id) if action else None
        if action and run and run.project_id == project_id:
            base.update({
                "automationKey": action.automation_key,
                "webwrightRunId": run.id,
                "testCaseId": run.test_case_id,
                "orderIndex": action.order_index,
                "actionType": action.type,
                "target": action.target,
                "selector": action.selector,
            })
        return base

    if origin_type == "webwright_run":
        run = session.get(WebwrightRun, origin_id)
        if run and run.project_id == project_id:
            base.update({
                "automationKey": run.automation_key,
                "testCaseId": run.test_case_id,
                "status": run.status,
            })
        return base

    return base


def _origins_by_file_id(session: Session, generated_file_ids: list[str]) -> dict[str, list[GeneratedFileOrigin]]:
    if not generated_file_ids:
        return {}
    origins = session.exec(
        select(GeneratedFileOrigin)
        .where(GeneratedFileOrigin.generated_file_id.in_(generated_file_ids))
        .order_by(
            GeneratedFileOrigin.generated_file_id,
            GeneratedFileOrigin.origin_type,
            GeneratedFileOrigin.origin_id,
        )
    ).all()
    grouped: dict[str, list[GeneratedFileOrigin]] = {}
    for origin in origins:
        grouped.setdefault(origin.generated_file_id, []).append(origin)
    return grouped


def _file_payload(
    session: Session,
    project_id: str,
    output: Path,
    row: GeneratedFile,
    assessment: dict[str, Any] | None,
    origins: list[GeneratedFileOrigin],
) -> dict[str, Any]:
    target = output / row.relative_path
    current_hash = assessment.get("currentHash") if assessment else hash_file(target)
    source = _origin_payload(session, project_id, row.source_type, row.source_id)
    return {
        "id": row.id,
        "path": row.relative_path,
        "relativePath": row.relative_path,
        "status": row.status,
        "automationKey": row.automation_key,
        "sourceType": row.source_type,
        "sourceId": row.source_id,
        "source": source,
        "origins": [
            _origin_payload(session, project_id, origin.origin_type, origin.origin_id)
            or {"type": origin.origin_type, "id": origin.origin_id}
            for origin in origins
        ],
        "contentHash": row.content_hash,
        "storedHash": row.content_hash,
        "currentHash": current_hash,
        "plannedHash": assessment.get("plannedHash") if assessment else None,
        "exists": target.is_file(),
        "onDiskChanged": assessment.get("onDiskChanged") if assessment else False,
        "sourceChanged": assessment.get("sourceChanged") if assessment else row.status in {
            GeneratedFileStatus.stale.value,
            GeneratedFileStatus.conflict.value,
        },
        "plannedDeletion": assessment.get("plannedDeletion") if assessment else False,
        "guidance": _guidance(row.status),
        "createdAt": _iso(row.created_at),
        "updatedAt": _iso(row.updated_at),
    }


def project_generated_file_status_summary(session: Session, project: Project) -> dict[str, Any]:
    output = Path(project.generated_project_path or Path(project.root_path) / "generated")
    assessments = refresh_generated_file_statuses(
        session,
        project.id,
        output,
        preserve_source_statuses=True,
        commit=True,
    )
    latest_rows = latest_generated_files_by_path(session, project.id)
    rows = sorted(
        latest_rows.values(),
        key=lambda row: (STATUS_ORDER.get(row.status, 99), row.relative_path, row.id or ""),
    )
    origins_by_file = _origins_by_file_id(
        session,
        [row.id for row in rows if row.id],
    )
    files = [
        _file_payload(
            session,
            project.id,
            output,
            row,
            assessments.get(row.relative_path),
            origins_by_file.get(row.id or "", []),
        )
        for row in rows
    ]
    counter = Counter(file["status"] for file in files)
    counts = {
        "total": len(files),
        **{status: counter.get(status, 0) for status in SUMMARY_STATUSES},
    }
    files_by_status = {
        f"{status}Files": sorted(file["path"] for file in files if file["status"] == status)
        for status in SUMMARY_STATUSES
    }
    blocking_statuses = {GeneratedFileStatus.edited.value, GeneratedFileStatus.conflict.value}
    return {
        "projectId": project.id,
        "generatedProjectPath": str(output),
        "ok": not any(file["status"] in blocking_statuses for file in files),
        "counts": counts,
        **files_by_status,
        "files": files,
    }
