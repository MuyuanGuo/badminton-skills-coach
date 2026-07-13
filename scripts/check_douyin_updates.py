#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path

from douyin_pipeline import (
    classify_video,
    compute_status_counts,
    load_classification_rules,
    now_iso,
    write_json,
)


ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "data" / "douyin_video_index.json"
TEACHING_PATH = ROOT / "data" / "douyin_teaching_filtered.json"
QUEUE_PATH = ROOT / "data" / "processing" / "douyin_queue.json"
REPORT_PATH = ROOT / "output" / "douyin-update-report.json"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def extract_video_id(item):
    for key in ("video_id", "aweme_id", "id"):
        value = item.get(key)
        if value:
            return str(value)
    url = str(item.get("url") or "")
    match = re.search(r"/video/(\d+)", url)
    if match:
        return match.group(1)
    return None


def normalize_video(item):
    video_id = extract_video_id(item)
    if not video_id:
        return None
    url = item.get("url") or f"https://www.douyin.com/video/{video_id}"
    title = (
        item.get("title")
        or item.get("desc")
        or item.get("description")
        or item.get("raw_text")
        or ""
    )
    raw_text = item.get("raw_text") or title
    return {
        "video_id": str(video_id),
        "url": str(url),
        "title": str(title).strip(),
        "teaching_candidate": item.get("teaching_candidate", "unknown"),
        "raw_text": str(raw_text).strip(),
    }


def load_observed(path):
    payload = load_json(path)
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("videos") or payload.get("items") or payload.get("aweme_list") or []
    else:
        raise SystemExit(f"Unsupported input JSON shape: {path}")

    videos = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        video = normalize_video(row)
        if not video or video["video_id"] in seen:
            continue
        seen.add(video["video_id"])
        videos.append(video)
    return videos


def known_ids():
    ids = set()
    for path, key in ((INDEX_PATH, "videos"), (TEACHING_PATH, "videos"), (QUEUE_PATH, "items")):
        if not path.exists():
            continue
        data = load_json(path)
        for item in data.get(key, []):
            ids.add(str(item["video_id"]))
    return ids


def append_to_index(new_videos):
    index = load_json(INDEX_PATH)
    existing = {str(item["video_id"]) for item in index["videos"]}
    inserts = [video for video in new_videos if video["video_id"] not in existing]
    if not inserts:
        return 0
    index["videos"] = inserts + index["videos"]
    index["collected_at"] = now_iso()
    index["collected_unique_links"] = len(index["videos"])
    index["note"] = "Updated by scripts/check_douyin_updates.py from observed homepage metadata."
    write_json(INDEX_PATH, index)
    return len(inserts)


def append_to_teaching_and_queue(classified):
    teaching = load_json(TEACHING_PATH)
    queue = load_json(QUEUE_PATH)
    teaching_existing = {str(item["video_id"]) for item in teaching["videos"]}
    queue_existing = {str(item["video_id"]) for item in queue["items"]}

    teaching_inserts = [
        item for item in classified
        if item["decision"] == "保留：教学" and item["video_id"] not in teaching_existing
    ]
    queue_inserts = [
        {
            "video_id": item["video_id"],
            "url": item["url"],
            "title": item["title"],
            "category": item["primary_category"],
            "tags": item["tags"],
            "status": "classified_teaching",
            "classification_decision": item["decision"],
            "classified_at": now_iso(),
            "media_path": None,
            "duration_seconds": None,
            "attempts": 0,
            "error": None,
        }
        for item in teaching_inserts
        if item["video_id"] not in queue_existing
    ]

    if classified:
        if teaching_inserts:
            teaching["videos"] = teaching_inserts + teaching["videos"]
        teaching["generated_at"] = now_iso()
        teaching["counts"]["total"] = teaching["counts"].get("total", 0) + len(classified)
        teaching["counts"]["kept_teaching"] = len(teaching["videos"])
        teaching["counts"]["review"] = teaching["counts"].get("review", 0) + sum(
            item["decision"].startswith("待复核") for item in classified
        )
        teaching["counts"]["excluded_ads"] = teaching["counts"].get("excluded_ads", 0) + sum(
            item["decision"] == "排除：广告/器材推广" for item in classified
        )
        teaching["counts"]["excluded_non_teaching"] = teaching["counts"].get("excluded_non_teaching", 0) + sum(
            item["decision"] == "排除：非教学" for item in classified
        )
        write_json(TEACHING_PATH, teaching)

    if queue_inserts:
        queue["items"] = queue_inserts + queue["items"]
        queue["counts"] = compute_status_counts(queue["items"])
        queue["updated_at"] = now_iso()
        write_json(QUEUE_PATH, queue)

    return len(teaching_inserts), len(queue_inserts)


def main():
    parser = argparse.ArgumentParser(
        description="Compare observed Douyin homepage videos with the local index and report new candidates."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "data" / "tmp" / "douyin_profile_latest.json",
        help="Observed homepage JSON with a videos/items list",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=REPORT_PATH,
        help="Where to write the update report",
    )
    parser.add_argument("--apply", action="store_true", help="Append new teaching videos to the local index, teaching list, and queue")
    parser.add_argument(
        "--rules",
        type=Path,
        default=ROOT / "config" / "douyin_classification_rules.json",
        help="Classification rules JSON",
    )
    args = parser.parse_args()

    input_path = args.input if args.input.is_absolute() else ROOT / args.input
    if not input_path.exists():
        raise SystemExit(
            f"Input snapshot not found: {input_path}\n"
            "Export the latest Douyin profile items to JSON first, then rerun this script."
        )

    observed = load_observed(input_path)
    existing_ids = known_ids()
    new_videos = [video for video in observed if video["video_id"] not in existing_ids]
    rules_path = args.rules if args.rules.is_absolute() else ROOT / args.rules
    rules = load_classification_rules(rules_path)
    classified = [classify_video(video, rules) for video in new_videos]
    teaching = [item for item in classified if item["decision"] == "保留：教学"]
    review = [item for item in classified if item["decision"].startswith("待复核")]
    excluded = [item for item in classified if item["decision"].startswith("排除")]

    applied = None
    if args.apply:
        index_count = append_to_index(new_videos)
        teaching_count, queue_count = append_to_teaching_and_queue(classified)
        applied = {
            "index_added": index_count,
            "teaching_added": teaching_count,
            "queue_added": queue_count,
        }

    report = {
        "generated_at": now_iso(),
        "input": str(input_path.relative_to(ROOT) if input_path.is_relative_to(ROOT) else input_path),
        "observed": len(observed),
        "new": len(new_videos),
        "teaching": len(teaching),
        "review": len(review),
        "excluded": len(excluded),
        "applied": applied,
        "new_videos": classified,
    }
    report_path = args.report if args.report.is_absolute() else ROOT / args.report
    write_json(report_path, report)
    print(json.dumps({
        "report": str(report_path),
        "observed": report["observed"],
        "new": report["new"],
        "teaching": report["teaching"],
        "review": report["review"],
        "excluded": report["excluded"],
        "applied": applied,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
