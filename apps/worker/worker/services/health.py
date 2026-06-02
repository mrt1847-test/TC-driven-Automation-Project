from __future__ import annotations

import subprocess
from pathlib import Path

from worker.core.config import get_settings_path, load_settings
from worker.core.runtime import resolve_runtime
from worker.services.generated_runtime import ensure_generated_runtime


def check_health() -> dict:
    settings = load_settings()
    profile = resolve_runtime(settings)
    settings_path = get_settings_path()
    template_path = Path(profile.template_path)
    python_cmd = profile.python
    browser = settings.runner.get("defaultBrowser", "chromium")
    webwright_readiness = profile.check_webwright_readiness()
    checks = {
        "worker": {"ok": True, "message": "Worker running"},
        "settings": {"ok": settings_path.exists(), "path": str(settings_path)},
        "runtimeMode": {"ok": True, "mode": profile.mode},
        "python": _check_command([python_cmd, "--version"], env=profile.subprocess_env()),
        "webwrightRoot": webwright_readiness.root.as_dict(),
        "webwrightPython": webwright_readiness.python.as_dict(),
        "webwrightCli": webwright_readiness.cli.as_dict(),
        "webwrightConfig": webwright_readiness.config.as_dict(),
        "templatePath": {"ok": template_path.exists(), "path": str(template_path)},
        "playwright": _check_command([python_cmd, "-m", "playwright", "--version"], env=profile.subprocess_env()),
        "playwrightBrowser": _check_playwright_browser(python_cmd, browser, profile.subprocess_env()),
        "mockMode": {
            "ok": not webwright_readiness.live_ok,
            "enabled": not webwright_readiness.live_ok,
            "message": "Live Webwright is ready" if webwright_readiness.live_ok else "Live Webwright is not ready; mock mode will be used",
        },
    }
    checks["allOk"] = all(v.get("ok", False) for k, v in checks.items() if k != "allOk")
    return checks


def _check_command(cmd: list[str], env: dict[str, str] | None = None) -> dict:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)
        return {"ok": result.returncode == 0, "message": (result.stdout or result.stderr).strip()}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


def _check_playwright_browser(python_cmd: str, browser: str, env: dict[str, str]) -> dict:
    script = (
        "from pathlib import Path\n"
        "from playwright.sync_api import sync_playwright\n"
        f"browser_name = {browser!r}\n"
        "p = sync_playwright().start()\n"
        "try:\n"
        "    browser_type = getattr(p, browser_name)\n"
        "    path = browser_type.executable_path\n"
        "    print(path)\n"
        "    raise SystemExit(0 if Path(path).exists() else 1)\n"
        "finally:\n"
        "    p.stop()\n"
    )
    result = _check_command([python_cmd, "-c", script], env=env)
    return {**result, "browser": browser}


def project_health_check(generated_path: Path) -> dict:
    checks = {
        "exists": generated_path.exists(),
        "requirements": (generated_path / "requirements.txt").exists(),
        "runner": (generated_path / "runner" / "cli.py").exists(),
        "mappings": (generated_path / "mappings" / "cases.yaml").exists(),
    }
    checks["allOk"] = all(checks.values())
    return checks


def install_dependencies(generated_path: Path) -> dict:
    return ensure_generated_runtime(generated_path, install=True)
