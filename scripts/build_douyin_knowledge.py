#!/usr/bin/env python3
import json
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUEUE_PATH = ROOT / "data" / "processing" / "douyin_queue.json"
TRANSCRIPT_ROOT = ROOT / "data" / "transcripts" / "douyin"
CURATED_PATH = ROOT / "data" / "knowledge" / "pilot_teaching_notes.json"
REVIEW_ANNOTATIONS_PATH = ROOT / "data" / "review" / "visual_review_annotations.json"
OUTPUT_PATH = ROOT / "data" / "knowledge" / "douyin_knowledge_base.json"

TEACHING_TERMS = re.compile(
    r"架拍|挥拍|击球|发力|步法|重心|侧身|回动|启动|落点|线路|"
    r"杀球|高远|吊球|搓球|勾球|发球|接发|防守|进攻|轮转|握拍|拍面"
)
ERROR_TERMS = re.compile(r"错误|问题|不要|不能|来不及|太晚|过低|过高|被动|丢失|不对")
CUE_TERMS = re.compile(r"应该|需要|一定|首先|然后|先|再|注意|记住|尽量|必须|可以")


def timestamp(seconds):
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes:02}:{secs:02}"


def clean_title(title):
    title = re.sub(r"#\S+", "", title)
    title = re.sub(r"@\S+", "", title)
    title = re.sub(r"^\d+(?:\.\d+)?万\s*", "", title)
    return re.sub(r"\s+", " ", title).strip()


def evidence_window(segments, index):
    start = max(0, index - 1)
    end = min(len(segments), index + 2)
    group = segments[start:end]
    return {
        "timestamp": f"{timestamp(group[0]['start'])}-{timestamp(group[-1]['end'])}",
        "text": "".join(item["text"] for item in group),
    }


def select_evidence(segments, pattern, limit):
    selected = []
    seen = set()
    scored = []
    for index, segment in enumerate(segments):
        matches = len(pattern.findall(segment["text"]))
        if matches:
            scored.append((matches, len(segment["text"]), index))
    for _, _, index in sorted(scored, reverse=True):
        item = evidence_window(segments, index)
        marker = item["text"][:18]
        if marker in seen:
            continue
        seen.add(marker)
        selected.append(item)
        if len(selected) == limit:
            break
    return sorted(selected, key=lambda item: item["timestamp"])


queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
curated_data = json.loads(CURATED_PATH.read_text(encoding="utf-8"))
curated = {item["video_id"]: item for item in curated_data["videos"]}
if REVIEW_ANNOTATIONS_PATH.exists():
    review_annotations_data = json.loads(REVIEW_ANNOTATIONS_PATH.read_text(encoding="utf-8"))
    review_annotations = {
        item["video_id"]: item
        for item in review_annotations_data.get("items", [])
        if item.get("review_status") != "pending"
    }
else:
    review_annotations = {}
transcripts = {
    path.stem: path
    for path in TRANSCRIPT_ROOT.rglob("*.json")
}
records = []

for item in queue["items"]:
    transcript_path = transcripts.get(item["video_id"])
    if not transcript_path:
        continue
    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    segments = transcript["segments"]
    has_speech = len(segments) >= 5 and len(transcript["full_text"]) >= 40
    record = {
        "video_id": item["video_id"],
        "title": clean_title(item["title"]),
        "url": item["url"],
        "category": item["category"],
        "tags": item["tags"].split("；") if item["tags"] else [],
        "duration_seconds": round(transcript["duration"], 1),
        "processing_status": "ready" if has_speech else "needs_visual_review",
        "confidence": "curated" if item["video_id"] in curated else ("medium" if has_speech else "low"),
        "transcript_file": str(transcript_path.relative_to(ROOT)),
    }
    if item["video_id"] in curated:
        record["teaching_note"] = curated[item["video_id"]]
    elif has_speech:
        record["teaching_note"] = {
            "topic": clean_title(item["title"]).split("，")[0][:100],
            "key_evidence": select_evidence(segments, TEACHING_TERMS, 5),
            "error_evidence": select_evidence(segments, ERROR_TERMS, 3),
            "action_cues": select_evidence(segments, CUE_TERMS, 4),
            "note": "自动抽取；用于正式回答前应结合上下文与视频画面复核术语。",
        }
    else:
        record["teaching_note"] = {
            "topic": clean_title(item["title"])[:100],
            "key_evidence": [],
            "error_evidence": [],
            "action_cues": [],
            "note": "口播不足，需视觉分析后生成教学结论。",
        }
    review_annotation = review_annotations.get(item["video_id"])
    if review_annotation:
        record["review_status"] = review_annotation["review_status"]
        record["review_notes"] = review_annotation["review_notes"]
        record["reviewed_at"] = review_annotation["reviewed_at"]
        if review_annotation["review_status"] == "not_teaching":
            record["processing_status"] = "not_teaching"
            record["confidence"] = "reviewed_non_teaching"
            record["teaching_note"] = {
                "topic": clean_title(item["title"])[:100],
                "review_summary": review_annotation["review_notes"],
                "key_evidence": [],
                "error_evidence": [],
                "action_cues": [],
                "note": "人工视觉复核：非教学视频，不作为教练证据使用。",
            }
        else:
            record["processing_status"] = "ready"
            record["confidence"] = "visual_reviewed"
            note = record.get("teaching_note") or {}
            note["review_summary"] = review_annotation["review_notes"]
            note["visual_review_evidence"] = [
                {
                    "timestamp": "visual_review_no_timestamp",
                    "text": review_annotation["review_notes"],
                }
            ]
            note["note"] = "人工视觉复核：可作为视觉示范类教学线索；若无精确时间戳，引用时需说明来自人工视觉复核笔记。"
            record["teaching_note"] = note
    records.append(record)

status_counts = {}
for record in records:
    status_counts[record["processing_status"]] = status_counts.get(record["processing_status"], 0) + 1

OUTPUT_PATH.write_text(
    json.dumps({
        "version": 1,
        "scope": "刘辉羽毛球抖音教学视频",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "queue_counts": queue["counts"],
        "knowledge_counts": {
            "videos": len(records),
            **status_counts,
            "curated": sum(item["confidence"] == "curated" for item in records),
            "visual_reviewed": sum(item["confidence"] == "visual_reviewed" for item in records),
        },
        "videos": records,
    }, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print(json.dumps({
    "output": str(OUTPUT_PATH),
    "videos": len(records),
    "ready": sum(item["processing_status"] == "ready" for item in records),
    "needs_visual_review": sum(
        item["processing_status"] == "needs_visual_review" for item in records
    ),
    "not_teaching": sum(item["processing_status"] == "not_teaching" for item in records),
}, ensure_ascii=False))
