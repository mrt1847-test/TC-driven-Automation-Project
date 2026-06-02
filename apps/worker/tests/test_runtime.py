"""Runtime profile resolution tests."""

from __future__ import annotations

import sys
from pathlib import Path

from worker.core.runtime import resolve_runtime
from worker.models.schemas import AppSettings


def test_resolve_runtime_custom_fallback(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TC_STUDIO_RESOURCES", raising=False)
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
