from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

import httpx
from openpyxl import load_workbook
from typing import Any

from sqlmodel import Session

from worker.core.config import load_settings, new_id
from worker.models.db import ExportLog, ExecutionRun


def _load_results(execution: ExecutionRun) -> dict[str, Any]:
    if not execution.result_path or not Path(execution.result_path).exists():
        raise FileNotFoundError("results.json not found")
    return json.loads(Path(execution.result_path).read_text(encoding="utf-8"))


def _result_updates(execution: ExecutionRun) -> list[dict[str, Any]]:
    results = _load_results(execution)
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
        message=json.dumps(log_payload, ensure_ascii=False),
    ))
    session.commit()


async def export_testrail_clone(session: Session, execution: ExecutionRun, preview: bool = False) -> dict:
    settings = load_settings()
    base_url = settings.integrations.get("testrailClone", {}).get("baseUrl", "http://localhost:3000")
    updates = _result_updates(execution)
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
        return {"preview": True, "payload": payload}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{base_url.rstrip('/')}/api/automation/results/bulk", json=payload)
        ok = resp.status_code < 400
        _log_export(
            session,
            execution,
            "testrail-clone",
            "success" if ok else "failed",
            updates,
            {"response": resp.text[:300]},
        )
        resp.raise_for_status()
        return resp.json()


def export_excel(session: Session, execution: ExecutionRun, preview: bool = False) -> dict:
    results = _load_results(execution)
    mapping_path = Path(execution.result_path).parents[3] / "mappings" / "cases.yaml"
    import yaml
    cases_map = yaml.safe_load(mapping_path.read_text(encoding="utf-8")) if mapping_path.exists() else {"cases": []}
    by_key = {c["automationKey"]: c for c in cases_map.get("cases", [])}

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
        return {"preview": True, "updates": updates}

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
    if preview:
        return {"preview": True, "updates": updates}
    _log_export(session, execution, "testrail", "success", updates, {"mode": "local-mock"})
    return {"updated": len(updates), "target": "testrail", "updates": updates}


async def export_google_sheets(session: Session, execution: ExecutionRun, preview: bool = False) -> dict:
    updates = _result_updates(execution)
    if preview:
        return {"preview": True, "updates": updates}
    _log_export(session, execution, "google-sheets", "success", updates, {"mode": "local-mock"})
    return {"updated": len(updates), "target": "google-sheets", "updates": updates}
