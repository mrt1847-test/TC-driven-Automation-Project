from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from runner.mapping_loader import load_cases, project_root
from runner.result_writer import parse_pytest_output, write_results


def _subprocess_env(env: str) -> dict[str, str]:
    merged = {**os.environ, "TC_ENV": env}
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


def run_pytest(case_keys: list[str], env: str, browser: str, headed: bool, run_id: str) -> Path:
    cases = load_cases()
    if case_keys:
        cases = [c for c in cases if c.get("automationKey") in case_keys]
    if not cases:
        return write_results(run_id, env, browser, [])

    test_paths: list[str] = []
    for case in cases:
        rel = case.get("testFile", "")
        path = project_root() / rel
        if path.exists():
            test_paths.append(str(path))

    if not test_paths:
        return write_results(run_id, env, browser, [])

    cmd = [sys.executable, "-m", "pytest", *test_paths, f"--browser={browser}"]
    if not headed:
        cmd.append("--headed=false")

    env_vars = _subprocess_env(env)
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

    results: list[dict[str, Any]] = []
    for case in cases:
        test_file = case.get("testFile", "")
        test_fn = case.get("testFunction") or f"test_{case.get('automationKey', '')}"
        status = _parse_case_status(combined, test_file, test_fn, proc.returncode)
        error = None
        if status != "passed":
            match = re.search(rf"{re.escape(test_file)}::{re.escape(test_fn)}.*?(\\n=+.*)", combined, re.DOTALL)
            error = match.group(0).strip() if match else combined.strip() or "pytest failed"
        results.append(parse_pytest_output(proc.stdout, case, status, error))

    return write_results(run_id, env, browser, results)
