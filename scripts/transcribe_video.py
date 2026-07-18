#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

from batch_transcribe_directory import (
    default_model_factory,
    payload_from_model,
    write_transcript_outputs,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("--model", default="small")
    parser.add_argument(
        "--output-dir", type=Path, default=Path("data/transcripts/douyin/pilot")
    )
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    model = default_model_factory(args.model)
    payload = payload_from_model(args.video.resolve(), args.model, model)
    write_transcript_outputs(args.output_dir.resolve(), payload)
    print(
        json.dumps(
            {
                "video_id": payload["video_id"],
                "segments": len(payload["segments"]),
                "duration": payload["duration"],
                "language_probability": payload["language_probability"],
                "output_dir": str(args.output_dir),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
