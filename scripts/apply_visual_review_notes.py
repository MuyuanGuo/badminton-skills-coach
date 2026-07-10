#!/usr/bin/env python3
import json
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_PATH = ROOT / "output" / "visual_review_queue.md"
ANNOTATIONS_PATH = ROOT / "data" / "review" / "visual_review_annotations.json"


ITEM_RE = re.compile(
    r"^###\s+(?P<rank>\d+)\.\s+(?P<title>.*?)\n"
    r"(?P<body>.*?)(?=^###\s+\d+\.|\Z)",
    re.DOTALL | re.MULTILINE,
)
FIELD_RE = re.compile(r"^- (?P<key>Video ID|Category|URL): (?P<value>.*)$", re.MULTILINE)
NOTES_RE = re.compile(r"Review notes:\s*(?P<notes>.*?)(?:\n-\s*$|\Z)", re.DOTALL | re.MULTILINE)


def extract_field(body, key):
    for match in FIELD_RE.finditer(body):
        if match.group("key") == key:
            return match.group("value").strip().strip("`")
    return ""


def clean_notes(notes):
    lines = []
    for line in notes.strip().splitlines():
        stripped = line.strip()
        if not stripped or stripped == "-":
            continue
        lines.append(stripped)
    return "\n".join(lines).strip()


def review_status(notes):
    if not notes:
        return "pending"
    if "非教学视频" in notes:
        return "not_teaching"
    if "价值不高" in notes or "低价值" in notes:
        return "low_value"
    if "按转写" in notes or "术语需要修正" in notes or "需要修正" in notes:
        return "needs_correction"
    return "approved"


def main():
    if ANNOTATIONS_PATH.exists():
        existing_data = json.loads(ANNOTATIONS_PATH.read_text(encoding="utf-8"))
        merged_by_id = {
            item["video_id"]: item
            for item in existing_data.get("items", [])
        }
    else:
        merged_by_id = {}

    text = MARKDOWN_PATH.read_text(encoding="utf-8")
    for match in ITEM_RE.finditer(text):
        body = match.group("body")
        notes_match = NOTES_RE.search(body)
        notes = clean_notes(notes_match.group("notes") if notes_match else "")
        if not notes:
            continue
        status = review_status(notes)
        video_id = extract_field(body, "Video ID")
        if not video_id:
            continue
        merged_by_id[video_id] = {
            "rank": int(match.group("rank")),
            "video_id": video_id,
            "title": match.group("title").strip(),
            "url": extract_field(body, "URL"),
            "category": extract_field(body, "Category"),
            "review_status": status,
            "review_notes": notes,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
        }

    items = sorted(merged_by_id.values(), key=lambda item: (item.get("rank", 9999), item["video_id"]))

    ANNOTATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    ANNOTATIONS_PATH.write_text(
        json.dumps(
            {
                "version": "visual-review-annotations-v1",
                "source": str(MARKDOWN_PATH.relative_to(ROOT)),
                "reviewed_count": len(items),
                "status_counts": {
                    status: sum(item["review_status"] == status for item in items)
                    for status in ["approved", "needs_correction", "not_teaching", "low_value"]
                },
                "items": items,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "reviewed_count": len(items),
                "status_counts": {
                    status: sum(item["review_status"] == status for item in items)
                    for status in ["approved", "needs_correction", "not_teaching", "low_value"]
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
