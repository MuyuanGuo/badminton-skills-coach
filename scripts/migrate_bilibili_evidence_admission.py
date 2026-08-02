#!/usr/bin/env python3
"""Migrate committed Bilibili evidence to the split admission model.

This migration is intentionally able to operate without the ephemeral raw
transcript cache.  A formerly quarantined record is admitted only when its
committed audit fields prove origin and source safety, then either the normal
automatic gate passes with non-blocking transcript issues or the role-aware
bounded-note recovery gate finds enough timestamped instructional evidence.
Such records expose only their already-bounded timestamped note windows until
a future full rebuild restores a verified raw transcript.
"""

import argparse
import copy
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from evidence_admission import (
    answer_admission,
    assess_bounded_note_recovery,
    infer_evidence_roles,
)
from project_artifacts import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_PATH = ROOT / "data" / "knowledge" / "bilibili_knowledge_base.json"
RULES_PATH = ROOT / "config" / "knowledge_quality_rules.json"


def restrict_note_to_recovered_windows(note, recovery):
    restricted = copy.deepcopy(note or {})
    allowed = {
        (item["field"], item["timestamp"])
        for item in recovery.get("supported_windows") or []
    }
    for field in ("key_evidence", "error_evidence", "action_cues"):
        restricted[field] = [
            item
            for item in restricted.get(field) or []
            if (field, str(item.get("timestamp") or "").strip()) in allowed
        ]
    return restricted


def migrate_record(record, rules):
    migrated = copy.deepcopy(record)
    quality = migrated.get("quality") or {}
    automatic = quality.get("automatic_evidence") or {}
    admission = answer_admission(
        origin_passed=(
            (quality.get("origin_verification") or {}).get("passed") is True
        ),
        transcript_issues=(quality.get("transcript") or {}).get("issues") or [],
        source_content_safe=(
            (quality.get("source_content_safety") or {}).get("passed") is True
        ),
        automatic_evidence_passed=automatic.get("passed") is True,
        duplicate=bool(migrated.get("possible_duplicate_evidence")),
    )
    recovery = assess_bounded_note_recovery(migrated, rules)
    if not automatic.get("passed"):
        quality["bounded_note_recovery"] = recovery
    elif "bounded_note_recovery" in quality:
        quality.pop("bounded_note_recovery")
    migrated["quality"] = quality

    committed_note_only = (
        (
            migrated.get("processing_status") == "low_value"
            or migrated.get("runtime_evidence_mode")
            == "bounded_note_windows"
        )
        and admission["answer_evidence_eligible"]
    )
    if recovery["passed"] or committed_note_only:
        migrated["processing_status"] = "ready"
        migrated["confidence"] = "supplemental_note_only"
        migrated["answer_eligibility"] = "supplemental"
        migrated["runtime_evidence_mode"] = "bounded_note_windows"
        migrated["metadata_title_trust"] = "limited"
        admission = {
            "disposition": (
                "supplemental_bounded_note_recovery"
                if recovery["passed"]
                else admission["disposition"]
            ),
            "answer_evidence_eligible": True,
            "answer_eligibility": "supplemental",
            "advisory_issues": sorted(
                set(admission["advisory_issues"])
                | (
                    set(automatic.get("issues") or [])
                    if recovery["passed"]
                    else set()
                )
            ),
            "blocking_issues": [],
            "rules_version": rules["version"],
        }
        note = migrated.get("teaching_note") or {}
        if recovery["passed"]:
            note = restrict_note_to_recovered_windows(note, recovery)
        note["note"] = (
            "来源、安全与证据门禁已通过；仅允许使用已提交的带时间戳证据窗口补充主证据。"
        )
        migrated["teaching_note"] = note
        migrated["transcript_segments"] = []
    elif admission["answer_evidence_eligible"]:
        migrated["processing_status"] = "ready"
        migrated["answer_eligibility"] = admission["answer_eligibility"]
        migrated["runtime_evidence_mode"] = "full_transcript"
        migrated["metadata_title_trust"] = admission["metadata_title_trust"]
        if admission["answer_eligibility"] == "supplemental":
            migrated["confidence"] = "supplemental_transcript"
    else:
        migrated["answer_eligibility"] = "none"
        migrated["runtime_evidence_mode"] = "quarantined"
        migrated["metadata_title_trust"] = admission["metadata_title_trust"]
        migrated["transcript_segments"] = []
    admission.pop("metadata_title_trust", None)
    admission["rules_version"] = rules["version"]
    migrated["automatic_admission"] = admission
    evidence_roles = set(infer_evidence_roles(
        migrated.get("category"),
        migrated.get("retrieval_title") or migrated.get("title"),
        migrated.get("teaching_note"),
    ))
    evidence_roles.update(recovery["roles"] if recovery["passed"] else [])
    migrated["evidence_roles"] = sorted(evidence_roles)
    return migrated


def migrate_knowledge(payload, rules=None, now=None):
    rules = rules or json.loads(RULES_PATH.read_text(encoding="utf-8"))
    migrated = copy.deepcopy(payload)
    records = [
        migrate_record(record, rules) for record in payload.get("videos", [])
    ]
    migrated["videos"] = records
    migrated["evidence_schema_version"] = 2
    migrated["quality_rules_version"] = rules["version"]
    status_counts = Counter(record["processing_status"] for record in records)
    migrated["knowledge_counts"] = {
        "videos": len(records),
        **dict(status_counts),
        "primary": sum(
            record.get("answer_eligibility") == "primary"
            for record in records
        ),
        "supplemental": sum(
            record.get("answer_eligibility") == "supplemental"
            for record in records
        ),
        "answer_ineligible": sum(
            record.get("answer_eligibility") == "none"
            for record in records
        ),
        "full_transcript_ready": sum(
            record.get("processing_status") == "ready"
            and record.get("runtime_evidence_mode", "full_transcript")
            == "full_transcript"
            for record in records
        ),
        "bounded_note_ready": sum(
            record.get("processing_status") == "ready"
            and record.get("runtime_evidence_mode")
            == "bounded_note_windows"
            for record in records
        ),
        "transcript_segment_videos": sum(
            bool(record.get("transcript_segments")) for record in records
        ),
        "transcript_segments": sum(
            len(record.get("transcript_segments") or []) for record in records
        ),
    }
    before = copy.deepcopy(payload)
    before.pop("updated_at", None)
    after = copy.deepcopy(migrated)
    after.pop("updated_at", None)
    if before != after:
        migrated["updated_at"] = now or datetime.now(timezone.utc).isoformat()
    return migrated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    payload = json.loads(KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    migrated = migrate_knowledge(payload, rules=rules)
    serialized = json.dumps(migrated, ensure_ascii=False, indent=2) + "\n"
    current = KNOWLEDGE_PATH.read_text(encoding="utf-8")
    changed = serialized != current
    if args.check:
        if changed:
            raise SystemExit("Bilibili evidence admission migration is stale")
    elif changed:
        atomic_write_text(KNOWLEDGE_PATH, serialized)
    print(
        json.dumps(
            {
                "changed": changed,
                "primary": migrated["knowledge_counts"]["primary"],
                "supplemental": migrated["knowledge_counts"]["supplemental"],
                "answer_ineligible": migrated["knowledge_counts"][
                    "answer_ineligible"
                ],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
