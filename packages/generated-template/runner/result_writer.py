from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runner.secret_redaction import redact_json, redact_text


def write_results(
    run_id: str,
    env: str,
    browser: str,
    cases: list[dict[str, Any]],
    pytest: dict[str, Any] | None = None,
    started_at: str | None = None,
    ended_at: str | None = None,
) -> Path:
    root = Path(__file__).resolve().parents[1]
    out_dir = root / "artifacts" / "runs" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    passed = sum(1 for c in cases if c.get("status") == "passed")
    failed = sum(1 for c in cases if c.get("status") == "failed")
    skipped = sum(1 for c in cases if c.get("status") == "skipped")
    now = datetime.now(timezone.utc).isoformat()

    payload = {
        "runId": run_id,
        "projectName": "generated-automation-project",
        "env": env,
        "browser": browser,
        "startedAt": started_at or now,
        "endedAt": ended_at or now,
        "summary": {
            "total": len(cases),
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
        },
        "pytest": pytest or {},
        "cases": cases,
    }
    path = out_dir / "results.json"
    path.write_text(json.dumps(redact_json(payload), indent=2), encoding="utf-8")
    return path


def parse_pytest_output(
    stdout: str,
    case_meta: dict[str, Any],
    status: str,
    error: str | None = None,
    artifacts: dict[str, str | None] | None = None,
    duration_ms: int = 0,
) -> dict[str, Any]:
    return {
        "automationKey": case_meta.get("automationKey"),
        "sourceType": case_meta.get("sourceType"),
        "sourceCaseId": case_meta.get("sourceCaseId"),
        "title": case_meta.get("title"),
        "status": status,
        "durationMs": duration_ms,
        "error": redact_text(error) if error else None,
        "artifacts": artifacts or {"screenshot": None, "trace": None, "video": None},
    }
