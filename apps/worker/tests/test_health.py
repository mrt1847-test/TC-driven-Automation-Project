from __future__ import annotations

from pathlib import Path

from worker.models.schemas import AppSettings
from worker.services import health


class _Check:
    def __init__(self, path: str | None = None) -> None:
        self.path = path

    def as_dict(self) -> dict:
        data = {"ok": True, "message": "ok"}
        if self.path is not None:
            data["path"] = self.path
        return data


class _Readiness:
    def __init__(self) -> None:
        self.root = _Check()
        self.python = _Check()
        self.config = _Check()
        self.cli = _Check()
        self.shell = _Check()
        self.live_ok = True


class _Profile:
    mode = "bundled"
    python = "python"
    template_path = ""

    def __init__(self, template_path: Path) -> None:
        self.template_path = str(template_path)

    def check_webwright_readiness(self) -> _Readiness:
        return _Readiness()

    def subprocess_env(self) -> dict[str, str]:
        return {}


def test_health_all_ok_ignores_live_mock_mode_indicator(monkeypatch, tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text("{}", encoding="utf-8")
    template_path = tmp_path / "template"
    template_path.mkdir()

    monkeypatch.setattr(health, "load_settings", lambda: AppSettings())
    monkeypatch.setattr(health, "get_settings_path", lambda: settings_path)
    monkeypatch.setattr(health, "resolve_runtime", lambda _settings: _Profile(template_path))
    monkeypatch.setattr(health, "_check_command", lambda *_args, **_kwargs: {"ok": True, "message": "ok"})
    monkeypatch.setattr(
        health,
        "_check_playwright_browser",
        lambda *_args, **_kwargs: {"ok": True, "message": "ok", "browser": "chromium"},
    )

    payload = health.check_health()

    assert payload["mockMode"] == {
        "ok": False,
        "enabled": False,
        "message": "Live Webwright is ready",
    }
    assert payload["allOk"] is True
