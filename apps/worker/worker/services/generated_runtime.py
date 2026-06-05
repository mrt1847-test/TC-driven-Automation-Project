from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

from sqlmodel import Session, select

from worker.core.config import new_id
from worker.core.runtime import resolve_runtime
from worker.models.db import GeneratedRuntimeInstallState


def ensure_generated_runtime(
    generated_path: Path,
    install: bool = False,
    *,
    session: Session | None = None,
    project_id: str | None = None,
    browser: str = "chromium",
) -> dict:
    generated_path = Path(generated_path)
    profile = resolve_runtime()
    req = generated_path / "requirements.txt"
    manifest = generated_path / "config" / "runtime-manifest.json"
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
            "cache": _cache_disabled(project_id),
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
            "cache": _cache_disabled(project_id),
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
            "cache": _cache_disabled(project_id),
        }

    env = profile.subprocess_env()
    if not install:
        checks["allOk"] = all(checks.values())
        checks["ok"] = checks["allOk"]
        checks["message"] = "Generated project runtime files are present" if checks["allOk"] else "Generated project runtime files are incomplete"
        return checks

    fingerprint = _runtime_fingerprint(generated_path, req, manifest, runner, mappings, profile, browser)
    cache_info, cached_state = _probe_runtime_cache(session, project_id, fingerprint)
    if cached_state is not None:
        browser_check = _browser_installed(profile.python, env, browser)
        if browser_check["ok"]:
            return {
                "ok": True,
                "allOk": True,
                "message": "Generated runtime is ready (cached)",
                "checks": checks,
                "pip": "",
                "pipError": "",
                "playwright": "",
                "playwrightError": "",
                "playwrightBrowser": browser_check,
                "cache": {
                    **cache_info,
                    "stateId": cached_state.id,
                    "readinessKey": cached_state.readiness_key,
                },
            }
        cache_info = _mark_cached_browser_stale(session, cached_state, browser_check)

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
            "cache": cache_info,
        }

    playwright = _run_command([profile.python, "-m", "playwright", "install", browser], env=env)
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
            "cache": cache_info,
        }

    browser_check = _browser_installed(profile.python, env, browser)
    browser_ok = browser_check["ok"]
    if browser_ok:
        cache_info = _store_runtime_cache_success(
            session,
            project_id,
            fingerprint,
            profile.python,
            browser,
            getattr(profile, "playwright_browsers_path", None) or "",
            cache_info,
        )
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
        "cache": cache_info,
    }


def _browser_installed(python_cmd: str, env: dict[str, str], browser: str = "chromium") -> dict:
    script = (
        "from pathlib import Path\n"
        "from playwright.sync_api import sync_playwright\n"
        f"browser_name = {browser!r}\n"
        "p = sync_playwright().start()\n"
        "try:\n"
        "    path = getattr(p, browser_name).executable_path\n"
        "    raise SystemExit(0 if Path(path).exists() else 1)\n"
        "finally:\n"
        "    p.stop()\n"
    )
    result = _run_command([python_cmd, "-c", script], env=env)
    return {
        "ok": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "message": f"{browser} executable exists" if result.returncode == 0 else f"{browser} executable missing or Playwright import failed",
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


def _runtime_fingerprint(
    generated_path: Path,
    requirements_path: Path,
    manifest_path: Path,
    runner_path: Path,
    mappings_path: Path,
    profile,
    browser: str,
) -> dict[str, str]:
    path = str(generated_path.resolve())
    requirements_hash = _hash_file(requirements_path)
    manifest_hash = _hash_file(manifest_path)
    generated_project_hash = _hash_payload({
        "requirements": requirements_hash,
        "runtimeManifest": manifest_hash,
        "runner": _hash_file(runner_path),
        "mappings": _hash_file(mappings_path),
    })
    runtime_profile_hash = _hash_payload({
        "mode": getattr(profile, "mode", ""),
        "python": _profile_value(profile, "python"),
        "playwrightBrowsersPath": getattr(profile, "playwright_browsers_path", None) or "",
        "templatePath": getattr(profile, "template_path", ""),
    })
    browser_cache_path = getattr(profile, "playwright_browsers_path", None) or ""
    readiness_payload = {
        "generatedProjectPath": path,
        "generatedProjectHash": generated_project_hash,
        "requirementsHash": requirements_hash,
        "runtimeManifestHash": manifest_hash,
        "runtimeProfileHash": runtime_profile_hash,
        "pythonPath": _profile_value(profile, "python"),
        "browser": browser,
        "browserCachePath": browser_cache_path,
    }
    return {
        **readiness_payload,
        "readinessKey": _hash_payload(readiness_payload),
    }


def _hash_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _profile_value(profile, name: str) -> str:
    value = getattr(profile, name, "")
    return str(value) if value else ""


def _hash_payload(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _cache_disabled(project_id: str | None) -> dict:
    return {
        "status": "disabled",
        "message": "Runtime install cache requires project/session context",
        "projectId": project_id,
    }


def _probe_runtime_cache(
    session: Session | None,
    project_id: str | None,
    fingerprint: dict[str, str],
) -> tuple[dict, GeneratedRuntimeInstallState | None]:
    if session is None or not project_id:
        return _cache_disabled(project_id), None

    ready = session.exec(
        select(GeneratedRuntimeInstallState).where(
            GeneratedRuntimeInstallState.project_id == project_id,
            GeneratedRuntimeInstallState.readiness_key == fingerprint["readinessKey"],
            GeneratedRuntimeInstallState.status == "ready",
        )
    ).first()
    if ready:
        return {
            "status": "hit",
            "message": "Using cached generated runtime readiness",
            "staleFields": [],
        }, ready

    same_path = session.exec(
        select(GeneratedRuntimeInstallState).where(
            GeneratedRuntimeInstallState.project_id == project_id,
            GeneratedRuntimeInstallState.generated_project_path == fingerprint["generatedProjectPath"],
        )
    ).all()
    if same_path:
        previous = max(same_path, key=lambda row: row.updated_at)
        stale_fields = _stale_fields(previous, fingerprint)
        reason = "Runtime install cache stale: " + ", ".join(stale_fields or ["status"])
        if previous.status == "ready":
            previous.status = "stale"
            previous.message = reason
            previous.updated_at = datetime.utcnow()
            session.add(previous)
            session.commit()
        return {
            "status": "stale",
            "message": reason,
            "reason": reason,
            "previousStateId": previous.id,
            "staleFields": stale_fields,
        }, None

    project_states = session.exec(
        select(GeneratedRuntimeInstallState).where(
            GeneratedRuntimeInstallState.project_id == project_id,
        )
    ).all()
    if project_states:
        previous = max(project_states, key=lambda row: row.updated_at)
        reason = "Runtime install cache stale: generatedProjectPath"
        return {
            "status": "stale",
            "message": reason,
            "reason": reason,
            "previousStateId": previous.id,
            "staleFields": ["generatedProjectPath"],
        }, None

    return {
        "status": "miss",
        "message": "No generated runtime readiness cache entry",
        "staleFields": [],
    }, None


def _stale_fields(state: GeneratedRuntimeInstallState, fingerprint: dict[str, str]) -> list[str]:
    fields: list[str] = []
    comparisons = [
        ("generatedProjectHash", state.generated_project_hash, fingerprint["generatedProjectHash"]),
        ("requirementsHash", state.requirements_hash, fingerprint["requirementsHash"]),
        ("runtimeManifestHash", state.runtime_manifest_hash, fingerprint["runtimeManifestHash"]),
        ("runtimeProfileHash", state.runtime_profile_hash, fingerprint["runtimeProfileHash"]),
        ("pythonPath", state.python_path, fingerprint["pythonPath"]),
        ("browser", state.browser, fingerprint["browser"]),
        ("browserCachePath", state.browser_cache_path, fingerprint["browserCachePath"]),
        ("readinessKey", state.readiness_key, fingerprint["readinessKey"]),
    ]
    for name, previous, current in comparisons:
        if previous != current:
            fields.append(name)
    if state.status != "ready":
        fields.append("status")
    return fields


def _mark_cached_browser_stale(session: Session | None, state: GeneratedRuntimeInstallState, browser_check: dict) -> dict:
    reason = "Runtime install cache stale: playwrightBrowser"
    if session is not None:
        state.status = "stale"
        state.message = reason
        state.updated_at = datetime.utcnow()
        session.add(state)
        session.commit()
    return {
        "status": "stale",
        "message": reason,
        "reason": reason,
        "previousStateId": state.id,
        "staleFields": ["playwrightBrowser"],
        "playwrightBrowser": browser_check,
    }


def _store_runtime_cache_success(
    session: Session | None,
    project_id: str | None,
    fingerprint: dict[str, str],
    python_path: str,
    browser: str,
    browser_cache_path: str,
    previous_cache_info: dict,
) -> dict:
    if session is None or not project_id:
        return previous_cache_info

    now = datetime.utcnow()
    state = session.exec(
        select(GeneratedRuntimeInstallState).where(
            GeneratedRuntimeInstallState.project_id == project_id,
            GeneratedRuntimeInstallState.readiness_key == fingerprint["readinessKey"],
        )
    ).first()
    if state is None:
        state = GeneratedRuntimeInstallState(
            id=new_id("rti"),
            project_id=project_id,
            generated_project_path=fingerprint["generatedProjectPath"],
            generated_project_hash=fingerprint["generatedProjectHash"],
            requirements_hash=fingerprint["requirementsHash"],
            runtime_manifest_hash=fingerprint["runtimeManifestHash"],
            runtime_profile_hash=fingerprint["runtimeProfileHash"],
            readiness_key=fingerprint["readinessKey"],
            python_path=python_path,
            browser=browser,
            browser_cache_path=browser_cache_path,
            created_at=now,
        )
    state.status = "ready"
    state.message = "Generated runtime install verified"
    state.updated_at = now
    session.add(state)
    session.commit()
    session.refresh(state)
    return {
        "status": "stored",
        "message": "Stored generated runtime readiness",
        "stateId": state.id,
        "readinessKey": state.readiness_key,
        "installReason": previous_cache_info.get("status"),
        "reason": previous_cache_info.get("reason") or previous_cache_info.get("message"),
        "staleFields": previous_cache_info.get("staleFields", []),
    }
