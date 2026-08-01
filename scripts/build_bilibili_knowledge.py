#!/usr/bin/env python3
"""Build verified Bilibili evidence with the same quality gates as Douyin."""

import argparse
import copy
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from build_douyin_knowledge import (
    assess_transcript,
    automatic_note,
    canonicalize_asr_text,
    clean_title,
    reconcile_updated_at,
    runtime_transcript_segments,
)
from batch_transcribe_directory import (
    transcription_recipe,
    validate_transcript_payload,
)
from bilibili_pipeline import acquire_bilibili_pipeline_lock
from bilibili_storage import (
    BILIBILI_TRANSCRIPT_CACHE_ENV,
    bilibili_transcript_cache_root,
    bilibili_transcript_roots,
    index_exact_transcript_candidates,
    portable_transcript_reference,
)
from project_artifacts import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
QUEUE_PATH = ROOT / "data" / "processing" / "bilibili_queue.json"
LEDGER_PATH = ROOT / "data" / "bilibili_classification_ledger.json"
TRANSCRIPT_ROOT = bilibili_transcript_cache_root(ROOT)
DOUYIN_KNOWLEDGE_PATH = ROOT / "data" / "knowledge" / "douyin_knowledge_base.json"
QUALITY_RULES_PATH = ROOT / "config" / "knowledge_quality_rules.json"
OUTPUT_PATH = ROOT / "data" / "knowledge" / "bilibili_knowledge_base.json"
TRANSCRIPT_HASH_FIELDS = (
    "video_id",
    "source_bytes",
    "source_sha256",
    "model",
    "language",
    "language_probability",
    "duration",
    "segments",
    "segment_quality_metrics",
    "full_text",
    "transcription_recipe",
)


def normalize_text(text):
    return "".join(re.findall(r"[\u4e00-\u9fff]+|[a-z0-9]+", str(text).lower()))


def stable_payload_hash(payload):
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def validate_queue_classification_policy(queue, ledger):
    """Fail closed if stale or excluded ledger rows remain in the build queue."""

    ledger_by_bvid = {}
    for record in ledger.get("videos") or []:
        bvid = str(record.get("bvid") or "")
        if not bvid:
            raise ValueError("Bilibili classification ledger has a blank BVID")
        if bvid in ledger_by_bvid:
            raise ValueError(
                f"Bilibili classification ledger has duplicate BVID {bvid}"
            )
        ledger_by_bvid[bvid] = record

    seen_queue_ids = set()
    rejected = []
    for item in queue.get("items") or []:
        bvid = str(item.get("video_id") or "")
        if not bvid:
            raise ValueError("Bilibili queue has a blank video_id")
        if bvid in seen_queue_ids:
            raise ValueError(f"Bilibili queue has duplicate video_id {bvid}")
        seen_queue_ids.add(bvid)
        record = ledger_by_bvid.get(bvid)
        decision = str((record or {}).get("decision") or "missing")
        if decision != "required_transcription_policy":
            rejected.append(f"{bvid}:{decision}")
    if rejected:
        raise ValueError(
            "Bilibili build queue contains videos not admitted by the current "
            "required-transcription policy: " + ", ".join(sorted(rejected))
        )


def transcript_integrity(transcript, rules):
    config = rules.get("bilibili_unattended", {})
    recipe = transcript.get("transcription_recipe")
    recipe_payload = (
        copy.deepcopy(recipe)
        if isinstance(recipe, dict)
        else {
            "schema_version": 0,
            "model": str(transcript.get("model") or ""),
            "metadata_complete": False,
        }
    )
    required = config.get("required_recipe_fields", [])
    recipe_complete = (
        isinstance(recipe, dict)
        and all(key in recipe for key in required)
        and str(recipe.get("model") or "") == str(transcript.get("model") or "")
    )
    accepted_recipes = config.get("accepted_transcription_recipes")
    if not isinstance(accepted_recipes, list) or not accepted_recipes:
        accepted_recipes = [
            transcription_recipe(str(transcript.get("model") or ""))
        ]
    comparable_recipes = [
        item
        for item in accepted_recipes
        if isinstance(item, dict)
        and item.get("model") == transcript.get("model")
        and item.get("schema_version") == (
            recipe.get("schema_version")
            if isinstance(recipe, dict)
            else None
        )
    ]
    expected_recipe = (
        comparable_recipes[0]
        if comparable_recipes
        else accepted_recipes[0]
    )
    recipe_matches_expected = recipe_complete and any(
        all(recipe.get(key) == candidate.get(key) for key in required)
        for candidate in comparable_recipes
    )
    recipe_mismatches = {
        key: {
            "expected": expected_recipe.get(key),
            "actual": recipe.get(key) if isinstance(recipe, dict) else None,
        }
        for key in required
        if (
            not isinstance(recipe, dict)
            or recipe.get(key) != expected_recipe.get(key)
        )
    }
    content = {
        key: transcript.get(key)
        for key in TRANSCRIPT_HASH_FIELDS
        if key in transcript
    }
    return {
        "transcript_sha256": stable_payload_hash(content),
        "recipe_sha256": stable_payload_hash(recipe_payload),
        "recipe_metadata_complete": recipe_complete,
        "recipe_matches_expected": recipe_matches_expected,
        "recipe_mismatches": recipe_mismatches,
        "source_sha256": transcript.get("source_sha256"),
        "source_bytes": transcript.get("source_bytes"),
    }


def merged_interval_duration(segments):
    intervals = sorted(
        (
            max(0.0, float(item.get("start") or 0)),
            max(0.0, float(item.get("end") or item.get("start") or 0)),
        )
        for item in segments
    )
    total = 0.0
    current_start = None
    current_end = None
    for start, end in intervals:
        if end <= start:
            continue
        if current_start is None:
            current_start, current_end = start, end
        elif start <= current_end:
            current_end = max(current_end, end)
        else:
            total += current_end - current_start
            current_start, current_end = start, end
    if current_start is not None:
        total += current_end - current_start
    return total


def sanitize_retrieval_title(title, rules):
    value = clean_title(title)
    safety_rules = rules.get("source_content_safety", {})
    for key in (
        "prompt_injection_patterns",
        "external_action_patterns",
        "promotion_patterns",
        "social_cta_patterns",
    ):
        for pattern in safety_rules.get(key, []):
            value = re.sub(pattern, " ", value, flags=re.IGNORECASE)
    for pattern in rules.get("bilibili_unattended", {}).get(
        "retrieval_title_boilerplate_patterns", []
    ):
        value = re.sub(pattern, " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"^[\s，。！？!?、:：;；\-—]+", "", value)
    value = re.sub(r"[\s，。！？!?、:：;；\-—]+$", "", value)
    return value or clean_title(title)


def assess_source_content(item, segments, rules):
    """Classify source text before it can become searchable evidence.

    Raw transcripts remain auditable on disk. Only clean segments flow into
    automatic notes, duplicate matching, runtime chunks, and answer packets.
    The result intentionally records pattern categories, never matched source
    text, so an injection is not copied into another model-visible field.
    """

    config = rules.get("source_content_safety", {})
    pattern_groups = {
        key.removesuffix("_patterns"): [
            re.compile(pattern, flags=re.IGNORECASE)
            for pattern in config.get(key, [])
        ]
        for key in (
            "prompt_injection_patterns",
            "external_action_patterns",
            "promotion_patterns",
            "social_cta_patterns",
        )
    }

    def categories(text):
        value = str(text or "")
        return [
            name
            for name, patterns in pattern_groups.items()
            if any(pattern.search(value) for pattern in patterns)
        ]

    signals = []
    metadata_prompt_injection = False
    for scope in ("title", "description"):
        matched = categories(item.get(scope))
        if not matched:
            continue
        signals.append({"scope": scope, "categories": matched})
        if "prompt_injection" in matched:
            metadata_prompt_injection = True

    segment_texts = [
        str(segment.get("text") or "") for segment in segments
    ]
    segment_categories = [
        set(categories(text)) for text in segment_texts
    ]
    prompt_patterns = pattern_groups.get("prompt_injection", [])
    for index in range(len(segment_texts) - 1):
        current_matches = any(
            pattern.search(segment_texts[index])
            for pattern in prompt_patterns
        )
        next_matches = any(
            pattern.search(segment_texts[index + 1])
            for pattern in prompt_patterns
        )
        joined = segment_texts[index] + segment_texts[index + 1]
        if (
            not current_matches
            and not next_matches
            and any(pattern.search(joined) for pattern in prompt_patterns)
        ):
            segment_categories[index].add("prompt_injection")
            segment_categories[index + 1].add("prompt_injection")

    safe_segments = []
    excluded_indexes = []
    redacted_indexes = []
    excluded_characters = 0
    total_characters = sum(map(len, segment_texts))
    for index, (segment, text, matched) in enumerate(
        zip(segments, segment_texts, segment_categories)
    ):
        if matched:
            signals.append(
                {
                    "scope": "transcript_segment",
                    "segment_index": index,
                    "categories": sorted(matched),
                }
            )
        else:
            safe_segments.append(segment)
            continue
        if "prompt_injection" in matched:
            excluded_indexes.append(index)
            excluded_characters += len(text)
            continue
        redacted_text = text
        for category in matched:
            for pattern in pattern_groups.get(category, []):
                redacted_text = pattern.sub(" ", redacted_text)
        redacted_text = re.sub(r"\s+", " ", redacted_text).strip(
            " \t\r\n，。！？!?、:：;；-—"
        )
        excluded_characters += max(0, len(text) - len(redacted_text))
        if redacted_text:
            if redacted_text != text:
                redacted_indexes.append(index)
                safe_segments.append({**segment, "text": redacted_text})
            else:
                safe_segments.append(segment)
        else:
            excluded_indexes.append(index)

    excluded_ratio = (
        excluded_characters / total_characters if total_characters else 0.0
    )
    issues = []
    if metadata_prompt_injection:
        issues.append("metadata_prompt_injection")
    if segments and not safe_segments:
        issues.append("no_safe_transcript_segments")
    if excluded_ratio > float(
        config.get("maximum_excluded_character_ratio", 0.35)
    ):
        issues.append("unsafe_source_text_ratio_exceeded")
    return {
        "boundary": config.get(
            "boundary", "untrusted_non_executable_evidence"
        ),
        "passed": not issues,
        "issues": issues,
        "signals": signals,
        "excluded_segment_indexes": excluded_indexes,
        "redacted_segment_indexes": redacted_indexes,
        "excluded_segment_count": len(excluded_indexes),
        "redacted_segment_count": len(redacted_indexes),
        "eligible_segment_count": len(safe_segments),
        "excluded_character_ratio": round(excluded_ratio, 4),
    }, safe_segments


def assess_title_content(title, transcript, rules):
    config = rules.get("bilibili_unattended", {})
    retrieval_title = sanitize_retrieval_title(title, rules)
    title_text = normalize_text(
        canonicalize_asr_text(retrieval_title, rules)
    )
    transcript_value = normalize_text(
        canonicalize_asr_text(transcript.get("full_text") or "", rules)
    )
    matched = []
    for term in sorted(
        set(config.get("title_consistency_terms", [])),
        key=lambda value: (-len(normalize_text(value)), value),
    ):
        normalized = normalize_text(canonicalize_asr_text(term, rules))
        if normalized and normalized in title_text:
            matched.append(term)
    supported = [
        term
        for term in matched
        if normalize_text(canonicalize_asr_text(term, rules)) in transcript_value
    ]
    support_ratio = len(supported) / len(matched) if matched else 0.0
    minimum_terms = int(config.get("minimum_title_technique_terms", 1))
    minimum_ratio = float(config.get("minimum_title_term_support_ratio", 0.5))
    issues = []
    if len(matched) < minimum_terms:
        issues.append("title_has_no_technical_concept")
    elif len(supported) < minimum_terms or support_ratio < minimum_ratio:
        issues.append("title_technical_concept_not_supported_by_transcript")
    return {
        "retrieval_title": retrieval_title,
        "matched_terms": matched,
        "supported_terms": supported,
        "unsupported_terms": [
            term for term in matched if term not in set(supported)
        ],
        "support_ratio": round(support_ratio, 4),
        "passed": not issues,
        "issues": issues,
    }


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


def build_shingle_index(videos, source_types=None):
    postings = defaultdict(set)
    sets = {}
    durations = {}
    source_types = set(source_types or [])
    for video in videos:
        if (
            video.get("processing_status") != "ready"
            or (
                source_types
                and video.get("source_type") not in source_types
            )
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


def build_douyin_shingle_index(knowledge):
    return build_shingle_index(
        knowledge.get("videos", []),
        source_types={"douyin_video"},
    )


def add_to_shingle_index(index, evidence_id, segments, duration):
    grams = shingles("".join(str(item.get("text") or "") for item in segments))
    if not grams:
        return
    postings, sets, durations = index
    sets[evidence_id] = grams
    durations[evidence_id] = float(duration or 0)
    for gram in grams:
        postings[gram].add(evidence_id)


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


def assess_bilibili_transcript(
    transcript,
    rules,
    *,
    evidence_id=None,
    title=None,
    title_content_segments=None,
):
    result = assess_transcript(transcript, rules)
    issues = list(result.get("issues") or [])
    config = rules.get("bilibili_unattended", {})
    integrity = transcript_integrity(transcript, rules)
    legacy_hashes = config.get(
        "legacy_metricless_transcript_sha256", {}
    )
    legacy_exception = (
        isinstance(legacy_hashes, dict)
        and legacy_hashes.get(evidence_id)
        == integrity["transcript_sha256"]
    )
    segments = transcript.get("segments") or []
    duration = float(transcript.get("duration") or 0)
    full_text = str(transcript.get("full_text") or "")
    minimum_characters = max(
        int(rules["transcript"]["minimum_text_characters"]),
        math.ceil(
            duration
            * float(config.get("minimum_text_characters_per_second", 0))
        ),
    )
    minimum_segments = max(
        int(rules["transcript"]["minimum_segments"]),
        math.ceil(
            duration
            / 60
            * float(config.get("minimum_segments_per_minute", 0))
        ),
    )
    speech_seconds = merged_interval_duration(segments)
    speech_coverage = speech_seconds / duration if duration > 0 else 0.0
    result.update(
        {
            "duration_seconds": round(duration, 3),
            "minimum_text_characters_for_duration": minimum_characters,
            "minimum_segments_for_duration": minimum_segments,
            "speech_seconds": round(speech_seconds, 3),
            "speech_coverage": round(speech_coverage, 4),
            "characters_per_second": round(
                len(full_text) / duration if duration > 0 else 0.0,
                4,
            ),
            "legacy_metricless_exception": legacy_exception,
        }
    )
    if result["language_probability"] < float(
        config.get("minimum_language_probability", 0)
    ):
        issues.append("low_bilibili_language_probability")
    if len(full_text) < minimum_characters:
        issues.append("too_little_text_for_duration")
    if len(segments) < minimum_segments:
        issues.append("too_few_segments_for_duration")
    if speech_coverage < float(config.get("minimum_speech_coverage", 0)):
        issues.append("insufficient_speech_coverage")

    raw_metrics = transcript.get("segment_quality_metrics")
    metrics = raw_metrics if isinstance(raw_metrics, list) else []
    valid_metrics = [
        item
        for item in metrics
        if isinstance(item, dict)
        and all(
            isinstance(item.get(key), (int, float))
            and not isinstance(item.get(key), bool)
            for key in ("avg_logprob", "no_speech_prob", "compression_ratio")
        )
    ]
    metric_coverage = len(valid_metrics) / len(segments) if segments else 0.0
    if valid_metrics:
        count = len(valid_metrics)
        low_logprob_threshold = float(
            config.get("low_logprob_threshold", -1.2)
        )
        no_speech_threshold = float(
            config.get("no_speech_probability_threshold", 0.6)
        )
        no_speech_low_logprob_threshold = float(
            config.get("no_speech_low_logprob_threshold", -1.0)
        )
        compression_threshold = float(
            config.get("compression_ratio_threshold", 2.4)
        )
        low_logprob_ratio = sum(
            item["avg_logprob"] < low_logprob_threshold
            for item in valid_metrics
        ) / count
        high_no_speech_ratio = sum(
            item["no_speech_prob"] > no_speech_threshold
            for item in valid_metrics
        ) / count
        suspicious_no_speech_ratio = sum(
            item["no_speech_prob"] > no_speech_threshold
            and item["avg_logprob"] < no_speech_low_logprob_threshold
            for item in valid_metrics
        ) / count
        high_compression_ratio = sum(
            item["compression_ratio"] > compression_threshold
            for item in valid_metrics
        ) / count
        if low_logprob_ratio > float(
            config.get("maximum_low_logprob_ratio", 0.25)
        ):
            issues.append("too_many_low_logprob_segments")
        if suspicious_no_speech_ratio > float(
            config.get("maximum_suspicious_no_speech_ratio", 0.15)
        ):
            issues.append("too_many_probable_no_speech_segments")
        if high_compression_ratio > float(
            config.get("maximum_high_compression_ratio", 0.12)
        ):
            issues.append("too_many_high_compression_segments")
        result["segment_metrics"] = {
            "available": True,
            "coverage": round(metric_coverage, 4),
            "low_logprob_ratio": round(low_logprob_ratio, 4),
            "high_no_speech_ratio": round(high_no_speech_ratio, 4),
            "suspicious_no_speech_ratio": round(
                suspicious_no_speech_ratio, 4
            ),
            "high_compression_ratio": round(high_compression_ratio, 4),
        }
    else:
        result["segment_metrics"] = {
            "available": False,
            "coverage": round(metric_coverage, 4),
        }
    if (
        not legacy_exception
        and metric_coverage
        < float(config.get("minimum_segment_metric_coverage", 1.0))
    ):
        issues.append("incomplete_segment_quality_metrics")

    normalized_segments = [
        normalize_text(item.get("text") or "")
        for item in segments
        if normalize_text(item.get("text") or "")
    ]
    repeated = Counter(normalized_segments)
    repeated_characters = sum(
        len(text) * (count - 1)
        for text, count in repeated.items()
        if len(text) >= 8 and count >= 3
    )
    total_characters = sum(map(len, normalized_segments))
    repeated_ratio = (
        repeated_characters / total_characters if total_characters else 0
    )
    minimum_near_repeat = int(
        config.get("minimum_near_repeat_characters", 8)
    )
    near_repeat_similarity = float(
        config.get("near_repeat_similarity", 0.9)
    )
    consecutive_repeated_characters = sum(
        len(current)
        for previous, current in zip(
            normalized_segments,
            normalized_segments[1:],
        )
        if min(len(previous), len(current)) >= minimum_near_repeat
        and SequenceMatcher(None, previous, current).ratio()
        >= near_repeat_similarity
    )
    consecutive_repeated_ratio = (
        consecutive_repeated_characters / total_characters
        if total_characters
        else 0
    )
    internal_repeat_pattern = re.compile(
        "(.{%d,%d}?)\\1{%d,}"
        % (
            int(config.get("minimum_internal_repeat_unit_characters", 4)),
            int(config.get("maximum_internal_repeat_unit_characters", 32)),
            max(1, int(config.get("minimum_internal_repeat_count", 3)) - 1),
        )
    )
    internal_repeated_characters = sum(
        len(match.group(0)) - len(match.group(1))
        for text in normalized_segments
        for match in internal_repeat_pattern.finditer(text)
    )
    internal_repeated_ratio = (
        internal_repeated_characters / total_characters
        if total_characters
        else 0
    )
    repetition_risk = max(
        repeated_ratio,
        consecutive_repeated_ratio,
        internal_repeated_ratio,
    )
    result["repeated_segment_character_ratio"] = round(repeated_ratio, 4)
    result["consecutive_near_repeat_character_ratio"] = round(
        consecutive_repeated_ratio, 4
    )
    result["internal_repeat_character_ratio"] = round(
        internal_repeated_ratio, 4
    )
    result["repetition_risk_ratio"] = round(repetition_risk, 4)
    if repetition_risk > float(
        config.get("maximum_repeated_character_ratio", 0.15)
    ):
        issues.append("repeated_segment_hallucination_risk")

    result["integrity"] = integrity
    if not legacy_exception and not integrity["recipe_metadata_complete"]:
        issues.append("incomplete_transcription_recipe")
    elif not legacy_exception and not integrity["recipe_matches_expected"]:
        issues.append("unexpected_transcription_recipe")
    if title is not None:
        title_transcript = transcript
        if title_content_segments is not None:
            title_transcript = {
                "full_text": "".join(
                    str(segment.get("text") or "")
                    for segment in title_content_segments
                )
            }
        title_content = assess_title_content(title, title_transcript, rules)
        title_issues = list(title_content["issues"])
        if (
            legacy_exception
            and title_issues
            == ["title_technical_concept_not_supported_by_transcript"]
        ):
            # These exact transcript hashes were already part of the reviewed
            # Bilibili baseline before segment-level metrics and recipe
            # metadata existed. Preserve that reviewed evidence when ASR
            # confuses a title term (for example 单打→丹达), but bind the
            # exception to the immutable transcript hash. Every other quality,
            # safety, automatic-evidence, and duplicate gate still applies.
            title_content["legacy_locked_hash_exception"] = True
            title_content["original_issues"] = title_issues
            title_content["issues"] = []
            title_content["passed"] = True
        result["title_content_consistency"] = title_content
        issues.extend(title_content["issues"])
    result["issues"] = sorted(set(issues))
    result["passed"] = not result["issues"]
    return result


_CATEGORY_TERMS = [
    ("发球与接发", ("发球", "接发")),
    ("步法与移动", ("启动", "步法", "蹬地", "移动")),
    ("单打战术", ("单打", "球路", "制胜")),
    ("双打战术", ("双打", "轮转", "混双")),
    (
        "后场技术",
        (
            "反手杀",
            "反手高远",
            "反手过渡",
            "后场反手",
            "高远球",
            "杀球",
            "快杀",
            "点杀",
            "重杀",
            "跳杀",
            "劈杀",
            "遁地炮",
            "顿地炮",
            "蹲地炮",
            "吊球",
            "后场",
            "架拍",
        ),
    ),
    ("网前技术", ("网前", "搓球", "勾球", "扑球", "放网")),
    ("中前场与抽挡", ("抽挡", "平抽", "中场")),
    ("握拍与基本动作", ("握拍", "拍面", "击球点")),
    ("发力与身体运用", ("发力", "手腕", "小臂", "转体")),
]


def infer_category(title, transcript_text=""):
    """Infer from the uploader title, with a conservative transcript fallback.

    Full transcripts contain feeder prompts and incidental coaching phrases
    such as “给我发球” or “移动一下”.  Letting the first such phrase win made
    smash lessons look like serving or footwork lessons, which then changed
    answer-scope filtering.  A title signal is therefore authoritative.  The
    transcript is used only when one category has at least two distinct
    technical signals and no tie.
    """

    normalized_title = str(title or "")
    for category, terms in _CATEGORY_TERMS:
        if any(term in normalized_title for term in terms):
            return category

    normalized_transcript = str(transcript_text or "")
    scored = sorted(
        (
            (sum(term in normalized_transcript for term in terms), category)
            for category, terms in _CATEGORY_TERMS
        ),
        reverse=True,
    )
    if scored and scored[0][0] >= 2 and (
        len(scored) == 1 or scored[0][0] > scored[1][0]
    ):
        return scored[0][1]
    return "训练与纠错"


def assess_origin_verification(item):
    verification = item.get("origin_verification") or {}
    status = str(verification.get("status") or "")
    methods = set(verification.get("methods") or [])
    signals = verification.get("signals") or {}
    verified_at = bool(verification.get("verified_at"))
    shared_signals_pass = all(
        signals.get(name) is True
        for name in (
            "video_id_matches",
            "uploader_profile_matches",
            "canonical_url_matches",
            "duration_valid",
        )
    )
    policy_contracts = {
        "verified_collection_policy": "user_confirmed_collection_policy",
        "verified_video_policy": "user_confirmed_video_policy",
    }
    if status in policy_contracts:
        passed = (
            verified_at
            and shared_signals_pass
            and {
                "verified_uploader_profile",
                policy_contracts[status],
            }.issubset(methods)
        )
    elif status == "verified_liuhui_clip":
        independent_methods = {
            "cross_platform_content_match",
            "direct_video_content_review",
            "verified_source_watermark",
        }
        publisher_declared = (
            "publisher_origin_annotation" in methods
            and signals.get("uploader_profile_matches") is True
            and signals.get("publisher_text_names_liuhui") is True
            and signals.get("dedicated_origin_tag") is True
        )
        passed = verified_at and (
            bool(methods & independent_methods) or publisher_declared
        )
    else:
        passed = False
    return {
        "passed": passed,
        "status": status or None,
        "issues": [] if passed else ["origin_verification_not_admitted"],
    }


def build_record(
    item,
    transcript_path,
    transcript,
    rules,
    duplicate_index,
):
    segments = transcript.get("segments") or []
    evidence_id = item["evidence_id"]
    release_cohort = (
        "stable_baseline"
        if evidence_id
        in rules["bilibili_unattended"].get(
            "stable_retrieval_evidence_ids", []
        )
        else "automatic_expansion"
    )
    source_content_safety, safe_segments = assess_source_content(
        item, segments, rules
    )
    transcript_quality = assess_bilibili_transcript(
        transcript,
        rules,
        evidence_id=evidence_id,
        title=item["title"],
        title_content_segments=safe_segments,
    )
    retrieval_title = transcript_quality["title_content_consistency"][
        "retrieval_title"
    ]
    enriched = {
        **item,
        "title": retrieval_title,
        "category": item.get("category") or infer_category(
            retrieval_title,
            "".join(
                str(segment.get("text") or "") for segment in safe_segments
            ),
        ),
    }
    automatic = automatic_note(
        enriched,
        safe_segments,
        rules,
        provenance_text=(
            transcript.get("full_text")
            or "".join(
                str(segment.get("text") or "")
                for segment in segments
            )
        ),
    )
    origin_verification = assess_origin_verification(item)
    automatic_ready = (
        origin_verification["passed"]
        and transcript_quality["passed"]
        and source_content_safety["passed"]
        and automatic["quality"]["passed"]
    )
    duplicates = duplicate_candidates(
        safe_segments,
        float(transcript.get("duration") or 0),
        duplicate_index,
    )
    # Unattended Bilibili runs fail closed. Low-quality ASR is quarantined as
    # low-value evidence instead of creating a human-review backlog.
    status = "ready" if automatic_ready and not duplicates else "low_value"
    confidence = "cross_platform_duplicate" if duplicates else (
        "medium" if automatic_ready else "low"
    )
    bvid = item["video_id"]
    canonical_url = f"https://www.bilibili.com/video/{bvid}/"
    if duplicates:
        disposition = "duplicate"
    elif not origin_verification["passed"]:
        disposition = "quarantined_origin_verification"
    elif not source_content_safety["passed"]:
        disposition = "quarantined_source_content_safety"
    elif not transcript_quality["passed"]:
        disposition = "quarantined_transcript_or_title_quality"
    elif not automatic["quality"]["passed"]:
        disposition = "quarantined_automatic_evidence_quality"
    else:
        disposition = "quality_gate_passed"
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
        # The queue remains the audit source for the verbatim uploader title.
        # Knowledge/runtime surfaces use the non-executable cleaned title.
        "title": retrieval_title,
        "retrieval_title": retrieval_title,
        "url": canonical_url,
        "category": enriched["category"],
        "tags": item["tags"].split("；") if item.get("tags") else [],
        "duration_seconds": round(float(transcript.get("duration") or 0), 1),
        "processing_status": status,
        "confidence": confidence,
        "quality_recipe_mode": (
            "legacy_metricless_exception"
            if transcript_quality.get("legacy_metricless_exception")
            else "current_recipe"
        ),
        "release_cohort": release_cohort,
        # Runtime compatibility alias.  Release membership is deliberately
        # independent from transcript-recipe compatibility.
        "retrieval_cohort": release_cohort,
        "transcript_file": portable_transcript_reference(
            transcript_path,
            project_root=ROOT,
            cache_root=TRANSCRIPT_ROOT,
        ),
        "quality": {
            "origin_verification": origin_verification,
            "transcript": transcript_quality,
            "source_content_safety": source_content_safety,
            "automatic_evidence": automatic["quality"],
        },
        "automatic_admission": {
            "disposition": disposition,
            "answer_evidence_eligible": status == "ready",
            "rules_version": rules["version"],
        },
        "classification": {
            "decision": item["classification_decision"],
            "reason": item["classification_reason"],
            "rules_version": item["classification_rules_version"],
            "rules_hash": item["classification_rules_hash"],
        },
        "origin_verification": copy.deepcopy(
            item.get("origin_verification") or {}
        ),
        "possible_duplicate_evidence": duplicates,
        "teaching_note": automatic["note"],
        "transcript_segments": (
            runtime_transcript_segments(safe_segments, rules)
            if status == "ready"
            else []
        ),
    }
    if duplicates:
        record["teaching_note"]["note"] = (
            "与现有已接纳证据高度重复；保留来源台账但不进入回答证据池。"
        )
    elif not automatic_ready:
        record["teaching_note"]["note"] = (
            "自动证据或来源文本安全门槛未通过；已隔离，不进入回答证据池。"
        )
    return record


def load_valid_queue_transcript(item, transcript_path):
    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    media_path = item.get("media_path")
    source_media = ROOT / media_path if media_path else None
    if source_media is not None and not source_media.exists():
        source_media = None
    validate_transcript_payload(
        transcript,
        item["video_id"],
        source_media=source_media,
    )
    expected_sha = item.get("transcript_source_sha256")
    expected_bytes = item.get("transcript_source_bytes")
    if expected_sha and transcript.get("source_sha256") != expected_sha:
        raise ValueError(
            f"Transcript SHA-256 does not match queue for {item['video_id']}"
        )
    if expected_bytes and transcript.get("source_bytes") != expected_bytes:
        raise ValueError(
            f"Transcript byte count does not match queue for {item['video_id']}"
        )
    return transcript


def build_transcription_quarantine_record(item, rules):
    bvid = item["video_id"]
    evidence_id = item["evidence_id"]
    release_cohort = (
        "stable_baseline"
        if evidence_id
        in rules["bilibili_unattended"].get(
            "stable_retrieval_evidence_ids", []
        )
        else "automatic_expansion"
    )
    canonical_url = f"https://www.bilibili.com/video/{bvid}/"
    title = sanitize_retrieval_title(item["title"], rules)
    source_content_safety, _ = assess_source_content(item, [], rules)
    return {
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
        "title": title,
        "retrieval_title": title,
        "url": canonical_url,
        "category": item.get("category") or infer_category(title),
        "tags": item["tags"].split("；") if item.get("tags") else [],
        "duration_seconds": round(
            float(item.get("media_duration_seconds") or 0),
            1,
        ),
        "processing_status": "low_value",
        "confidence": "low",
        "quality_recipe_mode": "missing_transcript",
        "release_cohort": release_cohort,
        "retrieval_cohort": release_cohort,
        "transcript_file": None,
        "quality": {
            "transcript": {
                "passed": False,
                "issues": ["transcription_retry_exhausted"],
            },
            "source_content_safety": source_content_safety,
            "automatic_evidence": {
                "passed": False,
                "issues": ["missing_transcript"],
            },
        },
        "automatic_admission": {
            "disposition": "quarantined_transcription_retry_exhausted",
            "answer_evidence_eligible": False,
            "rules_version": rules["version"],
        },
        "classification": {
            "decision": item["classification_decision"],
            "reason": item["classification_reason"],
            "rules_version": item["classification_rules_version"],
            "rules_hash": item["classification_rules_hash"],
        },
        "origin_verification": copy.deepcopy(item["origin_verification"]),
        "possible_duplicate_evidence": [],
        "teaching_note": {
            "topic": title[:100],
            "key_evidence": [],
            "error_evidence": [],
            "action_cues": [],
            "note": "转写自动重试已耗尽；终态隔离，不进入回答证据池。",
        },
        "transcript_segments": [],
    }


def build_knowledge(
    queue,
    transcripts,
    rules,
    douyin_knowledge,
):
    duplicate_index = build_douyin_shingle_index(douyin_knowledge)
    records = []
    missing = []
    for item in sorted(queue["items"], key=lambda value: value["video_id"]):
        if item.get("status") == "transcription_quarantined":
            records.append(build_transcription_quarantine_record(item, rules))
            continue
        if item.get("status") != "transcribed":
            continue
        transcript_paths = transcripts.get(item["video_id"])
        if transcript_paths is None:
            missing.append(item["video_id"])
            continue
        if isinstance(transcript_paths, (str, Path)):
            transcript_paths = [Path(transcript_paths)]
        transcript = None
        transcript_path = None
        for candidate in transcript_paths:
            try:
                transcript = load_valid_queue_transcript(item, candidate)
            except OSError:
                continue
            transcript_path = candidate
            break
        if transcript is None:
            missing.append(item["video_id"])
            continue
        record = build_record(
            item,
            transcript_path,
            transcript,
            rules,
            duplicate_index,
        )
        records.append(record)
        if record["processing_status"] == "ready":
            add_to_shingle_index(
                duplicate_index,
                record["evidence_id"],
                record.get("transcript_segments") or [],
                transcript.get("duration"),
            )
    if missing:
        raise SystemExit("Missing Bilibili transcripts: " + ", ".join(missing))
    status_counts = Counter(item["processing_status"] for item in records)
    return {
        "version": 1,
        "evidence_schema_version": 1,
        "scope": "用户确认技术合集及经来源核验的大G羽毛球B站教学视频",
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
    global TRANSCRIPT_ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--transcript-cache-dir",
        type=Path,
        help=(
            "Preferred Bilibili transcript cache "
            f"(default: {BILIBILI_TRANSCRIPT_CACHE_ENV} or repository data)"
        ),
    )
    args = parser.parse_args()
    TRANSCRIPT_ROOT = bilibili_transcript_cache_root(
        ROOT,
        override=args.transcript_cache_dir,
    )
    pipeline_lock = acquire_bilibili_pipeline_lock()
    queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    validate_queue_classification_policy(queue, ledger)
    rules = json.loads(QUALITY_RULES_PATH.read_text(encoding="utf-8"))
    douyin = json.loads(DOUYIN_KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    transcripts = index_exact_transcript_candidates(
        bilibili_transcript_roots(
            ROOT,
            override=TRANSCRIPT_ROOT,
        )
    )
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
