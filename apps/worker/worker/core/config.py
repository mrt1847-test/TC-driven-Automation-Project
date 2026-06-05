from __future__ import annotations

import json
import os
import re
from pathlib import Path
from collections.abc import Mapping
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
    from worker.core.runtime import apply_runtime_defaults

    path = get_settings_path()
    if not path.exists():
        settings = apply_runtime_defaults(AppSettings())
        save_settings(settings)
        return settings
    settings = AppSettings.model_validate(json.loads(path.read_text(encoding="utf-8-sig")))
    sanitized = sanitize_settings(settings)
    if sanitized.model_dump(mode="python") != settings.model_dump(mode="python"):
        _write_settings(sanitized)
    return apply_runtime_defaults(sanitized)


def save_settings(settings: AppSettings) -> None:
    _write_settings(sanitize_settings(settings))


def _write_settings(settings: AppSettings) -> None:
    path = get_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(settings.model_dump_json(indent=2), encoding="utf-8")


MASK = "***MASKED***"

SECRET_NAME_RE = re.compile(
    r"(api[_-]?key|token|secret|password|passwd|credential|private[_-]?key|bearer|session[_-]?cookie|cookie)",
    re.IGNORECASE,
)

SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9_-]{10,}"),
    re.compile(r"(?i)((?:api[_-]?key|token|secret|password)\s*[:=]\s*[\"']?)([^\s\"',;]+)"),
    re.compile(r"(?i)(Bearer\s+)([^\s]+)"),
    re.compile(r"(?i)(Set-Cookie:\s*)([^\r\n]+)"),
    re.compile(r"(?i)(Cookie:\s*)([^\r\n]+)"),
    re.compile(r"(?i)(session[_-]?cookie\s*[:=]\s*[\"']?)([^\s\"',;]+)"),
]


def _secret_values(environ: Mapping[str, str] | None = None) -> list[str]:
    values: set[str] = set()
    source = environ or os.environ
    for name, value in source.items():
        if not value or len(value) < 6:
            continue
        if SECRET_NAME_RE.search(name):
            values.add(value)
    return sorted(values, key=len, reverse=True)


def mask_secrets(text: str | None, environ: Mapping[str, str] | None = None) -> str:
    if not text:
        return ""
    masked = str(text)
    for value in _secret_values(environ):
        masked = masked.replace(value, MASK)
    masked = SECRET_PATTERNS[0].sub(MASK, masked)
    for pattern in SECRET_PATTERNS[1:]:
        masked = pattern.sub(r"\1" + MASK, masked)
    return masked


def mask_secret_data(value: Any, environ: Mapping[str, str] | None = None) -> Any:
    if isinstance(value, str):
        return mask_secrets(value, environ)
    if isinstance(value, list):
        return [mask_secret_data(item, environ) for item in value]
    if isinstance(value, dict):
        return {key: mask_secret_data(item, environ) for key, item in value.items()}
    return value


def sanitize_settings(settings: AppSettings) -> AppSettings:
    data = _drop_secret_settings(settings.model_dump(mode="python"))
    return AppSettings.model_validate(data)


def _drop_secret_settings(value: Any) -> Any:
    if isinstance(value, list):
        return [_drop_secret_settings(item) for item in value]
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if SECRET_NAME_RE.search(str(key)):
                continue
            cleaned[key] = _drop_secret_settings(item)
        return cleaned
    return value


def new_id(prefix: str) -> str:
    import uuid
    return f"{prefix}_{uuid.uuid4().hex[:12]}"
