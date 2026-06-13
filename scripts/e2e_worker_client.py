"""Shared live Worker HTTP client helpers for E2E scripts."""
from __future__ import annotations

import os

import httpx

WORKER_TOKEN_HEADER = "X-TC-Studio-Worker-Token"


def worker_client(base_url: str, timeout: float = 60.0) -> httpx.Client:
    token = os.environ.get("TC_STUDIO_WORKER_TOKEN")
    if not token:
        raise RuntimeError(
            "Set TC_STUDIO_WORKER_TOKEN to the token used by the live Worker "
            "before running this E2E script."
        )
    return httpx.Client(base_url=base_url, timeout=timeout, headers={WORKER_TOKEN_HEADER: token})
