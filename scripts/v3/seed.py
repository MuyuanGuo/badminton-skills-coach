"""Seed one real, explicitly unapproved vertical-slice candidate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from v3 import SCHEMA_VERSION
from v3.canonical import atomic_write_json, sha256_file, sha256_text
from v3.ledger import ReviewLedger
from v3.transcript import (
    build_candidate,
    candidate_event_payload,
    raw_registration_payload,
)


DEFAULT_VIDEO_ID = "7589749293205363633"


def _find_video(knowledge: dict[str, Any], video_id: str) -> dict[str, Any]:
    videos = knowledge.get("videos")
    if not isinstance(videos, list):
        raise ValueError("knowledge base videos are missing")
    matches = [video for video in videos if video.get("video_id") == video_id]
    if len(matches) != 1:
        raise ValueError(f"expected one knowledge record for {video_id}, found {len(matches)}")
    return matches[0]


def _load_private_suggestions(
    path: Path | None,
    *,
    video_id: str,
    raw_segments: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    """Load optional review hints without placing private transcript text in Git."""

    if path is None:
        return {}
    if not path.is_file():
        raise ValueError(f"private suggestion file is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("private suggestion schema version mismatch")
    if payload.get("kind") != "private-candidate-suggestions":
        raise ValueError("private suggestion kind mismatch")
    if payload.get("video_id") != video_id:
        raise ValueError("private suggestions belong to another video")
    entries = payload.get("suggestions")
    if not isinstance(entries, list):
        raise ValueError("private suggestions must be a list")

    suggestions: dict[int, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("private suggestion entry must be an object")
        index = entry.get("segment_index")
        if not isinstance(index, int) or isinstance(index, bool):
            raise ValueError("private suggestion segment_index must be an integer")
        if index < 0 or index >= len(raw_segments):
            raise ValueError("private suggestion references an unknown segment")
        if index in suggestions:
            raise ValueError("private suggestion segment_index must be unique")
        expected_hash = str(entry.get("raw_text_sha256") or "").strip()
        actual_hash = sha256_text(str(raw_segments[index]["text"]))
        if expected_hash != actual_hash:
            raise ValueError("private suggestion is bound to different raw text")
        suggested_text = str(entry.get("suggested_text") or "").strip()
        reason = str(entry.get("reason") or "").strip()
        risk_flags = entry.get("risk_flags")
        if not suggested_text or not reason:
            raise ValueError("private suggestion text and reason are required")
        if not isinstance(risk_flags, list) or any(
            not isinstance(flag, str) or not flag.strip() for flag in risk_flags
        ):
            raise ValueError("private suggestion risk_flags must be non-empty strings")
        suggestions[index] = {
            "text": suggested_text,
            "reason": reason,
            "risk_flags": risk_flags,
        }
    return suggestions


def seed_vertical_slice(
    *,
    video_id: str,
    knowledge_path: Path,
    source_config_path: Path,
    transcript_path: Path,
    media_path: Path,
    private_root: Path,
    suggestions_path: Path | None = None,
) -> dict[str, Any]:
    knowledge = json.loads(knowledge_path.read_text(encoding="utf-8"))
    source_config = json.loads(source_config_path.read_text(encoding="utf-8"))
    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    video = _find_video(knowledge, video_id)
    if transcript.get("video_id") != video_id:
        raise ValueError("transcript belongs to another video")
    if not media_path.is_file():
        raise ValueError(f"vertical-slice media is missing: {media_path}")
    duration_ms = round(float(transcript.get("duration", 0)) * 1000)
    raw_segments = [
        {
            "start_ms": round(float(segment["start"]) * 1000),
            "end_ms": round(float(segment["end"]) * 1000),
            "text": str(segment["text"]).strip(),
        }
        for segment in transcript.get("segments", [])
    ]
    suggestions = _load_private_suggestions(
        suggestions_path,
        video_id=video_id,
        raw_segments=raw_segments,
    )
    profile_id = str(source_config.get("profile_id") or "").strip()
    if not profile_id:
        raise ValueError("source profile identity is missing")
    candidate = build_candidate(
        source_id=f"douyin:{profile_id}:{video_id}",
        platform="douyin",
        canonical_url=str(video.get("canonical_url") or video.get("url") or ""),
        alternate_urls=[],
        title=str(video.get("title") or ""),
        media_sha256=sha256_file(media_path),
        duration_ms=duration_ms,
        raw_segments=raw_segments,
        asr_recipe={
            "engine": "faster-whisper",
            "model": transcript.get("model"),
            "language": transcript.get("language"),
            "transcript_input_sha256": sha256_file(transcript_path),
            "legacy_parameters_complete": False,
        },
        rule_version="v3-vertical-slice-suggestions-v1",
        suggestions=suggestions,
    )
    candidate_path = private_root / "candidates" / f"{video_id}.json"
    ledger_path = private_root / "review" / "review-ledger.sqlite3"
    session_path = private_root / "review" / "vertical-slice-session.json"
    atomic_write_json(candidate_path, candidate)
    with ReviewLedger(ledger_path) as ledger:
        transcript_id = candidate["candidate_id"]
        head = ledger.head("transcript", transcript_id)
        if head is None:
            ledger.append_event(
                entity_type="transcript",
                entity_id=transcript_id,
                action="register_raw",
                reviewer_id="system:vertical-slice-seed",
                human_confirmation=False,
                payload=raw_registration_payload(candidate),
                expected_revision=0,
                expected_base_fingerprint="",
            )
            head = ledger.head("transcript", transcript_id)
            assert head is not None
            ledger.append_event(
                entity_type="transcript",
                entity_id=transcript_id,
                action="create_candidate",
                reviewer_id="system:vertical-slice-seed",
                human_confirmation=False,
                payload=candidate_event_payload(candidate),
                expected_revision=int(head["revision"]),
                expected_base_fingerprint=head["content_fingerprint"],
            )
        else:
            candidate_fingerprint = candidate_event_payload(candidate)["content"]
            if head["state"] in {"raw_available", "stale"}:
                ledger.append_event(
                    entity_type="transcript",
                    entity_id=transcript_id,
                    action="create_candidate",
                    reviewer_id="system:vertical-slice-seed",
                    human_confirmation=False,
                    payload=candidate_event_payload(candidate),
                    expected_revision=int(head["revision"]),
                    expected_base_fingerprint=head["content_fingerprint"],
                )
            elif head["state"] == "candidate" and head["payload"]["content"] != candidate_fingerprint:
                raise ValueError("existing candidate state is bound to different content")
        ledger.verify_integrity()
        final_head = ledger.head("transcript", transcript_id)
        assert final_head is not None
    session = {
        "schema_version": candidate["schema_version"],
        "candidate_path": str(candidate_path.resolve()),
        "candidate_fingerprint": candidate["candidate_fingerprint"],
        "ledger_path": str(ledger_path.resolve()),
        "media_path": str(media_path.resolve()),
        "media_sha256": candidate["media"]["sha256"],
        "transcript_entity_id": candidate["candidate_id"],
        "evidence_status": "candidate_only",
    }
    atomic_write_json(session_path, session)
    return {
        "candidate_id": candidate["candidate_id"],
        "candidate_path": str(candidate_path),
        "ledger_path": str(ledger_path),
        "session_path": str(session_path),
        "media_sha256": candidate["media"]["sha256"],
        "state": final_head["state"],
        "evidence_status": "candidate_only",
        "formal_approvals_created": 0,
        "private_suggestions_loaded": len(suggestions),
    }
