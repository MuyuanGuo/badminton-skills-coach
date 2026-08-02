#!/usr/bin/env python3
"""Check canonical source links, with optional non-blocking network sampling."""

import argparse
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from project_artifacts import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "data" / "douyin_video_index.json"
BILIBILI_INDEX_PATH = ROOT / "data" / "bilibili_video_index.json"
OUTPUT_PATH = ROOT / "output" / "video-link-health.json"


def syntax_check(videos):
    invalid = []
    for video in videos:
        bvid = str(video.get("bvid") or "")
        if bvid:
            evidence_id = str(video.get("video_id") or "")
            expected = f"https://www.bilibili.com/video/{bvid}/"
            valid = (
                evidence_id == f"bilibili:{bvid}"
                and re.fullmatch(r"BV[0-9A-Za-z]{10}", bvid)
                and video.get("url") == expected
            )
            identifier = evidence_id or bvid
        else:
            identifier = str(video.get("video_id", ""))
            expected = f"https://www.douyin.com/video/{identifier}"
            valid = (
                identifier.isdigit()
                and 18 <= len(identifier) <= 20
                and video.get("url") == expected
            )
        if not valid:
            invalid.append(identifier or "missing")
    return sorted(set(invalid))


def deterministic_sample(videos, size):
    if size >= len(videos):
        return videos
    if size == 1:
        return videos[:1]
    indices = [round(index * (len(videos) - 1) / (size - 1)) for index in range(size)]
    return [videos[index] for index in dict.fromkeys(indices)]


def fetch_status(url, timeout):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 BadmintonSkillsCoachLinkCheck/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return {
                "reachable": response.status < 500,
                "http_status": response.status,
                "final_url": response.geturl(),
                "error": None,
            }
    except urllib.error.HTTPError as error:
        return {
            "reachable": error.code < 500,
            "http_status": error.code,
            "final_url": error.geturl(),
            "error": str(error),
        }
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return {
            "reachable": False,
            "http_status": None,
            "final_url": None,
            "error": str(error),
        }


def build_report(network=False, sample_size=5, timeout=10):
    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    bilibili_index = json.loads(BILIBILI_INDEX_PATH.read_text(encoding="utf-8"))
    videos = index["videos"] + bilibili_index["videos"]
    invalid = syntax_check(videos)
    checks = []
    if network:
        for video in deterministic_sample(videos, sample_size):
            checks.append(
                {
                    "video_id": video["video_id"],
                    "url": video["url"],
                    **fetch_status(video["url"], timeout),
                }
            )
    return {
        "source_collected_at": index.get("collected_at"),
        "source_updated_at": {
            "douyin": index.get("collected_at"),
            "bilibili": bilibili_index.get("updated_at"),
        },
        "source_video_counts": {
            "douyin": len(index["videos"]),
            "bilibili": len(bilibili_index["videos"]),
        },
        "indexed_video_count": len(videos),
        "canonical_syntax_invalid_video_ids": invalid,
        "network_check_requested": network,
        "sample_size": len(checks),
        "network_checks": checks,
        "network_failures": sum(not item["reachable"] for item in checks),
        "interpretation": (
            "Network failures are monitoring signals, not proof that corpus evidence is invalid."
        ),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Validate canonical links and optionally sample live reachability."
    )
    parser.add_argument("--network", action="store_true")
    parser.add_argument("--sample-size", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=10)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    if not 1 <= args.sample_size <= 50:
        raise SystemExit("--sample-size must be between 1 and 50")
    if not 1 <= args.timeout <= 60:
        raise SystemExit("--timeout must be between 1 and 60")
    report = build_report(args.network, args.sample_size, args.timeout)
    atomic_write_text(
        args.output,
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["canonical_syntax_invalid_video_ids"]:
        raise SystemExit("Canonical source link validation failed")


if __name__ == "__main__":
    main()
