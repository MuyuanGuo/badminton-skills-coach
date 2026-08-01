#!/usr/bin/env python3
"""Migrate committed Bilibili evidence to the split admission model.

This migration is intentionally able to operate without the ephemeral raw
transcript cache.  A formerly quarantined record is admitted only when its
committed audit fields prove origin, source safety, automatic evidence
quality, and title-only transcript issues.  Such records expose only their
already-bounded timestamped note windows until a future full rebuild restores
the verified raw transcript.
"""

import argparse
import copy
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from evidence_admission import (
    TITLE_ALIGNMENT_ISSUES,
    infer_evidence_roles,
)
from project_artifacts import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_PATH = ROOT / "data" / "knowledge" / "bilibili_knowledge_base.json"


def title_only_supplemental_candidate(record):
    quality = record.get("quality") or {}
    transcript = quality.get("transcript") or {}
    issues = transcript.get("issues") or []
    return (
        record.get("processing_status") == "low_value"
        and bool(issues)
        and all(issue in TITLE_ALIGNMENT_ISSUES for issue in issues)
        and (quality.get("origin_verification") or {}).get("passed") is True
        and (quality.get("source_content_safety") or {}).get("passed") is True
        and (quality.get("automatic_evidence") or {}).get("passed") is True
        and not record.get("possible_duplicate_evidence")
    )


def migrate_record(record):
    migrated = copy.deepcopy(record)
    status = migrated.get("processing_status")
    admission = migrated.get("automatic_admission") or {}
    if title_only_supplemental_candidate(migrated):
        migrated["processing_status"] = "ready"
        migrated["confidence"] = "supplemental_note_only"
        migrated["answer_eligibility"] = "supplemental"
        migrated["runtime_evidence_mode"] = "bounded_note_windows"
        migrated["metadata_title_trust"] = "limited"
        issues = sorted(
            set(
                (migrated.get("quality") or {})
                .get("transcript", {})
                .get("issues", [])
            )
        )
        admission.update(
            {
                "disposition": "supplemental_title_alignment",
                "answer_evidence_eligible": True,
                "answer_eligibility": "supplemental",
                "advisory_issues": issues,
                "blocking_issues": [],
            }
        )
        note = migrated.get("teaching_note") or {}
        note["note"] = (
            "来源、安全与教学证据门禁已通过；原始转写缓存当前不可完整复现，仅允许使用已提交的带时间戳证据窗口补充主证据。"
        )
        migrated["teaching_note"] = note
    elif status == "ready":
        migrated.setdefault("answer_eligibility", "primary")
        migrated.setdefault("runtime_evidence_mode", "full_transcript")
        migrated.setdefault("metadata_title_trust", "transcript_aligned")
        admission.setdefault("answer_eligibility", "primary")
        admission.setdefault("answer_evidence_eligible", True)
        admission.setdefault("advisory_issues", [])
        admission.setdefault("blocking_issues", [])
    else:
        migrated["answer_eligibility"] = "none"
        migrated.setdefault("runtime_evidence_mode", "quarantined")
        migrated.setdefault("metadata_title_trust", "unverified")
        admission["answer_eligibility"] = "none"
        admission["answer_evidence_eligible"] = False
        admission.setdefault("advisory_issues", [])
        admission.setdefault(
            "blocking_issues",
            list(
                (migrated.get("quality") or {})
                .get("transcript", {})
                .get("issues", [])
            ),
        )
    migrated["automatic_admission"] = admission
    migrated["evidence_roles"] = infer_evidence_roles(
        migrated.get("category"),
        migrated.get("retrieval_title") or migrated.get("title"),
        migrated.get("teaching_note"),
    )
    return migrated


def migrate_knowledge(payload, now=None):
    migrated = copy.deepcopy(payload)
    records = [migrate_record(record) for record in payload.get("videos", [])]
    migrated["videos"] = records
    migrated["evidence_schema_version"] = 2
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
    migrated = migrate_knowledge(payload)
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
