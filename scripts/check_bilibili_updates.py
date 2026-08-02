#!/usr/bin/env python3
"""Classify a Bilibili profile snapshot without admitting unverified videos."""

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from bilibili_pipeline import (
    acquire_bilibili_pipeline_lock,
    classify_video,
    extract_bvid,
    load_rules,
    may_enter_knowledge_base,
    normalize_video,
    stabilize_updated_at,
)
from douyin_pipeline import commit_json_transaction
from project_artifacts import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "config" / "bilibili_source.json"
INDEX_PATH = ROOT / "data" / "bilibili_video_index.json"
LEDGER_PATH = ROOT / "data" / "bilibili_classification_ledger.json"
REVIEW_PATH = ROOT / "data" / "processing" / "bilibili_origin_review_queue.json"
DOUYIN_INDEX_PATH = ROOT / "data" / "douyin_video_index.json"
TRANSACTION_PATH = ROOT / "data" / "processing" / ".bilibili-update-transaction.json"
DEFAULT_ARCHIVE_PATH = (
    ROOT / "data" / "snapshots" / "bilibili_profile_full_archive.json"
)
PRESERVED_OPERATIONAL_STAGES = {
    "metadata_ready",
    "downloaded",
    "transcribed",
    "transcription_failed",
    "transcription_quarantined",
    "acquisition_failed",
    "blocked_auth",
    "unavailable",
}


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def parse_iso_datetime(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Snapshot is missing collected_at")
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Snapshot collected_at must include a timezone")
    return parsed.astimezone(timezone.utc)


def normalize_snapshot_shape(payload):
    """Return the stable classifier shape plus the original archive payload."""

    if not isinstance(payload, dict):
        raise ValueError("Snapshot must be a JSON object")
    if isinstance(payload.get("videos"), list):
        return payload, payload
    if not isinstance(payload.get("items"), list):
        raise ValueError("Snapshot must contain either videos or items")
    publisher = payload.get("publisher") or {}
    coverage = payload.get("coverage") or {}
    profile_id = str(publisher.get("profile_id") or "")
    videos = []
    for item in payload["items"]:
        if not isinstance(item, dict):
            continue
        videos.append(
            {
                **item,
                "uploader_profile_id": profile_id,
            }
        )
    normalized = {
        "schema_version": payload.get("schema_version"),
        "profile_id": profile_id,
        "profile_url": str(publisher.get("profile_url") or ""),
        "collected_at": payload.get("generated_at"),
        "collected_unique_links": len(videos),
        "full_profile_archive": bool(coverage.get("full_profile_archive")),
        "profile_reported_video_count": coverage.get(
            "profile_reported_video_count"
        ),
        "profile_pages_complete": bool(coverage.get("profile_pages_complete")),
        "profile_pages": payload.get("profile_pages") or [],
        "coverage": coverage,
        "videos": videos,
    }
    return normalized, payload


def page_bvid_content_sha256(bvids):
    canonical = "\n".join(sorted(bvids)).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


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
    bvids = [extract_bvid(item) for item in videos]
    if any(not bvid for bvid in bvids):
        raise ValueError("Snapshot contains a video without a valid BVID")
    if len(bvids) != len(set(bvids)):
        raise ValueError("Snapshot contains duplicate BVIDs")

    full_archive = bool(payload.get("full_profile_archive"))
    if full_archive:
        reported = payload.get("profile_reported_video_count")
        if (
            not isinstance(reported, int)
            or isinstance(reported, bool)
            or reported <= 0
        ):
            raise ValueError("Full snapshot is missing a valid profile video count")
        if reported != len(videos):
            raise ValueError(
                "Full snapshot unique videos do not match the profile video count"
            )
        if not payload.get("profile_pages_complete"):
            raise ValueError("Full snapshot does not prove profile page completion")
        pages = payload.get("profile_pages")
        if not isinstance(pages, list) or not pages:
            raise ValueError("Full snapshot is missing profile page evidence")
        expected_pages = list(range(1, len(pages) + 1))
        actual_pages = [item.get("page") for item in pages]
        if actual_pages != expected_pages:
            raise ValueError("Full snapshot profile pages are not contiguous")
        if sum(int(item.get("count") or 0) for item in pages) != len(videos):
            raise ValueError("Full snapshot page counts do not match videos")
        videos_by_page = defaultdict(list)
        for item in videos:
            page = item.get("profile_page")
            if not isinstance(page, int) or isinstance(page, bool):
                raise ValueError("Full snapshot video is missing a valid profile_page")
            videos_by_page[page].append(extract_bvid(item))
        for page_evidence in pages:
            page = page_evidence["page"]
            page_bvids = videos_by_page.get(page, [])
            if len(page_bvids) != page_evidence.get("count"):
                raise ValueError(
                    f"Full snapshot page {page} count does not match its videos"
                )
            if (
                page_evidence.get("first_bvid") not in page_bvids
                or page_evidence.get("last_bvid") not in page_bvids
            ):
                raise ValueError(
                    f"Full snapshot page {page} boundaries do not match its videos"
                )
            if page_evidence.get(
                "sorted_bvid_sha256"
            ) != page_bvid_content_sha256(page_bvids):
                raise ValueError(
                    f"Full snapshot page {page} content hash does not match its videos"
                )
            if not re.fullmatch(
                r"[0-9a-f]{64}",
                str(page_evidence.get("bvid_sha256") or ""),
            ):
                raise ValueError(
                    f"Full snapshot page {page} is missing its capture-order hash"
                )
        coverage = payload.get("coverage") or {}
        if coverage.get("profile_pages") != len(pages):
            raise ValueError("Full snapshot coverage page count is inconsistent")
        for key in (
            "profile_reported_video_count",
            "profile_collected_count",
            "profile_unique_videos",
        ):
            if coverage.get(key) != len(videos):
                raise ValueError(f"Full snapshot coverage {key} is inconsistent")
    return {
        "profile_id": profile_id,
        "observed": len(videos),
        "age_hours": age_hours,
        "full_profile_archive": full_archive,
    }


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


def reconcile_processing_state(existing, classified):
    """Reset obsolete classification terminals without losing real work."""

    if classified["decision"] == "excluded_transcription_policy":
        return classified["processing_state"]
    existing_state = existing.get("processing_state") or {}
    existing_stage = existing_state.get("stage")
    same_rules = (
        existing.get("classification_rules_hash")
        == classified.get("classification_rules_hash")
    )
    if same_rules or existing_stage in PRESERVED_OPERATIONAL_STAGES:
        return existing_state or classified["processing_state"]
    return classified["processing_state"]


def build_payloads(snapshot):
    snapshot, _ = normalize_snapshot_shape(snapshot)
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

    observed_at = parse_iso_datetime(snapshot["collected_at"]).isoformat()
    full_archive = bool(snapshot.get("full_profile_archive"))
    old_index = load_json(INDEX_PATH)
    old_ledger = load_json(LEDGER_PATH)
    old_review = load_json(REVIEW_PATH)
    by_id = {item["video_id"]: item for item in old_index["videos"]}
    for item in normalized:
        existing = by_id.get(item["video_id"]) or {}
        item["first_seen_at"] = existing.get("first_seen_at") or observed_at
        item["last_seen_at"] = observed_at
        item.pop("missing_since", None)
        by_id[item["video_id"]] = item
    if full_archive:
        observed_ids = {item["video_id"] for item in normalized}
        for video_id, item in by_id.items():
            if video_id not in observed_ids:
                item["missing_since"] = item.get("missing_since") or observed_at
    ledger_by_id = {item["video_id"]: item for item in old_ledger["videos"]}
    for item in classified:
        existing = ledger_by_id.get(item["video_id"]) or {}
        item["first_seen_at"] = existing.get("first_seen_at") or observed_at
        item["last_seen_at"] = observed_at
        item.pop("missing_since", None)
        if existing.get("origin_verification"):
            item["origin_verification"] = existing["origin_verification"]
            item["knowledge_admission_eligible"] = may_enter_knowledge_base(item)
        item["processing_state"] = reconcile_processing_state(existing, item)
        ledger_by_id[item["video_id"]] = item
    if full_archive:
        observed_ids = {item["video_id"] for item in classified}
        for video_id, item in ledger_by_id.items():
            if video_id not in observed_ids:
                item["missing_since"] = item.get("missing_since") or observed_at
    ledger_items = sorted(ledger_by_id.values(), key=lambda item: item["video_id"])
    review_items = [
        item for item in ledger_items
        if item["decision"] in {
            "candidate_liuhui_teaching",
            "review_pending",
        }
        and not item["knowledge_admission_eligible"]
    ]
    index_payload = stabilize_updated_at(
        old_index,
        {
            **old_index,
            "videos": sorted(by_id.values(), key=lambda item: item["video_id"]),
        },
        observed_at,
    )
    ledger_payload = stabilize_updated_at(
        old_ledger,
        {
            **old_ledger,
            "counts": dict(Counter(item["decision"] for item in ledger_items)),
            "videos": ledger_items,
        },
        observed_at,
    )
    review_payload = stabilize_updated_at(
        old_review,
        {
            "version": 1,
            "platform": "bilibili",
            "updated_at": observed_at,
            "counts": dict(Counter(item["decision"] for item in review_items)),
            "items": review_items,
        },
        observed_at,
    )
    return {
        INDEX_PATH: index_payload,
        LEDGER_PATH: ledger_payload,
        REVIEW_PATH: review_payload,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--archive-out",
        type=Path,
        default=DEFAULT_ARCHIVE_PATH,
        help="Persist a validated full-profile archive to this path when applying",
    )
    args = parser.parse_args()
    pipeline_lock = acquire_bilibili_pipeline_lock()
    raw_snapshot = load_json(args.snapshot)
    snapshot, archive_payload = normalize_snapshot_shape(raw_snapshot)
    validation = validate_snapshot(snapshot, load_json(SOURCE_PATH))
    payloads = build_payloads(snapshot)
    ledger = payloads[LEDGER_PATH]
    if args.apply:
        commit_json_transaction(payloads, TRANSACTION_PATH)
        if validation["full_profile_archive"]:
            serialized = json.dumps(
                archive_payload,
                ensure_ascii=False,
                indent=2,
            ) + "\n"
            atomic_write_text(args.archive_out, serialized)
    print(json.dumps({
        "applied": args.apply,
        "observed": len(snapshot["videos"]),
        "full_profile_archive": validation["full_profile_archive"],
        "archive_out": (
            str(args.archive_out.relative_to(ROOT))
            if args.apply and validation["full_profile_archive"]
            else None
        ),
        "classified_total": len(ledger["videos"]),
        "counts": ledger["counts"],
        "knowledge_admission_eligible": sum(
            bool(item["knowledge_admission_eligible"])
            for item in ledger["videos"]
        ),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
