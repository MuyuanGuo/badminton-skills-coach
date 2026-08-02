#!/usr/bin/env python3
"""Safe metadata classification for the mixed-origin 大G羽毛球 Bilibili space."""

import hashlib
import json
import os
import re
from pathlib import Path

import fcntl


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RULES_PATH = ROOT / "config" / "bilibili_classification_rules.json"
PIPELINE_LOCK_PATH = ROOT / "data" / "processing" / ".bilibili-pipeline.lock"
PIPELINE_LOCK_OWNER_ENV = "BSC_BILIBILI_PIPELINE_LOCK_HELD"
BVID_PATTERN = re.compile(r"BV[0-9A-Za-z]{10}")
COLLECTION_LIST_ID_PATTERN = re.compile(r"/lists/(\d+)")


def stabilize_updated_at(old_payload, new_payload, changed_at):
    """Preserve timestamps when a durable payload has no semantic change."""

    old_semantic = {
        key: value for key, value in old_payload.items() if key != "updated_at"
    }
    new_semantic = {
        key: value for key, value in new_payload.items() if key != "updated_at"
    }
    updated_at = (
        old_payload.get("updated_at")
        if old_semantic == new_semantic and old_payload.get("updated_at")
        else changed_at
    )
    return {**new_payload, "updated_at": updated_at}


def acquire_bilibili_pipeline_lock():
    """Prevent concurrent whole-file writers from losing Bilibili state."""

    if os.environ.get(PIPELINE_LOCK_OWNER_ENV) == "1":
        return None
    PIPELINE_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    handle = PIPELINE_LOCK_PATH.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise RuntimeError(
            "Another Bilibili pipeline writer holds "
            f"{PIPELINE_LOCK_PATH.relative_to(ROOT)}"
        )
    return handle


def rules_identity(payload):
    digest = hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    return {"version": payload["version"], "sha256": digest}


def load_rules(path=DEFAULT_RULES_PATH):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    collection_policy = payload.get("collection_policy") or {}
    required = collection_policy.get("required_transcription") or []
    excluded = collection_policy.get("excluded") or []
    video_overrides = collection_policy.get("video_overrides") or {}
    video_required = video_overrides.get("required_transcription") or []
    video_excluded = video_overrides.get("excluded") or []
    configured_ids = [
        str(item.get("list_id") or "")
        for item in [*required, *excluded]
    ]
    configured_names = [
        str(item.get("name") or "")
        for item in [*required, *excluded]
    ]
    if (
        not required
        or not excluded
        or any(not value for value in [*configured_ids, *configured_names])
        or len(configured_ids) != len(set(configured_ids))
        or len(configured_names) != len(set(configured_names))
    ):
        raise ValueError("Bilibili collection policy is missing or overlaps")
    configured_bvids = [
        str(item.get("bvid") or "")
        for item in [*video_required, *video_excluded]
    ]
    if (
        not video_required
        or not video_excluded
        or any(
            not BVID_PATTERN.fullmatch(bvid)
            for bvid in configured_bvids
        )
        or len(configured_bvids) != len(set(configured_bvids))
        or any(
            not str(item.get("title") or "").strip()
            for item in [*video_required, *video_excluded]
        )
    ):
        raise ValueError("Bilibili video policy is missing, invalid, or overlaps")
    return {
        **payload,
        "_identity": rules_identity(payload),
        "signals": {
            name: re.compile(pattern)
            for name, pattern in payload["signals"].items()
        },
    }


def collection_list_id(membership):
    match = COLLECTION_LIST_ID_PATTERN.search(str(membership.get("url") or ""))
    return match.group(1) if match else None


def classify_collection_policy(video, rules):
    configured = rules["collection_policy"]
    by_id = {}
    by_name = {}
    for action, key in (
        ("required_transcription", "required_transcription"),
        ("excluded", "excluded"),
    ):
        for item in configured[key]:
            value = {
                "action": action,
                "list_id": str(item["list_id"]),
                "configured_name": str(item["name"]),
            }
            by_id[value["list_id"]] = value
            by_name[value["configured_name"]] = value

    matched = []
    for membership in video.get("collection_memberships") or []:
        list_id = collection_list_id(membership)
        name = str(membership.get("name") or "")
        policy = by_id.get(list_id) if list_id else by_name.get(name)
        if policy is None:
            continue
        matched.append({
            **policy,
            "name": name or policy["configured_name"],
        })
    actions = {item["action"] for item in matched}
    if len(actions) > 1:
        raise ValueError(
            f"Video {video.get('video_id')} matches conflicting collection policies"
        )
    video_overrides = configured.get("video_overrides") or {}
    video_policy = {}
    for action, key in (
        ("required_transcription", "required_transcription"),
        ("excluded", "excluded"),
    ):
        for item in video_overrides.get(key) or []:
            video_policy[str(item["bvid"])] = {
                "action": action,
                "bvid": str(item["bvid"]),
                "configured_title": str(item["title"]),
            }
    override = video_policy.get(str(video.get("bvid") or ""))
    if override and matched:
        raise ValueError(
            f"Video {video.get('video_id')} has both collection and video policy"
        )
    if override:
        action = override["action"]
        basis = "video_override"
    elif matched:
        action = matched[0]["action"]
        basis = "collection"
    else:
        action = configured.get("unmatched", "needs_confirmation")
        basis = "unmatched"
    return {
        "action": action,
        "basis": basis,
        "matches": matched,
        "video_override": override,
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
        "published_at_text": str(item.get("published_at_text") or ""),
        "duration_text": str(item.get("duration_text") or ""),
        "profile_page": item.get("profile_page"),
        "collection_memberships": list(item.get("collection_memberships") or []),
        "discovery_evidence": dict(item.get("discovery_evidence") or {}),
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
    collection_policy = classify_collection_policy(video, rules)
    policy_action = collection_policy["action"]
    if policy_action == "excluded":
        decision = "excluded_transcription_policy"
        origin_status = "excluded_transcription_policy"
        stage = "excluded_transcription_policy"
        terminal = True
    elif policy_action == "required_transcription":
        decision = "required_transcription_policy"
        origin_status = "transcription_policy_metadata_pending"
        stage = "metadata_pending"
        terminal = False
    elif signals["liuhui_origin"] and signals["teaching"]:
        decision = "candidate_liuhui_teaching"
        origin_status = "origin_verification_pending"
        stage = "metadata_pending"
        terminal = False
    else:
        decision = "review_pending"
        origin_status = "origin_confirmation_pending"
        stage = "review_pending"
        terminal = False
    return {
        **video,
        "collection_policy": collection_policy,
        "transcription_required": policy_action == "required_transcription",
        "origin_status": origin_status,
        "knowledge_admission_eligible": False,
        "decision": decision,
        "decision_reason": rules["decisions"][decision],
        "classification_signals": signals,
        "classification_rules_version": rules["_identity"]["version"],
        "classification_rules_hash": rules["_identity"]["sha256"],
        "processing_state": {
            "stage": stage,
            "terminal": terminal,
            "attempts_by_stage": {},
            "next_retry_at": None,
            "last_error_class": None,
            "last_error_at": None,
        },
    }


def may_enter_knowledge_base(item):
    """Return true only after a documented, auditable provenance decision."""

    verification = item.get("origin_verification") or {}
    methods = set(verification.get("methods") or [])
    signals = verification.get("signals") or {}
    independent_methods = {
        "cross_platform_content_match",
        "direct_video_content_review",
        "verified_source_watermark",
    }
    publisher_declared = (
        "publisher_origin_annotation" in methods
        and signals.get("uploader_profile_matches") is True
        and signals.get("publisher_text_names_liuhui") is True
        and signals.get("dedicated_origin_tag") is True
    )
    policy = item.get("collection_policy") or {}
    policy_basis = policy.get("basis")
    expected_policy_verification = {
        "collection": (
            "verified_collection_policy",
            "user_confirmed_collection_policy",
        ),
        "video_override": (
            "verified_video_policy",
            "user_confirmed_video_policy",
        ),
    }.get(policy_basis)
    policy_admitted = (
        item.get("decision") == "required_transcription_policy"
        and (item.get("collection_policy") or {}).get("action")
        == "required_transcription"
        and expected_policy_verification is not None
        and verification.get("status") == expected_policy_verification[0]
        and {
            "verified_uploader_profile",
            expected_policy_verification[1],
        }.issubset(methods)
        and signals.get("video_id_matches") is True
        and signals.get("uploader_profile_matches") is True
        and signals.get("canonical_url_matches") is True
        and signals.get("duration_valid") is True
        and bool(verification.get("verified_at"))
    )
    verified_liuhui_admitted = (
        item.get("decision")
        in {
            "candidate_liuhui_teaching",
            "required_transcription_policy",
        }
        and verification.get("status") == "verified_liuhui_clip"
        and (bool(methods & independent_methods) or publisher_declared)
        and bool(verification.get("verified_at"))
    )
    return (
        policy_admitted
        or verified_liuhui_admitted
    )
