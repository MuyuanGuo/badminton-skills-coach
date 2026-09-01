#!/usr/bin/env python3
"""Prepare the real but unapproved v3 vertical-slice review session."""

import argparse
import json
from pathlib import Path

from v3.routing import validate_pilot_review_queue
from v3.seed import DEFAULT_VIDEO_ID, seed_vertical_slice


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video-id")
    parser.add_argument(
        "--topic",
        help="select a candidate from the private pilot queue instead of passing --video-id",
    )
    parser.add_argument("--rank", type=int, default=1)
    parser.add_argument(
        "--queue",
        type=Path,
        default=ROOT / ".local/v3/review/pilot-review-queue.json",
    )
    parser.add_argument("--private-root", type=Path, default=ROOT / ".local/v3")
    parser.add_argument("--media", type=Path)
    parser.add_argument("--transcript", type=Path)
    parser.add_argument(
        "--suggestions",
        type=Path,
        help="optional ignored JSON file with hash-bound private review suggestions",
    )
    args = parser.parse_args()
    if args.topic and args.video_id:
        parser.error("--topic and --video-id are mutually exclusive")
    if args.rank < 1:
        parser.error("--rank must be positive")

    knowledge_path = ROOT / "data/knowledge/douyin_knowledge_base.json"
    knowledge = json.loads(knowledge_path.read_text(encoding="utf-8"))
    alternate_urls: list[str] = []
    selected_topic = ""
    selected_rank: int | None = None
    if args.topic:
        queue = json.loads(args.queue.read_text(encoding="utf-8"))
        validate_pilot_review_queue(queue)
        topic = next(
            (item for item in queue["topics"] if item["topic_id"] == args.topic),
            None,
        )
        if topic is None:
            parser.error(f"unknown pilot topic: {args.topic}")
        entry = next(
            (item for item in topic["entries"] if item["queue_rank"] == args.rank),
            None,
        )
        if entry is None:
            parser.error(f"pilot topic {args.topic} has no queue rank {args.rank}")
        route = next(
            item
            for item in queue["routes"]
            if item["source_group_id"] == entry["source_group_id"]
        )
        video_id = route["knowledge_video_id"]
        alternate_urls = list(route["alternate_urls"])
        selected_topic = args.topic
        selected_rank = args.rank
    else:
        video_id = args.video_id or DEFAULT_VIDEO_ID

    matches = [video for video in knowledge["videos"] if video.get("video_id") == video_id]
    if len(matches) != 1:
        parser.error(f"expected one knowledge record for {video_id}, found {len(matches)}")
    video = matches[0]
    transcript = args.transcript or ROOT / str(video.get("transcript_file") or "")
    if not transcript.is_file():
        parser.error(f"candidate transcript is unavailable: {transcript}")
    transcript_payload = json.loads(transcript.read_text(encoding="utf-8"))
    source_file = str(transcript_payload.get("source_file") or "")
    if not source_file and args.media is None:
        parser.error("candidate transcript does not identify a local media file")
    media = args.media or (ROOT / source_file)
    default_suggestions = (
        args.private_root
        / "inputs/suggestions"
        / f"{video_id.replace(':', '_')}.json"
    )
    suggestions = args.suggestions
    if suggestions is None and default_suggestions.is_file():
        suggestions = default_suggestions
    result = seed_vertical_slice(
        video_id=video_id,
        knowledge_path=knowledge_path,
        source_config_path=ROOT / "config/douyin_source.json",
        transcript_path=transcript,
        media_path=media,
        private_root=args.private_root,
        suggestions_path=suggestions,
        alternate_urls=alternate_urls,
    )
    if selected_topic:
        result["pilot_topic"] = selected_topic
        result["pilot_queue_rank"] = selected_rank
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
