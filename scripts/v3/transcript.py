"""Immutable transcript candidates and human-reviewed formal projections."""

from __future__ import annotations

from typing import Any

from v3 import SCHEMA_VERSION
from v3.canonical import content_id, sha256_json


SEGMENT_DECISIONS = {
    "accept_suggestion",
    "keep_raw",
    "human_corrected",
    "remove_false_positive",
}


def _nonempty(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def _time_range(start: Any, end: Any, duration_ms: int, name: str) -> tuple[int, int]:
    if not isinstance(start, int) or not isinstance(end, int):
        raise ValueError(f"{name} times must be integer milliseconds")
    if start < 0 or end <= start or end > duration_ms:
        raise ValueError(f"{name} has an invalid time range")
    return start, end


def build_candidate(
    *,
    source_id: str,
    platform: str,
    canonical_url: str,
    title: str,
    media_sha256: str,
    duration_ms: int,
    raw_segments: list[dict[str, Any]],
    asr_recipe: dict[str, Any],
    rule_version: str,
    suggestions: dict[int, dict[str, Any]] | None = None,
    alternate_urls: list[str] | None = None,
) -> dict[str, Any]:
    """Create a candidate without granting any evidentiary status."""

    _nonempty(source_id, "source id")
    _nonempty(platform, "platform")
    _nonempty(canonical_url, "canonical URL")
    _nonempty(media_sha256, "media SHA-256")
    _nonempty(rule_version, "candidate rule version")
    if len(media_sha256) != 64:
        raise ValueError("media_sha256 must contain 64 hexadecimal characters")
    try:
        int(media_sha256, 16)
    except ValueError as error:
        raise ValueError("media_sha256 must be hexadecimal") from error
    if not isinstance(duration_ms, int) or duration_ms < 0:
        raise ValueError("duration_ms must be non-negative")
    if not isinstance(asr_recipe, dict) or not asr_recipe:
        raise ValueError("ASR recipe must be a non-empty object")
    suggestion_map = suggestions or {}
    unknown_suggestions = set(suggestion_map) - set(range(len(raw_segments)))
    if unknown_suggestions:
        raise ValueError(f"suggestions reference unknown raw segments: {unknown_suggestions}")

    normalized_raw: list[dict[str, Any]] = []
    previous_end = 0
    for index, raw in enumerate(raw_segments):
        if not isinstance(raw, dict):
            raise ValueError("raw ASR segment must be an object")
        start, end = _time_range(
            raw.get("start_ms"), raw.get("end_ms"), duration_ms, "raw ASR segment"
        )
        if start < previous_end:
            raise ValueError("raw ASR segments must not overlap")
        previous_end = end
        normalized_raw.append(
            {
                "index": index,
                "start_ms": start,
                "end_ms": end,
                "text": _nonempty(raw.get("text"), "raw ASR text"),
            }
        )
    raw_identity = {
        "source_id": source_id,
        "media_sha256": media_sha256,
        "duration_ms": duration_ms,
        "asr_recipe": asr_recipe,
        "segments": normalized_raw,
    }
    raw_asr_sha256 = sha256_json(raw_identity)

    candidate_segments = []
    for raw in normalized_raw:
        segment_id = content_id(
            "seg",
            {
                "source_id": source_id,
                "raw_asr_sha256": raw_asr_sha256,
                "index": raw["index"],
                "start_ms": raw["start_ms"],
                "end_ms": raw["end_ms"],
            },
        )
        raw_index = int(raw["index"])
        suggestion = suggestion_map.get(raw_index, {})
        if not isinstance(suggestion, dict):
            raise ValueError("candidate suggestion must be an object")
        suggested_text = suggestion.get("text", raw["text"])
        _nonempty(suggested_text, "suggested text")
        risk_flags = suggestion.get("risk_flags", [])
        if not isinstance(risk_flags, list) or any(
            not isinstance(flag, str) or not flag.strip() for flag in risk_flags
        ):
            raise ValueError("risk flags must be non-empty strings")
        candidate_segments.append(
            {
                "segment_id": segment_id,
                "raw_index": raw["index"],
                "start_ms": raw["start_ms"],
                "end_ms": raw["end_ms"],
                "raw_text": raw["text"],
                "suggested_text": suggested_text.strip(),
                "suggestion_reason": str(suggestion.get("reason", "")).strip(),
                "risk_flags": sorted(set(risk_flags)),
            }
        )
    candidate_content = {
        "source_id": source_id,
        "media_sha256": media_sha256,
        "raw_asr_sha256": raw_asr_sha256,
        "duration_ms": duration_ms,
        "rule_version": rule_version,
        "segments": candidate_segments,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": content_id("candidate", candidate_content),
        "candidate_fingerprint": sha256_json(candidate_content),
        "source": {
            "source_id": source_id,
            "platform": platform,
            "canonical_url": canonical_url,
            "alternate_urls": sorted(set(alternate_urls or [])),
            "title": title,
        },
        "media": {
            "sha256": media_sha256,
            "duration_ms": duration_ms,
        },
        "raw_asr": {
            "sha256": raw_asr_sha256,
            "recipe": asr_recipe,
            "segments": normalized_raw,
        },
        "candidate": candidate_content,
        "evidence_status": "candidate_only",
    }


def validate_candidate(candidate: dict[str, Any]) -> None:
    if candidate.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("candidate schema version mismatch")
    content = candidate.get("candidate")
    if not isinstance(content, dict):
        raise ValueError("candidate content is missing")
    if candidate.get("candidate_fingerprint") != sha256_json(content):
        raise ValueError("candidate fingerprint mismatch")
    if content.get("raw_asr_sha256") != candidate.get("raw_asr", {}).get("sha256"):
        raise ValueError("candidate is bound to the wrong raw ASR")
    if content.get("media_sha256") != candidate.get("media", {}).get("sha256"):
        raise ValueError("candidate is bound to the wrong media")


def raw_registration_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    validate_candidate(candidate)
    return {
        "content": {
            "source_id": candidate["source"]["source_id"],
            "media_sha256": candidate["media"]["sha256"],
            "duration_ms": candidate["media"]["duration_ms"],
            "raw_asr_sha256": candidate["raw_asr"]["sha256"],
            "asr_recipe": candidate["raw_asr"]["recipe"],
        },
        "dependencies": [],
    }


def candidate_event_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    validate_candidate(candidate)
    return {
        "content": candidate["candidate"],
        "dependencies": [],
        "candidate_only": True,
    }


def compile_formal_transcript(
    candidate: dict[str, Any],
    decisions: list[dict[str, Any]],
    insertions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compile every explicit human response into a private formal projection."""

    validate_candidate(candidate)
    if not isinstance(decisions, list):
        raise ValueError("segment decisions must be a list")
    candidate_segments = {
        segment["segment_id"]: segment for segment in candidate["candidate"]["segments"]
    }
    decision_map: dict[str, dict[str, Any]] = {}
    for decision in decisions:
        if not isinstance(decision, dict):
            raise ValueError("segment decision must be an object")
        segment_id = decision.get("segment_id")
        if not isinstance(segment_id, str) or segment_id not in candidate_segments:
            raise ValueError(f"decision references unknown segment: {segment_id}")
        if segment_id in decision_map:
            raise ValueError(f"duplicate segment decision: {segment_id}")
        if decision.get("decision") not in SEGMENT_DECISIONS:
            raise ValueError(f"unsupported segment decision: {decision.get('decision')}")
        decision_map[segment_id] = decision
    missing = set(candidate_segments) - set(decision_map)
    if missing:
        raise ValueError(f"every raw ASR segment requires a decision: {sorted(missing)}")

    duration_ms = candidate["media"]["duration_ms"]
    formal_segments: list[dict[str, Any]] = []
    audit_decisions: list[dict[str, Any]] = []
    for segment_id, segment in candidate_segments.items():
        response = decision_map[segment_id]
        decision = response["decision"]
        start = response.get("start_ms", segment["start_ms"])
        end = response.get("end_ms", segment["end_ms"])
        start, end = _time_range(start, end, duration_ms, "reviewed segment")
        if decision == "remove_false_positive":
            _nonempty(response.get("reason"), "false-positive removal reason")
            audit_decisions.append(
                {
                    "segment_id": segment_id,
                    "decision": decision,
                    "reason": response["reason"].strip(),
                }
            )
            continue
        if decision == "keep_raw":
            text = segment["raw_text"]
        elif decision == "accept_suggestion":
            text = segment["suggested_text"]
        else:
            text = _nonempty(response.get("text"), "human-corrected text")
        formal_segments.append(
            {
                "segment_id": segment_id,
                "start_ms": start,
                "end_ms": end,
                "text": text.strip(),
                "correction_method": decision,
            }
        )
        audit_decisions.append(
            {
                "segment_id": segment_id,
                "decision": decision,
                "start_ms": start,
                "end_ms": end,
            }
        )

    insertion_audit = []
    for index, insertion in enumerate(insertions or []):
        if not isinstance(insertion, dict):
            raise ValueError("transcript insertion must be an object")
        start, end = _time_range(
            insertion.get("start_ms"),
            insertion.get("end_ms"),
            duration_ms,
            "transcript insertion",
        )
        text = _nonempty(insertion.get("text"), "inserted transcript text")
        reason = _nonempty(insertion.get("reason"), "transcript insertion reason")
        insertion_id = content_id(
            "insert",
            {
                "candidate_fingerprint": candidate["candidate_fingerprint"],
                "index": index,
                "start_ms": start,
                "end_ms": end,
                "text": text,
            },
        )
        formal_segments.append(
            {
                "segment_id": insertion_id,
                "start_ms": start,
                "end_ms": end,
                "text": text,
                "correction_method": "human_inserted",
            }
        )
        insertion_audit.append({"segment_id": insertion_id, "reason": reason})

    formal_segments.sort(
        key=lambda segment: (segment["start_ms"], segment["end_ms"], segment["segment_id"])
    )
    previous_end = 0
    for segment in formal_segments:
        if segment["start_ms"] < previous_end:
            raise ValueError("reviewed transcript segments must not overlap")
        previous_end = segment["end_ms"]
    projection = {
        "source_id": candidate["source"]["source_id"],
        "media_sha256": candidate["media"]["sha256"],
        "raw_asr_sha256": candidate["raw_asr"]["sha256"],
        "duration_ms": duration_ms,
        "segments": formal_segments,
    }
    formal_projection_sha256 = sha256_json(projection)
    content = dict(projection)
    content["formal_projection_sha256"] = formal_projection_sha256
    content["candidate_fingerprint"] = candidate["candidate_fingerprint"]
    content["rule_version"] = candidate["candidate"]["rule_version"]
    return {
        "transcript_revision_id": content_id(
            "transcript",
            {
                "source_id": projection["source_id"],
                "raw_asr_sha256": projection["raw_asr_sha256"],
                "rule_version": content["rule_version"],
                "formal_projection_sha256": formal_projection_sha256,
            },
        ),
        "formal_projection": content,
        "audit": {
            "segment_decisions": audit_decisions,
            "insertions": insertion_audit,
        },
        "evidence_status": "awaiting_completeness_confirmation",
    }


def verification_payload(
    compiled: dict[str, Any], attestation: dict[str, Any]
) -> dict[str, Any]:
    if not isinstance(compiled.get("formal_projection"), dict):
        raise ValueError("compiled formal transcript is missing")
    if not isinstance(attestation, dict):
        raise ValueError("completeness attestation must be an object")
    return {
        "content": compiled["formal_projection"],
        "dependencies": [],
        "attestation": attestation,
        "private_audit": compiled.get("audit", {}),
    }


def evidence_window(
    formal_content: dict[str, Any], segment_ids: list[str]
) -> dict[str, Any]:
    selected = [
        segment
        for segment in formal_content.get("segments", [])
        if segment.get("segment_id") in segment_ids
    ]
    if len(selected) != len(set(segment_ids)) or not selected:
        raise ValueError("evidence window references missing formal segments")
    selected.sort(key=lambda segment: (segment["start_ms"], segment["end_ms"]))
    return {
        "segment_ids": [segment["segment_id"] for segment in selected],
        "text": " ".join(segment["text"].strip() for segment in selected),
    }
