#!/usr/bin/env python3
"""Refresh only Bilibili records produced by an approved recovery ASR model.

The full Bilibili rebuild intentionally requires every raw transcript.  This
targeted path lets a quality-recovery transcript replace its committed record
without weakening that reproducibility contract for the other videos.
"""

import argparse
import copy
import json
from pathlib import Path

from build_bilibili_knowledge import (
    QUALITY_RULES_PATH,
    QUEUE_PATH,
    TRANSCRIPT_ROOT,
    add_to_shingle_index,
    build_record,
    build_shingle_index,
    load_valid_queue_transcript,
    stable_payload_hash,
    transcript_integrity,
)
from build_douyin_knowledge import reconcile_updated_at
from bilibili_storage import (
    bilibili_transcript_roots,
    index_exact_transcript_candidates,
)
from project_artifacts import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_PATH = ROOT / "data" / "knowledge" / "bilibili_knowledge_base.json"
DOUYIN_PATH = ROOT / "data" / "knowledge" / "douyin_knowledge_base.json"


def refreshed_knowledge(
    payload,
    queue,
    transcripts,
    rules,
    douyin,
    now=None,
    force=False,
):
    recovery_models = set(
        (rules.get("bilibili_unattended") or {}).get(
            "quality_recovery_models", []
        )
    )
    current_by_bvid = {
        record.get("source_video_id"): record
        for record in payload.get("videos", [])
    }
    candidates = []
    for item in queue.get("items", []):
        bvid = item.get("video_id")
        if (
            item.get("status") != "transcribed"
            or item.get("transcript_model") not in recovery_models
            or bvid not in current_by_bvid
        ):
            continue
        paths = transcripts.get(bvid) or []
        if isinstance(paths, (str, Path)):
            paths = [Path(paths)]
        for path in paths:
            try:
                transcript = load_valid_queue_transcript(item, path)
            except OSError:
                continue
            current_hash = (
                (current_by_bvid[bvid].get("quality") or {})
                .get("transcript", {})
                .get("integrity", {})
                .get("transcript_sha256")
            )
            recovered_hash = transcript_integrity(transcript, rules)[
                "transcript_sha256"
            ]
            assessment_rules_hash = (
                (current_by_bvid[bvid].get("quality") or {})
                .get("transcript", {})
                .get("assessment_rules_sha256")
            )
            if (
                force
                or current_hash != recovered_hash
                or assessment_rules_hash != stable_payload_hash(rules)
            ):
                candidates.append((item, path, transcript))
            break

    candidate_ids = {item["evidence_id"] for item, _, _ in candidates}
    duplicate_index = build_shingle_index(
        [
            record
            for record in douyin.get("videos", [])
            if record.get("evidence_id") not in candidate_ids
        ]
    )
    replacements = {}
    for item, path, transcript in sorted(
        candidates, key=lambda value: value[0]["video_id"]
    ):
        record = build_record(
            item,
            path,
            transcript,
            rules,
            duplicate_index,
        )
        record["quality_recovery"] = {
            "method": "higher_accuracy_retranscription",
            "model": item["transcript_model"],
            "transcript_source_sha256": item.get(
                "transcript_source_sha256"
            ),
            "transcript_source_bytes": item.get("transcript_source_bytes"),
            "transcript_sha256": (
                (record.get("quality") or {})
                .get("transcript", {})
                .get("integrity", {})
                .get("transcript_sha256")
            ),
        }
        replacements[record["evidence_id"]] = record
        if record["processing_status"] == "ready":
            add_to_shingle_index(
                duplicate_index,
                record["evidence_id"],
                record.get("transcript_segments") or [],
                transcript.get("duration"),
            )

    refreshed = copy.deepcopy(payload)
    refreshed["videos"] = [
        replacements.get(record.get("evidence_id"), record)
        for record in payload.get("videos", [])
    ]
    refreshed, _ = reconcile_updated_at(refreshed, payload, now=now)
    return refreshed, sorted(replacements)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reassess all locally available approved recovery transcripts",
    )
    args = parser.parse_args()
    if args.check and args.force:
        parser.error("--check and --force cannot be combined")
    payload = json.loads(KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    rules = json.loads(QUALITY_RULES_PATH.read_text(encoding="utf-8"))
    douyin = json.loads(DOUYIN_PATH.read_text(encoding="utf-8"))
    transcripts = index_exact_transcript_candidates(
        bilibili_transcript_roots(ROOT, override=TRANSCRIPT_ROOT)
    )
    refreshed, evidence_ids = refreshed_knowledge(
        payload,
        queue,
        transcripts,
        rules,
        douyin,
        force=args.force,
    )
    serialized = json.dumps(refreshed, ensure_ascii=False, indent=2) + "\n"
    changed = serialized != KNOWLEDGE_PATH.read_text(encoding="utf-8")
    if args.check and changed:
        raise SystemExit("Bilibili recovery records are stale")
    if changed and not args.check:
        atomic_write_text(KNOWLEDGE_PATH, serialized)
    print(
        json.dumps(
            {
                "changed": changed,
                "refreshed_evidence_ids": evidence_ids,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
