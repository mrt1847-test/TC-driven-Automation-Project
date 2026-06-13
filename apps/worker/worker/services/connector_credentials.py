from __future__ import annotations

from copy import deepcopy
from typing import Any

from worker.core.config import MASK, SECRET_NAME_RE, mask_secret_data
from worker.models.schemas import AppSettings


CREDENTIAL_SERVICE = "tc-studio"

CONNECTOR_CREDENTIALS: dict[str, list[dict[str, Any]]] = {
    "testrail": [
        {
            "kind": "apiToken",
            "account": "connector:testrail:apiToken",
            "label": "TestRail API token",
            "requiredFor": ["import", "export"],
        }
    ],
    "googleSheets": [
        {
            "kind": "serviceAccountJson",
            "account": "connector:googleSheets:serviceAccountJson",
            "label": "Google Sheets service account JSON",
            "requiredFor": ["import", "export"],
        }
    ],
}


def connector_credential_accounts() -> dict[str, list[dict[str, Any]]]:
    return deepcopy(CONNECTOR_CREDENTIALS)


def connector_credentials_response(settings: AppSettings) -> dict[str, Any]:
    integrations = settings.integrations or {}
    connectors: dict[str, dict[str, Any]] = {}
    for connector_id, credentials in CONNECTOR_CREDENTIALS.items():
        config = _public_connector_config(integrations.get(connector_id, {}))
        connectors[connector_id] = {
            "id": connector_id,
            "enabled": bool(config.get("enabled")),
            "config": config,
            "credentials": deepcopy(credentials),
            "presenceSource": "electronCredentialStore",
        }
    return {
        "service": CREDENTIAL_SERVICE,
        "storage": "osCredentialStore",
        "secretsReturned": False,
        "mask": MASK,
        "connectors": connectors,
    }


def _public_connector_config(value: Any) -> Any:
    if isinstance(value, list):
        return [_public_connector_config(item) for item in value]
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if SECRET_NAME_RE.search(str(key)):
                continue
            cleaned[key] = _public_connector_config(item)
        return mask_secret_data(cleaned)
    return mask_secret_data(value)
