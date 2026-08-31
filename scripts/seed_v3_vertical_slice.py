#!/usr/bin/env python3
"""Prepare the real but unapproved v3 vertical-slice review session."""

import argparse
import json
from pathlib import Path

from v3.seed import DEFAULT_VIDEO_ID, seed_vertical_slice


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video-id", default=DEFAULT_VIDEO_ID)
    parser.add_argument("--private-root", type=Path, default=ROOT / ".local/v3")
    parser.add_argument("--media", type=Path)
    parser.add_argument("--transcript", type=Path)
    parser.add_argument(
        "--suggestions",
        type=Path,
        help="optional ignored JSON file with hash-bound private review suggestions",
    )
    args = parser.parse_args()
    media = args.media or (
        ROOT / f"data/raw_videos/douyin/pilot/{args.video_id}.mp4"
    )
    transcript = args.transcript or (
        ROOT / f"data/transcripts/douyin/pilot/{args.video_id}.json"
    )
    default_suggestions = (
        args.private_root / "inputs/suggestions" / f"{args.video_id}.json"
    )
    suggestions = args.suggestions
    if suggestions is None and default_suggestions.is_file():
        suggestions = default_suggestions
    result = seed_vertical_slice(
        video_id=args.video_id,
        knowledge_path=ROOT / "data/knowledge/douyin_knowledge_base.json",
        source_config_path=ROOT / "config/douyin_source.json",
        transcript_path=transcript,
        media_path=media,
        private_root=args.private_root,
        suggestions_path=suggestions,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
