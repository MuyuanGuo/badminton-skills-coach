#!/usr/bin/env python3
"""Build a deterministic before/after impact report for a knowledge update."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from project_artifacts import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_PATH = Path("data/knowledge/douyin_knowledge_base.json")
RETRIEVAL_PATH = Path("data/knowledge/retrieval_index.json")
QUEUE_PATH = Path("data/processing/douyin_queue.json")
MANIFEST_PATH = Path("data/knowledge/build_manifest.json")
DEFAULT_OUTPUT = ROOT / "output" / "update-impact-report.json"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def evidence_source(video):
    confidence = video.get("confidence")
    if confidence == "visual_reviewed":
        return "visual_review"
    if confidence == "reviewed_transcript":
        return "reviewed_transcript"
    return "automatic_transcript"


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot(root=ROOT):
    root = Path(root)
    knowledge = load_json(root / KNOWLEDGE_PATH)
    retrieval = load_json(root / RETRIEVAL_PATH)
    queue = load_json(root / QUEUE_PATH)
    manifest = (
        load_json(root / MANIFEST_PATH)
        if (root / MANIFEST_PATH).exists()
        else {}
    )
    videos = {
        str(video["video_id"]): video for video in knowledge.get("videos", [])
    }
    ready = {
        video_id
        for video_id, video in videos.items()
        if video.get("processing_status") == "ready"
    }
    return {
        "knowledge_sha256": file_digest(root / KNOWLEDGE_PATH),
        "retrieval_sha256": file_digest(root / RETRIEVAL_PATH),
        "build_id": manifest.get("build_id"),
        "video_statuses": {
            video_id: video.get("processing_status") for video_id, video in videos.items()
        },
        "ready_video_ids": sorted(ready),
        "retrieval_video_ids": sorted(
            str(video["video_id"]) for video in retrieval.get("videos", [])
        ),
        "evidence_sources": dict(
            sorted(
                Counter(
                    evidence_source(videos[video_id])
                    for video_id in ready
                ).items()
            )
        ),
        "queue_counts": dict(sorted(queue.get("counts", {}).items())),
    }


def numeric_delta(before, after):
    return {
        key: after.get(key, 0) - before.get(key, 0)
        for key in sorted(set(before) | set(after))
        if after.get(key, 0) != before.get(key, 0)
    }


def build_report(before, after):
    before_ready = set(before["ready_video_ids"])
    after_ready = set(after["ready_video_ids"])
    before_retrieval = set(before["retrieval_video_ids"])
    after_retrieval = set(after["retrieval_video_ids"])
    transitions = []
    for video_id in sorted(
        set(before["video_statuses"]) | set(after["video_statuses"])
    ):
        old = before["video_statuses"].get(video_id)
        new = after["video_statuses"].get(video_id)
        if old != new:
            transitions.append(
                {
                    "video_id": video_id,
                    "before": old,
                    "after": new,
                }
            )
    report = {
        "schema_version": 1,
        "changed": (
            before["knowledge_sha256"] != after["knowledge_sha256"]
            or before["retrieval_sha256"] != after["retrieval_sha256"]
        ),
        "build": {
            "before": before.get("build_id"),
            "after": after.get("build_id"),
        },
        "ready_videos": {
            "before": len(before_ready),
            "after": len(after_ready),
            "added_video_ids": sorted(after_ready - before_ready),
            "removed_video_ids": sorted(before_ready - after_ready),
        },
        "retrieval_index": {
            "before": len(before_retrieval),
            "after": len(after_retrieval),
            "added_video_ids": sorted(after_retrieval - before_retrieval),
            "removed_video_ids": sorted(before_retrieval - after_retrieval),
        },
        "status_transitions": transitions,
        "evidence_source_delta": numeric_delta(
            before["evidence_sources"],
            after["evidence_sources"],
        ),
        "queue_count_delta": numeric_delta(
            before["queue_counts"],
            after["queue_counts"],
        ),
        "content_hashes": {
            "knowledge_before": before["knowledge_sha256"],
            "knowledge_after": after["knowledge_sha256"],
            "retrieval_before": before["retrieval_sha256"],
            "retrieval_after": after["retrieval_sha256"],
        },
    }
    report["invariants"] = {
        "ready_matches_retrieval": after_ready == after_retrieval,
        "no_silent_ready_removals": not bool(before_ready - after_ready),
    }
    return report


def write_report(before, after, output=DEFAULT_OUTPUT):
    report = build_report(before, after)
    if not all(report["invariants"].values()):
        raise ValueError("Update impact invariants failed")
    atomic_write_text(
        output,
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = write_report(
        load_json(args.before),
        load_json(args.after),
        args.output,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
