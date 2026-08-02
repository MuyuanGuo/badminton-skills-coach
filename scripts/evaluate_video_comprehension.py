#!/usr/bin/env python3
import argparse
import hashlib
import importlib.util
import json
import os
import re
from collections import Counter
from pathlib import Path

from evaluate_answer_context import planned_queries
from build_douyin_knowledge import (
    DOUYIN_TRANSCRIPT_CACHE_ENV,
    canonicalize_asr_text,
    runtime_transcript_segments,
)
from build_bilibili_knowledge import assess_source_content
from build_retrieval_index import (
    flatten as flatten_retrieval_value,
    normalize as normalize_retrieval_text,
    searchable_teaching_note,
)
from evidence_admission import split_transcript_issues
from bilibili_storage import (
    bilibili_transcript_roots,
    first_readable_transcript,
    index_exact_transcript_candidates,
)


ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_PATH = ROOT / "data" / "knowledge" / "douyin_knowledge_base.json"
RETRIEVAL_INDEX_PATH = ROOT / "data" / "knowledge" / "retrieval_index.json"
ANSWER_CASES_PATH = ROOT / "data" / "evaluation" / "answer_quality_cases.json"
QUALITY_RULES_PATH = ROOT / "config" / "knowledge_quality_rules.json"
SEARCH_PATH = (
    ROOT
    / "skills"
    / "liuhui-badminton-coach"
    / "scripts"
    / "search_knowledge.py"
)
TRANSCRIPT_EVIDENCE_FIELDS = ("key_evidence", "error_evidence", "action_cues")
ALL_EVIDENCE_FIELDS = TRANSCRIPT_EVIDENCE_FIELDS + (
    "principles",
    "visual_review_evidence",
)


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def decode_video_ngram_postings(encoded):
    if not isinstance(encoded, str):
        return encoded
    if not encoded:
        return ()
    return tuple(
        (int(record_index), int(channel_mask))
        for item in encoded.split(";")
        for record_index, channel_mask in [item.split(",", 1)]
    )


def decode_chunk_ngram_postings(encoded):
    if not isinstance(encoded, str):
        return encoded
    if not encoded:
        return ()
    return tuple(int(index) for index in encoded.split(","))


def load_search_module():
    spec = importlib.util.spec_from_file_location("liuhui_video_comprehension", SEARCH_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def normalize_text(value):
    return re.sub(r"\s+", "", str(value or "")).lower()


def normalize_index_text(value):
    # Keep the independent audit byte-for-byte aligned with the production
    # retrieval normalizer, including its Traditional -> Simplified mapping.
    # A second, almost-equivalent normalizer caused valid index records to be
    # reported as corrupt whenever a newly supported character variant
    # appeared in the corpus.
    return normalize_retrieval_text(value)


def ngram_hash(value):
    return hashlib.blake2b(value.encode("utf-8"), digest_size=6).hexdigest()


def hashed_ngrams(text, sizes):
    normalized = normalize_index_text(text)
    return {
        ngram_hash(normalized[index : index + size])
        for size in sizes
        for index in range(len(normalized) - size + 1)
    }


def append_failure(failures, failure):
    if failure not in failures:
        failures.append(failure)


def audit_chunk_first_index(
    video,
    segments,
    index_record,
    indexed_transcript_ngrams,
    chunks,
    indexed_chunk_ngrams,
    chunk_lexicon,
    transcript_ngram_sizes,
):
    """Verify a chunk-first transcript without expecting video-level postings.

    Chunk-first sources deliberately keep their video-level transcript channel
    empty. Their complete transcript is represented by a gap-free partition of
    runtime segments in ``chunk_index``. This audit reconstructs every chunk
    from those segments and independently verifies the fields used at search
    time, so changing the storage model does not weaken the release gate.
    """

    failures = []
    actual_video_ngrams = (
        indexed_transcript_ngrams
        if indexed_transcript_ngrams is not None
        else set((index_record or {}).get("transcript_ngrams", []))
    )
    if actual_video_ngrams:
        append_failure(failures, "chunk_first_video_transcript_index_not_empty")
    if (index_record or {}).get("field_lengths", {}).get("transcript") != 0:
        append_failure(failures, "chunk_first_video_transcript_length_not_zero")

    ordered_chunks = sorted(
        chunks or [],
        key=lambda item: (
            item.get("start_segment", -1),
            item.get("end_segment", -1),
            item.get("chunk_id", ""),
        ),
    )
    if not ordered_chunks:
        append_failure(failures, "missing_runtime_chunk_index")
        return failures

    cursor = 0
    seen_chunk_ids = set()
    for chunk in ordered_chunks:
        chunk_id = str(chunk.get("chunk_id", ""))
        start = chunk.get("start_segment")
        end = chunk.get("end_segment")
        if (
            not chunk_id
            or chunk_id in seen_chunk_ids
            or not isinstance(start, int)
            or not isinstance(end, int)
            or start != cursor
            or end <= start
            or end > len(segments)
        ):
            append_failure(failures, "runtime_chunk_partition_mismatch")
            continue
        seen_chunk_ids.add(chunk_id)
        cursor = end

        selected = segments[start:end]
        raw_text = "".join(str(item.get("text") or "") for item in selected)
        normalized_text = normalize_index_text(raw_text)
        expected_start_ms = max(
            0, round(float(selected[0].get("start") or 0.0) * 1000)
        )
        expected_end_ms = max(
            expected_start_ms,
            round(
                float(
                    selected[-1].get("end")
                    or selected[-1].get("start")
                    or 0.0
                )
                * 1000
            ),
        )
        if (
            chunk.get("start_ms") != expected_start_ms
            or chunk.get("end_ms") != expected_end_ms
        ):
            append_failure(failures, "runtime_chunk_timestamp_mismatch")
        if chunk.get("normalized_length") != len(normalized_text):
            append_failure(failures, "runtime_chunk_length_mismatch")
        if chunk.get("text_sha256") != hashlib.sha256(
            raw_text.encode("utf-8")
        ).hexdigest():
            append_failure(failures, "runtime_chunk_text_hash_mismatch")

        expected_frequencies = {
            term: normalized_text.count(normalize_index_text(term))
            for term in chunk_lexicon or ()
            if normalize_index_text(term) in normalized_text
        }
        if chunk.get("field_term_frequencies", {}) != expected_frequencies:
            append_failure(failures, "runtime_chunk_term_index_mismatch")

        expected_ngrams = hashed_ngrams(
            normalized_text, transcript_ngram_sizes
        )
        actual_chunk_ngrams = (indexed_chunk_ngrams or {}).get(chunk_id)
        if actual_chunk_ngrams is None or expected_ngrams != actual_chunk_ngrams:
            append_failure(failures, "runtime_chunk_ngram_index_mismatch")

    if cursor != len(segments):
        append_failure(failures, "runtime_chunk_partition_mismatch")
    return failures


def note_evidence(note, fields=ALL_EVIDENCE_FIELDS):
    evidence = []
    for field in fields:
        values = note.get(field, [])
        if not isinstance(values, list):
            continue
        for item in values:
            if isinstance(item, dict) and str(item.get("text", "")).strip():
                evidence.append(
                    {
                        "role": field,
                        "timestamp": str(item.get("timestamp", "")),
                        "text": str(item["text"]).strip(),
                    }
                )
    return evidence


def transcript_text(payload):
    full_text = str(payload.get("full_text", "")).strip()
    if full_text:
        return full_text
    return " ".join(
        str(segment.get("text", "")).strip()
        for segment in payload.get("segments", [])
        if isinstance(segment, dict)
    ).strip()


def bilibili_safe_runtime_segments(video, payload, quality_rules):
    """Rebuild the exact safe transcript boundary used by the Bilibili builder."""

    raw_segments = payload.get("segments") or []
    if not raw_segments:
        return None
    _, safe_segments = assess_source_content(
        video,
        raw_segments,
        quality_rules,
    )
    return runtime_transcript_segments(safe_segments, quality_rules)


def load_raw_transcript(
    video,
    *,
    root,
    require_raw_transcript=False,
    required_raw_transcript_sources=None,
    bilibili_transcript_candidates=None,
    douyin_transcript_root=None,
):
    """Load optional local provenance without changing the portable gate.

    Full-transcript and bounded-note evidence use the same resolver.  The
    latter may intentionally ship without its gitignored raw cache, but a
    cache that is present is still audited against every committed evidence
    window.
    """

    failures = []
    transcript_file = str(video.get("transcript_file", "")).strip()
    if not transcript_file:
        return None, "missing_reference", ["missing_transcript_file_reference"]

    candidate_paths = None
    if video.get("source_type") == "bilibili_video":
        source_video_id = str(video.get("source_video_id") or "").strip()
        if bilibili_transcript_candidates is None:
            bilibili_transcript_candidates = index_exact_transcript_candidates(
                bilibili_transcript_roots(root)
            )
        candidate_paths = bilibili_transcript_candidates.get(source_video_id, [])
        path = first_readable_transcript(candidate_paths)
    elif video.get("source_type") == "douyin_video":
        if douyin_transcript_root is None:
            douyin_transcript_root = (
                Path(os.environ[DOUYIN_TRANSCRIPT_CACHE_ENV])
                if os.environ.get(DOUYIN_TRANSCRIPT_CACHE_ENV)
                else root / "data" / "transcripts" / "douyin"
            )
        canonical_root = Path("data/transcripts/douyin")
        try:
            relative = Path(transcript_file).relative_to(canonical_root)
        except ValueError:
            path = root / transcript_file
        else:
            path = Path(douyin_transcript_root) / relative
    else:
        path = root / transcript_file

    if path is None or not path.exists():
        if candidate_paths:
            return None, "invalid", ["invalid_transcript_file"]
        if require_raw_transcript and (
            required_raw_transcript_sources is None
            or video.get("source_type") in required_raw_transcript_sources
        ):
            failures.append("missing_transcript_file")
        return None, "unavailable", failures

    try:
        payload = load_json(path)
    except (json.JSONDecodeError, OSError):
        return None, "invalid", ["invalid_transcript_file"]

    full_transcript = transcript_text(payload)
    if not full_transcript:
        return payload, "empty", ["empty_transcript"]
    return payload, "verified", failures


def audit_bounded_note_evidence(
    video,
    *,
    index_record=None,
    indexed_title_ngrams=None,
    indexed_teaching_note_ngrams=None,
    indexed_transcript_ngrams=None,
    transcript_ngram_sizes=(2, 3),
    root=ROOT,
    require_raw_transcript=False,
    required_raw_transcript_sources=None,
    bilibili_transcript_candidates=None,
    douyin_transcript_root=None,
):
    """Audit a supplemental record as bounded evidence, not a full transcript.

    Admission remains strict: title-alignment advisories or a passed bounded
    domain-note recovery may lower a safe, provenance-backed source to
    supplemental status. Runtime retrieval is limited to committed timestamped
    teaching-note windows.
    """

    failures = []
    quality = video.get("quality") or {}
    transcript_quality = quality.get("transcript") or {}
    advisory, blocking = split_transcript_issues(transcript_quality.get("issues"))
    bounded_recovery = quality.get("bounded_note_recovery") or {}
    automatic_passed = (
        (quality.get("automatic_evidence") or {}).get("passed") is True
    )
    recovery_passed = bounded_recovery.get("passed") is True
    if video.get("answer_eligibility") != "supplemental":
        append_failure(failures, "bounded_note_not_supplemental")
    if video.get("runtime_evidence_mode") != "bounded_note_windows":
        append_failure(failures, "invalid_bounded_note_runtime_mode")
    if video.get("metadata_title_trust") != "limited":
        append_failure(failures, "bounded_note_title_trust_not_limited")
    if blocking or (not advisory and not recovery_passed):
        append_failure(failures, "bounded_note_has_invalid_transcript_issues")
    if (quality.get("origin_verification") or {}).get("passed") is not True:
        append_failure(failures, "bounded_note_origin_not_verified")
    if (quality.get("source_content_safety") or {}).get("passed") is not True:
        append_failure(failures, "bounded_note_source_content_not_safe")
    if not automatic_passed and not recovery_passed:
        append_failure(failures, "bounded_note_automatic_evidence_not_passed")
    if video.get("transcript_segments"):
        append_failure(failures, "bounded_note_contains_runtime_transcript")

    note = video.get("teaching_note") or {}
    evidence = note_evidence(note, TRANSCRIPT_EVIDENCE_FIELDS)
    if not evidence:
        append_failure(failures, "bounded_note_has_no_evidence_windows")
    if any(not item["timestamp"].strip() for item in evidence):
        append_failure(failures, "bounded_note_evidence_missing_timestamp")

    if index_record is not None:
        if index_record.get("answer_eligibility") != "supplemental":
            append_failure(failures, "bounded_note_index_eligibility_mismatch")
        if index_record.get("runtime_evidence_mode") != "bounded_note_windows":
            append_failure(failures, "bounded_note_index_runtime_mode_mismatch")
        if index_record.get("metadata_title_trust") != "limited":
            append_failure(failures, "bounded_note_index_title_trust_mismatch")
        field_lengths = index_record.get("field_lengths") or {}
        ngram_counts = index_record.get("ngram_counts") or {}
        if field_lengths.get("transcript") != 0 or ngram_counts.get("transcript") != 0:
            append_failure(failures, "bounded_note_contains_transcript_index")
        if ngram_counts.get("title") != 0:
            append_failure(failures, "bounded_note_contains_limited_title_index")

        note_text = flatten_retrieval_value(searchable_teaching_note(note))
        expected_note_ngrams = hashed_ngrams(note_text, transcript_ngram_sizes)
        actual_note_ngrams = (
            indexed_teaching_note_ngrams
            if indexed_teaching_note_ngrams is not None
            else set()
        )
        if expected_note_ngrams != actual_note_ngrams:
            append_failure(failures, "bounded_note_index_mismatch")
        if field_lengths.get("teaching_note") != len(normalize_index_text(note_text)):
            append_failure(failures, "bounded_note_index_length_mismatch")
        if indexed_title_ngrams:
            append_failure(failures, "bounded_note_contains_limited_title_index")
        if indexed_transcript_ngrams:
            append_failure(failures, "bounded_note_contains_transcript_index")

    payload, raw_status, raw_failures = load_raw_transcript(
        video,
        root=root,
        require_raw_transcript=require_raw_transcript,
        required_raw_transcript_sources=required_raw_transcript_sources,
        bilibili_transcript_candidates=bilibili_transcript_candidates,
        douyin_transcript_root=douyin_transcript_root,
    )
    failures.extend(raw_failures)
    full_transcript = transcript_text(payload or {})
    if full_transcript:
        quality_rules = load_json(QUALITY_RULES_PATH)
        normalized_transcript = normalize_text(
            canonicalize_asr_text(full_transcript, quality_rules)
        )
        for item in evidence:
            if normalize_text(item["text"]) not in normalized_transcript:
                append_failure(
                    failures,
                    f"bounded_evidence_not_in_transcript:{item['role']}:{item['timestamp']}",
                )
    return failures, raw_status


def evidence_provenance_metrics(videos, quality_rules):
    transcript_items = 0
    timestamped_transcript_items = 0
    visual_observations = 0
    synthesized_principles = 0
    noncanonical_terms = Counter()
    canonicalization = quality_rules.get("asr_canonicalization", {})
    for video in videos:
        note = video.get("teaching_note") or {}
        for field in TRANSCRIPT_EVIDENCE_FIELDS:
            for item in note.get(field, []) or []:
                if not isinstance(item, dict) or not str(item.get("text", "")).strip():
                    continue
                transcript_items += 1
                if str(item.get("timestamp", "")).strip():
                    timestamped_transcript_items += 1
        visual_observations += len(
            [
                item
                for item in note.get("visual_review_evidence", []) or []
                if isinstance(item, dict) and str(item.get("text", "")).strip()
            ]
        )
        synthesized_principles += len(
            [
                item
                for item in note.get("principles", []) or []
                if isinstance(item, dict) and str(item.get("text", "")).strip()
            ]
        )
        transcript_segments = [
            str(segment.get("text", ""))
            for segment in video.get("transcript_segments", []) or []
            if isinstance(segment, dict)
        ]
        for noncanonical in canonicalization:
            # ASR terms are segment-local. Concatenating adjacent segments can
            # invent a token that never appeared in either source segment
            # (for example, one ending in "架" followed by one starting in
            # "攀"). Count each segment independently.
            occurrences = sum(
                segment.count(noncanonical)
                for segment in transcript_segments
            )
            if occurrences:
                noncanonical_terms[noncanonical] += occurrences
    return {
        "transcript_evidence_items": transcript_items,
        "timestamped_transcript_evidence_items": timestamped_transcript_items,
        "transcript_timestamp_coverage": (
            timestamped_transcript_items / max(1, transcript_items)
        ),
        "reviewed_visual_observation_items": visual_observations,
        "synthesized_principle_items": synthesized_principles,
        "noncanonical_asr_occurrence_count": sum(noncanonical_terms.values()),
        "noncanonical_asr_terms": dict(sorted(noncanonical_terms.items())),
    }


def audit_video_content(
    video,
    root=ROOT,
    indexed_video_ids=None,
    index_record=None,
    indexed_title_ngrams=None,
    indexed_teaching_note_ngrams=None,
    indexed_transcript_ngrams=None,
    chunk_first_sources=(),
    chunks=None,
    indexed_chunk_ngrams=None,
    chunk_lexicon=(),
    transcript_ngram_sizes=(2, 3),
    require_raw_transcript=False,
    required_raw_transcript_sources=None,
    bilibili_transcript_candidates=None,
    douyin_transcript_root=None,
):
    video_id = video["video_id"]
    note = video.get("teaching_note") or {}
    failures = []
    runtime_evidence_mode = video.get("runtime_evidence_mode")
    if runtime_evidence_mode == "bounded_note_windows":
        source_kind = "bounded_note_windows"
    elif video.get("confidence") == "visual_reviewed":
        source_kind = "visual_review"
    elif video.get("confidence") == "reviewed_transcript":
        source_kind = "reviewed_transcript"
    else:
        source_kind = "automatic_transcript"
    raw_transcript_status = "not_applicable"

    if indexed_video_ids is not None and video_id not in indexed_video_ids:
        failures.append("missing_retrieval_index_record")
    if not str(note.get("topic", "")).strip():
        failures.append("missing_teaching_topic")

    if source_kind == "bounded_note_windows":
        bounded_failures, raw_transcript_status = audit_bounded_note_evidence(
            video,
            index_record=index_record,
            indexed_title_ngrams=indexed_title_ngrams,
            indexed_teaching_note_ngrams=indexed_teaching_note_ngrams,
            indexed_transcript_ngrams=indexed_transcript_ngrams,
            transcript_ngram_sizes=transcript_ngram_sizes,
            root=root,
            require_raw_transcript=require_raw_transcript,
            required_raw_transcript_sources=required_raw_transcript_sources,
            bilibili_transcript_candidates=bilibili_transcript_candidates,
            douyin_transcript_root=douyin_transcript_root,
        )
        failures.extend(bounded_failures)
    elif source_kind == "visual_review":
        summary = str(note.get("review_summary", "")).strip()
        visual_evidence = note_evidence(note, ("visual_review_evidence",))
        if not summary:
            failures.append("missing_visual_review_summary")
        if not visual_evidence:
            failures.append("missing_visual_review_evidence")
        if video.get("transcript_segments"):
            failures.append("visual_review_contains_transcript_segments")
        transcript_index = (
            indexed_transcript_ngrams
            if indexed_transcript_ngrams is not None
            else set((index_record or {}).get("transcript_ngrams", []))
        )
        if index_record is not None and transcript_index:
            failures.append("visual_review_contains_transcript_index")
    else:
        quality = video.get("quality") or {}
        transcript_quality = quality.get("transcript") or {}
        evidence_quality = quality.get("automatic_evidence") or {}
        if source_kind == "automatic_transcript":
            admission = video.get("automatic_admission") or {}
            supplemental_advisory_accepted = (
                video.get("answer_eligibility") == "supplemental"
                and video.get("runtime_evidence_mode") == "full_transcript"
                and transcript_quality.get("evidence_passed") is True
                and admission.get("answer_evidence_eligible") is True
                and admission.get("answer_eligibility") == "supplemental"
            )
            if (
                transcript_quality.get("passed") is not True
                and not supplemental_advisory_accepted
            ):
                failures.append("transcript_quality_not_passed")
            if evidence_quality.get("passed") is not True:
                failures.append("automatic_evidence_quality_not_passed")
        elif not str(note.get("review_summary", "")).strip():
            failures.append("missing_reviewed_transcript_summary")

        segments = video.get("transcript_segments") or []
        if not segments:
            failures.append("missing_runtime_transcript_segments")
        for segment in segments:
            if (
                not isinstance(segment, dict)
                or not str(segment.get("text", "")).strip()
                or not isinstance(segment.get("start"), (int, float))
                or not isinstance(segment.get("end"), (int, float))
                or segment["end"] < segment["start"]
            ):
                failures.append("invalid_runtime_transcript_segment")
                break
        bundled_transcript = "".join(
            str(segment.get("text", ""))
            for segment in segments
            if isinstance(segment, dict)
        )
        chunk_first_transcript = video.get("source_type") in set(
            chunk_first_sources or ()
        )
        if index_record is not None and chunk_first_transcript:
            failures.extend(
                audit_chunk_first_index(
                    video,
                    segments,
                    index_record,
                    indexed_transcript_ngrams,
                    chunks,
                    indexed_chunk_ngrams,
                    chunk_lexicon,
                    transcript_ngram_sizes,
                )
            )
        elif index_record is not None:
            expected_ngrams = hashed_ngrams(
                bundled_transcript, transcript_ngram_sizes
            )
            actual_ngrams = (
                indexed_transcript_ngrams
                if indexed_transcript_ngrams is not None
                else set(index_record.get("transcript_ngrams", []))
            )
            if expected_ngrams != actual_ngrams:
                failures.append("runtime_transcript_index_mismatch")
            expected_length = len(normalize_index_text(bundled_transcript))
            if index_record.get("field_lengths", {}).get("transcript") != expected_length:
                failures.append("runtime_transcript_length_mismatch")

        payload, raw_transcript_status, raw_failures = load_raw_transcript(
            video,
            root=root,
            require_raw_transcript=require_raw_transcript,
            required_raw_transcript_sources=required_raw_transcript_sources,
            bilibili_transcript_candidates=bilibili_transcript_candidates,
            douyin_transcript_root=douyin_transcript_root,
        )
        failures.extend(raw_failures)
        full_transcript = transcript_text(payload or {})
        evidence = note_evidence(note)
        if source_kind == "automatic_transcript" and not evidence:
            failures.append("missing_teaching_evidence")

        if source_kind == "automatic_transcript" and video.get("confidence") != "curated" and full_transcript:
            quality_rules = load_json(QUALITY_RULES_PATH)
            provenance_transcript = full_transcript
            if video.get("source_type") == "bilibili_video":
                expected_runtime_segments = bilibili_safe_runtime_segments(
                    video,
                    payload or {},
                    quality_rules,
                )
                if expected_runtime_segments is not None:
                    if expected_runtime_segments != segments:
                        failures.append(
                            "runtime_transcript_raw_roundtrip_mismatch"
                        )
            normalized_transcript = normalize_text(
                canonicalize_asr_text(
                    provenance_transcript,
                    quality_rules,
                )
            )
            for item in note_evidence(note, TRANSCRIPT_EVIDENCE_FIELDS):
                if normalize_text(item["text"]) not in normalized_transcript:
                    failures.append(
                        f"evidence_not_in_transcript:{item['role']}:{item['timestamp']}"
                    )
    return {
        "video_id": video_id,
        "source_kind": source_kind,
        "raw_transcript_status": raw_transcript_status,
        "failures": failures,
    }


def evaluate(
    knowledge_path=KNOWLEDGE_PATH,
    retrieval_index_path=RETRIEVAL_INDEX_PATH,
    root=ROOT,
    run_retrieval_roundtrip=True,
    run_semantic_probes=True,
    require_raw_transcripts=False,
    required_raw_transcript_sources=None,
    answer_cases_path=ANSWER_CASES_PATH,
    semantic_top_k=12,
    douyin_transcript_root=None,
):
    knowledge = load_json(knowledge_path)
    retrieval_index = load_json(retrieval_index_path)
    ready_videos = [
        video for video in knowledge["videos"] if video["processing_status"] == "ready"
    ]
    index_by_id = {
        record["video_id"]: record for record in retrieval_index.get("videos", [])
    }
    title_ngrams_by_id = None
    teaching_note_ngrams_by_id = None
    transcript_ngrams_by_id = None
    if retrieval_index.get("ngram_vocabulary") is not None:
        title_ngrams_by_id = {
            record["video_id"]: set() for record in retrieval_index["videos"]
        }
        teaching_note_ngrams_by_id = {
            record["video_id"]: set() for record in retrieval_index["videos"]
        }
        transcript_ngrams_by_id = {
            record["video_id"]: set() for record in retrieval_index["videos"]
        }
        video_ids = [record["video_id"] for record in retrieval_index["videos"]]
        for gram, postings in zip(
            retrieval_index["ngram_vocabulary"],
            retrieval_index["ngram_postings"],
        ):
            for record_index, channel_mask in decode_video_ngram_postings(
                postings
            ):
                if channel_mask & 1:
                    title_ngrams_by_id[video_ids[record_index]].add(gram)
                if channel_mask & 2:
                    teaching_note_ngrams_by_id[video_ids[record_index]].add(gram)
                if channel_mask & 4:
                    transcript_ngrams_by_id[video_ids[record_index]].add(gram)
    indexed_video_ids = set(index_by_id)
    ngram_sizes = retrieval_index.get("transcript_ngram_sizes", [2, 3])
    chunk_index = retrieval_index.get("chunk_index") or {}
    chunk_first_sources = set(
        (chunk_index.get("config") or {}).get("source_allowlist", [])
    )
    chunks = chunk_index.get("chunks") or []
    chunks_by_video_id = {video_id: [] for video_id in indexed_video_ids}
    index_video_ids = [
        record["video_id"] for record in retrieval_index.get("videos", [])
    ]
    for chunk in chunks:
        video_index = chunk.get("video_index")
        if isinstance(video_index, int) and 0 <= video_index < len(index_video_ids):
            chunks_by_video_id[index_video_ids[video_index]].append(chunk)
    indexed_chunk_ngrams = {
        str(chunk.get("chunk_id", "")): set() for chunk in chunks
    }
    chunk_vocabulary = chunk_index.get("ngram_vocabulary") or []
    chunk_postings = chunk_index.get("ngram_postings") or []
    if len(chunk_vocabulary) != len(chunk_postings):
        raise ValueError("Chunk n-gram vocabulary/postings length mismatch")
    for gram, postings in zip(chunk_vocabulary, chunk_postings):
        for chunk_position in decode_chunk_ngram_postings(postings):
            if isinstance(chunk_position, int) and 0 <= chunk_position < len(chunks):
                indexed_chunk_ngrams[str(chunks[chunk_position]["chunk_id"])].add(
                    gram
                )
    chunk_lexicon = set(
        (chunk_index.get("term_cluster_document_frequency") or {}).keys()
    )
    bilibili_transcript_candidates = index_exact_transcript_candidates(
        bilibili_transcript_roots(root)
    )
    audits = [
        audit_video_content(
            video,
            root=root,
            indexed_video_ids=indexed_video_ids,
            index_record=index_by_id.get(video["video_id"]),
            indexed_title_ngrams=(
                title_ngrams_by_id.get(video["video_id"])
                if title_ngrams_by_id is not None
                else None
            ),
            indexed_teaching_note_ngrams=(
                teaching_note_ngrams_by_id.get(video["video_id"])
                if teaching_note_ngrams_by_id is not None
                else None
            ),
            indexed_transcript_ngrams=(
                transcript_ngrams_by_id.get(video["video_id"])
                if transcript_ngrams_by_id is not None
                else None
            ),
            chunk_first_sources=chunk_first_sources,
            chunks=chunks_by_video_id.get(video["video_id"], []),
            indexed_chunk_ngrams=indexed_chunk_ngrams,
            chunk_lexicon=chunk_lexicon,
            transcript_ngram_sizes=ngram_sizes,
            require_raw_transcript=require_raw_transcripts,
            required_raw_transcript_sources=(
                set(required_raw_transcript_sources)
                if required_raw_transcript_sources is not None
                else None
            ),
            bilibili_transcript_candidates=bilibili_transcript_candidates,
            douyin_transcript_root=douyin_transcript_root,
        )
        for video in ready_videos
    ]
    audit_by_id = {audit["video_id"]: audit for audit in audits}

    runtime_lookup_count = 0
    semantic_expected = 0
    semantic_recalled = 0
    semantic_primary_cases = 0
    semantic_primary_top_k = 0
    hard_negative_total = 0
    hard_negative_top_k_violations = []
    search_module = None
    if run_retrieval_roundtrip or run_semantic_probes:
        search_module = load_search_module()
        runtime_knowledge, runtime_index, runtime_rules = search_module.load_resources()
    if run_retrieval_roundtrip:
        ready_ids = [video["video_id"] for video in ready_videos]
        lookup = search_module.lookup_videos(
            ready_ids, local_personalization=False
        )
        lookup_by_id = {item["video_id"]: item for item in lookup["results"]}
        for video_id in ready_ids:
            item = lookup_by_id.get(video_id)
            if not item:
                audit_by_id[video_id]["failures"].append("runtime_lookup_missing")
                continue
            teaching_note = item.get("teaching_note") or {}
            if not teaching_note.get("summary") and not teaching_note.get("evidence"):
                audit_by_id[video_id]["failures"].append(
                    "runtime_lookup_has_no_teaching_content"
                )
                continue
            runtime_lookup_count += 1

    if run_semantic_probes:
        answer_registry = load_json(answer_cases_path)
        for case in answer_registry.get("cases", []):
            gold = case.get("gold", {})
            expected_ids = gold.get("required_video_ids", [])
            primary_ids = gold.get("primary_video_ids", [])
            irrelevant_ids = set(gold.get("irrelevant_video_ids", []))
            plan = search_module.plan_query(case["query"])
            payloads = [
                search_module.search(
                    query,
                    limit=semantic_top_k,
                    mode="hybrid",
                    recall_mode="exhaustive",
                    manifest_limit=None,
                    local_personalization=False,
                )
                for query in planned_queries(search_module, plan, case["query"])
            ]
            manifest_ids = {
                item["video_id"]
                for payload in payloads
                for item in payload["candidate_manifest"]
            }
            top_ids = [item["video_id"] for item in payloads[0]["results"]]
            semantic_expected += len(expected_ids)
            semantic_recalled += len(set(expected_ids) & manifest_ids)
            if primary_ids:
                semantic_primary_cases += 1
                if set(primary_ids) & set(top_ids):
                    semantic_primary_top_k += 1
            hard_negative_total += len(irrelevant_ids)
            violating = sorted(irrelevant_ids & set(top_ids))
            if violating:
                hard_negative_top_k_violations.append(
                    {"case_id": case["case_id"], "video_ids": violating}
                )

    source_counts = Counter(audit["source_kind"] for audit in audits)
    quality_rules = load_json(QUALITY_RULES_PATH)
    provenance = evidence_provenance_metrics(ready_videos, quality_rules)
    pending_statuses = Counter(
        video.get("processing_status")
        for video in knowledge["videos"]
        if video.get("processing_status") in {"needs_visual_review", "needs_correction"}
    )
    raw_transcript_counts = Counter(
        audit["raw_transcript_status"]
        for audit in audits
        if audit["source_kind"] != "visual_review"
    )
    failure_items = [audit for audit in audits if audit["failures"]]
    understood = len(audits) - len(failure_items)
    denominator = max(1, len(audits))
    return {
        "ready_videos": len(audits),
        "understood_videos": understood,
        "understanding_coverage": understood / denominator,
        "transcript_backed": (
            source_counts["automatic_transcript"]
            + source_counts["reviewed_transcript"]
        ),
        "bounded_note_windows": source_counts["bounded_note_windows"],
        "automatic_transcript": source_counts["automatic_transcript"],
        "reviewed_transcript": source_counts["reviewed_transcript"],
        "visual_review_fallback": source_counts["visual_review"],
        "evidence_provenance": provenance,
        "automated_review_backlog": dict(sorted(pending_statuses.items())),
        "raw_transcript_requirement_enabled": require_raw_transcripts,
        "required_raw_transcript_sources": (
            sorted(required_raw_transcript_sources)
            if required_raw_transcript_sources is not None
            else ["all"]
        ),
        "raw_transcript_files_verified": raw_transcript_counts["verified"],
        "raw_transcript_files_unavailable": raw_transcript_counts["unavailable"],
        "raw_transcript_roundtrip_coverage": (
            raw_transcript_counts["verified"]
            / max(
                1,
                source_counts["automatic_transcript"]
                + source_counts["reviewed_transcript"]
                + source_counts["bounded_note_windows"],
            )
        ),
        "runtime_lookup_coverage": (
            runtime_lookup_count / denominator if run_retrieval_roundtrip else None
        ),
        "independent_probe_cases": (
            len(load_json(answer_cases_path).get("cases", []))
            if run_semantic_probes
            else 0
        ),
        "independent_probe_expected_videos": semantic_expected,
        "independent_probe_candidate_recall": (
            semantic_recalled / max(1, semantic_expected)
            if run_semantic_probes
            else None
        ),
        "independent_probe_primary_top_k": (
            semantic_primary_top_k / max(1, semantic_primary_cases)
            if run_semantic_probes
            else None
        ),
        "hard_negative_count": hard_negative_total,
        "hard_negative_top_k_violation_count": sum(
            len(item["video_ids"]) for item in hard_negative_top_k_violations
        ),
        "hard_negative_top_k_violations": hard_negative_top_k_violations,
        "failure_count": len(failure_items),
        "failures": failure_items,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Audit whether every ready video has understandable source evidence."
    )
    parser.add_argument("--knowledge", type=Path, default=KNOWLEDGE_PATH)
    parser.add_argument("--retrieval-index", type=Path, default=RETRIEVAL_INDEX_PATH)
    parser.add_argument(
        "--require-ready",
        type=int,
        help="Optional historical lower bound; exact corpus/index consistency is always audited.",
    )
    parser.add_argument("--min-understanding-coverage", type=float, default=1.0)
    parser.add_argument("--min-runtime-lookup-coverage", type=float, default=1.0)
    parser.add_argument("--min-independent-probe-recall", type=float, default=1.0)
    parser.add_argument("--min-primary-top-k", type=float, default=0.85)
    parser.add_argument("--max-hard-negative-top-k-violations", type=int)
    parser.add_argument("--min-transcript-timestamp-coverage", type=float, default=1.0)
    parser.add_argument("--max-noncanonical-asr-occurrences", type=int, default=0)
    parser.add_argument("--skip-retrieval-roundtrip", action="store_true")
    parser.add_argument(
        "--require-raw-transcripts",
        action="store_true",
        help=(
            "Fail when gitignored local transcript files are unavailable. "
            "Use this maintainer-only check after ingestion; clean CI validates "
            "the portable knowledge and retrieval artifacts instead."
        ),
    )
    parser.add_argument(
        "--require-raw-transcript-source",
        action="append",
        choices=("douyin_video", "bilibili_video"),
        help=(
            "With --require-raw-transcripts, fail only when a selected "
            "source's raw transcript is unavailable. Repeat for both "
            "sources; omit to require every source."
        ),
    )
    parser.add_argument(
        "--douyin-transcript-cache-dir",
        type=Path,
        default=(
            Path(os.environ[DOUYIN_TRANSCRIPT_CACHE_ENV])
            if os.environ.get(DOUYIN_TRANSCRIPT_CACHE_ENV)
            else None
        ),
    )
    args = parser.parse_args()
    if (
        args.require_raw_transcript_source
        and not args.require_raw_transcripts
    ):
        parser.error(
            "--require-raw-transcript-source requires "
            "--require-raw-transcripts"
        )

    result = evaluate(
        args.knowledge,
        args.retrieval_index,
        run_retrieval_roundtrip=not args.skip_retrieval_roundtrip,
        run_semantic_probes=not args.skip_retrieval_roundtrip,
        require_raw_transcripts=args.require_raw_transcripts,
        required_raw_transcript_sources=(
            args.require_raw_transcript_source
            if args.require_raw_transcript_source
            else None
        ),
        douyin_transcript_root=args.douyin_transcript_cache_dir,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.require_ready is not None and result["ready_videos"] < args.require_ready:
        raise SystemExit(
            f"Only {result['ready_videos']} ready videos; requires {args.require_ready}"
        )
    if result["understanding_coverage"] < args.min_understanding_coverage:
        raise SystemExit(
            "Video understanding coverage "
            f"{result['understanding_coverage']:.3f} is below "
            f"{args.min_understanding_coverage:.3f}"
        )
    provenance = result["evidence_provenance"]
    if (
        provenance["transcript_timestamp_coverage"]
        < args.min_transcript_timestamp_coverage
    ):
        raise SystemExit("Transcript evidence timestamp coverage is below the threshold")
    if (
        provenance["noncanonical_asr_occurrence_count"]
        > args.max_noncanonical_asr_occurrences
    ):
        raise SystemExit("Runtime transcript evidence contains noncanonical ASR terms")
    if not args.skip_retrieval_roundtrip:
        if result["runtime_lookup_coverage"] < args.min_runtime_lookup_coverage:
            raise SystemExit("Runtime lookup coverage is below the required threshold")
        if (
            result["independent_probe_candidate_recall"]
            < args.min_independent_probe_recall
        ):
            raise SystemExit("Independent-probe candidate recall is below the required threshold")
        if result["independent_probe_primary_top_k"] < args.min_primary_top_k:
            raise SystemExit("Independent-probe primary top-k rate is below the threshold")
        if (
            args.max_hard_negative_top_k_violations is not None
            and result["hard_negative_top_k_violation_count"]
            > args.max_hard_negative_top_k_violations
        ):
            raise SystemExit("Known irrelevant videos appeared in independent-probe top-k")


if __name__ == "__main__":
    main()
