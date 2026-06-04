from __future__ import annotations

import importlib
import sys
from pathlib import Path


TEMPLATE_ROOT = Path(__file__).resolve().parents[3] / "packages" / "generated-template"


def _with_template_path():
    if str(TEMPLATE_ROOT) not in sys.path:
        sys.path.insert(0, str(TEMPLATE_ROOT))


def test_env_fixture_resolves_base_url_and_artifact_dir(monkeypatch, tmp_path: Path) -> None:
    _with_template_path()
    from fixtures import env_fixture

    monkeypatch.setenv("TC_BASE_URL", "https://override.example")
    assert env_fixture._base_url({"baseUrl": "https://stg.example"}) == "https://override.example"

    monkeypatch.delenv("TC_BASE_URL", raising=False)
    assert env_fixture._base_url({"base_url": "https://snake.example"}) == "https://snake.example"

    artifact_dir = tmp_path / "artifacts"
    monkeypatch.setenv("TC_ARTIFACT_DIR", str(artifact_dir))
    assert env_fixture._artifact_dir() == artifact_dir
    assert artifact_dir.exists()


def test_browser_fixture_resolves_storage_state_and_viewport(monkeypatch, tmp_path: Path) -> None:
    _with_template_path()
    from fixtures import browser_fixture

    storage = tmp_path / "storage-state.json"
    storage.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("TC_STORAGE_STATE", str(storage))
    assert browser_fixture._storage_state({"storageState": "config/storage-state.json"}) == str(storage)

    monkeypatch.setenv("TC_VIEWPORT_WIDTH", "1440")
    monkeypatch.setenv("TC_VIEWPORT_HEIGHT", "900")
    assert browser_fixture._viewport({"viewport": {"width": 800, "height": 600}}) == {"width": 1440, "height": 900}


def test_pytest_runner_passes_fixture_policy_environment(monkeypatch) -> None:
    _with_template_path()
    pytest_runner = importlib.import_module("runner.pytest_runner")

    monkeypatch.delenv("TC_BASE_URL", raising=False)
    env = pytest_runner._subprocess_env("stg", "run_123", "chromium")

    assert env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert env["TC_ENV"] == "stg"
    assert env["TC_RUN_ID"] == "run_123"
    assert env["TC_BROWSER"] == "chromium"
    assert env["TC_ARTIFACT_DIR"].endswith(str(Path("artifacts") / "runs" / "run_123"))
    assert env["TC_BASE_URL"] == "https://example.com"


def test_pytest_runner_maps_deterministic_case_artifact_paths() -> None:
    _with_template_path()
    pytest_runner = importlib.import_module("runner.pytest_runner")

    run_id = "artifact_policy"
    artifacts = TEMPLATE_ROOT / "artifacts" / "runs" / run_id
    artifacts.mkdir(parents=True, exist_ok=True)
    screenshot = artifacts / "tests_test_sample.py__test_sample.png"
    trace = artifacts / "tests_test_sample.py__test_sample.zip"
    screenshot.write_text("png", encoding="utf-8")
    trace.write_text("zip", encoding="utf-8")
    try:
        mapped = pytest_runner._case_artifacts(run_id, "tests/test_sample.py", "test_sample")
        assert mapped["screenshot"] == "artifacts/runs/artifact_policy/tests_test_sample.py__test_sample.png"
        assert mapped["trace"] == "artifacts/runs/artifact_policy/tests_test_sample.py__test_sample.zip"
        assert mapped["video"] is None
    finally:
        screenshot.unlink(missing_ok=True)
        trace.unlink(missing_ok=True)
