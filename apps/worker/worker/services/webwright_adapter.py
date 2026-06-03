from __future__ import annotations

import asyncio
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from worker.core.config import mask_secrets, new_id
from worker.core.runtime import resolve_runtime
from worker.core.log_stream import log_streams
from worker.services.prompt_builder import build_webwright_prompt
from worker.services.case_import import case_to_normalized
from worker.models.db import TestCase, WebwrightRun, WebwrightRunStatus
from worker.services.artifact_indexing import index_webwright_run_artifacts
from sqlmodel import Session


ERROR_PATTERNS = {
    "api_access_forbidden": r"403|forbidden",
    "api_key_invalid": r"401|unauthorized",
    "api_key_missing": r"api.?key|authentication",
    "bash_missing": r"/bin/bash|winerror 2",
    "browser_missing": r"browser.*not.*install|executable.*doesn't exist",
    "timeout": r"timeout|timed out",
    "url_unreachable": r"net::ERR|ECONNREFUSED|404",
    "script_generation_failed": r"final_script|generation failed",
}


def classify_error(stderr: str) -> str:
    text = stderr.lower()
    for name, pattern in ERROR_PATTERNS.items():
        if re.search(pattern, text, re.IGNORECASE):
            return name
    return "unknown"


def _resolve_output_root() -> Path:
    profile = resolve_runtime()
    root = profile.webwright_output_root or str(Path.home() / "webwright-runs")
    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _find_webwright_artifact(output_root: Path, file_name: str) -> Path | None:
    direct = output_root / file_name
    if direct.exists():
        return direct

    top_level_nested = [path for path in output_root.glob(f"*/{file_name}") if path.is_file()]
    if top_level_nested:
        return max(top_level_nested, key=lambda path: path.stat().st_mtime)

    nested = [path for path in output_root.rglob(file_name) if path.is_file()]
    if nested:
        return max(nested, key=lambda path: path.stat().st_mtime)
    return None


def _relative_artifact(output_root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.resolve().relative_to(output_root.resolve()))
    except ValueError:
        return str(path)


async def run_webwright_for_case(session: Session, project_id: str, case: TestCase, model_config: str, job_id: str) -> WebwrightRun:
    profile = resolve_runtime()
    normalized = case_to_normalized(case)
    start_url = case.start_url or "https://example.com"
    prompt = build_webwright_prompt(normalized, start_url=start_url)

    run_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_root = _resolve_output_root() / case.automation_key / f"run_{run_ts}"
    output_root.mkdir(parents=True, exist_ok=True)

    run = WebwrightRun(
        id=new_id("ww"),
        project_id=project_id,
        test_case_id=case.id,
        automation_key=case.automation_key,
        status=WebwrightRunStatus.running.value,
        output_path=str(output_root),
        started_at=datetime.utcnow(),
    )
    session.add(run)
    case.status = "webwright_running"
    session.add(case)
    session.commit()
    session.refresh(run)

    execution_mode = profile.execution_mode
    webwright_root = profile.webwright_root
    python_path = profile.webwright_python
    base_config = profile.base_config
    model_cfg = profile.model_config or model_config
    config_args = [base_config, model_cfg]
    if profile.model_name:
        config_args.append(f"model.model_name={profile.model_name}")
    if profile.webwright_shell:
        config_args.append(f"environment.shell={profile.webwright_shell}")
    if profile.webwright_step_limit:
        config_args.append(f"agent.step_limit={profile.webwright_step_limit}")
    subprocess_env = profile.subprocess_env()

    cmd = [
        python_path, "-m", "webwright.run.cli",
    ]
    for config_arg in config_args:
        cmd.extend(["-c", config_arg])
    cmd.extend([
        "-t", prompt,
        "--start-url", start_url,
        "--task-id", case.automation_key,
        "-o", str(output_root),
    ])

    await log_streams.publish(job_id, f"[webwright] Starting run for {case.automation_key}")

    try:
        if execution_mode == "wsl":
            inner = " ".join([f"'{c}'" if " " in c else c for c in cmd])
            shell_cmd = ["wsl.exe", "bash", "-lc", f"cd {webwright_root} && source .venv/bin/activate && {inner}"]
            process = await asyncio.create_subprocess_exec(
                *shell_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=webwright_root or None,
                env=subprocess_env,
            )
        else:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=webwright_root or None,
                env=subprocess_env,
            )

        timed_out = False
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=profile.webwright_run_timeout_seconds,
            )
        except asyncio.TimeoutError:
            timed_out = True
            process.kill()
            stdout, stderr = await process.communicate()
        stdout_text = mask_secrets(stdout.decode("utf-8", errors="replace"))
        stderr_text = mask_secrets(stderr.decode("utf-8", errors="replace"))
        if timed_out:
            stderr_text = (stderr_text + "\n" if stderr_text else "") + (
                f"[timeout] Webwright exceeded {profile.webwright_run_timeout_seconds}s; harvesting available artifacts."
            )
        (output_root / "stdout.log").write_text(stdout_text, encoding="utf-8")
        (output_root / "stderr.log").write_text(stderr_text, encoding="utf-8")
        await log_streams.publish(job_id, stdout_text)
        if stderr_text:
            await log_streams.publish(job_id, stderr_text)

        final_script = _find_webwright_artifact(output_root, "final_script.py")
        trajectory = _find_webwright_artifact(output_root, "trajectory.json")

        if not final_script:
            run.status = WebwrightRunStatus.failed.value
            run.error_message = "timeout" if timed_out else classify_error(stderr_text)
            case.status = "webwright_failed"
        else:
            run.status = WebwrightRunStatus.completed.value
            run.final_script_path = str(final_script)
            run.trajectory_path = str(trajectory) if trajectory else None
            case.status = "webwright_completed"

        metadata = {
            "runId": output_root.name,
            "automationKey": case.automation_key,
            "caseId": case.source_case_id,
            "sourceType": case.source_type,
            "startUrl": start_url,
            "status": run.status,
            "startedAt": run.started_at.isoformat() if run.started_at else None,
            "endedAt": datetime.utcnow().isoformat(),
            "artifacts": {
                "finalScript": _relative_artifact(output_root, final_script),
                "trajectory": _relative_artifact(output_root, trajectory),
                "stdout": "stdout.log",
                "stderr": "stderr.log",
            },
            "timedOut": timed_out,
        }
        (output_root / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    except FileNotFoundError as exc:
        run.status = WebwrightRunStatus.failed.value
        run.error_message = "webwright_not_found"
        case.status = "webwright_failed"
        await log_streams.publish(job_id, f"[error] {exc}")

    run.ended_at = datetime.utcnow()
    session.add(run)
    session.add(case)
    session.commit()
    session.refresh(run)
    index_webwright_run_artifacts(session, run)
    return run


async def create_mock_run(session: Session, project_id: str, case: TestCase, job_id: str) -> WebwrightRun:
    """Create a mock Webwright run when CLI is unavailable (dev/demo)."""
    run_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_root = _resolve_output_root() / case.automation_key / f"run_{run_ts}"
    output_root.mkdir(parents=True, exist_ok=True)

    script = f'''from playwright.sync_api import sync_playwright, expect

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("{case.start_url or 'https://example.com'}")
        page.get_by_role("link", name="More information").click()
        expect(page).to_have_url("https://www.iana.org/help/example-domains")
        browser.close()

if __name__ == "__main__":
    run()
'''
    (output_root / "final_script.py").write_text(script, encoding="utf-8")
    (output_root / "trajectory.json").write_text("[]", encoding="utf-8")
    (output_root / "stdout.log").write_text("[mock] generated sample script\n", encoding="utf-8")
    (output_root / "stderr.log").write_text("", encoding="utf-8")

    run = WebwrightRun(
        id=new_id("ww"),
        project_id=project_id,
        test_case_id=case.id,
        automation_key=case.automation_key,
        status=WebwrightRunStatus.completed.value,
        output_path=str(output_root),
        final_script_path=str(output_root / "final_script.py"),
        trajectory_path=str(output_root / "trajectory.json"),
        started_at=datetime.utcnow(),
        ended_at=datetime.utcnow(),
    )
    metadata = {
        "runId": output_root.name,
        "automationKey": case.automation_key,
        "caseId": case.source_case_id,
        "sourceType": case.source_type,
        "startUrl": case.start_url or "https://example.com",
        "status": run.status,
        "startedAt": run.started_at.isoformat() if run.started_at else None,
        "endedAt": run.ended_at.isoformat() if run.ended_at else None,
        "artifacts": {
            "finalScript": "final_script.py",
            "trajectory": "trajectory.json",
            "stdout": "stdout.log",
            "stderr": "stderr.log",
        },
    }
    (output_root / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    case.status = "webwright_completed"
    session.add(run)
    session.add(case)
    session.commit()
    session.refresh(run)
    index_webwright_run_artifacts(session, run)
    await log_streams.publish(job_id, f"[mock] Created sample Webwright run for {case.automation_key}")
    return run
