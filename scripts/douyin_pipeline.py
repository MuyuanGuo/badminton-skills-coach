#!/usr/bin/env python3
import json
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RULES_PATH = ROOT / "config" / "douyin_classification_rules.json"

QUEUE_STATUSES = {
    "classified_teaching": {
        "stage": "classification",
        "description": "Teaching candidate accepted and waiting for media extraction.",
    },
    "pending": {
        "stage": "classification",
        "description": "Legacy alias for classified_teaching.",
        "legacy": True,
    },
    "media_ready": {
        "stage": "media",
        "description": "Media asset URL captured and curl config generated.",
    },
    "downloaded": {
        "stage": "media",
        "description": "Temporary media downloaded and waiting for transcription.",
    },
    "transcribed": {
        "stage": "transcription",
        "description": "Transcript files exist and can be built into the knowledge base.",
    },
    "download_failed": {
        "stage": "media",
        "description": "Media download failed; retry after refreshing asset/curl config.",
        "failure": True,
    },
    "extraction_failed": {
        "stage": "media",
        "description": "Media asset extraction failed in the browser.",
        "failure": True,
    },
    "transcription_failed": {
        "stage": "transcription",
        "description": "Local transcription failed; inspect media and retry.",
        "failure": True,
    },
    "skipped_non_teaching": {
        "stage": "classification",
        "description": "Known non-teaching item retained only for accounting.",
        "terminal": True,
    },
}

PRE_MEDIA_STATUSES = {"classified_teaching", "pending", "media_ready", "download_failed", "extraction_failed"}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_classification_rules(path=None):
    rules_path = path or DEFAULT_RULES_PATH
    rules = load_json(rules_path)
    compiled = {
        **rules,
        "taxonomy": [
            {"name": item["name"], "pattern": re.compile(item["pattern"])}
            for item in rules["taxonomy"]
        ],
        "signals": {
            name: re.compile(pattern)
            for name, pattern in rules["signals"].items()
        },
    }
    return compiled


def classify_video(video, rules):
    text = f"{video.get('title', '')} {video.get('raw_text', '')}"
    signals = rules["signals"]
    reasons = rules["decision_reasons"]
    ad = bool(signals["ad_strong"].search(text))
    has_teaching = bool(signals["teaching"].search(text))
    equipment_only = bool(signals["equipment"].search(text)) and not has_teaching
    explicit_non_teaching = bool(signals["non_teaching"].search(text)) and not has_teaching

    decision = "排除：非教学"
    reason = reasons["default_excluded"]
    if ad and has_teaching:
        decision = "待复核：教学夹带推广"
        reason = reasons["mixed_ad_teaching"]
    elif ad or equipment_only:
        decision = "排除：广告/器材推广"
        reason = reasons["ad_or_equipment"]
    elif has_teaching and not explicit_non_teaching:
        decision = "保留：教学"
        reason = reasons["teaching"]
    elif explicit_non_teaching:
        reason = reasons["explicit_non_teaching"]

    manual_exclusions = rules.get("manual_exclusions", {})
    if video["video_id"] in manual_exclusions:
        decision = manual_exclusions[video["video_id"]]
        reason = reasons["manual_exclusion"]

    matched = [item["name"] for item in rules["taxonomy"] if item["pattern"].search(text)]
    primary_category = matched[0] if decision in {"保留：教学", "待复核：教学夹带推广"} and matched else ""
    return {
        **video,
        "author_status": "主页最新作品区发现",
        "decision": decision,
        "decision_reason": reason,
        "primary_category": primary_category,
        "tags": "；".join(matched),
    }


def compute_status_counts(items):
    counts = {}
    for item in items:
        status = item.get("status", "")
        counts[status] = counts.get(status, 0) + 1
    return counts


def validate_queue_statuses(items):
    allowed = set(QUEUE_STATUSES)
    invalid = sorted({item.get("status", "") for item in items} - allowed)
    if invalid:
        raise SystemExit(f"Queue contains unknown status values: {', '.join(invalid)}")
