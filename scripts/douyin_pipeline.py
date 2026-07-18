#!/usr/bin/env python3
import json
import hashlib
import os
import re
import shutil
import tempfile
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
TEMPORARY_MEDIA_FIELDS = {
    "media_asset_kind",
    "media_asset_source",
    "media_asset_url",
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def normalize_transcribed_media_state(item):
    """Remove references to temporary media after durable transcription succeeds."""

    if item.get("status") != "transcribed":
        return False
    changed = item.get("media_path") is not None
    item["media_path"] = None
    for field in TEMPORARY_MEDIA_FIELDS:
        if field in item:
            item.pop(field)
            changed = True
    return changed


def file_sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    os.close(handle)
    try:
        shutil.copyfile(source, temporary_name)
        os.replace(temporary_name, target)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def recover_json_transaction(journal_path):
    journal_path = Path(journal_path)
    if not journal_path.exists():
        return False
    journal = load_json(journal_path)
    staged_paths = []
    for entry in journal["entries"]:
        staged = Path(entry["staged"])
        target = Path(entry["target"])
        if not staged.exists():
            raise RuntimeError(f"Transaction staging file is missing: {staged}")
        if file_sha256(staged) != entry["sha256"]:
            raise RuntimeError(f"Transaction staging checksum mismatch: {staged}")
        atomic_copy(staged, target)
        staged_paths.append(staged)
    journal_path.unlink()
    for staged in staged_paths:
        staged.unlink(missing_ok=True)
    stage_dir = Path(journal["stage_dir"])
    try:
        stage_dir.rmdir()
    except OSError:
        pass
    return True


def commit_json_transaction(payloads, journal_path):
    journal_path = Path(journal_path)
    recover_json_transaction(journal_path)
    stage_dir = journal_path.parent / f".{journal_path.stem}.staged"
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True)
    entries = []
    for index, (target, payload) in enumerate(payloads.items(), start=1):
        target = Path(target).resolve()
        staged = stage_dir / f"{index:02d}-{target.name}"
        write_json(staged, payload)
        entries.append(
            {
                "target": str(target),
                "staged": str(staged.resolve()),
                "sha256": file_sha256(staged),
            }
        )
    write_json(
        journal_path,
        {
            "version": 1,
            "created_at": now_iso(),
            "stage_dir": str(stage_dir.resolve()),
            "entries": entries,
        },
    )
    recover_json_transaction(journal_path)


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
    content_text = re.sub(r"#\S+", " ", text)
    signals = rules["signals"]
    reasons = rules["decision_reasons"]
    ad = bool(signals["ad_strong"].search(text))
    has_equipment = bool(signals["equipment"].search(content_text))
    has_commerce = bool(signals["commerce"].search(content_text))
    has_teaching = bool(signals["teaching"].search(content_text))
    has_teaching_hashtag = bool(signals["teaching_hashtag"].search(text))
    explicit_non_teaching = bool(signals["non_teaching"].search(content_text))
    equipment_only = has_equipment and not has_teaching
    ad = ad or (has_equipment and has_commerce)

    decision = "排除：非教学"
    reason = reasons["default_excluded"]
    if ad and has_teaching:
        decision = "待复核：教学夹带推广"
        reason = reasons["mixed_ad_teaching"]
    elif explicit_non_teaching and not has_teaching:
        reason = reasons["explicit_non_teaching"]
    elif ad or equipment_only:
        decision = "排除：广告/器材推广"
        reason = reasons["ad_or_equipment"]
    elif has_teaching:
        decision = "保留：教学"
        reason = reasons["teaching"]
    elif has_teaching_hashtag:
        decision = "待复核：仅通用教学标签"
        reason = reasons["hashtag_only_review"]

    manual_exclusions = rules.get("manual_exclusions", {})
    if video["video_id"] in manual_exclusions:
        decision = manual_exclusions[video["video_id"]]
        reason = reasons["manual_exclusion"]

    matched = [
        item["name"]
        for item in rules["taxonomy"]
        if item["pattern"].search(content_text)
    ]
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
