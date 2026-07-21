#!/usr/bin/env python3
import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from douyin_pipeline import (
    classify_video,
    commit_json_transaction,
    compute_status_counts,
    load_classification_rules,
    now_iso,
    recover_json_transaction,
    write_json,
)


ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "data" / "douyin_video_index.json"
TEACHING_PATH = ROOT / "data" / "douyin_teaching_filtered.json"
LEDGER_PATH = ROOT / "data" / "douyin_classification_ledger.json"
QUEUE_PATH = ROOT / "data" / "processing" / "douyin_queue.json"
DISCOVERY_STATE_PATH = ROOT / "data" / "processing" / "douyin_discovery_state.json"
TRANSACTION_PATH = ROOT / "data" / "processing" / ".douyin-update-transaction.json"
REPORT_PATH = ROOT / "output" / "douyin-update-report.json"
SOURCE_CONFIG_PATH = ROOT / "config" / "douyin_source.json"


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


def parse_iso_datetime(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Snapshot is missing collected_at")
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("Snapshot collected_at must include a timezone")
    return parsed.astimezone(timezone.utc)


def validate_snapshot_payload(payload, known_count, source_config, current_time=None):
    if not isinstance(payload, dict):
        raise ValueError("Validated snapshots must be JSON objects with metadata")
    profile_url = str(payload.get("profile_url") or "")
    expected_profile_id = source_config["profile_id"]
    match = re.search(r"/user/([^/?#]+)", profile_url)
    observed_profile_id = match.group(1) if match else None
    if observed_profile_id != expected_profile_id:
        raise ValueError(
            "Snapshot profile does not match the configured creator: "
            f"expected {expected_profile_id}, observed {observed_profile_id or 'missing'}"
        )

    videos = payload.get("videos")
    if not isinstance(videos, list):
        raise ValueError("Snapshot videos must be a list")
    declared_count = payload.get("collected_unique_links")
    if declared_count != len(videos):
        raise ValueError(
            "Snapshot collected_unique_links does not match the videos array: "
            f"declared {declared_count}, actual {len(videos)}"
        )

    collected_at = parse_iso_datetime(payload.get("collected_at"))
    now = current_time or datetime.now(timezone.utc)
    age_hours = (now.astimezone(timezone.utc) - collected_at).total_seconds() / 3600
    max_age = source_config["snapshot"]["max_age_hours"]
    if age_hours < -0.25:
        raise ValueError("Snapshot collected_at is unexpectedly in the future")
    if age_hours > max_age:
        raise ValueError(
            f"Snapshot is stale: {age_hours:.1f} hours old; maximum is {max_age}"
        )

    minimum = max(
        source_config["snapshot"]["min_observed_links"],
        int(known_count * source_config["snapshot"]["min_known_coverage_ratio"] + 0.999),
    )
    if len(videos) < minimum:
        raise ValueError(
            f"Snapshot coverage is too low: observed {len(videos)}, required at least {minimum}"
        )
    return {
        "profile_id": observed_profile_id,
        "collected_at": collected_at.isoformat(),
        "age_hours": round(age_hours, 2),
        "observed": len(videos),
        "minimum_required": minimum,
        "known_index_count": known_count,
    }


def known_ids():
    ids = set()
    for path, key in (
        (INDEX_PATH, "videos"),
        (DISCOVERY_STATE_PATH, "items"),
    ):
        if not path.exists():
            continue
        data = load_json(path)
        for item in data.get(key, []):
            ids.add(str(item["video_id"]))
    return ids


def discovery_status(decision):
    if decision == "保留：教学":
        return "classified_teaching"
    if decision.startswith("待复核"):
        return "review_pending"
    if decision == "排除：广告/器材推广":
        return "excluded_ad"
    return "excluded_non_teaching"


def load_discovery_state(index_count):
    if DISCOVERY_STATE_PATH.exists():
        return load_json(DISCOVERY_STATE_PATH)
    return {
        "version": 1,
        "created_at": now_iso(),
        "updated_at": None,
        "baseline_index_count": index_count,
        "counts": {},
        "items": [],
    }


def build_apply_payloads(new_videos, classified):
    applied_at = now_iso()
    rules_identity = load_classification_rules()["_rules_identity"]
    classified = [
        {
            **item,
            "classification_rules_version": item.get(
                "classification_rules_version", rules_identity["version"]
            ),
            "classification_rules_hash": item.get(
                "classification_rules_hash", rules_identity["sha256"]
            ),
        }
        for item in classified
    ]
    index = load_json(INDEX_PATH)
    teaching = load_json(TEACHING_PATH)
    ledger = load_json(LEDGER_PATH)
    queue = load_json(QUEUE_PATH)
    discovery = load_discovery_state(len(index["videos"]))

    existing = {str(item["video_id"]) for item in index["videos"]}
    inserts = [video for video in new_videos if video["video_id"] not in existing]
    index["videos"] = inserts + index["videos"]
    index["collected_at"] = applied_at
    index["collected_unique_links"] = len(index["videos"])
    index["note"] = "Updated by scripts/check_douyin_updates.py from observed homepage metadata."

    teaching_existing = {str(item["video_id"]) for item in teaching["videos"]}
    ledger_existing = {str(item["video_id"]) for item in ledger["videos"]}
    queue_existing = {str(item["video_id"]) for item in queue["items"]}
    discovery_existing = {str(item["video_id"]) for item in discovery["items"]}

    teaching_inserts = [
        item for item in classified
        if item["decision"] == "保留：教学" and item["video_id"] not in teaching_existing
    ]
    ledger_inserts = [
        {
            **item,
            "automatic_decision": item["decision"],
            "automatic_decision_reason": item["decision_reason"],
            "previous_decision": "new_discovery",
            "migration_action": (
                "await_manual_review"
                if item["decision"].startswith("待复核")
                else "accept_current_rules"
            ),
            "classified_at": applied_at,
        }
        for item in classified
        if item["video_id"] not in ledger_existing
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
            "classification_reason": item["decision_reason"],
            "classification_rules_version": item["classification_rules_version"],
            "classification_rules_hash": item["classification_rules_hash"],
            "classified_at": applied_at,
            "media_path": None,
            "duration_seconds": None,
            "attempts": 0,
            "error": None,
        }
        for item in teaching_inserts
        if item["video_id"] not in queue_existing
    ]
    discovery_inserts = [
        {
            "video_id": item["video_id"],
            "status": discovery_status(item["decision"]),
            "decision": item["decision"],
            "decision_reason": item["decision_reason"],
            "discovered_at": applied_at,
            "resolved_at": None,
            "resolution_note": None,
            "classification": item,
        }
        for item in classified
        if item["video_id"] not in discovery_existing
    ]

    teaching["videos"] = teaching_inserts + teaching["videos"]
    teaching["generated_at"] = applied_at
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

    ledger["videos"] = ledger_inserts + ledger["videos"]
    ledger["generated_at"] = applied_at
    ledger["classification_rules"] = rules_identity
    ledger["counts"] = dict(
        sorted(Counter(item["decision"] for item in ledger["videos"]).items())
    )

    queue["items"] = queue_inserts + queue["items"]
    queue["counts"] = compute_status_counts(queue["items"])
    queue["updated_at"] = applied_at

    discovery["items"] = discovery_inserts + discovery["items"]
    discovery["updated_at"] = applied_at
    discovery["counts"] = compute_status_counts(discovery["items"])

    return {
        INDEX_PATH: index,
        TEACHING_PATH: teaching,
        LEDGER_PATH: ledger,
        QUEUE_PATH: queue,
        DISCOVERY_STATE_PATH: discovery,
    }, {
        "index_added": len(inserts),
        "teaching_added": len(teaching_inserts),
        "ledger_added": len(ledger_inserts),
        "queue_added": len(queue_inserts),
        "discovery_recorded": len(discovery_inserts),
        "review_pending": sum(
            item["status"] == "review_pending" for item in discovery["items"]
        ),
    }


def apply_updates(new_videos, classified):
    payloads, counts = build_apply_payloads(new_videos, classified)
    commit_json_transaction(payloads, TRANSACTION_PATH)
    return counts


REVIEW_RESOLUTIONS = {
    "keep": ("classified_teaching", "保留：教学"),
    "exclude-ad": ("excluded_ad", "排除：广告/器材推广"),
    "exclude-non-teaching": ("excluded_non_teaching", "排除：非教学"),
}


def resolve_review(video_id, resolution, note):
    discovery = load_json(DISCOVERY_STATE_PATH)
    teaching = load_json(TEACHING_PATH)
    ledger = load_json(LEDGER_PATH)
    queue = load_json(QUEUE_PATH)
    item = next(
        (row for row in discovery["items"] if str(row["video_id"]) == str(video_id)),
        None,
    )
    if not item:
        raise ValueError(f"Review item not found: {video_id}")
    if item["status"] != "review_pending":
        raise ValueError(
            f"Review item {video_id} has already been resolved as {item['status']}"
        )
    if resolution not in REVIEW_RESOLUTIONS:
        raise ValueError(f"Unsupported review resolution: {resolution}")

    resolved_at = now_iso()
    status, decision = REVIEW_RESOLUTIONS[resolution]
    classification = dict(item["classification"])
    classification["decision"] = decision
    classification["decision_reason"] = note.strip() or "人工复核决定"
    ledger_item = next(
        (row for row in ledger["videos"] if str(row["video_id"]) == str(video_id)),
        None,
    )
    if not ledger_item:
        raise ValueError(f"Classification ledger item not found: {video_id}")

    if teaching["counts"].get("review", 0) <= 0:
        raise ValueError("Teaching review count is already zero; refusing inconsistent resolution")
    teaching["counts"]["review"] -= 1
    if resolution == "keep":
        teaching_ids = {str(row["video_id"]) for row in teaching["videos"]}
        queue_ids = {str(row["video_id"]) for row in queue["items"]}
        if str(video_id) not in teaching_ids:
            teaching["videos"] = [classification] + teaching["videos"]
        if str(video_id) not in queue_ids:
            queue["items"] = [
                {
                    "video_id": str(video_id),
                    "url": classification["url"],
                    "title": classification["title"],
                    "category": classification["primary_category"],
                    "tags": classification["tags"],
                    "status": "classified_teaching",
                    "classification_decision": decision,
                    "classification_reason": classification["decision_reason"],
                    "classification_rules_version": classification.get(
                        "classification_rules_version"
                    ),
                    "classification_rules_hash": classification.get(
                        "classification_rules_hash"
                    ),
                    "classified_at": resolved_at,
                    "media_path": None,
                    "duration_seconds": None,
                    "attempts": 0,
                    "error": None,
                }
            ] + queue["items"]
    elif resolution == "exclude-ad":
        teaching["counts"]["excluded_ads"] = teaching["counts"].get("excluded_ads", 0) + 1
    else:
        teaching["counts"]["excluded_non_teaching"] = (
            teaching["counts"].get("excluded_non_teaching", 0) + 1
        )

    teaching["counts"]["kept_teaching"] = len(teaching["videos"])
    teaching["generated_at"] = resolved_at
    queue["counts"] = compute_status_counts(queue["items"])
    queue["updated_at"] = resolved_at
    ledger_item.update(
        {
            "decision": decision,
            "decision_reason": classification["decision_reason"],
            "migration_action": f"manual_review_{resolution.replace('-', '_')}",
        }
    )
    ledger["generated_at"] = resolved_at
    ledger["counts"] = dict(
        sorted(Counter(row["decision"] for row in ledger["videos"]).items())
    )
    item.update(
        {
            "status": status,
            "decision": decision,
            "decision_reason": classification["decision_reason"],
            "resolved_at": resolved_at,
            "resolution_note": note.strip() or "人工复核决定",
            "classification": classification,
        }
    )
    discovery["updated_at"] = resolved_at
    discovery["counts"] = compute_status_counts(discovery["items"])
    commit_json_transaction(
        {
            TEACHING_PATH: teaching,
            LEDGER_PATH: ledger,
            QUEUE_PATH: queue,
            DISCOVERY_STATE_PATH: discovery,
        },
        TRANSACTION_PATH,
    )
    return {
        "video_id": str(video_id),
        "status": status,
        "decision": decision,
        "resolution_note": item["resolution_note"],
    }


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
    parser.add_argument(
        "--source-config",
        type=Path,
        default=SOURCE_CONFIG_PATH,
        help="Expected creator profile and snapshot quality thresholds",
    )
    parser.add_argument(
        "--skip-snapshot-validation",
        action="store_true",
        help="Allow historical or metadata-free fixtures; never use for monitoring conclusions",
    )
    parser.add_argument("--resolve-review", metavar="VIDEO_ID")
    parser.add_argument(
        "--resolution",
        choices=sorted(REVIEW_RESOLUTIONS),
        help="Resolution used with --resolve-review",
    )
    parser.add_argument(
        "--resolution-note",
        default="",
        help="Human review note retained in the discovery ledger",
    )
    args = parser.parse_args()

    recover_json_transaction(TRANSACTION_PATH)

    if args.resolve_review:
        if not args.resolution:
            parser.error("--resolution is required with --resolve-review")
        try:
            result = resolve_review(
                args.resolve_review,
                args.resolution,
                args.resolution_note,
            )
        except ValueError as error:
            parser.error(str(error))
        print(json.dumps(result, ensure_ascii=False))
        return
    if args.resolution:
        parser.error("--resolve-review is required with --resolution")

    input_path = args.input if args.input.is_absolute() else ROOT / args.input
    if not input_path.exists():
        raise SystemExit(
            f"Input snapshot not found: {input_path}\n"
            "Export the latest Douyin profile items to JSON first, then rerun this script."
        )

    raw_snapshot = load_json(input_path)
    snapshot_validation = None
    if not args.skip_snapshot_validation:
        source_config_path = (
            args.source_config if args.source_config.is_absolute() else ROOT / args.source_config
        )
        try:
            snapshot_validation = validate_snapshot_payload(
                raw_snapshot,
                len(load_json(INDEX_PATH)["videos"]),
                load_json(source_config_path),
            )
        except ValueError as error:
            parser.error(str(error))
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
        applied = apply_updates(new_videos, classified)

    report = {
        "generated_at": now_iso(),
        "classification_rules": rules["_rules_identity"],
        "input": str(input_path.relative_to(ROOT) if input_path.is_relative_to(ROOT) else input_path),
        "snapshot_validation": snapshot_validation,
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
