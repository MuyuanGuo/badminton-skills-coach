#!/usr/bin/env python3
"""Classify changed paths into documentation, tooling, or quality CI scopes."""

import argparse
from pathlib import PurePosixPath


DOC_EXACT = {"LICENSE", "NOTICE"}
TOOLING_EXACT = {
    ".gitattributes",
    ".gitignore",
    "requirements-dev.txt",
    "requirements-transcription.txt",
    "scripts/generate_release_sbom.py",
    "scripts/package_skill_release.py",
    "scripts/release_inventory.py",
    "scripts/require_successful_validation.py",
}


def normalize_path(path):
    value = str(path).strip()
    while value.startswith("./"):
        value = value[2:]
    return value


def is_documentation(path):
    value = normalize_path(path)
    name = PurePosixPath(value).name
    return (
        value.startswith("docs/")
        or ("/" not in value and name.endswith(".md"))
        or name in DOC_EXACT
        or name.startswith("LICENSE-")
    )


def is_tooling_only(path):
    value = normalize_path(path)
    name = PurePosixPath(value).name
    return (
        value.startswith(".github/")
        or value in TOOLING_EXACT
        or (
            value.startswith("scripts/")
            and name.startswith("test_")
            and value != "scripts/test_answer_context.py"
        )
    )


def classify_paths(paths):
    normalized = [
        normalize_path(path)
        for path in paths
        if str(path).strip()
    ]
    if not normalized:
        raise ValueError("CI scope classification requires at least one path")
    non_docs = [path for path in normalized if not is_documentation(path)]
    return {
        "static": bool(non_docs),
        "artifact": bool(non_docs),
        "quality": any(not is_tooling_only(path) for path in non_docs),
        "docs_only": not non_docs,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()
    try:
        scope = classify_paths(args.paths)
    except ValueError as error:
        parser.error(str(error))
    for key in ("static", "artifact", "quality", "docs_only"):
        print(f"{key}={str(scope[key]).lower()}")


if __name__ == "__main__":
    main()
