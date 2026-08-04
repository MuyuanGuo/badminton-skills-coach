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

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None
    import msvcrt


SOURCE_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = [
    "SKILL.md",
    "scripts/doctor.py",
    "scripts/runtime_store.py",
    "references/runtime-store.sqlite3",
]


def default_destination():
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    return codex_home / "skills" / "liuhui-badminton-coach"


def validate_source(source):
    missing = [path for path in REQUIRED_FILES if not (source / path).is_file()]
    if missing:
        raise ValueError("Skill source is incomplete: " + ", ".join(missing))


def source_build_id(source):
    manifest_path = source / "references" / "build-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Skill source has no readable build manifest") from error
    build_id = str(manifest.get("build_id") or "")
    if not build_id:
        raise ValueError("Skill source build manifest has no build_id")
    return build_id


class installation_lock:
    def __init__(self, destination):
        self.destination = Path(destination)
        self.handle = None

    def __enter__(self):
        lock_path = (
            self.destination.parent
            / f".{self.destination.name}.install.lock"
        )
        self.handle = lock_path.open("a+", encoding="utf-8")
        try:
            if fcntl is not None:
                fcntl.flock(
                    self.handle.fileno(),
                    fcntl.LOCK_EX | fcntl.LOCK_NB,
                )
            else:
                self.handle.seek(0)
                self.handle.write("0")
                self.handle.flush()
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
        except (BlockingIOError, OSError) as error:
            self.handle.close()
            self.handle = None
            raise ValueError(
                f"Another install is already updating {self.destination}"
            ) from error
        return self

    def __exit__(self, *_exc):
        if self.handle is not None:
            self.handle.close()
            self.handle = None


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


def install_skill(
    source=SOURCE_ROOT,
    destination=None,
    dry_run=False,
    expected_build_id=None,
):
    source = Path(source).resolve()
    destination = Path(destination or default_destination()).expanduser().resolve()
    validate_source(source)
    source_id = source_build_id(source)
    if expected_build_id and source_id != expected_build_id:
        raise ValueError(
            "Skill source build_id changed after validation: "
            f"expected {expected_build_id}, found {source_id}"
        )
    if source == destination:
        raise ValueError("Source is already the installed destination")
    if dry_run:
        doctor = run_doctor(source)
        if expected_build_id and doctor["version"]["build_id"] != expected_build_id:
            raise ValueError("Doctor build_id does not match the validated build")
        return {
            "status": "dry_run",
            "source": str(source),
            "destination": str(destination),
            "build_id": source_id,
            "doctor": doctor["summary"],
        }

    destination.parent.mkdir(parents=True, exist_ok=True)
    with installation_lock(destination):
        staging_parent = Path(
            tempfile.mkdtemp(prefix=".liuhui-install-", dir=destination.parent)
        )
        staged = staging_parent / destination.name
        backup = (
            destination.parent
            / f".{destination.name}.backup-{uuid.uuid4().hex[:10]}"
        )
        destination_moved = False
        committed = False
        try:
            shutil.copytree(
                source,
                staged,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
            )
            doctor = run_doctor(staged)
            if doctor["version"]["build_id"] != source_id:
                raise ValueError("Staged Skill build_id changed while copying")
            if expected_build_id and doctor["version"]["build_id"] != expected_build_id:
                raise ValueError("Staged Skill does not match the validated build")
            if destination.exists():
                os.replace(destination, backup)
                destination_moved = True
            os.replace(staged, destination)
            committed = True
            return {
                "status": "installed",
                "source": str(source),
                "destination": str(destination),
                "build_id": source_id,
                "doctor": doctor["summary"],
                "stale_files_removed": destination_moved,
            }
        except BaseException:
            if (
                not committed
                and destination_moved
                and backup.exists()
                and not destination.exists()
            ):
                os.replace(backup, destination)
            raise
        finally:
            if committed and destination_moved:
                shutil.rmtree(backup, ignore_errors=True)
            shutil.rmtree(staging_parent, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(
        description="Atomically install or replace the Liu Hui badminton Skill."
    )
    parser.add_argument("--source", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--expected-build-id")
    args = parser.parse_args()
    try:
        result = install_skill(
            args.source,
            args.destination,
            args.dry_run,
            args.expected_build_id,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
