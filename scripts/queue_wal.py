#!/usr/bin/env python3
"""Append-only recovery journal for long-running JSON queue workers."""

import json
import os
from pathlib import Path


class QueueWAL:
    def __init__(self, queue_path, checkpoint_interval=10):
        self.queue_path = Path(queue_path)
        self.path = self.queue_path.with_suffix(self.queue_path.suffix + ".wal")
        self.checkpoint_interval = checkpoint_interval
        self.pending_events = 0

    def replay(self, queue):
        if not self.path.exists():
            return False
        by_id = {str(item["video_id"]): item for item in queue["items"]}
        changed = False
        with self.path.open(encoding="utf-8") as source:
            for line_number, line in enumerate(source, start=1):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(
                        f"queue WAL has invalid JSON at line {line_number}"
                    ) from error
                item = event.get("item") if event.get("schema_version") == 1 else None
                video_id = str((item or {}).get("video_id") or "")
                if not video_id or video_id not in by_id:
                    raise ValueError("queue WAL references an unknown video")
                by_id[video_id].clear()
                by_id[video_id].update(item)
                changed = True
        return changed

    def record(self, item):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"schema_version": 1, "item": item},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self.path.open("a", encoding="utf-8") as destination:
            destination.write(payload + "\n")
            destination.flush()
            os.fsync(destination.fileno())
        self.pending_events += 1

    def should_checkpoint(self):
        return self.pending_events >= self.checkpoint_interval

    def clear(self):
        self.path.unlink(missing_ok=True)
        self.pending_events = 0
