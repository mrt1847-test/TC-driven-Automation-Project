from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runner.mapping_loader import load_cases, load_env_config, project_root
from runner.result_writer import parse_pytest_output, write_results


def _subprocess_env(env: str, run_id: str, browser: str) -> dict[str, str]:
    env_config = load_env_config(env)
    artifact_dir = project_root() / "artifacts" / "runs" / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    merged = {
        **os.environ,
        "TC_ENV": env,
        "TC_RUN_ID": run_id,
        "TC_BROWSER": browser,
        "TC_ARTIFACT_DIR": str(artifact_dir),
    }
    base_url = env_config.get("baseUrl") or env_config.get("base_url")
    if base_url and not merged.get("TC_BASE_URL"):
        merged["TC_BASE_URL"] = str(base_url)
    if os.environ.get("TC_STUDIO_PLAYWRIGHT_BROWSERS_PATH"):
        merged["PLAYWRIGHT_BROWSERS_PATH"] = os.environ["TC_STUDIO_PLAYWRIGHT_BROWSERS_PATH"]
    return merged


def _parse_case_status(combined: str, test_file: str, test_fn: str, returncode: int) -> str:
    node = f"{test_file}::{test_fn}"
    if f"{node} PASSED" in combined:
        return "passed"
    if f"{node} FAILED" in combined or f"{node} ERROR" in combined:
        return "failed"
    if returncode == 0:
        return "passed"
    return "failed"


def _artifact_dir(run_id: str) -> Path:
    path = project_root() / "artifacts" / "runs" / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_node_name(test_file: str, test_fn: str) -> str:
    node_id = f"{test_file}::{test_fn}".replace("\\", "/")
    return node_id.replace("::", "__").replace("/", "_").replace("\\", "_")


def _relative_artifact(path: Path | None) -> str | None:
    if not path:
        return None
    try:
        return path.relative_to(project_root()).as_posix()
    except ValueError:
        return str(path)


def _case_artifacts(run_id: str, test_file: str, test_fn: str) -> dict[str, str | None]:
    out_dir = _artifact_dir(run_id)
    safe_name = _safe_node_name(test_file, test_fn)
    screenshot = out_dir / f"{safe_name}.png"
    trace = out_dir / f"{safe_name}.zip"
    videos_dir = out_dir / "videos"
    video = None
    if videos_dir.exists():
        videos = sorted(videos_dir.glob("*.webm"))
        if len(videos) == 1:
            video = videos[0]
    return {
        "screenshot": _relative_artifact(screenshot if screenshot.exists() else None),
        "trace": _relative_artifact(trace if trace.exists() else None),
        "video": _relative_artifact(video),
    }


def _write_pytest_logs(run_id: str, stdout: str, stderr: str) -> None:
    out_dir = _artifact_dir(run_id)
    (out_dir / "stdout.log").write_text(stdout, encoding="utf-8")
    (out_dir / "stderr.log").write_text(stderr, encoding="utf-8")


def run_pytest(case_keys: list[str], env: str, browser: str, headed: bool, run_id: str) -> Path:
    started_at = datetime.now(timezone.utc).isoformat()
    cases = load_cases()
    if case_keys:
        cases = [c for c in cases if c.get("automationKey") in case_keys]
    if not cases:
        return write_results(run_id, env, browser, [], started_at=started_at, ended_at=datetime.now(timezone.utc).isoformat())

    test_paths: list[str] = []
    for case in cases:
        rel = case.get("testFile", "")
        path = project_root() / rel
        if path.exists():
            test_paths.append(str(path))

    if not test_paths:
        return write_results(run_id, env, browser, [], started_at=started_at, ended_at=datetime.now(timezone.utc).isoformat())

    cmd = [sys.executable, "-m", "pytest", *test_paths, f"--browser={browser}"]
    if headed:
        cmd.append("--headed")

    env_vars = _subprocess_env(env, run_id, browser)
    if headed:
        env_vars["TC_HEADLESS"] = "false"
    else:
        env_vars["TC_HEADLESS"] = "true"

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(project_root()),
        env=env_vars,
    )
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    _write_pytest_logs(run_id, proc.stdout or "", proc.stderr or "")

    results: list[dict[str, Any]] = []
    for case in cases:
        test_file = case.get("testFile", "")
        test_fn = case.get("testFunction") or f"test_{case.get('automationKey', '')}"
        status = _parse_case_status(combined, test_file, test_fn, proc.returncode)
        error = None
        if status != "passed":
            match = re.search(rf"{re.escape(test_file)}::{re.escape(test_fn)}.*?(\\n=+.*)", combined, re.DOTALL)
            error = match.group(0).strip() if match else combined.strip() or "pytest failed"
        results.append(parse_pytest_output(
            proc.stdout,
            case,
            status,
            error,
            artifacts=_case_artifacts(run_id, test_file, test_fn),
        ))

    ended_at = datetime.now(timezone.utc).isoformat()
    metadata = {
        "command": cmd,
        "returnCode": proc.returncode,
        "stdoutPath": f"artifacts/runs/{run_id}/stdout.log",
        "stderrPath": f"artifacts/runs/{run_id}/stderr.log",
    }
    return write_results(run_id, env, browser, results, pytest=metadata, started_at=started_at, ended_at=ended_at)
