#!/usr/bin/env python3
"""Reconcile Bilibili transcript outputs into the durable processing queue."""

import json
from collections import Counter
from pathlib import Path

from batch_transcribe_directory import load_valid_transcript, mark_transcribed
from douyin_pipeline import now_iso, write_json


ROOT = Path(__file__).resolve().parents[1]
QUEUE_PATH = ROOT / "data" / "processing" / "bilibili_queue.json"
MEDIA_ROOT = ROOT / "data" / "raw_videos" / "bilibili"
TRANSCRIPT_ROOT = ROOT / "data" / "transcripts" / "bilibili"


def main():
    queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    completed = []
    for item in queue["items"]:
        bvid = item["video_id"]
        transcript_path = TRANSCRIPT_ROOT / f"{bvid}.json"
        media_candidates = list(MEDIA_ROOT.glob(f"{bvid}.*"))
        media = next(
            (path for path in media_candidates if path.suffix in {".m4a", ".mp3", ".webm"}),
            None,
        )
        if not transcript_path.exists() or media is None:
            continue
        payload = load_valid_transcript(transcript_path, bvid, media)
        mark_transcribed(item, payload)
        item["platform"] = "bilibili"
        item["media_path"] = None
        completed.append(bvid)
    queue["counts"] = dict(Counter(item["status"] for item in queue["items"]))
    queue["updated_at"] = now_iso()
    write_json(QUEUE_PATH, queue)
    print(json.dumps({
        "completed": len(completed),
        "video_ids": completed,
        "counts": queue["counts"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
