#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = ROOT / "data" / "tmp" / "douyin_profile_incremental_snapshot.json"
DEFAULT_REPORT = ROOT / "output" / "douyin-update-report.json"
DEFAULT_STATE = ROOT / "output" / "douyin-monitor-state.json"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def run(command, *, check=True):
    print(f"$ {' '.join(command)}", flush=True)
    completed = subprocess.run(command, cwd=ROOT, check=False, text=True)
    if check and completed.returncode:
        raise subprocess.CalledProcessError(completed.returncode, command)
    return completed.returncode


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def git_has_changes():
    output = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True)
    return bool(output.strip())


def commit_and_push(message, push):
    if not git_has_changes():
        return {"committed": False, "pushed": False}
    run(["git", "add", "."])
    run(["git", "diff", "--cached", "--stat"])
    run(["git", "commit", "-m", message])
    if push:
        run(["git", "push"])
    return {"committed": True, "pushed": push}


def run_snapshot_command(command):
    if not command:
        return None
    return run(command, check=True)


def run_update_check(snapshot, report, apply):
    command = [
        sys.executable,
        "scripts/check_douyin_updates.py",
        "--input",
        str(snapshot.relative_to(ROOT) if snapshot.is_relative_to(ROOT) else snapshot),
        "--report",
        str(report.relative_to(ROOT) if report.is_relative_to(ROOT) else report),
    ]
    if apply:
        command.append("--apply")
    run(command)
    return load_json(report)


def main():
    parser = argparse.ArgumentParser(
        description="Run the Douyin update-monitoring flow around a latest profile snapshot."
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=DEFAULT_SNAPSHOT,
        help="Latest observed Douyin profile snapshot JSON",
    )
    parser.add_argument(
        "--snapshot-command",
        nargs="+",
        help="Optional command that refreshes the snapshot before checking",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT,
        help="Update report path",
    )
    parser.add_argument(
        "--state",
        type=Path,
        default=DEFAULT_STATE,
        help="Monitor state output path",
    )
    parser.add_argument("--apply", action="store_true", help="Apply safe teaching additions to index and queue")
    parser.add_argument("--validate", action="store_true", help="Run project validation after the check")
    parser.add_argument("--commit", action="store_true", help="Commit changes created by --apply")
    parser.add_argument("--push", action="store_true", help="Push after committing")
    parser.add_argument(
        "--commit-message",
        default="Update Douyin teaching queue",
        help="Commit message used with --commit",
    )
    args = parser.parse_args()

    snapshot = args.snapshot if args.snapshot.is_absolute() else ROOT / args.snapshot
    report = args.report if args.report.is_absolute() else ROOT / args.report
    state = args.state if args.state.is_absolute() else ROOT / args.state

    started_at = now_iso()
    status = "ok"
    error = None
    payload = {}

    try:
        run_snapshot_command(args.snapshot_command)
        if not snapshot.exists():
            raise SystemExit(
                f"Snapshot not found: {snapshot}\n"
                "Provide --snapshot or --snapshot-command that writes this file."
            )

        report_payload = run_update_check(snapshot, report, args.apply)
        validation = None
        if args.validate:
            run([sys.executable, "scripts/validate_project.py"])
            validation = {"validate_project": "passed"}

        git_result = None
        if args.commit:
            git_result = commit_and_push(args.commit_message, args.push)

        payload = {
            "report": str(report.relative_to(ROOT) if report.is_relative_to(ROOT) else report),
            "new": report_payload["new"],
            "teaching": report_payload["teaching"],
            "review": report_payload["review"],
            "excluded": report_payload["excluded"],
            "applied": report_payload["applied"],
            "validation": validation,
            "git": git_result,
        }
    except BaseException as exc:
        status = "failed"
        error = str(exc)
        if isinstance(exc, SystemExit) and isinstance(exc.code, int):
            return_code = exc.code
        elif isinstance(exc, subprocess.CalledProcessError):
            return_code = exc.returncode
        else:
            return_code = 1
    else:
        return_code = 0

    state_payload = {
        "started_at": started_at,
        "finished_at": now_iso(),
        "status": status,
        "error": error,
        "snapshot": str(snapshot.relative_to(ROOT) if snapshot.is_relative_to(ROOT) else snapshot),
        **payload,
    }
    write_json(state, state_payload)
    print(json.dumps(state_payload, ensure_ascii=False))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
