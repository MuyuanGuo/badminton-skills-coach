#!/usr/bin/env python3
"""Generate a deterministic CycloneDX file-level SBOM for a Skill archive."""

import argparse
import hashlib
import json
import re
import subprocess
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_URL = "https://github.com/MuyuanGuo/badminton-skills-coach"
VERSION_PATTERN = re.compile(r"v?\d+\.\d+\.\d+(?:-dev\.\d+)?")


def sha256_bytes(content):
    return hashlib.sha256(content).hexdigest()


def append_checksum(checksum_path, artifact_path):
    checksum_path = Path(checksum_path)
    artifact_path = Path(artifact_path)
    if not artifact_path.is_file():
        raise ValueError(f"Release artifact does not exist: {artifact_path}")
    existing = (
        checksum_path.read_text(encoding="utf-8")
        if checksum_path.exists()
        else ""
    )
    if existing and not existing.endswith("\n"):
        existing += "\n"
    checksum_path.parent.mkdir(parents=True, exist_ok=True)
    checksum_path.write_text(
        f"{existing}{sha256_bytes(artifact_path.read_bytes())}  {artifact_path.name}\n",
        encoding="utf-8",
    )


def source_timestamp(source_commit):
    if not source_commit:
        return "2026-01-01T00:00:00Z"
    completed = subprocess.run(
        ["git", "show", "-s", "--format=%cI", source_commit],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    parsed = datetime.fromisoformat(completed.stdout.strip().replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_sbom(archive_path, version, source_commit=None):
    archive_path = Path(archive_path)
    normalized_version = version.strip().removeprefix("v")
    if not VERSION_PATTERN.fullmatch(version.strip()):
        raise ValueError("Version must look like 1.2.0, v1.2.0, or 1.3.0-dev.1")
    if not archive_path.is_file():
        raise ValueError(f"Release archive does not exist: {archive_path}")

    archive_digest = sha256_bytes(archive_path.read_bytes())
    package_ref = f"pkg:generic/liuhui-badminton-coach@{normalized_version}"
    components = []
    with zipfile.ZipFile(archive_path) as archive:
        for name in sorted(archive.namelist()):
            if name.endswith("/"):
                continue
            content = archive.read(name)
            components.append(
                {
                    "type": "file",
                    "bom-ref": f"file:{name}",
                    "name": name,
                    "hashes": [{"alg": "SHA-256", "content": sha256_bytes(content)}],
                }
            )

    serial = uuid.uuid5(uuid.NAMESPACE_URL, f"{REPOSITORY_URL}:{archive_digest}")
    properties = [
        {"name": "source.repository", "value": REPOSITORY_URL},
        {"name": "archive.sha256", "value": archive_digest},
    ]
    if source_commit:
        properties.append({"name": "source.commit", "value": source_commit})

    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{serial}",
        "version": 1,
        "metadata": {
            "timestamp": source_timestamp(source_commit),
            "tools": {
                "components": [
                    {
                        "type": "application",
                        "name": "generate_release_sbom.py",
                        "version": "1",
                    }
                ]
            },
            "component": {
                "type": "application",
                "bom-ref": package_ref,
                "name": "liuhui-badminton-coach",
                "version": normalized_version,
                "hashes": [{"alg": "SHA-256", "content": archive_digest}],
                "externalReferences": [
                    {"type": "vcs", "url": REPOSITORY_URL},
                    {
                        "type": "distribution",
                        "url": f"{REPOSITORY_URL}/releases/tag/v{normalized_version}",
                    },
                ],
                "properties": properties,
            },
        },
        "components": components,
        "dependencies": [
            {
                "ref": package_ref,
                "dependsOn": [component["bom-ref"] for component in components],
            }
        ],
    }


def main():
    parser = argparse.ArgumentParser(
        description="Generate a CycloneDX 1.6 SBOM for a packaged Skill archive."
    )
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-commit")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checksum-file", type=Path)
    args = parser.parse_args()
    try:
        sbom = build_sbom(args.archive, args.version, args.source_commit)
    except (OSError, ValueError, subprocess.CalledProcessError, zipfile.BadZipFile) as error:
        raise SystemExit(str(error)) from error
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(sbom, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if args.checksum_file:
        append_checksum(args.checksum_file, args.output)
    print(args.output)


if __name__ == "__main__":
    main()
