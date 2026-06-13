from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from worker.core.config import get_settings_path, load_settings
from worker.models.schemas import AppSettings
from worker.services.connector_credentials import connector_credentials_response


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


def test_connector_credentials_metadata_excludes_plaintext_secrets(client: TestClient, tmp_path: Path) -> None:
    testrail_secret = "tr-secret-token-value-1234567890"
    sheets_secret = "-----BEGIN PRIVATE KEY-----\nvery-secret-google-key\n-----END PRIVATE KEY-----\n"
    response = client.put(
        "/settings",
        json={
            "integrations": {
                "testrail": {
                    "baseUrl": "https://testrail.example",
                    "enabled": True,
                    "username": "qa@example.com",
                    "apiToken": testrail_secret,
                },
                "googleSheets": {
                    "enabled": True,
                    "spreadsheetId": "sheet-123",
                    "serviceAccountEmail": "svc@example.iam.gserviceaccount.com",
                    "serviceAccountJson": sheets_secret,
                },
            },
        },
    )

    assert response.status_code == 200
    assert testrail_secret not in response.text
    assert sheets_secret not in response.text
    body = response.json()
    assert body["integrations"]["testrail"]["username"] == "qa@example.com"
    assert body["integrations"]["googleSheets"]["spreadsheetId"] == "sheet-123"
    assert "apiToken" not in body["integrations"]["testrail"]
    assert "serviceAccountJson" not in body["integrations"]["googleSheets"]

    settings_text = (tmp_path / "settings.json").read_text(encoding="utf-8")
    assert testrail_secret not in settings_text
    assert sheets_secret not in settings_text
    assert "apiToken" not in settings_text
    assert "serviceAccountJson" not in settings_text

    metadata = client.get("/settings/connector-credentials")
    assert metadata.status_code == 200
    payload = metadata.json()
    assert payload["service"] == "tc-studio"
    assert payload["storage"] == "osCredentialStore"
    assert payload["secretsReturned"] is False
    assert payload["connectors"]["testrail"]["config"]["username"] == "qa@example.com"
    assert payload["connectors"]["testrail"]["credentials"][0]["account"] == "connector:testrail:apiToken"
    assert payload["connectors"]["googleSheets"]["credentials"][0]["account"] == (
        "connector:googleSheets:serviceAccountJson"
    )
    assert testrail_secret not in metadata.text
    assert sheets_secret not in metadata.text
    assert "apiToken" in metadata.text
    assert "serviceAccountJson" in metadata.text


def test_connector_credentials_response_masks_loggable_config_values() -> None:
    secret_like_username = "sk-secret-looking-value-1234567890"
    payload = connector_credentials_response(
        AppSettings(
            integrations={
                "testrail": {
                    "enabled": True,
                    "baseUrl": "https://testrail.example",
                    "username": secret_like_username,
                },
                "googleSheets": {
                    "enabled": True,
                    "serviceAccountEmail": "svc@example.iam.gserviceaccount.com",
                },
            }
        )
    )

    assert payload["connectors"]["testrail"]["config"]["username"] == "***MASKED***"
    assert secret_like_username not in json.dumps(payload)
