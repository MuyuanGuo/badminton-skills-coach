#!/usr/bin/env python3
"""Bind full-profile page evidence to the exact BVID set on each page."""

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from project_artifacts import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE = (
    ROOT / "data" / "snapshots" / "bilibili_profile_full_archive.json"
)
BVID_PATTERN = re.compile(r"BV[0-9A-Za-z]{10}")


def content_hash(bvids):
    return hashlib.sha256("\n".join(sorted(bvids)).encode("utf-8")).hexdigest()


def upgrade(payload):
    coverage = payload.get("coverage") or {}
    pages = payload.get("profile_pages")
    items = payload.get("items")
    if not coverage.get("full_profile_archive"):
        raise ValueError("Archive does not claim complete profile coverage")
    if not isinstance(pages, list) or not pages:
        raise ValueError("Archive has no page evidence")
    if not isinstance(items, list) or not items:
        raise ValueError("Archive has no videos")

    by_page = defaultdict(list)
    for item in items:
        bvid = str(item.get("bvid") or "")
        page = item.get("profile_page")
        if not BVID_PATTERN.fullmatch(bvid) or not isinstance(page, int):
            raise ValueError("Archive item has an invalid BVID or profile_page")
        by_page[page].append(bvid)

    for expected_page, evidence in enumerate(pages, start=1):
        if evidence.get("page") != expected_page:
            raise ValueError("Archive pages are not contiguous")
        bvids = by_page.get(expected_page, [])
        if evidence.get("count") != len(bvids):
            raise ValueError(f"Page {expected_page} count does not match its videos")
        if (
            evidence.get("first_bvid") not in bvids
            or evidence.get("last_bvid") not in bvids
        ):
            raise ValueError(f"Page {expected_page} boundaries do not match")
        capture_hash = str(evidence.get("bvid_sha256") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", capture_hash):
            raise ValueError(f"Page {expected_page} capture hash is invalid")
        evidence["sorted_bvid_sha256"] = content_hash(bvids)

    unique_bvids = {item["bvid"] for item in items}
    if len(unique_bvids) != len(items):
        raise ValueError("Archive contains duplicate BVIDs")
    for key in (
        "profile_reported_video_count",
        "profile_collected_count",
        "profile_unique_videos",
    ):
        if coverage.get(key) != len(items):
            raise ValueError(f"Coverage {key} does not match the archive")
    if coverage.get("profile_pages") != len(pages):
        raise ValueError("Coverage page count does not match page evidence")

    payload["schema_version"] = max(3, int(payload.get("schema_version") or 0))
    coverage["page_content_hash_algorithm"] = "sha256(sorted_bvids_newline_v1)"
    payload["coverage"] = coverage
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", nargs="?", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    payload = json.loads(args.archive.read_text(encoding="utf-8"))
    upgraded = upgrade(payload)
    if not args.check:
        atomic_write_text(
            args.archive,
            json.dumps(upgraded, ensure_ascii=False, indent=2) + "\n",
        )
    print(
        json.dumps(
            {
                "archive": str(args.archive),
                "schema_version": upgraded["schema_version"],
                "pages": len(upgraded["profile_pages"]),
                "videos": len(upgraded["items"]),
                "updated": not args.check,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
