from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from worker.core.config import get_settings_path, load_settings


def check_health() -> dict:
    settings = load_settings()
    settings_path = get_settings_path()
    template_path = Path(settings.generator.get("templatePath", ""))
    webwright_root = settings.webwright.get("root")
    python_cmd = settings.webwright.get("python") or "python"
    browser = settings.runner.get("defaultBrowser", "chromium")
    checks = {
        "worker": {"ok": True, "message": "Worker running"},
        "settings": {"ok": settings_path.exists(), "path": str(settings_path)},
        "python": _check_command([python_cmd, "--version"]),
        "webwrightRoot": {"ok": bool(webwright_root) and Path(webwright_root).exists(), "path": webwright_root},
        "templatePath": {"ok": template_path.exists(), "path": str(template_path)},
        "playwright": _check_command([python_cmd, "-m", "playwright", "--version"]),
        "playwrightBrowser": _check_playwright_browser(python_cmd, browser),
    }
    checks["allOk"] = all(v.get("ok", False) for k, v in checks.items() if k != "allOk")
    return checks


def _check_command(cmd: list[str]) -> dict:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return {"ok": result.returncode == 0, "message": (result.stdout or result.stderr).strip()}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


def _check_playwright_browser(python_cmd: str, browser: str) -> dict:
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
    result = _check_command([python_cmd, "-c", script])
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
    req = generated_path / "requirements.txt"
    if not req.exists():
        return {"ok": False, "message": "requirements.txt missing"}
    result = subprocess.run(["pip", "install", "-r", str(req)], capture_output=True, text=True, cwd=str(generated_path))
    playwright = subprocess.run(["python", "-m", "playwright", "install", "chromium"], capture_output=True, text=True)
    return {
        "ok": result.returncode == 0,
        "pip": result.stdout,
        "playwright": playwright.stdout or playwright.stderr,
    }
