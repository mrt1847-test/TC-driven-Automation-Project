from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from worker.core.config import MASK
from worker.services.integrations import testrail as testrail_module
from worker.services.integrations.testrail import TestRailConnectorError, import_from_testrail


def test_testrail_preview_requires_secure_token_when_real_configured(client: TestClient, project_id: str) -> None:
    client.put(
        "/settings",
        json={
            "integrations": {
                "testrail": {
                    "enabled": True,
                    "baseUrl": "https://testrail.example",
                    "username": "qa@example.com",
                }
            }
        },
    )

    response = client.post(
        f"/projects/{project_id}/cases/import/testrail/preview",
        json={"project_id": 12, "suite_id": 3},
    )

    assert response.status_code == 400
    assert "apiToken" in response.text
    assert "qa@example.com" not in response.text


def test_testrail_preview_and_import_normalize_real_api_payload(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    project_id: str,
) -> None:
    secret = "tr-secret-token-value-abcdef"
    captured: list[dict] = []

    async def fake_fetch(project_id_arg: int, suite_id_arg: int | None, config: dict) -> list[dict]:
        captured.append(
            {
                "project_id": project_id_arg,
                "suite_id": suite_id_arg,
                "base_url": config["base_url"],
                "username": config["username"],
                "api_token": config["api_token"],
            }
        )
        return [
            {
                "id": 321,
                "title": "Checkout works",
                "custom_preconds": "User is logged in\nCart has an item",
                "custom_steps_separated": [
                    {"content": "Open checkout", "expected": "Checkout page opens"},
                    {"content": "Submit order", "expected": "Confirmation is shown"},
                ],
                "custom_expected": "Order is created",
                "custom_automation_key": "checkout_works",
                "priority_id": 2,
                "custom_start_url": "https://shop.example/checkout",
            }
        ]

    monkeypatch.setattr(testrail_module, "_fetch_testrail_cases", fake_fetch)
    client.put(
        "/settings",
        json={
            "integrations": {
                "testrail": {
                    "enabled": True,
                    "baseUrl": "https://testrail.example",
                    "username": "qa@example.com",
                }
            }
        },
    )

    preview = client.post(
        f"/projects/{project_id}/cases/import/testrail/preview",
        json={"project_id": 12, "suite_id": 3, "apiToken": secret},
    )

    assert preview.status_code == 200
    assert secret not in preview.text
    preview_cases = preview.json()
    assert preview_cases[0]["source_type"] == "testrail"
    assert preview_cases[0]["source_id"] == "321"
    assert preview_cases[0]["automation_key"] == "checkout_works"
    assert preview_cases[0]["preconditions"] == ["User is logged in", "Cart has an item"]
    assert preview_cases[0]["steps"][1]["expected"] == "Confirmation is shown"
    assert preview_cases[0]["expected_result"] == "Order is created"
    assert preview_cases[0]["priority"] == "2"
    assert preview_cases[0]["start_url"] == "https://shop.example/checkout"
    assert preview_cases[0]["source_location"]["api_endpoint"].startswith(
        "https://testrail.example/index.php?/api/v2/get_cases/12"
    )

    imported = client.post(
        f"/projects/{project_id}/cases/import/testrail",
        json={"project_id": 12, "suite_id": 3, "apiToken": secret},
    )

    assert imported.status_code == 200
    assert secret not in imported.text
    imported_case = imported.json()[0]
    detail = client.get(f"/projects/{project_id}/cases/{imported_case['id']}")
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["status"] == "imported"
    assert detail_body["source_type"] == "testrail"
    assert detail_body["automation_key"] == "checkout_works"
    assert detail_body["source_location"]["api_endpoint"].endswith("get_cases/12&suite_id=3")
    assert captured[-1] == {
        "project_id": 12,
        "suite_id": 3,
        "base_url": "https://testrail.example",
        "username": "qa@example.com",
        "api_token": secret,
    }


def test_testrail_mock_mode_keeps_local_connector_flow(client: TestClient, project_id: str) -> None:
    response = client.post(
        f"/projects/{project_id}/cases/import/testrail/preview",
        json={"project_id": 12, "suite_id": 3, "mock": True},
    )

    assert response.status_code == 200
    assert response.json()[0]["automation_key"] == "sample_testrail_case"


def test_testrail_api_error_masks_token(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    secret = "tr-secret-token-value-abcdef"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/index.php")
        assert "get_cases/12" in str(request.url)
        return httpx.Response(401, json={"error": f"bad token {secret}"})

    class FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(testrail_module.httpx, "AsyncClient", FakeAsyncClient)

    with pytest.raises(TestRailConnectorError) as exc:
        import asyncio

        asyncio.run(
            import_from_testrail(
                12,
                3,
                {
                    "base_url": "https://testrail.example",
                    "username": "qa@example.com",
                    "api_token": secret,
                },
                set(),
            )
        )

    assert exc.value.status_code == 401
    assert secret not in exc.value.message
    assert MASK in exc.value.message
