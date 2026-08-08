#!/usr/bin/env python3
"""Require a stable release tag to match every packaged version source."""

import argparse
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TAG_PATTERN = re.compile(r"v(\d+\.\d+\.\d+)")
PROJECT_RULES = Path("config/feedback_rules.json")
SKILL_RULES = Path(
    "skills/liuhui-badminton-coach/references/feedback-rules.json"
)


def validate_release_metadata(tag, root=ROOT):
    match = TAG_PATTERN.fullmatch(tag)
    if not match:
        raise ValueError("Release tag must use vMAJOR.MINOR.PATCH")
    version = match.group(1)
    root = Path(root)
    project = json.loads((root / PROJECT_RULES).read_text(encoding="utf-8"))
    skill = json.loads((root / SKILL_RULES).read_text(encoding="utf-8"))
    if project != skill:
        raise ValueError("Project and packaged Skill version metadata differ")
    if project.get("channel") != "stable":
        raise ValueError("A stable release tag requires stable-channel metadata")
    if {
        project.get("skill_version"),
        project.get("stable_version"),
    } != {version}:
        raise ValueError("Release tag does not match the configured stable version")
    return {
        "tag": tag,
        "version": version,
        "channel": "stable",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    try:
        result = validate_release_metadata(args.tag)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
