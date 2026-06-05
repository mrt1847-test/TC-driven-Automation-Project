from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Any

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


def redact_text(text: str | None, environ: Mapping[str, str] | None = None) -> str:
    if not text:
        return ""
    redacted = str(text)
    for value in _secret_values(environ):
        redacted = redacted.replace(value, MASK)
    redacted = SECRET_PATTERNS[0].sub(MASK, redacted)
    for pattern in SECRET_PATTERNS[1:]:
        redacted = pattern.sub(r"\1" + MASK, redacted)
    return redacted


def redact_json(value: Any, environ: Mapping[str, str] | None = None) -> Any:
    if isinstance(value, str):
        return redact_text(value, environ)
    if isinstance(value, list):
        return [redact_json(item, environ) for item in value]
    if isinstance(value, dict):
        return {key: redact_json(item, environ) for key, item in value.items()}
    return value
