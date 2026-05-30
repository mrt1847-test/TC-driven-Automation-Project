from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from runner.mapping_loader import load_cases, project_root
from runner.result_writer import parse_pytest_output, write_results


def run_pytest(case_keys: list[str], env: str, browser: str, headed: bool, run_id: str) -> Path:
    cases = load_cases()
    if case_keys:
        cases = [c for c in cases if c.get("automationKey") in case_keys]

    results: list[dict[str, Any]] = []
    for case in cases:
        test_path = project_root() / case.get("testFile", "")
        cmd = [
            sys.executable, "-m", "pytest", str(test_path),
            f"--browser={browser}",
        ]
        if not headed:
            cmd.append("--headed=false")
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(project_root()),
            env={**__import__("os").environ, **env_vars},
        )
        status = "passed" if proc.returncode == 0 else "failed"
        error = proc.stderr.strip() or proc.stdout.strip() if proc.returncode != 0 else None
        results.append(parse_pytest_output(proc.stdout, case, status, error))

    return write_results(run_id, env, browser, results)
