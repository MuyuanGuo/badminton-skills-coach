#!/usr/bin/env python3
import json
import copy
import re
from datetime import datetime, timezone
from pathlib import Path

from project_artifacts import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
QUEUE_PATH = ROOT / "data" / "processing" / "douyin_queue.json"
TRANSCRIPT_ROOT = ROOT / "data" / "transcripts" / "douyin"
CURATED_PATH = ROOT / "data" / "knowledge" / "pilot_teaching_notes.json"
REVIEW_ANNOTATIONS_PATH = ROOT / "data" / "review" / "visual_review_annotations.json"
QUALITY_RULES_PATH = ROOT / "config" / "knowledge_quality_rules.json"
OUTPUT_PATH = ROOT / "data" / "knowledge" / "douyin_knowledge_base.json"


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


def compile_terms(terms):
    values = sorted({term for term in terms if term}, key=lambda term: (-len(term), term))
    return re.compile("|".join(re.escape(term) for term in values)) if values else None


def select_evidence(segments, patterns, limit):
    selected = []
    seen = set()
    scored = []
    for index, segment in enumerate(segments):
        score = sum(
            weight * len(pattern.findall(segment["text"]))
            for pattern, weight in patterns
            if pattern is not None
        )
        if score:
            scored.append((score, len(segment["text"]), index))
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


def han_ratio(text):
    non_space = [character for character in text if not character.isspace()]
    if not non_space:
        return 0.0
    han_count = sum("\u3400" <= character <= "\u9fff" for character in non_space)
    return han_count / len(non_space)


def assess_transcript(transcript, rules):
    transcript_rules = rules["transcript"]
    language = str(transcript.get("language") or "").lower()
    probability = float(transcript.get("language_probability") or 0)
    segments = transcript.get("segments") or []
    full_text = str(transcript.get("full_text") or "")
    metrics = {
        "language": language,
        "language_probability": round(probability, 4),
        "segment_count": len(segments),
        "text_characters": len(full_text),
        "han_ratio": round(han_ratio(full_text), 4),
    }
    issues = []
    if not any(
        language.startswith(prefix.lower())
        for prefix in transcript_rules["allowed_language_prefixes"]
    ):
        issues.append("unexpected_language")
    if probability < transcript_rules["minimum_language_probability"]:
        issues.append("low_language_probability")
    if len(segments) < transcript_rules["minimum_segments"]:
        issues.append("too_few_segments")
    if len(full_text) < transcript_rules["minimum_text_characters"]:
        issues.append("too_little_text")
    if metrics["han_ratio"] < transcript_rules["minimum_han_ratio"]:
        issues.append("low_han_ratio")
    return {**metrics, "passed": not issues, "issues": issues}


def topic_terms(item, rules):
    metadata = " ".join(
        [clean_title(item.get("title", "")), item.get("category", ""), item.get("tags", "")]
    )
    matched = []
    for group in rules["evidence"]["topic_term_groups"]:
        if any(term in metadata for term in group):
            matched.extend(group)
    return sorted(set(matched), key=lambda term: (-len(term), term))


def automatic_note(item, segments, rules):
    evidence_rules = rules["evidence"]
    teaching_pattern = compile_terms(evidence_rules["teaching_terms"])
    topic_values = topic_terms(item, rules)
    topic_pattern = compile_terms(topic_values)
    key_evidence = select_evidence(
        segments,
        [(topic_pattern, 3), (teaching_pattern, 1)],
        evidence_rules["key_evidence_limit"],
    )
    error_evidence = select_evidence(
        segments,
        [(compile_terms(evidence_rules["error_terms"]), 1)],
        evidence_rules["error_evidence_limit"],
    )
    action_cues = select_evidence(
        segments,
        [(compile_terms(evidence_rules["cue_terms"]), 1)],
        evidence_rules["action_cue_limit"],
    )
    teaching_term_matches = sum(
        len(teaching_pattern.findall(segment["text"])) for segment in segments
    )
    evidence_text_characters = len("".join(segment["text"] for segment in segments))
    issues = []
    if len(key_evidence) < evidence_rules["minimum_key_evidence_items"]:
        issues.append("missing_key_evidence")
    if teaching_term_matches < evidence_rules["minimum_teaching_term_matches"]:
        issues.append("too_few_teaching_term_matches")
    elif (
        teaching_term_matches == evidence_rules["minimum_teaching_term_matches"]
        and evidence_text_characters
        < evidence_rules["minimum_text_characters_for_single_match"]
    ):
        issues.append("insufficient_context_for_single_match")
    return {
        "note": {
            "topic": clean_title(item["title"]).split("，")[0][:100],
            "key_evidence": key_evidence,
            "error_evidence": error_evidence,
            "action_cues": action_cues,
            "note": "自动抽取；用于正式回答前应结合上下文与视频画面复核术语。",
        },
        "quality": {
            "topic_terms": topic_values,
            "key_evidence_count": len(key_evidence),
            "teaching_term_matches": teaching_term_matches,
            "evidence_text_characters": evidence_text_characters,
            "passed": not issues,
            "issues": issues,
        },
    }


def apply_review_annotation(record, review_annotation):
    status = review_annotation["review_status"]
    record["review_status"] = status
    record["review_notes"] = review_annotation["review_notes"]
    record["reviewed_at"] = review_annotation["reviewed_at"]

    if status == "not_teaching":
        record["processing_status"] = "not_teaching"
        record["confidence"] = "reviewed_non_teaching"
        record["teaching_note"] = {
            "topic": record["title"][:100],
            "review_summary": review_annotation["review_notes"],
            "key_evidence": [],
            "error_evidence": [],
            "action_cues": [],
            "note": "人工视觉复核：非教学视频，不作为教练证据使用。",
        }
    elif status == "low_value":
        record["processing_status"] = "low_value"
        record["confidence"] = "reviewed_low_value"
        note = record.get("teaching_note") or {}
        note["review_summary"] = review_annotation["review_notes"]
        note["note"] = "人工视觉复核：存在教学内容，但证据价值不足，不进入回答检索。"
        record["teaching_note"] = note
    elif status == "needs_correction":
        record["processing_status"] = "needs_correction"
        record["confidence"] = "review_needs_correction"
        note = record.get("teaching_note") or {}
        note["review_summary"] = review_annotation["review_notes"]
        note["note"] = "人工视觉复核：术语或主题仍需修正，修正完成前不得用于回答。"
        record["teaching_note"] = note
    elif status == "approved":
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
    else:
        raise ValueError(f"Unsupported visual review status: {status}")
    return record


def build_record(item, transcript_path, transcript, curated, review_annotations, rules):
    segments = transcript.get("segments") or []
    transcript_quality = assess_transcript(transcript, rules)
    automatic = automatic_note(item, segments, rules)
    is_curated = item["video_id"] in curated
    automatic_ready = transcript_quality["passed"] and automatic["quality"]["passed"]
    record = {
        "video_id": item["video_id"],
        "title": clean_title(item["title"]),
        "url": item["url"],
        "category": item["category"],
        "tags": item["tags"].split("；") if item["tags"] else [],
        "duration_seconds": round(transcript.get("duration") or 0, 1),
        "processing_status": "ready" if is_curated or automatic_ready else "needs_visual_review",
        "confidence": "curated" if is_curated else ("medium" if automatic_ready else "low"),
        "transcript_file": str(transcript_path.relative_to(ROOT)),
        "quality": {
            "transcript": transcript_quality,
            "automatic_evidence": automatic["quality"],
        },
    }
    if is_curated:
        record["teaching_note"] = curated[item["video_id"]]
    else:
        record["teaching_note"] = automatic["note"]
        if not automatic_ready:
            record["teaching_note"]["note"] = "自动证据未达到质量门槛，需复核后才能用于回答。"
    review_annotation = review_annotations.get(item["video_id"])
    if review_annotation:
        apply_review_annotation(record, review_annotation)
    return record


def build_knowledge(queue, curated_data, review_annotations_data, transcripts, rules):
    curated = {item["video_id"]: item for item in curated_data["videos"]}
    review_annotations = {
        item["video_id"]: item
        for item in review_annotations_data.get("items", [])
        if item.get("review_status") != "pending"
    }
    records = []
    missing_transcripts = []
    for item in queue["items"]:
        transcript_path = transcripts.get(item["video_id"])
        if not transcript_path:
            missing_transcripts.append(item["video_id"])
            continue
        transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
        records.append(
            build_record(item, transcript_path, transcript, curated, review_annotations, rules)
        )
    if missing_transcripts:
        raise SystemExit("Missing transcripts: " + ", ".join(missing_transcripts))
    status_counts = {}
    for record in records:
        status = record["processing_status"]
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "version": 1,
        "scope": "刘辉羽毛球抖音教学视频",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "quality_rules_version": rules["version"],
        "queue_counts": queue["counts"],
        "knowledge_counts": {
            "videos": len(records),
            **status_counts,
            "curated": sum(item["confidence"] == "curated" for item in records),
            "visual_reviewed": sum(item["confidence"] == "visual_reviewed" for item in records),
        },
        "videos": records,
    }


def reconcile_updated_at(candidate, existing=None, now=None):
    """Keep the corpus version stable when only the rebuild time changed."""

    candidate = copy.deepcopy(candidate)
    now = now or datetime.now(timezone.utc).isoformat()
    if existing:
        candidate_semantic = copy.deepcopy(candidate)
        existing_semantic = copy.deepcopy(existing)
        candidate_semantic.pop("updated_at", None)
        existing_semantic.pop("updated_at", None)
        if candidate_semantic == existing_semantic and existing.get("updated_at"):
            candidate["updated_at"] = existing["updated_at"]
            return candidate, False
    candidate["updated_at"] = now
    return candidate, True


def main():
    queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    curated_data = json.loads(CURATED_PATH.read_text(encoding="utf-8"))
    review_annotations_data = (
        json.loads(REVIEW_ANNOTATIONS_PATH.read_text(encoding="utf-8"))
        if REVIEW_ANNOTATIONS_PATH.exists()
        else {"items": []}
    )
    rules = json.loads(QUALITY_RULES_PATH.read_text(encoding="utf-8"))
    transcripts = {path.stem: path for path in TRANSCRIPT_ROOT.rglob("*.json")}
    output = build_knowledge(
        queue, curated_data, review_annotations_data, transcripts, rules
    )
    existing = (
        json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        if OUTPUT_PATH.exists()
        else None
    )
    output, changed = reconcile_updated_at(output, existing)
    serialized = json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    if not OUTPUT_PATH.exists() or OUTPUT_PATH.read_text(encoding="utf-8") != serialized:
        atomic_write_text(OUTPUT_PATH, serialized)
    counts = output["knowledge_counts"]
    print(
        json.dumps(
            {
                "output": str(OUTPUT_PATH),
                "videos": counts["videos"],
                "ready": counts.get("ready", 0),
                "needs_visual_review": counts.get("needs_visual_review", 0),
                "not_teaching": counts.get("not_teaching", 0),
                "semantic_change": changed,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
