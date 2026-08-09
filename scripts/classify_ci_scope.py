#!/usr/bin/env python3
"""Classify changed paths into documentation, tooling, or quality CI scopes."""

import argparse
from pathlib import PurePosixPath


DOC_EXACT = {"LICENSE", "NOTICE"}
VALIDATION_WORKFLOW = ".github/workflows/validate.yml"
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
ARTIFACT_TOOLING_EXACT = {
    ".gitattributes",
    "requirements-dev.txt",
    "requirements-transcription.txt",
    "scripts/generate_release_sbom.py",
    "scripts/package_skill_release.py",
    "scripts/release_inventory.py",
}
ARTIFACT_TEST_FILES = {
    "test_build_reproducibility.py",
    "test_knowledge_graph_html.py",
    "test_media_assets.py",
    "test_project_artifacts.py",
    "test_project_site.py",
    "test_release_package.py",
    "test_repository_links.py",
    "test_skill_portability.py",
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
        (value.startswith(".github/") and value != VALIDATION_WORKFLOW)
        or value in TOOLING_EXACT
        or (
            value.startswith("scripts/")
            and name.startswith("test_")
            and value != "scripts/test_answer_context.py"
        )
    )


def is_artifact_affecting(path):
    value = normalize_path(path)
    name = PurePosixPath(value).name
    if value == VALIDATION_WORKFLOW or value in ARTIFACT_TOOLING_EXACT:
        return True
    if value.startswith("scripts/") and name in ARTIFACT_TEST_FILES:
        return True
    if is_documentation(value) or is_tooling_only(value):
        return False
    # The answer-context regression file is routed to its dedicated quality
    # shards; changing the test itself does not change a packaged artifact.
    if value == "scripts/test_answer_context.py":
        return False
    return True


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
        "artifact": any(is_artifact_affecting(path) for path in non_docs),
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
