from __future__ import annotations

import os
import secrets
from hmac import compare_digest

from fastapi import WebSocket
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

WORKER_TOKEN_ENV = "TC_STUDIO_WORKER_TOKEN"
WORKER_ALLOWED_ORIGINS_ENV = "TC_STUDIO_ALLOWED_ORIGINS"
WORKER_TOKEN_HEADER = "X-TC-Studio-Worker-Token"
WORKER_TOKEN_QUERY_PARAM = "token"

DEFAULT_ALLOWED_ORIGINS = (
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:8765",
    "http://localhost:8765",
    "file://",
    "null",
)

PROTECTED_HTTP_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

_WORKER_TOKEN = os.environ.get(WORKER_TOKEN_ENV) or secrets.token_urlsafe(32)


def allowed_origins() -> list[str]:
    configured = os.environ.get(WORKER_ALLOWED_ORIGINS_ENV)
    if not configured:
        return list(DEFAULT_ALLOWED_ORIGINS)
    origins = [origin.strip() for origin in configured.split(",") if origin.strip()]
    return origins or list(DEFAULT_ALLOWED_ORIGINS)


def is_allowed_origin(origin: str | None) -> bool:
    if not origin:
        return True
    return origin in set(allowed_origins())


def is_valid_worker_token(token: str | None) -> bool:
    if not token:
        return False
    return compare_digest(token, _WORKER_TOKEN)


def websocket_trust_denied_reason(websocket: WebSocket) -> str | None:
    if not is_allowed_origin(websocket.headers.get("origin")):
        return "Worker origin is not allowed"
    if not is_valid_worker_token(websocket.query_params.get(WORKER_TOKEN_QUERY_PARAM)):
        return "Worker authorization required"
    return None


class WorkerTrustBoundaryMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method.upper() not in PROTECTED_HTTP_METHODS:
            return await call_next(request)
        if not is_allowed_origin(request.headers.get("origin")):
            return JSONResponse({"detail": "Worker origin is not allowed"}, status_code=403)
        if not is_valid_worker_token(request.headers.get(WORKER_TOKEN_HEADER)):
            return JSONResponse({"detail": "Worker authorization required"}, status_code=401)
        return await call_next(request)
