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
    checks = {
        "worker": {"ok": True, "message": "Worker running"},
        "settings": {"ok": settings_path.exists(), "path": str(settings_path)},
        "python": _check_command(["python", "--version"]),
        "webwrightRoot": {"ok": bool(webwright_root) and Path(webwright_root).exists(), "path": webwright_root},
        "templatePath": {"ok": template_path.exists(), "path": str(template_path)},
    }
    checks["allOk"] = all(v.get("ok", False) for k, v in checks.items() if k != "allOk")
    return checks


def _check_command(cmd: list[str]) -> dict:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return {"ok": result.returncode == 0, "message": (result.stdout or result.stderr).strip()}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


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
