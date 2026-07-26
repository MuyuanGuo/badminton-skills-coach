#!/usr/bin/env python3
"""Classify a Bilibili profile snapshot without admitting unverified videos."""

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from bilibili_pipeline import (
    classify_video,
    load_rules,
    may_enter_knowledge_base,
    normalize_video,
)
from douyin_pipeline import commit_json_transaction, now_iso


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "config" / "bilibili_source.json"
INDEX_PATH = ROOT / "data" / "bilibili_video_index.json"
LEDGER_PATH = ROOT / "data" / "bilibili_classification_ledger.json"
REVIEW_PATH = ROOT / "data" / "processing" / "bilibili_origin_review_queue.json"
DOUYIN_INDEX_PATH = ROOT / "data" / "douyin_video_index.json"
TRANSACTION_PATH = ROOT / "data" / "processing" / ".bilibili-update-transaction.json"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def parse_iso_datetime(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Snapshot is missing collected_at")
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Snapshot collected_at must include a timezone")
    return parsed.astimezone(timezone.utc)


def validate_snapshot(payload, source, current_time=None):
    if not isinstance(payload, dict):
        raise ValueError("Snapshot must be a JSON object")
    profile_id = str(payload.get("profile_id") or "")
    profile_url = str(payload.get("profile_url") or "")
    match = re.search(r"space\.bilibili\.com/(\d+)", profile_url)
    url_profile_id = match.group(1) if match else ""
    if profile_id != source["profile_id"] or url_profile_id != source["profile_id"]:
        raise ValueError("Snapshot profile does not match the configured Bilibili space")
    videos = payload.get("videos")
    if not isinstance(videos, list):
        raise ValueError("Snapshot videos must be a list")
    if payload.get("collected_unique_links") != len(videos):
        raise ValueError("Snapshot collected_unique_links does not match videos")
    if len(videos) < source["snapshot"]["min_observed_links"]:
        raise ValueError("Snapshot coverage is too low")
    collected_at = parse_iso_datetime(payload.get("collected_at"))
    now = current_time or datetime.now(timezone.utc)
    age_hours = (now - collected_at).total_seconds() / 3600
    if age_hours < -0.25:
        raise ValueError("Snapshot collected_at is unexpectedly in the future")
    if age_hours > source["snapshot"]["max_age_hours"]:
        raise ValueError("Snapshot is stale")
    return {"profile_id": profile_id, "observed": len(videos), "age_hours": age_hours}


def normalized_terms(text):
    normalized = text.lower()
    terms = set(re.findall(r"[a-z0-9]+", normalized))
    for sequence in re.findall(r"[\u4e00-\u9fff]+", normalized):
        terms.update(sequence[index:index + 2] for index in range(len(sequence) - 1))
    return terms


def build_douyin_term_index(videos):
    postings = defaultdict(set)
    titles = {}
    for video in videos:
        video_id = str(video["video_id"])
        terms = normalized_terms(str(video.get("title") or ""))
        titles[video_id] = terms
        for term in terms:
            postings[term].add(video_id)
    return postings, titles


def possible_douyin_duplicates(title, postings, titles, threshold=0.55):
    terms = normalized_terms(title)
    candidate_ids = set()
    for term in terms:
        candidate_ids.update(postings.get(term, ()))
    scored = []
    for video_id in candidate_ids:
        other = titles[video_id]
        union = terms | other
        score = len(terms & other) / len(union) if union else 0
        if score >= threshold:
            scored.append({"video_id": video_id, "title_term_jaccard": round(score, 3)})
    return sorted(scored, key=lambda item: (-item["title_term_jaccard"], item["video_id"]))[:5]


def build_payloads(snapshot):
    source = load_json(SOURCE_PATH)
    validate_snapshot(snapshot, source)
    rules = load_rules()
    normalized = []
    seen = set()
    for raw in snapshot["videos"]:
        item = normalize_video(raw)
        if not item or item["video_id"] in seen:
            continue
        if item["uploader_profile_id"] != source["profile_id"]:
            raise ValueError(
                f"Video {item['video_id']} has an unexpected uploader profile"
            )
        seen.add(item["video_id"])
        normalized.append(item)
    douyin = load_json(DOUYIN_INDEX_PATH)["videos"]
    postings, titles = build_douyin_term_index(douyin)
    classified = []
    for item in normalized:
        result = classify_video(item, rules)
        result["possible_douyin_duplicates"] = possible_douyin_duplicates(
            result["title"], postings, titles
        )
        classified.append(result)

    applied_at = now_iso()
    old_index = load_json(INDEX_PATH)
    old_ledger = load_json(LEDGER_PATH)
    by_id = {item["video_id"]: item for item in old_index["videos"]}
    by_id.update({item["video_id"]: item for item in normalized})
    ledger_by_id = {item["video_id"]: item for item in old_ledger["videos"]}
    for item in classified:
        existing = ledger_by_id.get(item["video_id"]) or {}
        if existing.get("origin_verification"):
            item["origin_verification"] = existing["origin_verification"]
            item["knowledge_admission_eligible"] = may_enter_knowledge_base(item)
        ledger_by_id[item["video_id"]] = item
    ledger_items = sorted(ledger_by_id.values(), key=lambda item: item["video_id"])
    review_items = [
        item for item in ledger_items
        if item["decision"] in {"candidate_liuhui_teaching", "review_pending"}
        and not item["knowledge_admission_eligible"]
    ]
    return {
        INDEX_PATH: {
            **old_index,
            "updated_at": applied_at,
            "videos": sorted(by_id.values(), key=lambda item: item["video_id"]),
        },
        LEDGER_PATH: {
            **old_ledger,
            "updated_at": applied_at,
            "counts": dict(Counter(item["decision"] for item in ledger_items)),
            "videos": ledger_items,
        },
        REVIEW_PATH: {
            "version": 1,
            "platform": "bilibili",
            "updated_at": applied_at,
            "counts": dict(Counter(item["decision"] for item in review_items)),
            "items": review_items,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    snapshot = load_json(args.snapshot)
    payloads = build_payloads(snapshot)
    ledger = payloads[LEDGER_PATH]
    if args.apply:
        commit_json_transaction(payloads, TRANSACTION_PATH)
    print(json.dumps({
        "applied": args.apply,
        "observed": len(snapshot["videos"]),
        "classified_total": len(ledger["videos"]),
        "counts": ledger["counts"],
        "knowledge_admission_eligible": sum(
            bool(item["knowledge_admission_eligible"])
            for item in ledger["videos"]
        ),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
