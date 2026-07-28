#!/usr/bin/env python3
"""Build verified Bilibili evidence with the same quality gates as Douyin."""

import copy
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from build_douyin_knowledge import (
    assess_transcript,
    automatic_note,
    clean_title,
    reconcile_updated_at,
    runtime_transcript_segments,
)
from project_artifacts import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
QUEUE_PATH = ROOT / "data" / "processing" / "bilibili_queue.json"
TRANSCRIPT_ROOT = ROOT / "data" / "transcripts" / "bilibili"
DOUYIN_KNOWLEDGE_PATH = ROOT / "data" / "knowledge" / "douyin_knowledge_base.json"
QUALITY_RULES_PATH = ROOT / "config" / "knowledge_quality_rules.json"
OUTPUT_PATH = ROOT / "data" / "knowledge" / "bilibili_knowledge_base.json"


def normalize_text(text):
    return "".join(re.findall(r"[\u4e00-\u9fff]+|[a-z0-9]+", str(text).lower()))


def shingles(text, size=6):
    value = normalize_text(text)
    return {
        value[index:index + size]
        for index in range(max(0, len(value) - size + 1))
    }


def transcript_text(video):
    return "".join(
        str(segment.get("text") or "")
        for segment in video.get("transcript_segments") or []
    )


def build_douyin_shingle_index(knowledge):
    postings = defaultdict(set)
    sets = {}
    durations = {}
    for video in knowledge.get("videos", []):
        if (
            video.get("processing_status") != "ready"
            or video.get("source_type") != "douyin_video"
        ):
            continue
        grams = shingles(transcript_text(video))
        if not grams:
            continue
        video_id = video["video_id"]
        sets[video_id] = grams
        durations[video_id] = float(video.get("duration_seconds") or 0)
        for gram in grams:
            postings[gram].add(video_id)
    return postings, sets, durations


def duplicate_candidates(segments, duration, index, threshold=0.85):
    grams = shingles("".join(str(item.get("text") or "") for item in segments))
    if not grams:
        return []
    postings, sets, durations = index
    candidates = set()
    for gram in grams:
        candidates.update(postings.get(gram, ()))
    matches = []
    for video_id in candidates:
        other = sets[video_id]
        intersection = len(grams & other)
        union = len(grams | other)
        jaccard = intersection / union if union else 0
        containment = intersection / min(len(grams), len(other))
        other_duration = durations[video_id]
        duration_ratio = (
            max(duration, other_duration) / min(duration, other_duration)
            if duration > 0 and other_duration > 0
            else float("inf")
        )
        duplicate = jaccard >= threshold or (
            containment >= 0.92 and duration_ratio <= 1.25
        )
        if duplicate:
            matches.append({
                "evidence_id": video_id,
                "transcript_jaccard": round(jaccard, 4),
                "shorter_transcript_containment": round(containment, 4),
                "duration_ratio": round(duration_ratio, 4),
            })
    return sorted(
        matches,
        key=lambda item: (
            -item["transcript_jaccard"],
            -item["shorter_transcript_containment"],
            item["evidence_id"],
        ),
    )[:5]


def infer_category(text):
    for category, pattern in [
        ("发球与接发", r"发球|接发"),
        ("步法与移动", r"启动|步法|蹬地|移动"),
        ("单打战术", r"单打|球路|制胜"),
        ("双打战术", r"双打|轮转|混双"),
        ("网前技术", r"网前|搓球|勾球|扑球|放网"),
        ("中前场与抽挡", r"抽挡|平抽|中场"),
        ("后场技术", r"反手|高远球|杀球|吊球|后场|架拍"),
        ("握拍与基本动作", r"握拍|拍面|击球点"),
        ("发力与身体运用", r"发力|手腕|小臂|转体"),
    ]:
        if re.search(pattern, text):
            return category
    return "训练与纠错"


def build_record(item, transcript_path, transcript, rules, duplicate_index):
    segments = transcript.get("segments") or []
    transcript_quality = assess_transcript(transcript, rules)
    enriched = {
        **item,
        "category": item.get("category") or infer_category(
            f"{item.get('title', '')} {item.get('description', '')}"
        ),
    }
    automatic = automatic_note(enriched, segments, rules)
    automatic_ready = transcript_quality["passed"] and automatic["quality"]["passed"]
    duplicates = duplicate_candidates(
        segments, float(transcript.get("duration") or 0), duplicate_index
    )
    status = "low_value" if duplicates else (
        "ready" if automatic_ready else "needs_visual_review"
    )
    confidence = "cross_platform_duplicate" if duplicates else (
        "medium" if automatic_ready else "low"
    )
    bvid = item["video_id"]
    evidence_id = item["evidence_id"]
    canonical_url = f"https://www.bilibili.com/video/{bvid}/"
    record = {
        "video_id": evidence_id,
        "evidence_id": evidence_id,
        "source_type": "bilibili_video",
        "canonical_url": canonical_url,
        "parent_source_id": None,
        "clip_start_seconds": None,
        "clip_end_seconds": None,
        "source_video_id": bvid,
        "publisher": "大G羽毛球",
        "uploader_profile_id": "1423436652",
        "title": clean_title(item["title"]),
        "url": canonical_url,
        "category": enriched["category"],
        "tags": item["tags"].split("；") if item.get("tags") else [],
        "duration_seconds": round(float(transcript.get("duration") or 0), 1),
        "processing_status": status,
        "confidence": confidence,
        "transcript_file": str(transcript_path.relative_to(ROOT)),
        "quality": {
            "transcript": transcript_quality,
            "automatic_evidence": automatic["quality"],
        },
        "classification": {
            "decision": item["classification_decision"],
            "reason": item["classification_reason"],
            "rules_version": item["classification_rules_version"],
            "rules_hash": item["classification_rules_hash"],
        },
        "origin_verification": copy.deepcopy(item["origin_verification"]),
        "possible_duplicate_evidence": duplicates,
        "teaching_note": automatic["note"],
        "transcript_segments": (
            runtime_transcript_segments(segments, rules)
            if status == "ready"
            else []
        ),
    }
    if duplicates:
        record["teaching_note"]["note"] = (
            "与现有抖音证据高度重复；保留来源台账但不进入回答证据池。"
        )
    elif not automatic_ready:
        record["teaching_note"]["note"] = (
            "自动证据未达到质量门槛，需复核后才能用于回答。"
        )
    return record


def build_knowledge(queue, transcripts, rules, douyin_knowledge):
    duplicate_index = build_douyin_shingle_index(douyin_knowledge)
    records = []
    missing = []
    for item in queue["items"]:
        if item.get("status") != "transcribed":
            continue
        transcript_path = transcripts.get(item["video_id"])
        if transcript_path is None:
            missing.append(item["video_id"])
            continue
        transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
        records.append(
            build_record(item, transcript_path, transcript, rules, duplicate_index)
        )
    if missing:
        raise SystemExit("Missing Bilibili transcripts: " + ", ".join(missing))
    status_counts = Counter(item["processing_status"] for item in records)
    return {
        "version": 1,
        "evidence_schema_version": 1,
        "scope": "经来源核验的大G羽毛球B站刘辉教学切片",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "quality_rules_version": rules["version"],
        "queue_counts": queue["counts"],
        "knowledge_counts": {
            "videos": len(records),
            **dict(status_counts),
            "transcript_segment_videos": sum(
                bool(item["transcript_segments"]) for item in records
            ),
            "transcript_segments": sum(
                len(item["transcript_segments"]) for item in records
            ),
        },
        "runtime_transcript_segments_bundled": True,
        "videos": records,
    }


def main():
    queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    rules = json.loads(QUALITY_RULES_PATH.read_text(encoding="utf-8"))
    douyin = json.loads(DOUYIN_KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    transcripts = {path.stem: path for path in TRANSCRIPT_ROOT.rglob("*.json")}
    output = build_knowledge(queue, transcripts, rules, douyin)
    existing = json.loads(OUTPUT_PATH.read_text(encoding="utf-8")) if OUTPUT_PATH.exists() else None
    output, changed = reconcile_updated_at(output, existing)
    serialized = json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    if not OUTPUT_PATH.exists() or OUTPUT_PATH.read_text(encoding="utf-8") != serialized:
        atomic_write_text(OUTPUT_PATH, serialized)
    print(json.dumps({
        "output": str(OUTPUT_PATH.relative_to(ROOT)),
        "videos": output["knowledge_counts"]["videos"],
        "ready": output["knowledge_counts"].get("ready", 0),
        "low_value": output["knowledge_counts"].get("low_value", 0),
        "semantic_change": changed,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
