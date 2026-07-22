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


def canonicalize_asr_text(text, rules):
    canonical = str(text or "")
    replacements = rules.get("asr_canonicalization", {})
    for source in sorted(replacements, key=len, reverse=True):
        canonical = canonical.replace(source, replacements[source])
    return canonical


def evidence_window(segments, index, rules):
    start = max(0, index - 1)
    end = min(len(segments), index + 2)
    group = segments[start:end]
    raw_text = "".join(str(item.get("text", "")) for item in group)
    text = canonicalize_asr_text(raw_text, rules)
    item = {
        "timestamp": f"{timestamp(group[0]['start'])}-{timestamp(group[-1]['end'])}",
        "text": text,
        "_segment_indexes": set(range(start, end)),
        "_start": float(group[0]["start"]),
    }
    if text != raw_text:
        item["raw_text"] = raw_text
    return item


def compile_terms(terms):
    values = sorted({term for term in terms if term}, key=lambda term: (-len(term), term))
    return re.compile("|".join(re.escape(term) for term in values)) if values else None


def select_evidence(
    segments, patterns, limit, rules, temporal_buckets=1, minimum_duration=0
):
    selected = []
    scored = []
    evidence_rules = rules["evidence"]
    for index, segment in enumerate(segments):
        canonical_text = canonicalize_asr_text(segment["text"], rules)
        score = sum(
            weight * len(pattern.findall(canonical_text))
            for pattern, weight in patterns
            if pattern is not None
        )
        if score:
            scored.append((score, len(canonical_text), index))
    ranked = sorted(scored, key=lambda item: (-item[0], item[2]))
    ordered_indexes = []
    if segments and temporal_buckets > 1:
        transcript_start = float(segments[0].get("start") or 0)
        transcript_end = float(
            segments[-1].get("end") or segments[-1].get("start") or transcript_start
        )
        duration = transcript_end - transcript_start
        if duration >= minimum_duration:
            for bucket in range(temporal_buckets):
                bucket_start = transcript_start + duration * bucket / temporal_buckets
                bucket_end = transcript_start + duration * (bucket + 1) / temporal_buckets
                candidates = [
                    item
                    for item in ranked
                    if bucket_start
                    <= float(segments[item[2]].get("start") or 0)
                    < bucket_end
                ]
                if candidates:
                    ordered_indexes.append(candidates[0][2])
    ordered_indexes.extend(
        index for _, _, index in ranked if index not in ordered_indexes
    )

    for index in ordered_indexes:
        item = evidence_window(segments, index, rules)
        if len(re.sub(r"\s+", "", item["text"])) < evidence_rules.get(
            "minimum_evidence_window_characters", 1
        ):
            continue
        overlaps = []
        for existing in selected:
            shared = item["_segment_indexes"] & existing["_segment_indexes"]
            denominator = min(
                len(item["_segment_indexes"]), len(existing["_segment_indexes"])
            )
            overlaps.append(len(shared) / max(1, denominator))
        if overlaps and max(overlaps) > evidence_rules.get(
            "maximum_window_segment_overlap", 1.0
        ):
            continue
        selected.append(item)
        if len(selected) == limit:
            break
    clean = []
    for item in sorted(selected, key=lambda value: value["_start"]):
        clean.append(
            {
                key: value
                for key, value in item.items()
                if not key.startswith("_")
            }
        )
    return clean


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


def runtime_transcript_segments(segments, rules=None):
    """Keep the complete timestamped transcript needed for query-time evidence lookup."""

    compact = []
    for segment in segments:
        raw_text = re.sub(r"\s+", " ", str(segment.get("text") or "")).strip()
        text = canonicalize_asr_text(raw_text, rules or {})
        if not text:
            continue
        start = round(float(segment.get("start") or 0), 2)
        end = round(float(segment.get("end") or start), 2)
        item = {
                "start": start,
                "end": end,
                "timestamp": f"{timestamp(start)}-{timestamp(end)}",
                "text": text,
            }
        if text != raw_text:
            item["raw_text"] = raw_text
        compact.append(item)
    return compact


def normalize_time_ranges(ranges):
    normalized = []
    for item in ranges or []:
        if not isinstance(item, dict):
            raise ValueError("Transcript time ranges must be objects")
        start = round(float(item.get("start", 0)), 2)
        end = round(float(item.get("end", start)), 2)
        if end <= start:
            raise ValueError("Transcript time range end must be greater than start")
        normalized.append({"start": start, "end": end})
    return normalized


def filter_segments_by_time_ranges(segments, ranges):
    normalized = normalize_time_ranges(ranges)
    if not normalized:
        return list(segments)
    return [
        segment
        for segment in segments
        if any(
            float(segment.get("start") or 0) >= item["start"] - 0.01
            and float(segment.get("end") or segment.get("start") or 0)
            <= item["end"] + 0.01
            for item in normalized
        )
    ]


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
        rules,
    )
    coverage_evidence = []
    minimum_coverage_duration = evidence_rules.get(
        "minimum_duration_for_temporal_coverage_seconds", 0
    )
    transcript_duration = (
        float(segments[-1].get("end") or segments[-1].get("start") or 0)
        - float(segments[0].get("start") or 0)
        if segments
        else 0
    )
    if transcript_duration >= minimum_coverage_duration:
        coverage_evidence = select_evidence(
            segments,
            [(topic_pattern, 3), (teaching_pattern, 1)],
            evidence_rules.get("coverage_evidence_limit", 3),
            rules,
            temporal_buckets=evidence_rules.get(
                "coverage_evidence_temporal_buckets", 1
            ),
            minimum_duration=minimum_coverage_duration,
        )
        key_markers = {
            (item.get("timestamp"), item.get("text")) for item in key_evidence
        }
        coverage_evidence = [
            item
            for item in coverage_evidence
            if (item.get("timestamp"), item.get("text")) not in key_markers
        ]
    error_evidence = select_evidence(
        segments,
        [(compile_terms(evidence_rules["error_terms"]), 1)],
        evidence_rules["error_evidence_limit"],
        rules,
    )
    action_cues = select_evidence(
        segments,
        [(compile_terms(evidence_rules["cue_terms"]), 1)],
        evidence_rules["action_cue_limit"],
        rules,
    )
    canonical_segments = [
        canonicalize_asr_text(segment["text"], rules) for segment in segments
    ]
    teaching_term_matches = sum(
        len(teaching_pattern.findall(text)) for text in canonical_segments
    )
    unique_teaching_terms = sorted(
        {
            match
            for text in canonical_segments
            for match in teaching_pattern.findall(text)
        }
    )
    instruction_pattern = compile_terms(evidence_rules.get("instruction_terms", []))
    instruction_signal_matches = sum(
        len(instruction_pattern.findall(text)) for text in canonical_segments
    )
    evidence_text_characters = len("".join(canonical_segments))
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
    if (
        len(unique_teaching_terms) == 1
        and instruction_signal_matches
        < evidence_rules.get("minimum_instruction_signal_matches_for_single_term", 0)
    ):
        issues.append("single_term_without_instruction_signal")
    note = {
        "topic": clean_title(item["title"]).split("，")[0][:100],
        "key_evidence": key_evidence,
        "error_evidence": error_evidence,
        "action_cues": action_cues,
        "note": "自动抽取；用于正式回答前应结合上下文与视频画面复核术语。",
    }
    if coverage_evidence:
        note["coverage_evidence"] = coverage_evidence
    return {
        "note": note,
        "quality": {
            "topic_terms": topic_values,
            "key_evidence_count": len(key_evidence),
            "teaching_term_matches": teaching_term_matches,
            "unique_teaching_terms": unique_teaching_terms,
            "instruction_signal_matches": instruction_signal_matches,
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
    if review_annotation.get("retrieval_title"):
        record["retrieval_title"] = review_annotation["retrieval_title"].strip()
    if review_annotation.get("category_override"):
        record["category"] = review_annotation["category_override"].strip()
    if review_annotation.get("tags_override") is not None:
        tags = review_annotation["tags_override"]
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise ValueError("Review tags_override must be a list of strings")
        record["tags"] = [tag.strip() for tag in tags if tag.strip()]

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
        notes = review_annotation["review_notes"]
        evidence_source = review_annotation.get("evidence_source")
        if not evidence_source:
            normalized_notes = notes.lower()
            evidence_source = (
                "reviewed_transcript"
                if "按转写的结果加进skill" in normalized_notes
                or "按转写结果加进skill" in normalized_notes
                else "visual_summary"
            )
        record["review_evidence_source"] = evidence_source
        automatic_quality = record.get("quality", {}).get("automatic_evidence", {})
        automatic_quality["searchable"] = False
        automatic_quality["disposition"] = "replaced_by_approved_review"
        if evidence_source == "reviewed_transcript":
            record["confidence"] = "reviewed_transcript"
            allowed_time_ranges = normalize_time_ranges(
                review_annotation.get("allowed_time_ranges")
            )
            if allowed_time_ranges:
                record["transcript_scope"] = {
                    "allowed_time_ranges": allowed_time_ranges,
                    "excluded_content_note": review_annotation.get(
                        "excluded_content_note", ""
                    ).strip(),
                }
            record["teaching_note"] = {
                "topic": (
                    record.get("retrieval_title") or record["title"]
                )[:100],
                "review_summary": review_annotation.get(
                    "teaching_summary", notes
                ).strip(),
                "note": (
                    "用户复核确认口播转写可用；回答时只引用查询命中的完整时间戳段落"
                    "和允许的教学时间范围，不使用范围外内容作为结论。"
                ),
            }
        elif evidence_source == "visual_summary":
            record["confidence"] = "visual_reviewed"
            record["teaching_note"] = {
                "topic": record["title"][:100],
                "review_summary": notes,
                "visual_review_evidence": [
                    {
                        "timestamp": "visual_review_no_timestamp",
                        "text": notes,
                    }
                ],
                "note": "用户视觉复核：仅以复核摘要作为可检索证据；失败或无关的自动转写已从运行时证据中移除。",
            }
        else:
            raise ValueError(f"Unsupported review evidence source: {evidence_source}")
    else:
        raise ValueError(f"Unsupported visual review status: {status}")
    return record


def build_record(item, transcript_path, transcript, curated, review_annotations, rules):
    segments = transcript.get("segments") or []
    transcript_quality = assess_transcript(transcript, rules)
    automatic = automatic_note(item, segments, rules)
    is_curated = item["video_id"] in curated
    automatic_ready = transcript_quality["passed"] and automatic["quality"]["passed"]
    classification_decision = item.get("classification_decision", "保留：教学")
    classification_reason = item.get("classification_reason", "")
    if classification_decision.startswith("排除"):
        initial_status = "not_teaching"
        initial_confidence = "classified_non_teaching"
    elif classification_decision.startswith("待复核"):
        initial_status = "needs_visual_review"
        initial_confidence = "classification_review_required"
    else:
        initial_status = (
            "ready" if is_curated or automatic_ready else "needs_visual_review"
        )
        initial_confidence = (
            "curated" if is_curated else ("medium" if automatic_ready else "low")
        )
    record = {
        "video_id": item["video_id"],
        "evidence_id": item["video_id"],
        "source_type": "douyin_video",
        "canonical_url": item["url"],
        "parent_source_id": None,
        "clip_start_seconds": None,
        "clip_end_seconds": None,
        "title": clean_title(item["title"]),
        "url": item["url"],
        "category": item["category"],
        "tags": item["tags"].split("；") if item["tags"] else [],
        "duration_seconds": round(transcript.get("duration") or 0, 1),
        "processing_status": initial_status,
        "confidence": initial_confidence,
        "transcript_file": str(transcript_path.relative_to(ROOT)),
        "quality": {
            "transcript": transcript_quality,
            "automatic_evidence": automatic["quality"],
        },
        "classification": {
            "decision": classification_decision,
            "reason": classification_reason,
            "rules_version": item.get("classification_rules_version"),
            "rules_hash": item.get("classification_rules_hash"),
        },
    }
    if is_curated:
        record["teaching_note"] = curated[item["video_id"]]
    else:
        record["teaching_note"] = automatic["note"]
        if classification_decision.startswith("排除"):
            record["teaching_note"]["note"] = (
                "版本化分类规则已排除此视频，不得作为回答证据。"
            )
        elif classification_decision.startswith("待复核"):
            record["teaching_note"]["note"] = (
                "版本化分类规则要求复核，复核完成前不得用于回答。"
            )
        elif not automatic_ready:
            record["teaching_note"]["note"] = "自动证据未达到质量门槛，需复核后才能用于回答。"
    review_annotation = review_annotations.get(item["video_id"])
    if review_annotation:
        apply_review_annotation(record, review_annotation)
    transcript_backed = (
        record["processing_status"] == "ready"
        and record["confidence"] != "visual_reviewed"
    )
    scoped_segments = filter_segments_by_time_ranges(
        segments,
        (record.get("transcript_scope") or {}).get("allowed_time_ranges"),
    )
    record["transcript_segments"] = (
        runtime_transcript_segments(scoped_segments, rules) if transcript_backed else []
    )
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
        if item.get("status") != "transcribed":
            continue
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
        "evidence_schema_version": 1,
        "scope": "刘辉羽毛球抖音教学视频",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "quality_rules_version": rules["version"],
        "queue_counts": queue["counts"],
        "knowledge_counts": {
            "videos": len(records),
            **status_counts,
            "curated": sum(item["confidence"] == "curated" for item in records),
            "visual_reviewed": sum(item["confidence"] == "visual_reviewed" for item in records),
            "reviewed_transcript": sum(
                item["confidence"] == "reviewed_transcript" for item in records
            ),
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
