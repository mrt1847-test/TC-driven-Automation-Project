from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from worker.models.schemas import AppSettings


def get_data_dir() -> Path:
    base = os.environ.get("TC_STUDIO_DATA_DIR")
    if base:
        return Path(base)
    return Path.home() / ".tc-automation-studio"


def get_db_path() -> Path:
    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "studio.db"


def get_settings_path() -> Path:
    return get_data_dir() / "settings.json"


def load_settings() -> AppSettings:
    path = get_settings_path()
    if not path.exists():
        settings = AppSettings()
        template_path = Path(__file__).resolve().parents[4] / "packages" / "generated-template"
        if template_path.exists():
            settings.generator["templatePath"] = str(template_path)
        save_settings(settings)
        return settings
    return AppSettings.model_validate(json.loads(path.read_text(encoding="utf-8")))


def save_settings(settings: AppSettings) -> None:
    path = get_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(settings.model_dump_json(indent=2), encoding="utf-8")


def mask_secrets(text: str) -> str:
    patterns = [
        r"(sk-[a-zA-Z0-9]{20,})",
        r"(api[_-]?key[\"']?\s*[:=]\s*[\"']?)([^\s\"']+)",
        r"(password[\"']?\s*[:=]\s*[\"']?)([^\s\"']+)",
        r"(Bearer\s+)([^\s]+)",
    ]
    masked = text
    for pattern in patterns:
        masked = re.sub(pattern, r"\1***MASKED***", masked, flags=re.IGNORECASE)
    return masked


def new_id(prefix: str) -> str:
    import uuid
    return f"{prefix}_{uuid.uuid4().hex[:12]}"
