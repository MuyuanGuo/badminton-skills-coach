#!/usr/bin/env python3
"""Reconcile Bilibili transcript outputs into the durable processing queue."""

import json
from collections import Counter
from pathlib import Path

from batch_transcribe_directory import load_valid_transcript, mark_transcribed
from bilibili_pipeline import acquire_bilibili_pipeline_lock
from douyin_pipeline import normalize_transcribed_media_state, now_iso, write_json


ROOT = Path(__file__).resolve().parents[1]
QUEUE_PATH = ROOT / "data" / "processing" / "bilibili_queue.json"
MEDIA_ROOT = ROOT / "data" / "raw_videos" / "bilibili"
TRANSCRIPT_ROOT = ROOT / "data" / "transcripts" / "bilibili"


def main():
    pipeline_lock = acquire_bilibili_pipeline_lock()
    queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    completed = []
    changed = False
    for item in queue["items"]:
        bvid = item["video_id"]
        transcript_path = TRANSCRIPT_ROOT / f"{bvid}.json"
        media_candidates = list(MEDIA_ROOT.glob(f"{bvid}.*"))
        media = next(
            (
                path
                for path in media_candidates
                if path.suffix.lower() in {".m4a", ".mp3", ".webm", ".wav", ".mp4"}
                and not path.name.endswith(".part")
            ),
            None,
        )
        if not transcript_path.exists() or media is None:
            continue
        payload = load_valid_transcript(transcript_path, bvid, media)
        item_changed = mark_transcribed(item, payload)
        item_changed = normalize_transcribed_media_state(item) or item_changed
        if item.get("platform") != "bilibili":
            item["platform"] = "bilibili"
            item_changed = True
        if item_changed or not item.get("media_validated_at"):
            item["media_validated_at"] = now_iso()
            item_changed = True
        changed = changed or item_changed
        completed.append(bvid)
    counts = dict(Counter(item["status"] for item in queue["items"]))
    if queue.get("counts") != counts:
        queue["counts"] = counts
        changed = True
    if changed:
        queue["updated_at"] = now_iso()
        write_json(QUEUE_PATH, queue)
    print(json.dumps({
        "completed": len(completed),
        "video_ids": completed,
        "counts": queue["counts"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
