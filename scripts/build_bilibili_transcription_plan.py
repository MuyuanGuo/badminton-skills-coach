#!/usr/bin/env python3
"""Freeze the exact resumable Bilibili transcription campaign."""

import argparse
import hashlib
import json
from pathlib import Path

from bilibili_pipeline import load_rules
from bilibili_storage import (
    BILIBILI_TRANSCRIPT_CACHE_ENV,
    bilibili_transcript_roots,
    first_readable_transcript,
    index_exact_transcript_candidates,
)
from check_bilibili_updates import extract_bvid
from douyin_pipeline import write_json


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_PATH = ROOT / "data" / "snapshots" / "bilibili_profile_full_archive.json"
LEDGER_PATH = ROOT / "data" / "bilibili_classification_ledger.json"
QUEUE_PATH = ROOT / "data" / "processing" / "bilibili_queue.json"
TRANSCRIPT_ROOT = ROOT / "data" / "transcripts" / "bilibili"
DEFAULT_OUTPUT = ROOT / "data" / "processing" / "bilibili_transcription_plan.json"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ids_sha256(values):
    return hashlib.sha256("\n".join(sorted(values)).encode("utf-8")).hexdigest()


def stable_payload_sha256(payload):
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def build_plan(
    archive,
    ledger,
    queue,
    *,
    archive_sha256,
    rules,
    transcript_roots=None,
):
    archive_items = archive.get("items") or archive.get("videos") or []
    archive_ids = {
        bvid for item in archive_items if (bvid := extract_bvid(item))
    }
    if len(archive_ids) != len(archive_items):
        raise ValueError("Bilibili archive IDs are missing or duplicated")
    ledger_by_id = {item["bvid"]: item for item in ledger["videos"]}
    if set(ledger_by_id) != archive_ids:
        raise ValueError("Bilibili ledger does not exactly match the archive")
    required_ids = {
        item["bvid"]
        for item in ledger["videos"]
        if item["decision"] == "required_transcription_policy"
    }
    excluded_ids = {
        item["bvid"]
        for item in ledger["videos"]
        if item["decision"] == "excluded_transcription_policy"
    }
    if required_ids & excluded_ids or required_ids | excluded_ids != archive_ids:
        raise ValueError("Bilibili transcription policy is not an exact partition")
    queue_ids = {item["video_id"] for item in queue["items"]}
    if len(queue_ids) != len(queue["items"]) or not queue_ids <= required_ids:
        raise ValueError("Bilibili queue is duplicated or outside the required set")
    completed_ids = {
        item["video_id"]
        for item in queue["items"]
        if item.get("status") == "transcribed"
    }
    if completed_ids != queue_ids:
        raise ValueError("Baseline Bilibili queue is not fully transcribed")
    transcript_index = index_exact_transcript_candidates(
        transcript_roots or [TRANSCRIPT_ROOT]
    )
    missing_transcripts = sorted(
        bvid
        for bvid in completed_ids
        if first_readable_transcript(transcript_index.get(bvid)) is None
    )
    if missing_transcripts:
        raise ValueError(
            "Baseline Bilibili transcripts are missing: "
            + ", ".join(missing_transcripts)
        )
    pending_ids = required_ids - completed_ids
    policy_basis_counts = {}
    for item in ledger["videos"]:
        key = (
            f"{item['decision']}:"
            f"{(item.get('collection_policy') or {}).get('basis', 'missing')}"
        )
        policy_basis_counts[key] = policy_basis_counts.get(key, 0) + 1
    payload = {
        "schema_version": 1,
        "platform": "bilibili",
        "profile_id": "1423436652",
        "archive": {
            "path": str(ARCHIVE_PATH.relative_to(ROOT)),
            "sha256": archive_sha256,
            "generated_at": archive.get("generated_at")
            or archive.get("collected_at"),
            "video_count": len(archive_ids),
        },
        "classification_rules": {
            "version": rules["_identity"]["version"],
            "sha256": rules["_identity"]["sha256"],
        },
        "baseline_queue_updated_at": queue.get("updated_at"),
        "counts": {
            "archive": len(archive_ids),
            "required": len(required_ids),
            "excluded": len(excluded_ids),
            "baseline_completed": len(completed_ids),
            "pending": len(pending_ids),
        },
        "policy_basis_counts": dict(sorted(policy_basis_counts.items())),
        "set_sha256": {
            "required": ids_sha256(required_ids),
            "excluded": ids_sha256(excluded_ids),
            "baseline_completed": ids_sha256(completed_ids),
            "pending": ids_sha256(pending_ids),
        },
        "required_bvids": sorted(required_ids),
        "excluded_bvids": sorted(excluded_ids),
        "baseline_completed_bvids": sorted(completed_ids),
        "pending_bvids": sorted(pending_ids),
    }
    payload["plan_id"] = stable_payload_sha256(payload)
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--expect-required", type=int)
    parser.add_argument("--expect-excluded", type=int)
    parser.add_argument("--expect-completed", type=int)
    parser.add_argument("--expect-pending", type=int)
    parser.add_argument(
        "--transcript-cache-dir",
        type=Path,
        help=(
            "Preferred Bilibili transcript cache "
            f"(default: {BILIBILI_TRANSCRIPT_CACHE_ENV} or repository data)"
        ),
    )
    args = parser.parse_args()
    plan = build_plan(
        load_json(ARCHIVE_PATH),
        load_json(LEDGER_PATH),
        load_json(QUEUE_PATH),
        archive_sha256=file_sha256(ARCHIVE_PATH),
        rules=load_rules(),
        transcript_roots=bilibili_transcript_roots(
            ROOT,
            override=args.transcript_cache_dir,
        ),
    )
    for key, expected in (
        ("required", args.expect_required),
        ("excluded", args.expect_excluded),
        ("baseline_completed", args.expect_completed),
        ("pending", args.expect_pending),
    ):
        if expected is not None and plan["counts"][key] != expected:
            raise SystemExit(
                f"Unexpected {key}: {plan['counts'][key]} != {expected}"
            )
    write_json(args.output, plan)
    print(json.dumps({
        "output": str(args.output),
        "plan_id": plan["plan_id"],
        "counts": plan["counts"],
        "set_sha256": plan["set_sha256"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
