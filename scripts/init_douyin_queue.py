#!/usr/bin/env python3
import json
from pathlib import Path

from douyin_pipeline import (
    compute_status_counts,
    normalize_transcribed_media_state,
    now_iso,
    validate_queue_statuses,
    write_json,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "douyin_teaching_filtered.json"
TRANSCRIPTS = ROOT / "data" / "transcripts" / "douyin"
QUEUE_PATH = ROOT / "data" / "processing" / "douyin_queue.json"

source = json.loads(SOURCE.read_text(encoding="utf-8"))
existing = {}
if QUEUE_PATH.exists():
    current = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    existing = {item["video_id"]: item for item in current["items"]}

items = []
for video in source["videos"]:
    transcript_exists = any(TRANSCRIPTS.glob(f"**/{video['video_id']}.json"))
    previous = existing.get(video["video_id"], {})
    status = "transcribed" if transcript_exists else previous.get("status", "classified_teaching")
    item = dict(previous)
    item.update(
        {
            "video_id": video["video_id"],
            "url": video["url"],
            "title": video["title"],
            "category": video["primary_category"],
            "tags": video["tags"],
            "status": status,
            "media_path": previous.get("media_path"),
            "duration_seconds": previous.get("duration_seconds"),
            "attempts": previous.get("attempts", 0),
            "error": previous.get("error"),
        }
    )
    normalize_transcribed_media_state(item)
    items.append(item)

validate_queue_statuses(items)
counts = compute_status_counts(items)

write_json(
    QUEUE_PATH,
    {
        "updated_at": now_iso(),
        "source": str(SOURCE.relative_to(ROOT)),
        "counts": counts,
        "items": items,
    },
)
print(json.dumps({"queue": str(QUEUE_PATH), "counts": counts}, ensure_ascii=False))
