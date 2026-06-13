"""Runtime profile resolution tests."""

from __future__ import annotations

import sys
import os
from pathlib import Path

from worker.core.runtime import resolve_runtime
from worker.models.schemas import AppSettings


def test_resolve_runtime_custom_fallback(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TC_STUDIO_RESOURCES", raising=False)
    monkeypatch.setenv("TC_STUDIO_DATA_DIR", str(tmp_path / ".data"))
    settings = AppSettings(
        runtime={"mode": "custom"},
        webwright={"root": str(tmp_path / "ww"), "python": sys.executable},
        generator={"templatePath": str(tmp_path / "tpl")},
    )
    (tmp_path / "ww" / "base.yaml").parent.mkdir(parents=True)
    (tmp_path / "ww" / "base.yaml").write_text("{}", encoding="utf-8")
    (tmp_path / "tpl").mkdir()

    profile = resolve_runtime(settings)
    assert profile.mode == "custom"
    assert profile.webwright_root == str(tmp_path / "ww")
    readiness = profile.check_webwright_readiness()
    assert readiness.root.ok is True
    assert readiness.config.ok is False
    assert readiness.cli.ok is False
    assert profile.has_webwright_cli is False
    assert profile.webwright_output_root == str(tmp_path / ".data" / "webwright-runs")


def test_webwright_readiness_requires_importable_cli(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TC_STUDIO_RESOURCES", raising=False)
    webwright_root = tmp_path / "ww"
    (webwright_root / "webwright" / "run").mkdir(parents=True)
    (webwright_root / "webwright" / "__init__.py").write_text("", encoding="utf-8")
    (webwright_root / "webwright" / "run" / "__init__.py").write_text("", encoding="utf-8")
    (webwright_root / "webwright" / "run" / "cli.py").write_text("def main():\n    return 0\n", encoding="utf-8")
    (webwright_root / "base.yaml").write_text("{}\n", encoding="utf-8")
    (webwright_root / "model_openai.yaml").write_text("{}\n", encoding="utf-8")

    settings = AppSettings(
        runtime={"mode": "custom"},
        webwright={"root": str(webwright_root), "python": sys.executable},
        generator={"templatePath": str(tmp_path / "tpl")},
    )
    (tmp_path / "tpl").mkdir()

    profile = resolve_runtime(settings)
    readiness = profile.check_webwright_readiness()
    assert readiness.root.ok is True
    assert readiness.python.ok is True
    assert readiness.config.ok is True
    assert readiness.cli.ok is True
    assert readiness.live_ok is True
    assert profile.has_webwright_cli is True


def test_webwright_readiness_accepts_source_checkout_config_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TC_STUDIO_RESOURCES", raising=False)
    webwright_root = tmp_path / "Webwright"
    config_dir = webwright_root / "src" / "webwright" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "base.yaml").write_text("{}\n", encoding="utf-8")
    (config_dir / "model_openai.yaml").write_text("{}\n", encoding="utf-8")

    settings = AppSettings(
        runtime={"mode": "custom"},
        webwright={"root": str(webwright_root), "python": sys.executable},
        generator={"templatePath": str(tmp_path / "tpl")},
    )
    (tmp_path / "tpl").mkdir()

    profile = resolve_runtime(settings)
    readiness = profile.check_webwright_readiness()
    assert readiness.root.ok is True
    assert readiness.config.ok is True
    assert str(config_dir / "base.yaml") in readiness.config.path
    assert readiness.cli.ok is False
    assert readiness.live_ok is False


def test_runtime_subprocess_env_maps_generic_api_key_by_provider(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TC_STUDIO_RESOURCES", raising=False)
    monkeypatch.setenv("API_KEY", "secret-for-test")
    monkeypatch.setenv("TC_WEBWRIGHT_SHELL", str(tmp_path / "bash.exe"))

    settings = AppSettings(
        runtime={"mode": "custom"},
        webwright={
            "root": str(tmp_path / "ww"),
            "python": sys.executable,
            "apiProvider": "anthropic",
            "modelConfig": "model_claude.yaml",
            "stepLimit": 12,
            "runTimeoutSeconds": 34,
        },
        generator={"templatePath": str(tmp_path / "tpl")},
    )
    (tmp_path / "ww").mkdir()
    (tmp_path / "tpl").mkdir()

    profile = resolve_runtime(settings)
    env = profile.subprocess_env()
    assert env["ANTHROPIC_API_KEY"] == "secret-for-test"
    assert env["PYTHONUTF8"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["TC_WEBWRIGHT_SHELL"] == str(tmp_path / "bash.exe")
    assert profile.webwright_shell == str(tmp_path / "bash.exe")
    assert profile.webwright_step_limit == 12
    assert profile.webwright_run_timeout_seconds == 34


def test_runtime_subprocess_env_prefers_webwright_python_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TC_STUDIO_RESOURCES", raising=False)
    scripts_dir = tmp_path / ".venv" / "Scripts"
    scripts_dir.mkdir(parents=True)
    python = scripts_dir / "python.exe"
    python.write_text("", encoding="utf-8")

    settings = AppSettings(
        runtime={"mode": "custom"},
        webwright={"root": str(tmp_path / "ww"), "python": str(python)},
        generator={"templatePath": str(tmp_path / "tpl")},
    )
    (tmp_path / "ww").mkdir()
    (tmp_path / "tpl").mkdir()

    env = resolve_runtime(settings).subprocess_env()
    assert env["PATH"].split(os.pathsep)[0] == str(scripts_dir)
    assert env["VIRTUAL_ENV"] == str(tmp_path / ".venv")


def test_resolve_runtime_defaults_to_vendored_webwright(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TC_STUDIO_RESOURCES", raising=False)
    monkeypatch.delenv("TC_LIVE_WEBWRIGHT_ROOT", raising=False)

    settings = AppSettings(
        runtime={"mode": "custom", "python": sys.executable},
        webwright={"root": "", "python": sys.executable},
        generator={"templatePath": str(tmp_path / "tpl")},
    )
    (tmp_path / "tpl").mkdir()

    profile = resolve_runtime(settings)
    assert profile.webwright_root.endswith(str(Path("third_party") / "webwright"))
    assert (Path(profile.webwright_root) / "LICENSE").exists()
    assert (Path(profile.webwright_root).parent / "NOTICE.md").exists()


def test_resolve_runtime_bundled(monkeypatch, tmp_path: Path) -> None:
    staging = tmp_path / "runtime-staging"
    (staging / "python").mkdir(parents=True)
    (staging / "webwright").mkdir()
    (staging / "webwright" / "base.yaml").write_text("{}", encoding="utf-8")
    (staging / "generated-template").mkdir()
    monkeypatch.setenv("TC_STUDIO_RESOURCES", str(staging))
    monkeypatch.setenv("TC_STUDIO_RUNTIME_MODE", "bundled")

    settings = AppSettings(runtime={"mode": "bundled"})
    profile = resolve_runtime(settings)
    assert profile.mode == "bundled"
    assert profile.webwright_root == str(staging / "webwright")
    assert profile.template_path == str(staging / "generated-template")
