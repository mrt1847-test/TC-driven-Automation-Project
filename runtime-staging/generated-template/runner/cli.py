from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from runner.mapping_loader import case_by_key, load_cases, project_root
from runner.pytest_runner import run_pytest
from runner.result_writer import write_results


def cmd_list_cases(_: argparse.Namespace) -> int:
    for case in load_cases():
        print(f"{case.get('automationKey')}\t{case.get('title')}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    keys: list[str] = []
    if args.case_key:
        keys = args.case_key
    elif not args.all:
        print("Specify --all or --case-key")
        return 1
    path = run_pytest(keys, args.env, args.browser, args.headed, run_id)
    print(f"Results written to {path}")
    return 0


def cmd_rerun_failed(args: argparse.Namespace) -> int:
    results_path = project_root() / "artifacts" / "runs" / args.from_run_id / "results.json"
    if not results_path.exists():
        print("Previous run not found")
        return 1
    data = json.loads(results_path.read_text(encoding="utf-8"))
    failed_keys = [c["automationKey"] for c in data.get("cases", []) if c.get("status") == "failed"]
    if not failed_keys:
        print("No failed cases")
        return 0
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = run_pytest(failed_keys, data.get("env", "stg"), data.get("browser", "chromium"), False, run_id)
    print(f"Rerun results: {path}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    results_path = project_root() / "artifacts" / "runs" / args.run_id / "results.json"
    if not results_path.exists():
        print("Run not found")
        return 1
    if args.target == "testrail-clone":
        from runner.testrail_clone_uploader import upload
        upload(results_path)
    elif args.target == "testrail":
        from runner.testrail_uploader import upload
        upload(results_path)
    elif args.target == "excel":
        from runner.excel_writer import write
        write(results_path)
    elif args.target == "google-sheets":
        from runner.google_sheets_writer import write
        write(results_path)
    else:
        print(f"Unknown target: {args.target}")
        return 1
    print("Export completed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="runner.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    list_p = sub.add_parser("list-cases")
    list_p.set_defaults(func=cmd_list_cases)

    run_p = sub.add_parser("run")
    run_p.add_argument("--env", default="stg")
    run_p.add_argument("--browser", default="chromium")
    run_p.add_argument("--headed", action="store_true")
    run_p.add_argument("--all", action="store_true")
    run_p.add_argument("--case-key", action="append")
    run_p.add_argument("--run-id")
    run_p.set_defaults(func=cmd_run)

    rerun_p = sub.add_parser("rerun-failed")
    rerun_p.add_argument("--from-run-id", required=True)
    rerun_p.add_argument("--run-id")
    rerun_p.set_defaults(func=cmd_rerun_failed)

    export_p = sub.add_parser("export")
    export_p.add_argument("--run-id", required=True)
    export_p.add_argument("--target", required=True)
    export_p.set_defaults(func=cmd_export)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
