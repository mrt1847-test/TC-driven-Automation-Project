from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from worker.core.config import get_settings_path, load_settings


def test_settings_api_strips_plaintext_secret_fields(client: TestClient, tmp_path: Path) -> None:
    secret = "sk-test-secret-value-1234567890"
    response = client.put(
        "/settings",
        json={
            "webwright": {
                "apiProvider": "openai",
                "modelConfig": "model_openai.yaml",
                "apiKey": secret,
                "token": secret,
            },
            "integrations": {
                "testrail": {
                    "baseUrl": "https://testrail.example",
                    "enabled": True,
                    "apiToken": secret,
                }
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["webwright"]["apiProvider"] == "openai"
    assert body["webwright"]["modelConfig"] == "model_openai.yaml"
    assert "apiKey" not in body["webwright"]
    assert "token" not in body["webwright"]
    assert "apiToken" not in body["integrations"]["testrail"]
    assert secret not in response.text

    settings_text = (tmp_path / "settings.json").read_text(encoding="utf-8")
    assert secret not in settings_text
    assert "apiKey" not in settings_text
    assert "apiToken" not in settings_text

    get_response = client.get("/settings")
    assert get_response.status_code == 200
    assert secret not in get_response.text


def test_load_settings_scrubs_existing_plaintext_secret_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TC_STUDIO_DATA_DIR", str(tmp_path))
    secret = "sk-existing-secret-value-1234567890"
    path = get_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "webwright": {
                    "apiProvider": "anthropic",
                    "apiKey": secret,
                    "modelConfig": "model_claude.yaml",
                }
            }
        ),
        encoding="utf-8",
    )

    settings = load_settings()

    assert settings.webwright["apiProvider"] == "anthropic"
    assert settings.webwright["modelConfig"] == "model_claude.yaml"
    assert "apiKey" not in settings.webwright
    settings_text = path.read_text(encoding="utf-8")
    assert secret not in settings_text
    assert "apiKey" not in settings_text
