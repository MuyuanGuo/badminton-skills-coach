"""Build a sanitized input-status inventory for all answer-eligible sources."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from v3 import SCHEMA_VERSION
from v3.canonical import atomic_write_json, sha256_json


ANSWER_ELIGIBILITY = {"primary", "supplemental"}


def source_identity(video: dict[str, Any], douyin_profile_id: str) -> tuple[str, str, str]:
    """Return the stable v3 identity for a supported source record."""

    source_type = video.get("source_type")
    if source_type == "douyin_video":
        native_id = str(video.get("video_id") or "").strip()
        publisher_id = douyin_profile_id
        platform = "douyin"
    elif source_type == "bilibili_video":
        native_id = str(video.get("source_video_id") or "").strip()
        publisher_id = str(video.get("uploader_profile_id") or "").strip()
        platform = "bilibili"
    else:
        raise ValueError(f"unsupported v3 inventory source type: {source_type}")
    if not native_id or not publisher_id:
        raise ValueError("source identity requires native video and publisher ids")
    return f"{platform}:{publisher_id}:{native_id}", platform, native_id


# Kept for callers from the M1 implementation that imported the private helper.
_source_identity = source_identity


def _candidate_status(
    root: Path, video: dict[str, Any]
) -> tuple[str, str, str]:
    transcript_path_value = str(video.get("transcript_file") or "")
    transcript_path = root / transcript_path_value if transcript_path_value else None
    embedded = video.get("transcript_segments")
    if transcript_path is not None and transcript_path.is_file():
        transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
        transcript_status = "local_candidate_present"
        transcript_fingerprint = sha256_json(transcript)
        source_file = str(transcript.get("source_file") or "")
        media_status = (
            "local_candidate_present_unhashed"
            if source_file and (root / source_file).is_file()
            else "input_missing"
        )
    elif isinstance(embedded, list) and embedded:
        transcript_status = "embedded_legacy_candidate"
        transcript_fingerprint = sha256_json(embedded)
        media_status = "input_missing"
    else:
        transcript_status = "input_missing"
        transcript_fingerprint = ""
        media_status = "input_missing"
    return transcript_status, transcript_fingerprint, media_status


def eligible_source_identities(
    knowledge: dict[str, Any], douyin_profile_id: str
) -> set[str]:
    return {
        source_identity(video, douyin_profile_id)[0]
        for video in knowledge.get("videos", [])
        if video.get("answer_eligibility") in ANSWER_ELIGIBILITY
    }


def build_source_inventory(
    root: Path,
    knowledge_path: Path,
    douyin_source_path: Path,
) -> dict[str, Any]:
    knowledge = json.loads(knowledge_path.read_text(encoding="utf-8"))
    source_config = json.loads(douyin_source_path.read_text(encoding="utf-8"))
    douyin_profile_id = str(source_config.get("profile_id") or "").strip()
    if not douyin_profile_id:
        raise ValueError("Douyin source profile identity is missing")
    sources = []
    for video in knowledge.get("videos", []):
        if video.get("answer_eligibility") not in ANSWER_ELIGIBILITY:
            continue
        source_id, platform, native_id = source_identity(video, douyin_profile_id)
        transcript_status, transcript_fingerprint, media_status = _candidate_status(
            root, video
        )
        canonical_url = str(video.get("canonical_url") or video.get("url") or "")
        if not canonical_url.startswith("https://"):
            raise ValueError(f"source canonical URL is invalid: {source_id}")
        sources.append(
            {
                "source_id": source_id,
                "legacy_evidence_id": str(video.get("evidence_id") or video["video_id"]),
                "platform": platform,
                "native_video_id": native_id,
                "canonical_url": canonical_url,
                "answer_eligibility": video["answer_eligibility"],
                "candidate_transcript_status": transcript_status,
                "candidate_transcript_fingerprint": transcript_fingerprint,
                "candidate_media_status": media_status,
                "mirror_resolution_status": "unresolved",
                "v3_formal_status": "missing",
            }
        )
    sources.sort(key=lambda item: item["source_id"])
    identities = [source["source_id"] for source in sources]
    if len(identities) != len(set(identities)):
        raise ValueError("v3 source inventory identities are not unique")
    transcript_counts = Counter(
        source["candidate_transcript_status"] for source in sources
    )
    media_counts = Counter(source["candidate_media_status"] for source in sources)
    platform_counts = Counter(source["platform"] for source in sources)
    body = {
        "schema_version": SCHEMA_VERSION,
        "kind": "v3-sanitized-source-inventory",
        "authority": "private_input_snapshot_candidate_only",
        "summary": {
            "answer_eligible_sources": len(sources),
            "by_platform": dict(sorted(platform_counts.items())),
            "by_candidate_transcript_status": dict(sorted(transcript_counts.items())),
            "by_candidate_media_status": dict(sorted(media_counts.items())),
            "v3_formal_sources": 0,
        },
        "sources": sources,
    }
    result = dict(body)
    result["inventory_fingerprint"] = sha256_json(body)
    return result


def validate_source_inventory(inventory: dict[str, Any]) -> dict[str, int]:
    if inventory.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("v3 source inventory schema mismatch")
    if inventory.get("kind") != "v3-sanitized-source-inventory":
        raise ValueError("v3 source inventory kind mismatch")
    body = {
        key: value
        for key, value in inventory.items()
        if key != "inventory_fingerprint"
    }
    if inventory.get("inventory_fingerprint") != sha256_json(body):
        raise ValueError("v3 source inventory fingerprint mismatch")
    sources = inventory.get("sources")
    if not isinstance(sources, list):
        raise ValueError("v3 source inventory sources must be a list")
    identities = [source.get("source_id") for source in sources]
    if len(identities) != len(set(identities)):
        raise ValueError("v3 source inventory identities are not unique")
    summary = inventory.get("summary")
    if not isinstance(summary, dict) or summary.get("answer_eligible_sources") != len(
        sources
    ):
        raise ValueError("v3 source inventory summary count mismatch")
    if any(source.get("v3_formal_status") != "missing" for source in sources):
        raise ValueError("M1 inventory cannot claim a formal v3 source")
    expected_transcript_counts = dict(
        sorted(Counter(source.get("candidate_transcript_status") for source in sources).items())
    )
    expected_media_counts = dict(
        sorted(Counter(source.get("candidate_media_status") for source in sources).items())
    )
    expected_platform_counts = dict(
        sorted(Counter(source.get("platform") for source in sources).items())
    )
    if summary.get("by_candidate_transcript_status") != expected_transcript_counts:
        raise ValueError("v3 source inventory transcript summary mismatch")
    if summary.get("by_candidate_media_status") != expected_media_counts:
        raise ValueError("v3 source inventory media summary mismatch")
    if summary.get("by_platform") != expected_platform_counts:
        raise ValueError("v3 source inventory platform summary mismatch")
    return {"sources": len(sources), "formal_sources": 0}


def validate_inventory_source_coverage(
    inventory: dict[str, Any],
    knowledge_path: Path,
    douyin_source_path: Path,
) -> None:
    knowledge = json.loads(knowledge_path.read_text(encoding="utf-8"))
    source_config = json.loads(douyin_source_path.read_text(encoding="utf-8"))
    expected = eligible_source_identities(
        knowledge, str(source_config.get("profile_id") or "").strip()
    )
    actual = {source["source_id"] for source in inventory["sources"]}
    if actual != expected:
        missing = sorted(expected - actual)[:5]
        unexpected = sorted(actual - expected)[:5]
        raise ValueError(
            "v3 source inventory coverage mismatch: "
            f"missing={missing}, unexpected={unexpected}"
        )


def write_source_inventory(
    root: Path,
    output_path: Path,
    knowledge_path: Path | None = None,
    douyin_source_path: Path | None = None,
) -> dict[str, Any]:
    inventory = build_source_inventory(
        root,
        knowledge_path or root / "data/knowledge/douyin_knowledge_base.json",
        douyin_source_path or root / "config/douyin_source.json",
    )
    validate_source_inventory(inventory)
    atomic_write_json(output_path, inventory, indent=2)
    return inventory
