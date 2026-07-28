#!/usr/bin/env python3
"""Verify and download audio for quarantined Bilibili Liu Hui candidates."""

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from bilibili_pipeline import may_enter_knowledge_base
from douyin_pipeline import commit_json_transaction, now_iso


ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = ROOT / "data" / "bilibili_classification_ledger.json"
REVIEW_PATH = ROOT / "data" / "processing" / "bilibili_origin_review_queue.json"
QUEUE_PATH = ROOT / "data" / "processing" / "bilibili_queue.json"
RAW_ROOT = ROOT / "data" / "raw_videos" / "bilibili"
TRANSACTION_PATH = ROOT / "data" / "processing" / ".bilibili-media-transaction.json"
EXPECTED_UPLOADER_ID = "1423436652"
ORIGIN_PATTERN = re.compile(r"刘辉(?:教练|羽毛球)?|辉哥")
TRUSTED_ORIGIN_TAGS = {"刘辉", "刘辉羽毛球"}


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def verify_metadata(info, expected_bvid):
    tags = {str(tag).strip() for tag in info.get("tags") or []}
    title = str(info.get("title") or "")
    description = str(info.get("description") or "")
    duration = info.get("duration")
    canonical_url = str(info.get("webpage_url") or "")
    signals = {
        "video_id_matches": info.get("id") == expected_bvid,
        "uploader_profile_matches": str(info.get("uploader_id") or "")
        == EXPECTED_UPLOADER_ID,
        "canonical_url_matches": f"/video/{expected_bvid}" in canonical_url,
        "publisher_text_names_liuhui": bool(
            ORIGIN_PATTERN.search(f"{title} {description}")
        ),
        "dedicated_origin_tag": bool(tags & TRUSTED_ORIGIN_TAGS),
        "duration_valid": (
            isinstance(duration, (int, float))
            and not isinstance(duration, bool)
            and 0 < duration <= 7200
        ),
    }
    verified = all(signals.values())
    return {
        "status": "verified_liuhui_clip" if verified else "verification_failed",
        "methods": [
            "verified_uploader_profile",
            "publisher_origin_annotation",
        ] if verified else [],
        "verified_at": now_iso(),
        "signals": signals,
        "source_metadata": {
            "uploader": str(info.get("uploader") or ""),
            "uploader_id": str(info.get("uploader_id") or ""),
            "title": title,
            "description": description,
            "tags": sorted(tags),
            "duration_seconds": round(float(duration), 3) if signals["duration_valid"] else None,
            "upload_date": str(info.get("upload_date") or ""),
        },
    }


def preserve_verification_timestamp(previous, current):
    previous = previous or {}
    previous_stable = {key: value for key, value in previous.items() if key != "verified_at"}
    current_stable = {key: value for key, value in current.items() if key != "verified_at"}
    if previous_stable == current_stable and previous.get("verified_at"):
        current["verified_at"] = previous["verified_at"]
    return current


def ydl_options(output_dir=None):
    options = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "socket_timeout": 30,
        "retries": 2,
        "fragment_retries": 2,
        "format": "worstaudio[ext=m4a]/bestaudio[ext=m4a]/bestaudio",
    }
    if output_dir is not None:
        options.update({
            "outtmpl": str(Path(output_dir) / "%(id)s.%(ext)s"),
            "overwrites": False,
        })
    return options


def extract_metadata(url):
    from yt_dlp import YoutubeDL

    with YoutubeDL(ydl_options()) as ydl:
        return ydl.extract_info(url, download=False)


def download_audio(url, bvid):
    from yt_dlp import YoutubeDL

    RAW_ROOT.mkdir(parents=True, exist_ok=True)
    existing = list(RAW_ROOT.glob(f"{bvid}.*"))
    if not existing:
        with YoutubeDL(ydl_options(RAW_ROOT)) as ydl:
            ydl.download([url])
        existing = list(RAW_ROOT.glob(f"{bvid}.*"))
    media = next(
        (path for path in existing if path.suffix.lower() in {".m4a", ".mp3", ".webm"}),
        None,
    )
    if media is None or media.stat().st_size < 4096:
        raise RuntimeError(f"Downloaded audio is missing or too small for {bvid}")
    return media


def queue_item(record, verification, media):
    metadata = verification["source_metadata"]
    return {
        "platform": "bilibili",
        "video_id": record["bvid"],
        "evidence_id": record["video_id"],
        "url": record["url"],
        "title": metadata["title"] or record["title"],
        "description": metadata["description"],
        "category": "",
        "tags": "；".join(metadata["tags"]),
        "status": "downloaded",
        "classification_decision": "保留：教学",
        "classification_reason": "B站发布者元数据通过刘辉教学切片来源门禁",
        "classification_rules_version": record["classification_rules_version"],
        "classification_rules_hash": record["classification_rules_hash"],
        "origin_verification": verification,
        "media_path": str(media.relative_to(ROOT)),
        "duration_seconds": metadata["duration_seconds"],
        "attempts": 0,
        "error": None,
        "error_stage": None,
        "downloaded_at": now_iso()
    }


def persist(ledger, queue):
    ledger["updated_at"] = now_iso()
    ledger["counts"] = dict(Counter(item["decision"] for item in ledger["videos"]))
    queue["updated_at"] = now_iso()
    queue["counts"] = dict(Counter(item["status"] for item in queue["items"]))
    review_items = [
        item for item in ledger["videos"]
        if item["decision"] in {"candidate_liuhui_teaching", "review_pending"}
        and not item.get("knowledge_admission_eligible")
    ]
    review = {
        "version": 1,
        "platform": "bilibili",
        "updated_at": now_iso(),
        "counts": dict(Counter(item["decision"] for item in review_items)),
        "items": review_items,
    }
    commit_json_transaction(
        {LEDGER_PATH: ledger, QUEUE_PATH: queue, REVIEW_PATH: review},
        TRANSACTION_PATH,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bvid", action="append", default=[])
    parser.add_argument("--metadata-only", action="store_true")
    args = parser.parse_args()
    requested = set(args.bvid)
    ledger = load_json(LEDGER_PATH)
    queue = load_json(QUEUE_PATH)
    queue_by_id = {item["video_id"]: item for item in queue["items"]}
    candidates = [
        item for item in ledger["videos"]
        if item["decision"] == "candidate_liuhui_teaching"
        and (not requested or item["bvid"] in requested)
    ]
    results = []
    for record in candidates:
        bvid = record["bvid"]
        try:
            info = extract_metadata(record["url"])
            verification = preserve_verification_timestamp(
                record.get("origin_verification"),
                verify_metadata(info, bvid),
            )
            record["origin_verification"] = verification
            record["knowledge_admission_eligible"] = may_enter_knowledge_base(record)
            result = {
                "bvid": bvid,
                "origin_status": verification["status"],
                "eligible": record["knowledge_admission_eligible"],
            }
            if record["knowledge_admission_eligible"] and not args.metadata_only:
                existing = queue_by_id.get(bvid)
                if existing and existing.get("status") == "transcribed":
                    existing["origin_verification"] = verification
                    result["status"] = "already_transcribed"
                else:
                    media = download_audio(record["url"], bvid)
                    queue_by_id[bvid] = queue_item(record, verification, media)
                    result["status"] = "downloaded"
                    result["media_bytes"] = media.stat().st_size
            results.append(result)
        except Exception as error:
            results.append({"bvid": bvid, "status": "failed", "error": str(error)[-500:]})
        queue["items"] = sorted(queue_by_id.values(), key=lambda item: item["video_id"])
        persist(ledger, queue)
    print(json.dumps({"processed": len(results), "results": results}, ensure_ascii=False, indent=2))
    return 1 if any(item.get("status") == "failed" for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
