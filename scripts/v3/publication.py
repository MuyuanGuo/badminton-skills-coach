"""Sanitize private ledger state into the only allowed public v3 input."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from v3 import SCHEMA_VERSION
from v3.canonical import atomic_write_json, sha256_json
from v3.ledger import ACTIVE_DEPENDENCY_STATES, ReviewLedger


_ABSOLUTE_WINDOWS_PATH = re.compile(r"^[A-Za-z]:[\\/]")
_FORBIDDEN_KEYS = {
    "asr_recipe",
    "attestation",
    "draft",
    "draft_json",
    "human_confirmation",
    "media_path",
    "payload",
    "private_audit",
    "raw_asr",
    "raw_asr_sha256",
    "reviewer",
    "reviewer_id",
    "segment_ids",
    "segments",
    "transcript",
}
_TOP_LEVEL_KEYS = {
    "schema_version",
    "kind",
    "scope",
    "sources",
    "teaching_events",
    "semantic_claims",
    "review_provenance",
    "privacy_contract",
    "publication_id",
    "publication_fingerprint",
}


def _leak_paths(value: Any, path: str = "$") -> list[str]:
    leaks: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key.casefold() in _FORBIDDEN_KEYS:
                leaks.append(f"{child_path}: forbidden private key")
            leaks.extend(_leak_paths(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            leaks.extend(_leak_paths(child, f"{path}[{index}]"))
    elif isinstance(value, str):
        folded = value.casefold()
        if value.startswith("/") or _ABSOLUTE_WINDOWS_PATH.match(value):
            leaks.append(f"{path}: absolute local path")
        if ".local/v3" in folded or "file://" in folded:
            leaks.append(f"{path}: private workspace reference")
    return leaks


def assert_no_private_leaks(value: Any) -> None:
    leaks = _leak_paths(value)
    if leaks:
        raise ValueError("private data leak detected: " + "; ".join(leaks))


def _publication_body(publication: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in publication.items()
        if key not in {"publication_id", "publication_fingerprint"}
    }


def finalize_publication(body: dict[str, Any]) -> dict[str, Any]:
    if set(body) & {"publication_id", "publication_fingerprint"}:
        raise ValueError("publication body must not contain identity fields")
    fingerprint = sha256_json(body)
    publication = dict(body)
    publication["publication_id"] = f"publication_{fingerprint[:24]}"
    publication["publication_fingerprint"] = fingerprint
    validate_publication(publication)
    return publication


def empty_publication() -> dict[str, Any]:
    return finalize_publication(
        {
            "schema_version": SCHEMA_VERSION,
            "kind": "v3-shadow-publication",
            "scope": {"mode": "shadow", "topics": []},
            "sources": [],
            "teaching_events": [],
            "semantic_claims": [],
            "review_provenance": {
                "ledger_schema_version": SCHEMA_VERSION,
                "approved_entity_event_ids": [],
                "chain_fingerprint": sha256_json([]),
            },
            "privacy_contract": {
                "full_transcripts_included": False,
                "raw_asr_included": False,
                "reviewer_identities_included": False,
                "sealed_evaluations_included": False,
            },
        }
    )


def _current_dependency(
    ledger: ReviewLedger, dependency: dict[str, Any]
) -> dict[str, Any]:
    head = ledger.head(dependency["entity_type"], dependency["entity_id"])
    if head is None:
        raise ValueError(
            "publication dependency is missing: "
            f"{dependency['entity_type']}:{dependency['entity_id']}"
        )
    if head["content_fingerprint"] != dependency["fingerprint"]:
        raise ValueError(
            "publication dependency fingerprint is stale: "
            f"{dependency['entity_type']}:{dependency['entity_id']}"
        )
    if head["state"] not in ACTIVE_DEPENDENCY_STATES:
        raise ValueError(
            "publication dependency is not formally verified: "
            f"{dependency['entity_type']}:{dependency['entity_id']}"
        )
    return head


def _public_source(source: dict[str, Any]) -> dict[str, Any]:
    required = {"source_id", "platform", "canonical_url", "alternate_urls", "title"}
    if set(source) != required:
        raise ValueError("source metadata must contain only the public source fields")
    if not all(isinstance(source[field], str) and source[field].strip() for field in required - {"alternate_urls"}):
        raise ValueError("public source metadata contains an empty value")
    if not isinstance(source["alternate_urls"], list):
        raise ValueError("alternate URLs must be a list")
    return {
        "source_id": source["source_id"],
        "platform": source["platform"],
        "canonical_url": source["canonical_url"],
        "alternate_urls": sorted(set(source["alternate_urls"])),
        "title": source["title"],
    }


def export_publication(
    ledger: ReviewLedger, topics: set[str] | None = None
) -> dict[str, Any]:
    """Export only current published claims and their claim-scoped evidence."""

    ledger.verify_integrity()
    sources: dict[str, dict[str, Any]] = {}
    events: dict[str, dict[str, Any]] = {}
    claims: list[dict[str, Any]] = []
    approved_event_ids: set[str] = set()
    selected_topics: set[str] = set()

    def include_review_chain(entity_type: str, entity_id: str) -> None:
        approved_event_ids.update(
            event["event_id"] for event in ledger.events(entity_type, entity_id)
        )

    for claim_head in ledger.heads("semantic_claim"):
        if claim_head["state"] != "published":
            continue
        content = claim_head["payload"]["content"]
        if topics is not None and content.get("topic") not in topics:
            continue
        support_ids = content.get("support_event_ids", [])
        public_support_ids: list[str] = []
        claim_dependencies = claim_head["payload"].get("dependencies", [])
        dependency_by_id = {
            dependency["entity_id"]: dependency
            for dependency in claim_dependencies
            if dependency["entity_type"] == "teaching_event"
        }
        if sorted(support_ids) != sorted(dependency_by_id):
            raise ValueError(f"published claim supports are inconsistent: {claim_head['entity_id']}")
        for event_id in support_ids:
            event_head = _current_dependency(ledger, dependency_by_id[event_id])
            if event_head["state"] != "source_verified":
                raise ValueError(f"supporting event is not source verified: {event_id}")
            event_content = event_head["payload"]["content"]
            transcript_dependencies = [
                dependency
                for dependency in event_head["payload"].get("dependencies", [])
                if dependency["entity_type"] == "transcript"
            ]
            for dependency in transcript_dependencies:
                transcript_head = _current_dependency(ledger, dependency)
                if transcript_head["state"] != "source_verified":
                    raise ValueError(f"event transcript is not source verified: {event_id}")
                include_review_chain("transcript", transcript_head["entity_id"])
            source = _public_source(event_content["source"])
            existing_source = sources.get(source["source_id"])
            if existing_source is not None and existing_source != source:
                raise ValueError(f"conflicting public source metadata: {source['source_id']}")
            sources[source["source_id"]] = source
            window = event_content["evidence_window"]
            text = window.get("text", "")
            visual_observation = window.get("visual_observation", "")
            if not isinstance(text, str) or not isinstance(visual_observation, str):
                raise ValueError("evidence window values must be text")
            if len(text) > 500 or len(visual_observation) > 500:
                raise ValueError("public evidence window exceeds the 500-character limit")
            if event_content["end_ms"] - event_content["start_ms"] > 120_000:
                raise ValueError("public evidence window exceeds the 120-second limit")
            public_event = {
                "teaching_event_id": event_id,
                "source_id": source["source_id"],
                "start_ms": event_content["start_ms"],
                "end_ms": event_content["end_ms"],
                "modality": event_content["modality"],
                "evidence_boundary": event_content["evidence_boundary"],
                "evidence_text": text,
                "visual_observation": visual_observation,
                "viewing_value": event_content.get("viewing_value", ""),
                "watch_focus": event_content.get("watch_focus", ""),
                "formal_projection_sha256": event_content.get(
                    "formal_projection_sha256", ""
                ),
            }
            existing_event = events.get(event_id)
            if existing_event is not None and existing_event != public_event:
                raise ValueError(f"conflicting public teaching event: {event_id}")
            events[event_id] = public_event
            include_review_chain("teaching_event", event_id)
            public_support_ids.append(event_id)
        public_claim = {
            "claim_id": claim_head["entity_id"],
            "topic": content["topic"],
            "symptoms": content["symptoms"],
            "applicability": content["applicability"],
            "mechanism": content["mechanism"],
            "correction_direction": content["correction_direction"],
            "exclusions": content["exclusions"],
            "confidence": content["confidence"],
            "training_method": content.get("training_method", ""),
            "aliases": sorted(set(content.get("aliases", []))),
            "support_event_ids": sorted(public_support_ids),
        }
        claims.append(public_claim)
        selected_topics.add(content["topic"])
        include_review_chain("semantic_claim", claim_head["entity_id"])

    ordered_event_ids = sorted(approved_event_ids)
    return finalize_publication(
        {
            "schema_version": SCHEMA_VERSION,
            "kind": "v3-shadow-publication",
            "scope": {"mode": "shadow", "topics": sorted(selected_topics)},
            "sources": [sources[source_id] for source_id in sorted(sources)],
            "teaching_events": [events[event_id] for event_id in sorted(events)],
            "semantic_claims": sorted(claims, key=lambda claim: claim["claim_id"]),
            "review_provenance": {
                "ledger_schema_version": SCHEMA_VERSION,
                "approved_entity_event_ids": ordered_event_ids,
                "chain_fingerprint": sha256_json(ordered_event_ids),
            },
            "privacy_contract": {
                "full_transcripts_included": False,
                "raw_asr_included": False,
                "reviewer_identities_included": False,
                "sealed_evaluations_included": False,
            },
        }
    )


def write_publication(
    ledger: ReviewLedger,
    path: Path,
    topics: set[str] | None = None,
) -> dict[str, Any]:
    """Export, validate, and atomically write the public projection."""

    publication = export_publication(ledger, topics)
    counts = validate_publication(publication)
    atomic_write_json(path, publication, indent=2)
    return {
        "publication": str(path),
        "publication_id": publication["publication_id"],
        "publication_fingerprint": publication["publication_fingerprint"],
        **counts,
    }


def validate_publication(publication: dict[str, Any]) -> dict[str, int]:
    if set(publication) != _TOP_LEVEL_KEYS:
        raise ValueError("publication top-level fields do not match the v3 contract")
    if publication.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("publication schema version mismatch")
    if publication.get("kind") != "v3-shadow-publication":
        raise ValueError("publication kind mismatch")
    body = _publication_body(publication)
    fingerprint = sha256_json(body)
    if publication.get("publication_fingerprint") != fingerprint:
        raise ValueError("publication fingerprint mismatch")
    if publication.get("publication_id") != f"publication_{fingerprint[:24]}":
        raise ValueError("publication identity mismatch")
    privacy = publication.get("privacy_contract")
    if not isinstance(privacy, dict) or any(privacy.values()):
        raise ValueError("publication privacy contract must exclude all private classes")
    sources = publication.get("sources")
    events = publication.get("teaching_events")
    claims = publication.get("semantic_claims")
    if not isinstance(sources, list) or not isinstance(events, list) or not isinstance(claims, list):
        raise ValueError("publication entity collections must be lists")
    source_ids = [source.get("source_id") for source in sources]
    event_ids = [event.get("teaching_event_id") for event in events]
    claim_ids = [claim.get("claim_id") for claim in claims]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("publication source ids are not unique")
    if len(event_ids) != len(set(event_ids)):
        raise ValueError("publication teaching event ids are not unique")
    if len(claim_ids) != len(set(claim_ids)):
        raise ValueError("publication claim ids are not unique")
    known_sources = set(source_ids)
    known_events = set(event_ids)
    for event in events:
        if event.get("source_id") not in known_sources:
            raise ValueError("publication event references an unknown source")
        if len(event.get("evidence_text", "")) > 500:
            raise ValueError("publication evidence text is too long")
    for claim in claims:
        supports = claim.get("support_event_ids")
        if not isinstance(supports, list) or not supports:
            raise ValueError("published claim requires public support events")
        if not set(supports) <= known_events:
            raise ValueError("publication claim references an unknown event")
        for field in ("applicability", "exclusions"):
            if not isinstance(claim.get(field), list) or not claim[field]:
                raise ValueError(f"published claim requires {field}")
    assert_no_private_leaks(publication)
    return {"sources": len(sources), "events": len(events), "claims": len(claims)}
