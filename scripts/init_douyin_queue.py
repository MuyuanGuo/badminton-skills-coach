#!/usr/bin/env python3
import json
from datetime import datetime, timezone
from pathlib import Path


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
    status = "transcribed" if transcript_exists else previous.get("status", "pending")
    items.append({
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
    })

counts = {}
for item in items:
    counts[item["status"]] = counts.get(item["status"], 0) + 1

QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
QUEUE_PATH.write_text(
    json.dumps({
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(SOURCE.relative_to(ROOT)),
        "counts": counts,
        "items": items,
    }, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print(json.dumps({"queue": str(QUEUE_PATH), "counts": counts}, ensure_ascii=False))
