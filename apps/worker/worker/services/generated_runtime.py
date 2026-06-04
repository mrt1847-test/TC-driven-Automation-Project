from __future__ import annotations

import subprocess
from pathlib import Path

from worker.core.runtime import resolve_runtime


def ensure_generated_runtime(generated_path: Path, install: bool = False) -> dict:
    profile = resolve_runtime()
    req = generated_path / "requirements.txt"
    runner = generated_path / "runner" / "cli.py"
    mappings = generated_path / "mappings" / "cases.yaml"
    checks = {
        "requirements": req.exists(),
        "runner": runner.exists(),
        "mappings": mappings.exists(),
    }
    if not req.exists():
        return {
            "ok": False,
            "allOk": False,
            "message": "requirements.txt missing",
            "checks": checks,
            "pip": "",
            "pipError": "",
            "playwright": "",
            "playwrightError": "",
            "playwrightBrowser": {"ok": False, "message": "not checked"},
        }
    if not runner.exists():
        return {
            "ok": False,
            "allOk": False,
            "message": "runner/cli.py missing",
            "checks": checks,
            "pip": "",
            "pipError": "",
            "playwright": "",
            "playwrightError": "",
            "playwrightBrowser": {"ok": False, "message": "not checked"},
        }
    if not mappings.exists():
        return {
            "ok": False,
            "allOk": False,
            "message": "mappings/cases.yaml missing",
            "checks": checks,
            "pip": "",
            "pipError": "",
            "playwright": "",
            "playwrightError": "",
            "playwrightBrowser": {"ok": False, "message": "not checked"},
        }

    env = profile.subprocess_env()
    if not install:
        checks["allOk"] = all(checks.values())
        checks["ok"] = checks["allOk"]
        checks["message"] = "Generated project runtime files are present" if checks["allOk"] else "Generated project runtime files are incomplete"
        return checks

    pip = _run_command(
        [profile.python, "-m", "pip", "install", "-r", str(req)],
        cwd=generated_path,
        env=env,
    )
    if pip.returncode != 0:
        return {
            "ok": False,
            "allOk": False,
            "message": "pip install failed",
            "checks": checks,
            "pip": pip.stdout,
            "pipError": pip.stderr,
            "playwright": "",
            "playwrightError": "",
            "playwrightBrowser": {"ok": False, "message": "not checked"},
        }

    playwright = _run_command([profile.python, "-m", "playwright", "install", "chromium"], env=env)
    if playwright.returncode != 0:
        return {
            "ok": False,
            "allOk": False,
            "message": "playwright install failed",
            "checks": checks,
            "pip": pip.stdout,
            "pipError": pip.stderr,
            "playwright": playwright.stdout,
            "playwrightError": playwright.stderr,
            "playwrightBrowser": {"ok": False, "message": "not checked"},
        }

    browser_check = _browser_installed(profile.python, env)
    browser_ok = browser_check["ok"]
    return {
        "ok": browser_ok,
        "allOk": browser_ok,
        "message": "Generated runtime is ready" if browser_ok else "Playwright browser executable check failed",
        "checks": checks,
        "pip": pip.stdout,
        "pipError": pip.stderr,
        "playwright": playwright.stdout,
        "playwrightError": playwright.stderr,
        "playwrightBrowser": browser_check,
    }


def _browser_installed(python_cmd: str, env: dict[str, str]) -> dict:
    script = (
        "from pathlib import Path\n"
        "from playwright.sync_api import sync_playwright\n"
        "p = sync_playwright().start()\n"
        "try:\n"
        "    path = p.chromium.executable_path\n"
        "    raise SystemExit(0 if Path(path).exists() else 1)\n"
        "finally:\n"
        "    p.stop()\n"
    )
    result = _run_command([python_cmd, "-c", script], env=env)
    return {
        "ok": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "message": "chromium executable exists" if result.returncode == 0 else "chromium executable missing or Playwright import failed",
    }


def _run_command(command: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(cwd) if cwd else None,
            env=env,
        )
    except OSError as exc:
        return subprocess.CompletedProcess(command, 1, "", f"{command[0]}: {exc}")
