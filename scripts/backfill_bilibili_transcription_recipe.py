#!/usr/bin/env python3
"""Backfill the known recipe for the metric-bearing July 2026 Bilibili batch."""

import argparse
import hashlib
import json
from pathlib import Path

from batch_transcribe_directory import (
    load_valid_transcript,
    transcript_directories,
    transcription_recipe,
    write_transcript_outputs,
)
from bilibili_storage import (
    BILIBILI_TRANSCRIPT_CACHE_ENV,
    bilibili_transcript_roots,
    index_exact_transcript_candidates,
    lexical_absolute,
)
from douyin_pipeline import write_json


ROOT = Path(__file__).resolve().parents[1]
QUEUE_PATH = ROOT / "data" / "processing" / "bilibili_queue.json"
TRANSCRIPT_ROOT = ROOT / "data" / "transcripts" / "bilibili"
KNOWN_RECIPE_BACKFILL_SHA256 = {
    "BV11F411D7s4": "f5249d4c010c5bf1337da2174f049694211eca13b61c6dbda67fb57c81c22f53",
    "BV11c411s7Gq": "c31d528405eccc37e0118203b51a3d48db675708670a7d47d4572598ee87f9f5",
    "BV12Z4y1n7b4": "b1aae940c494a23c181e9eb4083148fe94ea62e42b6d8ed00a81202521a7ae5b",
    "BV1994y167xY": "beb8fdf827400e76dc07d7e954f1fbc62a7934befe11e9944fa494da044fef21",
    "BV19C4y1S7z2": "9294c28aa895ae188ee49e8ea5b753941bcee76a98c4b0d81251564829129b04",
    "BV19g4y1S75f": "c93f232dd7ef52621980f435b51d3692f81cacc8276247458d83dc5f85d30969",
    "BV1Ac411q7eJ": "c735372f52cd2f5e7cc7ae606cf224d6630840f29ad01070eaec49363d5155e2",
    "BV1Az4y147ob": "1da21f652b04f9da5876199bc1be0a145e93bb01e93ede9905b65e2341188bcb",
    "BV1Bi4y1q7eh": "03ecaab2dd91d903798c133da8897728012963a93e4e43e8cae799e0ae9f6b2a",
    "BV1Cj411n7zV": "36399496b4b14ab7a275e208f46df31f28853f50138088ee05577a8a4f6ad2f8",
    "BV1DW4y1A7fx": "a4880180d7ec06093de65ea1719af910376b78fe6a58b9892fefde5f175755eb",
    "BV1Dh4y1h7vW": "f5e8663979d5e457fa3e5775351fdeb2b86d08b266954a0bd17f61cc49888f4f",
    "BV1FB4y1Z7cD": "643b2f0644cfadabf7c1f60462cfb989955ef3ce879dd0aba0ebeaf23d4c24a8",
}


def stable_payload_hash(payload):
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def eligible_for_backfill(payload, queue_item):
    segments = payload.get("segments") or []
    metrics = payload.get("segment_quality_metrics")
    expected_payload_hash = KNOWN_RECIPE_BACKFILL_SHA256.get(
        str(payload.get("video_id") or "")
    )
    return (
        not payload.get("transcription_recipe")
        and expected_payload_hash is not None
        and stable_payload_hash(payload) == expected_payload_hash
        and payload.get("model") == "small"
        and isinstance(metrics, list)
        and len(metrics) == len(segments)
        and queue_item.get("transcript_source_sha256")
        == payload.get("source_sha256")
        and queue_item.get("transcript_source_bytes")
        == payload.get("source_bytes")
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--transcript-cache-dir",
        type=Path,
        help=(
            "Preferred Bilibili transcript cache "
            f"(default: {BILIBILI_TRANSCRIPT_CACHE_ENV} or repository data)"
        ),
    )
    args = parser.parse_args()
    queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    queue_by_id = {item["video_id"]: item for item in queue["items"]}
    eligible = []
    already_present = []
    skipped = []
    transcript_roots = bilibili_transcript_roots(
        ROOT,
        override=args.transcript_cache_dir,
    )
    transcript_index = index_exact_transcript_candidates(transcript_roots)
    for bvid in sorted(transcript_index):
        queue_item = queue_by_id.get(bvid)
        if not queue_item:
            skipped.append(bvid)
            continue
        payload = None
        transcript_path = None
        for candidate in transcript_index[bvid]:
            try:
                payload = load_valid_transcript(candidate, bvid)
            except OSError:
                continue
            transcript_path = candidate
            break
        if payload is None:
            skipped.append(bvid)
            continue
        if payload.get("transcription_recipe"):
            already_present.append(bvid)
            continue
        if not eligible_for_backfill(payload, queue_item):
            skipped.append(bvid)
            continue
        payload["transcription_recipe"] = transcription_recipe(payload["model"])
        if not args.check:
            preferred_root = transcript_roots[0]
            try:
                transcript_path.relative_to(lexical_absolute(preferred_root))
            except ValueError:
                preferred_root.mkdir(parents=True, exist_ok=True)
                target_dir = transcript_directories(
                    preferred_root,
                    set(queue_by_id),
                )[bvid]
                write_transcript_outputs(target_dir, payload)
            else:
                write_json(transcript_path, payload)
        eligible.append(bvid)
    print(
        json.dumps(
            {
                "eligible": len(eligible),
                "updated": 0 if args.check else len(eligible),
                "already_present": len(already_present),
                "skipped": len(skipped),
                "eligible_video_ids": eligible,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
