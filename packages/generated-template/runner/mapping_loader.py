from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_cases() -> list[dict[str, Any]]:
    path = project_root() / "mappings" / "cases.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data.get("cases", [])


def load_env_config(env: str) -> dict[str, Any]:
    path = project_root() / "config" / f"env.{env}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def case_by_key(automation_key: str) -> dict[str, Any] | None:
    for case in load_cases():
        if case.get("automationKey") == automation_key:
            return case
    return None
