#!/usr/bin/env python3
import json
from collections import defaultdict
from pathlib import Path

from project_artifacts import atomic_write_bundle


ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_PATH = ROOT / "data" / "knowledge" / "douyin_knowledge_base.json"
TOPIC_INDEX_PATH = ROOT / "data" / "knowledge" / "topic_index.json"
JSON_OUTPUT = ROOT / "data" / "review" / "visual_review_queue.json"
MARKDOWN_OUTPUT = ROOT / "output" / "visual_review_queue.md"


CORE_CATEGORY_WEIGHTS = {
    "后场技术": 12,
    "发力与身体运用": 11,
    "步法与移动": 10,
    "双打战术": 9,
    "中前场与抽挡": 8,
    "发球与接发": 7,
    "握拍与基本动作": 6,
    "训练与纠错": 5,
}

TECHNICAL_TERMS = {
    "被动": 5,
    "高远": 4,
    "杀球": 5,
    "架拍": 5,
    "框架": 5,
    "发力": 5,
    "步法": 5,
    "启动": 4,
    "回动": 4,
    "双打": 4,
    "接发": 4,
    "防守": 4,
    "抽挡": 4,
    "网前": 4,
    "握拍": 4,
    "拍面": 3,
    "纠错": 3,
}


def flatten(value):
    if isinstance(value, dict):
        return " ".join(flatten(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(flatten(item) for item in value)
    return str(value)


def build_topic_maps(topic_index):
    topic_hits = defaultdict(list)
    representative_hits = defaultdict(list)
    for category in topic_index["categories"]:
        for subtopic in category["subtopics"]:
            for video in subtopic["representative_videos"]:
                video_id = video["video_id"]
                topic_hits[video_id].append(f"{category['name']} / {subtopic['name']}")
                representative_hits[video_id].append(subtopic["name"])
    return topic_hits, representative_hits


def score_video(video, topic_hits, representative_hits):
    text = flatten(
        {
            "title": video["title"],
            "category": video["category"],
            "tags": video["tags"],
            "teaching_note": video["teaching_note"],
        }
    )
    score = 0
    reasons = []

    category_weight = CORE_CATEGORY_WEIGHTS.get(video["category"], 3)
    score += category_weight
    reasons.append(f"category:{video['category']}+{category_weight}")

    if video["video_id"] in topic_hits:
        topic_score = min(len(topic_hits[video["video_id"]]) * 4, 16)
        score += topic_score
        reasons.append(f"topic-index:{len(topic_hits[video['video_id']])}+{topic_score}")

    if video["video_id"] in representative_hits:
        rep_score = min(len(representative_hits[video["video_id"]]) * 6, 18)
        score += rep_score
        reasons.append(f"representative:{len(representative_hits[video['video_id']])}+{rep_score}")

    matched_terms = []
    for term, weight in TECHNICAL_TERMS.items():
        if term in text:
            score += weight
            matched_terms.append(term)
    if matched_terms:
        reasons.append("terms:" + ",".join(matched_terms[:8]))

    duration = video.get("duration_seconds") or 0
    if duration >= 60:
        score += 3
        reasons.append("duration>=60+3")
    if duration >= 120:
        score += 2
        reasons.append("duration>=120+2")

    note = video.get("teaching_note") or {}
    evidence_count = 0
    for key in ["key_evidence", "error_evidence", "action_cues", "principles", "common_errors", "training_cues"]:
        value = note.get(key)
        if isinstance(value, list):
            evidence_count += len(value)
    if evidence_count:
        evidence_score = min(evidence_count, 8)
        score += evidence_score
        reasons.append(f"evidence:{evidence_count}+{evidence_score}")

    return score, reasons, matched_terms


def compact_note(video):
    note = video.get("teaching_note") or {}
    snippets = []
    for key in ["topic", "problem", "note"]:
        if note.get(key):
            snippets.append(str(note[key]))
    for key in ["key_evidence", "error_evidence", "action_cues", "principles"]:
        values = note.get(key)
        if isinstance(values, list):
            for item in values[:2]:
                if isinstance(item, dict):
                    snippets.append(f"{item.get('timestamp', '')} {item.get('text', '')}".strip())
                else:
                    snippets.append(str(item))
    return " / ".join(snippets[:5])


def build_queue():
    knowledge = json.loads(KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    topic_index = json.loads(TOPIC_INDEX_PATH.read_text(encoding="utf-8"))
    topic_hits, representative_hits = build_topic_maps(topic_index)

    items = []
    for video in knowledge["videos"]:
        if video["processing_status"] not in {"needs_visual_review", "needs_correction"}:
            continue
        score, reasons, matched_terms = score_video(video, topic_hits, representative_hits)
        items.append(
            {
                "rank": 0,
                "review_status": video.get("review_status", "pending"),
                "priority_score": score,
                "priority_reasons": reasons,
                "matched_terms": matched_terms,
                "topic_hits": topic_hits.get(video["video_id"], []),
                "representative_hits": representative_hits.get(video["video_id"], []),
                "video_id": video["video_id"],
                "title": video["title"],
                "url": video["url"],
                "category": video["category"],
                "tags": video["tags"],
                "duration_seconds": video.get("duration_seconds"),
                "confidence": video["confidence"],
                "review_checklist": [
                    "confirm_teaching_content",
                    "confirm_terms_and_action_direction",
                    "capture_1_to_3_timestamped_cues",
                    "mark_approved_needs_correction_not_teaching_or_low_value",
                ],
                "review_notes": video.get("review_notes", ""),
                "teaching_note_preview": compact_note(video),
            }
        )

    items.sort(key=lambda item: (-item["priority_score"], item["category"], item["title"]))
    for index, item in enumerate(items, 1):
        item["rank"] = index

    return {
        "version": "visual-review-queue-v1",
        "source": str(KNOWLEDGE_PATH.relative_to(ROOT)),
        "source_updated_at": knowledge["updated_at"],
        "topic_index": str(TOPIC_INDEX_PATH.relative_to(ROOT)),
        "total_pending": len(items),
        "status_counts": {"pending": len(items)},
        "allowed_review_statuses": [
            "pending",
            "approved",
            "needs_correction",
            "not_teaching",
            "low_value",
        ],
        "items": items,
    }


def render_markdown(queue):
    lines = [
        "# 刘辉羽毛球视觉复核队列",
        "",
        "This queue ranks `needs_visual_review` videos by likely coaching value. Use it to review the most useful visual-first clips before treating them as strong evidence.",
        "",
        f"- Source: `{queue['source']}`",
        f"- Pending videos: `{queue['total_pending']}`",
        "",
        "## Review Status Values",
        "",
        "- `approved`: teaching content is clear and timestamped cues are reliable.",
        "- `needs_correction`: teaching content is useful, but ASR/topic fields need correction.",
        "- `not_teaching`: exclude from coaching evidence.",
        "- `low_value`: teaching exists but should not be prioritized.",
        "",
        "## Top Priority Items",
        "",
    ]
    for item in queue["items"]:
        lines.extend(
            [
                f"### {item['rank']}. {item['title']}",
                "",
                f"- Status: `{item['review_status']}`",
                f"- Priority score: `{item['priority_score']}`",
                f"- Video ID: `{item['video_id']}`",
                f"- Category: `{item['category']}`",
                f"- URL: {item['url']}",
                f"- Topic hits: {', '.join(item['topic_hits']) if item['topic_hits'] else 'none'}",
                f"- Matched terms: {', '.join(item['matched_terms']) if item['matched_terms'] else 'none'}",
                f"- Reasons: {'; '.join(item['priority_reasons'])}",
                f"- Preview: {item['teaching_note_preview'] or 'none'}",
                "",
                "Review notes:",
                "",
                f"- {item['review_notes']}" if item["review_notes"] else "-",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def main():
    queue = build_queue()
    JSON_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    MARKDOWN_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bundle(
        {
            JSON_OUTPUT: (
                json.dumps(queue, ensure_ascii=False, indent=2) + "\n"
            ).encode("utf-8"),
            MARKDOWN_OUTPUT: render_markdown(queue).encode("utf-8"),
        }
    )
    print(json.dumps({"total_pending": queue["total_pending"], "top_video_id": queue["items"][0]["video_id"] if queue["items"] else None}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
