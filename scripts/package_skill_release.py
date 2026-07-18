#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
import zipfile
from pathlib import Path

from project_artifacts import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "liuhui-badminton-coach"
ARCHIVE_ROOT = "liuhui-badminton-coach"
FIXED_TIMESTAMP = (2026, 1, 1, 0, 0, 0)
SKIPPED_NAMES = {".DS_Store", "__pycache__"}
VERSION_PATTERN = re.compile(r"v?\d+\.\d+\.\d+(?:-dev\.\d+)?")
FEEDBACK_RULES_PATH = ROOT / "config" / "feedback_rules.json"


def release_files():
    return [
        path
        for path in sorted(SKILL_ROOT.rglob("*"))
        if path.is_file()
        and not any(part in SKIPPED_NAMES for part in path.relative_to(SKILL_ROOT).parts)
        and path.suffix not in {".pyc", ".pyo"}
    ]


def archive_name(version):
    normalized = version.strip()
    if not VERSION_PATTERN.fullmatch(normalized):
        raise ValueError(
            "Version must look like 1.0.0, v1.0.0, or 1.1.0-dev.3"
        )
    return f"liuhui-badminton-coach-{normalized}.zip"


def package_skill(version, output_dir):
    normalized_version = version.strip().removeprefix("v")
    version_metadata = json.loads(FEEDBACK_RULES_PATH.read_text(encoding="utf-8"))
    allowed_versions = {
        version_metadata["skill_version"],
        version_metadata["stable_version"],
    }
    if normalized_version not in allowed_versions:
        raise ValueError(
            "Package version does not match the configured development or stable Skill version"
        )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / archive_name(version)
    files = release_files()
    if not files:
        raise ValueError("Skill directory contains no files")

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{archive_path.name}.", suffix=".tmp", dir=output_dir
    )
    os.close(descriptor)
    try:
        with zipfile.ZipFile(
            temporary_name,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for path in files:
                relative = path.relative_to(SKILL_ROOT)
                info = zipfile.ZipInfo(
                    f"{ARCHIVE_ROOT}/{relative.as_posix()}",
                    date_time=FIXED_TIMESTAMP,
                )
                info.compress_type = zipfile.ZIP_DEFLATED
                mode = path.stat().st_mode
                permissions = 0o755 if mode & stat.S_IXUSR else 0o644
                info.external_attr = permissions << 16
                archive.writestr(info, path.read_bytes(), compresslevel=9)
        with zipfile.ZipFile(temporary_name) as archive:
            corrupt_member = archive.testzip()
            if corrupt_member:
                raise zipfile.BadZipFile(
                    f"Release archive contains a corrupt member: {corrupt_member}"
                )
        os.replace(temporary_name, archive_path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)

    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    checksum_path = output_dir / "SHA256SUMS.txt"
    atomic_write_text(checksum_path, f"{digest}  {archive_path.name}\n")
    return {
        "archive": str(archive_path),
        "checksum_file": str(checksum_path),
        "sha256": digest,
        "file_count": len(files),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Create a deterministic, install-ready Liu Hui badminton Skill archive."
    )
    parser.add_argument("--version", required=True)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    try:
        result = package_skill(args.version, args.output_dir)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
