#!/usr/bin/env python3
import argparse
import hashlib
import json
import stat
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "liuhui-badminton-coach"
ARCHIVE_ROOT = "liuhui-badminton-coach"
FIXED_TIMESTAMP = (2026, 1, 1, 0, 0, 0)
SKIPPED_NAMES = {".DS_Store", "__pycache__"}


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
    if not normalized:
        raise ValueError("Version cannot be empty")
    return f"liuhui-badminton-coach-{normalized}.zip"


def package_skill(version, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / archive_name(version)
    files = release_files()
    if not files:
        raise ValueError("Skill directory contains no files")

    with zipfile.ZipFile(
        archive_path,
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

    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    checksum_path = output_dir / "SHA256SUMS.txt"
    checksum_path.write_text(
        f"{digest}  {archive_path.name}\n",
        encoding="utf-8",
    )
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
