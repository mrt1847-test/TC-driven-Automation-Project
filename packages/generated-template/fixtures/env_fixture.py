import json
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def env_config():
    env = __import__("os").environ.get("TC_ENV", "stg")
    path = Path(__file__).resolve().parents[1] / "config" / f"env.{env}.json"
    return json.loads(path.read_text(encoding="utf-8"))
