from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from worker.core.security import WORKER_TOKEN_HEADER, WORKER_TOKEN_QUERY_PARAM
from worker.main import app

TEST_WORKER_TOKEN = "test-worker-token"


def _generated_root(client: TestClient, project_id: str) -> Path:
    response = client.get(f"/projects/{project_id}")
    assert response.status_code == 200
    root = Path(response.json()["generated_project_path"])
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_generated_file_mutations_require_token_before_side_effect(
    client: TestClient,
    project_id: str,
) -> None:
    root = _generated_root(client, project_id)
    target = root / "blocked.py"

    with TestClient(app) as unauthenticated_client:
        missing = unauthenticated_client.put(
            f"/projects/{project_id}/generated-files/content",
            json={"path": "blocked.py", "content": "missing token\n"},
        )
        invalid = unauthenticated_client.put(
            f"/projects/{project_id}/generated-files/content",
            headers={WORKER_TOKEN_HEADER: "wrong-token"},
            json={"path": "blocked.py", "content": "wrong token\n"},
        )

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert not target.exists()


def test_generated_file_delete_requires_token_before_side_effect(
    client: TestClient,
    project_id: str,
) -> None:
    root = _generated_root(client, project_id)
    target = root / "keep.py"
    target.write_text("keep\n", encoding="utf-8")

    with TestClient(app) as unauthenticated_client:
        response = unauthenticated_client.delete(
            f"/projects/{project_id}/generated-files",
            params={"path": "keep.py"},
        )

    assert response.status_code == 401
    assert target.read_text(encoding="utf-8") == "keep\n"


def test_cross_origin_generated_file_write_rejected_before_side_effect(
    client: TestClient,
    project_id: str,
) -> None:
    root = _generated_root(client, project_id)
    target = root / "evil.py"

    with TestClient(app) as direct_client:
        response = direct_client.put(
            f"/projects/{project_id}/generated-files/content",
            headers={WORKER_TOKEN_HEADER: TEST_WORKER_TOKEN, "Origin": "http://evil.example"},
            json={"path": "evil.py", "content": "evil\n"},
        )

    assert response.status_code == 403
    assert not target.exists()


def test_allowed_dev_origin_and_test_token_can_mutate_generated_file(
    client: TestClient,
    project_id: str,
) -> None:
    root = _generated_root(client, project_id)

    response = client.put(
        f"/projects/{project_id}/generated-files/content",
        headers={"Origin": "http://127.0.0.1:5173"},
        json={"path": "allowed.py", "content": "allowed\n"},
    )

    assert response.status_code == 200
    assert (root / "allowed.py").read_text(encoding="utf-8") == "allowed\n"


def test_cors_preflight_allows_dev_origin_and_rejects_untrusted_origin(
    client: TestClient,
    project_id: str,
) -> None:
    path = f"/projects/{project_id}/generated-files/content"
    headers = {
        "Access-Control-Request-Method": "PUT",
        "Access-Control-Request-Headers": "content-type,x-tc-studio-worker-token",
    }

    allowed = client.options(path, headers={**headers, "Origin": "http://127.0.0.1:5173"})
    rejected = client.options(path, headers={**headers, "Origin": "http://evil.example"})

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert rejected.status_code == 400
    assert "access-control-allow-origin" not in rejected.headers


def test_settings_update_requires_token_but_health_stays_readable(client: TestClient) -> None:
    settings = client.get("/settings").json()

    with TestClient(app) as unauthenticated_client:
        health = unauthenticated_client.get("/health")
        missing = unauthenticated_client.put("/settings", json=settings)
        invalid = unauthenticated_client.put(
            "/settings",
            headers={WORKER_TOKEN_HEADER: "wrong-token"},
            json=settings,
        )

    allowed = client.put("/settings", json=settings)

    assert health.status_code == 200
    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert allowed.status_code == 200


def test_websocket_log_stream_requires_token_and_allowed_origin(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as missing:
        with client.websocket_connect("/ws/logs/missing-token"):
            pass
    assert missing.value.code == 1008

    with pytest.raises(WebSocketDisconnect) as blocked_origin:
        with client.websocket_connect(
            f"/ws/logs/bad-origin?{WORKER_TOKEN_QUERY_PARAM}={TEST_WORKER_TOKEN}",
            headers={"Origin": "http://evil.example"},
        ):
            pass
    assert blocked_origin.value.code == 1008

    with client.websocket_connect(
        f"/ws/logs/allowed?{WORKER_TOKEN_QUERY_PARAM}={TEST_WORKER_TOKEN}",
        headers={"Origin": "http://127.0.0.1:5173"},
    ) as websocket:
        websocket.send_text("ping")
