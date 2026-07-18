#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = ["SKILL.md", "scripts/doctor.py", "references/knowledge-base.json"]


def default_destination():
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    return codex_home / "skills" / "liuhui-badminton-coach"


def validate_source(source):
    missing = [path for path in REQUIRED_FILES if not (source / path).is_file()]
    if missing:
        raise ValueError("Skill source is incomplete: " + ", ".join(missing))


def run_doctor(skill_root):
    completed = subprocess.run(
        [
            sys.executable,
            str(skill_root / "scripts" / "doctor.py"),
            "--skill-root",
            str(skill_root),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise ValueError("Staged Skill failed doctor checks:\n" + completed.stdout + completed.stderr)
    return json.loads(completed.stdout)


def install_skill(source=SOURCE_ROOT, destination=None, dry_run=False):
    source = Path(source).resolve()
    destination = Path(destination or default_destination()).expanduser().resolve()
    validate_source(source)
    if source == destination:
        raise ValueError("Source is already the installed destination")
    if dry_run:
        return {
            "status": "dry_run",
            "source": str(source),
            "destination": str(destination),
            "doctor": run_doctor(source)["summary"],
        }

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging_parent = Path(
        tempfile.mkdtemp(prefix=".liuhui-install-", dir=destination.parent)
    )
    staged = staging_parent / destination.name
    backup = destination.parent / f".{destination.name}.backup-{uuid.uuid4().hex[:10]}"
    destination_moved = False
    try:
        shutil.copytree(
            source,
            staged,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
        )
        doctor = run_doctor(staged)
        if destination.exists():
            os.replace(destination, backup)
            destination_moved = True
        os.replace(staged, destination)
        if destination_moved:
            shutil.rmtree(backup, ignore_errors=True)
        return {
            "status": "installed",
            "source": str(source),
            "destination": str(destination),
            "doctor": doctor["summary"],
            "stale_files_removed": destination_moved,
        }
    except Exception:
        if destination_moved and backup.exists() and not destination.exists():
            os.replace(backup, destination)
        raise
    finally:
        shutil.rmtree(staging_parent, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(
        description="Atomically install or replace the Liu Hui badminton Skill."
    )
    parser.add_argument("--source", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        result = install_skill(args.source, args.destination, args.dry_run)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
