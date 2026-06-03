from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _env_name() -> str:
    return os.environ.get("TC_ENV", "stg")


def _load_env_config(env: str) -> dict[str, Any]:
    path = project_root() / "config" / f"env.{env}.json"
    if not path.exists():
        return {"name": env}
    return json.loads(path.read_text(encoding="utf-8"))


def _base_url(config: dict[str, Any]) -> str:
    return os.environ.get("TC_BASE_URL") or config.get("baseUrl") or config.get("base_url") or ""


def _artifact_dir() -> Path:
    configured = os.environ.get("TC_ARTIFACT_DIR")
    if configured:
        path = Path(configured)
    else:
        run_id = os.environ.get("TC_RUN_ID", "local")
        path = project_root() / "artifacts" / "runs" / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture(scope="session")
def tc_env_name() -> str:
    return _env_name()


@pytest.fixture(scope="session")
def env_config(tc_env_name: str) -> dict[str, Any]:
    return _load_env_config(tc_env_name)


@pytest.fixture(scope="session")
def base_url(env_config: dict[str, Any]) -> str:
    return _base_url(env_config)


@pytest.fixture(scope="session")
def artifact_dir() -> Path:
    return _artifact_dir()
