from __future__ import annotations

import asyncio
import json

import pytest

from worker.core.config import MASK, mask_secret_data, mask_secrets
from worker.core.log_stream import LogStreamManager


@pytest.mark.parametrize(
    ("raw", "secret"),
    [
        ("provider key sk-abcdefghijklmnopqrstuvwxyz123456", "sk-abcdefghijklmnopqrstuvwxyz123456"),
        ("anthropic key sk-ant-api03-abcdefghijklmnopqrstuvwxyz", "sk-ant-api03-abcdefghijklmnopqrstuvwxyz"),
        ("api_key=super-secret-token-value", "super-secret-token-value"),
        ("password: my-local-password", "my-local-password"),
        ("Authorization: Bearer jwt-token-value-here", "jwt-token-value-here"),
        ("Set-Cookie: sessionid=abc123secretcookie", "abc123secretcookie"),
        ("Cookie: auth=session-cookie-value", "session-cookie-value"),
        ("session_cookie=hidden-session-value", "hidden-session-value"),
    ],
)
def test_mask_secrets_redacts_known_patterns(raw: str, secret: str) -> None:
    masked = mask_secrets(raw)
    assert secret not in masked
    assert MASK in masked


def test_mask_secrets_redacts_secret_env_values(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "value-visible-only-via-env-123456789"
    monkeypatch.setenv("TESTRAIL_API_KEY", secret)
    masked = mask_secrets(f"export failed with {secret}")
    assert secret not in masked
    assert MASK in masked


def test_mask_secret_data_redacts_nested_values(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "nested-secret-value-abcdef"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    payload = {
        "message": f"pip failed with {secret}",
        "checks": {"requirements": True},
        "pipError": f"stderr {secret}",
    }
    redacted = mask_secret_data(payload)
    dumped = json.dumps(redacted)
    assert secret not in dumped
    assert MASK in dumped


def test_log_stream_publish_masks_buffered_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "stream-secret-value-abcdef"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    manager = LogStreamManager()
    asyncio.run(manager.publish("job_mask", f"stdout secret={secret}"))

    assert manager._buffers["job_mask"] == [f"stdout secret={MASK}"]


def test_log_stream_publish_masks_provider_key_patterns() -> None:
    manager = LogStreamManager()
    raw = "Bearer leaked-jwt-token-value"
    asyncio.run(manager.publish("job_pattern", raw))

    assert "leaked-jwt-token-value" not in manager._buffers["job_pattern"][0]
    assert MASK in manager._buffers["job_pattern"][0]
