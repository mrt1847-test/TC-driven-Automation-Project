from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

import httpx
from openpyxl import load_workbook
from typing import Any

from sqlmodel import Session, select

from worker.core.config import load_settings, mask_secret_data, mask_secrets, new_id
from worker.models.db import ExportLog, ExecutionResult, ExecutionRun


class ExportValidationError(ValueError):
    """Raised when an export would write back to an unsafe target mapping."""


def _load_results(execution: ExecutionRun) -> dict[str, Any]:
    if not execution.result_path or not Path(execution.result_path).exists():
        raise FileNotFoundError("results.json not found")
    return json.loads(Path(execution.result_path).read_text(encoding="utf-8"))


def _result_updates(execution: ExecutionRun, results: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    results = results if results is not None else _load_results(execution)
    return [
        {
            "automationKey": case.get("automationKey"),
            "sourceType": case.get("sourceType"),
            "sourceCaseId": case.get("sourceCaseId"),
            "title": case.get("title"),
            "status": case.get("status"),
            "durationMs": case.get("durationMs"),
            "runId": execution.run_id,
            "comment": case.get("error") or "Automation passed",
            "artifacts": case.get("artifacts") or {},
        }
        for case in results.get("cases", [])
    ]


def _generated_project_root(execution: ExecutionRun) -> Path:
    if not execution.result_path:
        raise FileNotFoundError("results.json not found")
    try:
        return Path(execution.result_path).parents[3]
    except IndexError as exc:
        raise ExportValidationError("results.json path is not inside a generated project run directory") from exc


def _load_mapping_entries(execution: ExecutionRun) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    mapping_path = _generated_project_root(execution) / "mappings" / "cases.yaml"
    if not mapping_path.exists():
        return [], [{
            "kind": "mapping_file_missing",
            "message": "Generated mappings/cases.yaml was not found",
            "path": str(mapping_path),
        }]

    try:
        import yaml

        mapping_data = yaml.safe_load(mapping_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        return [], [{
            "kind": "mapping_load_failed",
            "message": f"Generated mappings/cases.yaml could not be loaded: {exc}",
            "path": str(mapping_path),
        }]

    cases = mapping_data.get("cases")
    if not isinstance(cases, list):
        return [], [{
            "kind": "mapping_cases_invalid",
            "message": "Generated mappings/cases.yaml must contain a cases list",
            "path": str(mapping_path),
        }]
    return cases, []


def _group_by_key(items: list[Any], key_getter) -> dict[str | None, list[Any]]:
    grouped: dict[str | None, list[Any]] = {}
    for item in items:
        grouped.setdefault(key_getter(item), []).append(item)
    return grouped


def _issue(kind: str, message: str, automation_key: str | None = None, **extra: Any) -> dict[str, Any]:
    item = {"kind": kind, "message": message}
    if automation_key is not None:
        item["automationKey"] = automation_key
    item.update(extra)
    return item


def _compare_identity(
    issues: list[dict[str, Any]],
    *,
    automation_key: str,
    left_name: str,
    right_name: str,
    left: dict[str, Any],
    right: dict[str, Any],
) -> None:
    left_source_type = left.get("sourceType")
    right_source_type = right.get("sourceType")
    if left_source_type != right_source_type:
        issues.append(_issue(
            "source_type_mismatch",
            f"{left_name} sourceType does not match {right_name}",
            automation_key,
            resultValue=left_source_type,
            expectedValue=right_source_type,
        ))

    left_source_case_id = left.get("sourceCaseId")
    right_source_case_id = right.get("sourceCaseId")
    if left_source_case_id != right_source_case_id:
        issues.append(_issue(
            "source_case_id_mismatch",
            f"{left_name} sourceCaseId does not match {right_name}",
            automation_key,
            resultValue=left_source_case_id,
            expectedValue=right_source_case_id,
        ))


def _db_result_identity(result: ExecutionResult) -> dict[str, Any]:
    return {
        "sourceType": result.source_type,
        "sourceCaseId": result.source_case_id,
    }


def _mapping_identity(mapping: dict[str, Any]) -> dict[str, Any]:
    return {
        "sourceType": mapping.get("sourceType"),
        "sourceCaseId": mapping.get("sourceCaseId"),
    }


def _validate_export(
    session: Session,
    execution: ExecutionRun,
    updates: list[dict[str, Any]],
    mapping_entries: list[dict[str, Any]],
    preload_issues: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    issues = list(preload_issues or [])

    mapping_groups = _group_by_key(mapping_entries, lambda item: item.get("automationKey"))
    db_results = session.exec(
        select(ExecutionResult).where(ExecutionResult.execution_run_id == execution.id)
    ).all()
    db_groups = _group_by_key(db_results, lambda item: item.automation_key)

    for key, rows in mapping_groups.items():
        if key is None:
            issues.append(_issue("missing_automation_key", "Generated mapping row is missing automationKey"))
        elif len(rows) > 1:
            issues.append(_issue(
                "ambiguous_mapping",
                "Generated mappings/cases.yaml contains duplicate automationKey rows",
                key,
            ))

    for key, rows in db_groups.items():
        if not key:
            issues.append(_issue("missing_automation_key", "ExecutionResult row is missing automation_key"))
        elif len(rows) > 1:
            issues.append(_issue(
                "ambiguous_execution_result",
                "ExecutionResult rows contain duplicate automation_key values",
                key,
            ))

    for update in updates:
        automation_key = update.get("automationKey")
        if not automation_key:
            issues.append(_issue("missing_automation_key", "Result row is missing automationKey"))
            continue

        mapping_matches = mapping_groups.get(automation_key, [])
        if not mapping_matches:
            issues.append(_issue(
                "missing_mapping",
                "No generated mapping row exists for result automationKey",
                automation_key,
            ))
        elif len(mapping_matches) == 1:
            _compare_identity(
                issues,
                automation_key=automation_key,
                left_name="Result row",
                right_name="generated mapping",
                left=update,
                right=_mapping_identity(mapping_matches[0]),
            )

        db_matches = db_groups.get(automation_key, [])
        if not db_matches:
            issues.append(_issue(
                "missing_execution_result",
                "No ExecutionResult row exists for result automationKey",
                automation_key,
            ))
        elif len(db_matches) == 1:
            _compare_identity(
                issues,
                automation_key=automation_key,
                left_name="Result row",
                right_name="ExecutionResult",
                left=update,
                right=_db_result_identity(db_matches[0]),
            )

    return {
        "ok": not issues,
        "checked": len(updates),
        "issues": issues,
    }


def _raise_if_invalid(validation: dict[str, Any]) -> None:
    if validation.get("ok"):
        return
    kinds = sorted({issue.get("kind", "unknown") for issue in validation.get("issues", [])})
    raise ExportValidationError(f"Export validation failed: {', '.join(kinds)}")


def _log_export(
    session: Session,
    execution: ExecutionRun,
    target: str,
    status: str,
    updates: list[dict[str, Any]],
    extra: dict[str, Any] | None = None,
) -> None:
    log_payload = {
        "runId": execution.run_id,
        "updates": [
            {
                "automationKey": item.get("automationKey"),
                "sourceCaseId": item.get("sourceCaseId"),
                "status": item.get("status"),
            }
            for item in updates
        ],
    }
    if extra:
        log_payload.update(extra)
    session.add(ExportLog(
        id=new_id("exp"),
        execution_run_id=execution.id,
        target=target,
        status=status,
        message=json.dumps(mask_secret_data(log_payload), ensure_ascii=False),
    ))
    session.commit()


async def export_testrail_clone(session: Session, execution: ExecutionRun, preview: bool = False) -> dict:
    settings = load_settings()
    base_url = settings.integrations.get("testrailClone", {}).get("baseUrl", "http://localhost:3000")
    updates = _result_updates(execution)
    mapping_entries, mapping_issues = _load_mapping_entries(execution)
    validation = _validate_export(session, execution, updates, mapping_entries, mapping_issues)
    payload = {
        "runId": execution.run_id,
        "results": [
            {
                "automationKey": item.get("automationKey"),
                "sourceType": item.get("sourceType"),
                "sourceCaseId": item.get("sourceCaseId"),
                "title": item.get("title"),
                "status": item.get("status"),
                "durationMs": item.get("durationMs"),
                "comment": item.get("comment"),
                "artifacts": item.get("artifacts"),
            }
            for item in updates
        ],
    }
    if preview:
        return {"preview": True, "payload": payload, "validation": validation}

    _raise_if_invalid(validation)

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{base_url.rstrip('/')}/api/automation/results/bulk", json=payload)
        ok = resp.status_code < 400
        _log_export(
            session,
            execution,
            "testrail-clone",
            "success" if ok else "failed",
            updates,
            {"response": mask_secrets(resp.text[:300])},
        )
        resp.raise_for_status()
        return resp.json()


def export_excel(session: Session, execution: ExecutionRun, preview: bool = False) -> dict:
    results = _load_results(execution)
    result_updates = _result_updates(execution, results)
    mapping_entries, mapping_issues = _load_mapping_entries(execution)
    validation = _validate_export(session, execution, result_updates, mapping_entries, mapping_issues)
    by_key = {c.get("automationKey"): c for c in mapping_entries}

    updates = []
    for case in results.get("cases", []):
        key = case.get("automationKey")
        meta = by_key.get(key, {})
        excel_meta = (meta.get("resultTargets") or {}).get("excel") or {}
        if not excel_meta.get("file"):
            continue
        updates.append({
            "automationKey": key,
            "sourceCaseId": case.get("sourceCaseId"),
            "file": excel_meta.get("file"),
            "row": excel_meta.get("row"),
            "status": case.get("status"),
            "runId": execution.run_id,
            "comment": case.get("error") or "Automation passed",
        })

    if preview:
        return {"preview": True, "updates": updates, "validation": validation}

    _raise_if_invalid(validation)

    failed = []
    for item in updates:
        src = Path(item["file"])
        if not src.exists():
            failed.append({**item, "error": "source file not found"})
            continue
        backup = src.with_suffix(src.suffix + f".backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}")
        shutil.copy2(src, backup)
        wb = load_workbook(src)
        ws = wb.active
        row = item["row"]
        headers = [cell.value for cell in ws[1]]
        col_map = {
            "Automation Result": item["status"],
            "Automation Run ID": execution.run_id,
            "Automation Executed At": datetime.utcnow().isoformat(),
            "Automation Comment": item.get("comment") or "",
        }
        for col_name, value in col_map.items():
            if col_name in headers:
                column = headers.index(col_name) + 1
            else:
                column = len(headers) + 1
                ws.cell(row=1, column=column, value=col_name)
                headers.append(col_name)
            ws.cell(row=row, column=column, value=value)
        wb.save(src)

    updated = len(updates) - len(failed)
    _log_export(
        session,
        execution,
        "excel",
        "failed" if failed else "success",
        updates,
        {"failed": failed},
    )
    return {"updated": updated, "failed": failed}


async def export_testrail(session: Session, execution: ExecutionRun, preview: bool = False) -> dict:
    updates = _result_updates(execution)
    mapping_entries, mapping_issues = _load_mapping_entries(execution)
    validation = _validate_export(session, execution, updates, mapping_entries, mapping_issues)
    if preview:
        return {"preview": True, "updates": updates, "validation": validation}
    _raise_if_invalid(validation)
    _log_export(session, execution, "testrail", "success", updates, {"mode": "local-mock"})
    return {"updated": len(updates), "target": "testrail", "updates": updates}


async def export_google_sheets(session: Session, execution: ExecutionRun, preview: bool = False) -> dict:
    updates = _result_updates(execution)
    mapping_entries, mapping_issues = _load_mapping_entries(execution)
    validation = _validate_export(session, execution, updates, mapping_entries, mapping_issues)
    if preview:
        return {"preview": True, "updates": updates, "validation": validation}
    _raise_if_invalid(validation)
    _log_export(session, execution, "google-sheets", "success", updates, {"mode": "local-mock"})
    return {"updated": len(updates), "target": "google-sheets", "updates": updates}
