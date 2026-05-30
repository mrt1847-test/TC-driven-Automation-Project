from __future__ import annotations

import json
from pathlib import Path

import httpx


def upload(results_path: Path, base_url: str = "http://localhost:3000") -> None:
    data = json.loads(results_path.read_text(encoding="utf-8"))
    payload = {
        "runId": data.get("runId"),
        "results": [
            {
                "automationKey": c.get("automationKey"),
                "status": c.get("status"),
                "durationMs": c.get("durationMs"),
                "comment": c.get("error") or "Automation passed",
                "artifacts": [],
            }
            for c in data.get("cases", [])
        ],
    }
    with httpx.Client(timeout=30) as client:
        resp = client.post(f"{base_url.rstrip('/')}/api/automation/results/bulk", json=payload)
        resp.raise_for_status()
