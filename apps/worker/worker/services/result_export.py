from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

import httpx
from openpyxl import load_workbook
from sqlmodel import Session

from worker.core.config import load_settings, new_id
from worker.models.db import ExportLog, ExecutionRun


async def export_testrail_clone(session: Session, execution: ExecutionRun, preview: bool = False) -> dict:
    settings = load_settings()
    base_url = settings.integrations.get("testrailClone", {}).get("baseUrl", "http://localhost:3000")
    if not execution.result_path or not Path(execution.result_path).exists():
        raise FileNotFoundError("results.json not found")

    results = json.loads(Path(execution.result_path).read_text(encoding="utf-8"))
    payload = {
        "runId": execution.run_id,
        "results": [
            {
                "automationKey": c.get("automationKey"),
                "status": c.get("status"),
                "durationMs": c.get("durationMs"),
                "comment": c.get("error") or "Automation passed",
                "artifacts": [],
            }
            for c in results.get("cases", [])
        ],
    }
    if preview:
        return {"preview": True, "payload": payload}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{base_url.rstrip('/')}/api/automation/results/bulk", json=payload)
        ok = resp.status_code < 400
        session.add(ExportLog(
            id=new_id("exp"),
            execution_run_id=execution.id,
            target="testrail-clone",
            status="success" if ok else "failed",
            message=resp.text[:500],
        ))
        session.commit()
        resp.raise_for_status()
        return resp.json()


def export_excel(session: Session, execution: ExecutionRun, preview: bool = False) -> dict:
    if not execution.result_path:
        raise FileNotFoundError("results.json not found")
    results = json.loads(Path(execution.result_path).read_text(encoding="utf-8"))
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
        })

    if preview:
        return {"preview": True, "updates": updates}

    for item in updates:
        src = Path(item["file"])
        if not src.exists():
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
            "Automation Comment": item.get("error") or "",
        }
        for col_name, value in col_map.items():
            if col_name in headers:
                ws.cell(row=row, column=headers.index(col_name) + 1, value=value)
        wb.save(src)

    session.add(ExportLog(id=new_id("exp"), execution_run_id=execution.id, target="excel", status="success"))
    session.commit()
    return {"updated": len(updates)}


async def export_testrail(session: Session, execution: ExecutionRun, preview: bool = False) -> dict:
    return {"preview": preview, "message": "TestRail export stub"}


async def export_google_sheets(session: Session, execution: ExecutionRun, preview: bool = False) -> dict:
    return {"preview": preview, "message": "Google Sheets export stub"}
