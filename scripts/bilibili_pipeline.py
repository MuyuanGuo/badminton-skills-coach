#!/usr/bin/env python3
"""Safe metadata classification for the mixed-origin 大G羽毛球 Bilibili space."""

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RULES_PATH = ROOT / "config" / "bilibili_classification_rules.json"
BVID_PATTERN = re.compile(r"BV[0-9A-Za-z]{10}")


def rules_identity(payload):
    digest = hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    return {"version": payload["version"], "sha256": digest}


def load_rules(path=DEFAULT_RULES_PATH):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return {
        **payload,
        "_identity": rules_identity(payload),
        "signals": {
            name: re.compile(pattern)
            for name, pattern in payload["signals"].items()
        },
    }


def extract_bvid(item):
    for key in ("bvid", "video_id", "id"):
        value = str(item.get(key) or "")
        match = BVID_PATTERN.fullmatch(value) or BVID_PATTERN.search(value)
        if match:
            return match.group(0)
    match = BVID_PATTERN.search(str(item.get("url") or ""))
    return match.group(0) if match else None


def normalize_video(item):
    bvid = extract_bvid(item)
    if not bvid:
        return None
    title = str(item.get("title") or "").strip()
    card_text = str(item.get("card_text") or item.get("raw_text") or title).strip()
    tags = item.get("tags") or []
    if isinstance(tags, str):
        tags = [part.strip() for part in re.split(r"[,，;；]", tags) if part.strip()]
    return {
        "video_id": f"bilibili:{bvid}",
        "bvid": bvid,
        "url": f"https://www.bilibili.com/video/{bvid}/",
        "title": title,
        "card_text": card_text,
        "tags": [str(tag).strip() for tag in tags if str(tag).strip()],
        "source_platform": "bilibili",
        "uploader_profile_id": str(item.get("uploader_profile_id") or ""),
    }


def classify_video(video, rules):
    # Deliberately exclude SEO description. Bilibili appends uploader biography and
    # related-video titles to it, which leaks 刘辉 terms into unrelated originals.
    evidence_text = " ".join(
        [video.get("title", ""), video.get("card_text", ""), *video.get("tags", [])]
    )
    signals = {
        name: bool(pattern.search(evidence_text))
        for name, pattern in rules["signals"].items()
    }
    if signals["non_teaching"] or signals["medical"] or signals["promotion"]:
        decision = "excluded_non_teaching"
    elif signals["liuhui_origin"] and signals["teaching"]:
        decision = "candidate_liuhui_teaching"
    elif signals["teaching"]:
        decision = "excluded_creator_original_or_unknown"
    else:
        decision = "review_pending"
    return {
        **video,
        "origin_status": (
            "origin_verification_pending"
            if decision == "candidate_liuhui_teaching"
            else "not_verified_liuhui"
        ),
        "knowledge_admission_eligible": False,
        "decision": decision,
        "decision_reason": rules["decisions"][decision],
        "classification_signals": signals,
        "classification_rules_version": rules["_identity"]["version"],
        "classification_rules_hash": rules["_identity"]["sha256"],
    }


def may_enter_knowledge_base(item):
    """Return true only after independent provenance verification."""

    verification = item.get("origin_verification") or {}
    methods = set(verification.get("methods") or [])
    allowed_methods = {
        "verified_collection_membership",
        "direct_video_content_review",
        "publisher_origin_annotation",
    }
    return (
        item.get("decision") == "candidate_liuhui_teaching"
        and verification.get("status") == "verified_liuhui_clip"
        and len(methods & allowed_methods) >= 1
        and bool(verification.get("verified_at"))
    )
