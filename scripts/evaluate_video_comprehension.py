#!/usr/bin/env python3
import argparse
import hashlib
import importlib.util
import json
import re
from collections import Counter
from pathlib import Path

from evaluate_answer_context import planned_queries
from build_douyin_knowledge import canonicalize_asr_text


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


def load_search_module():
    spec = importlib.util.spec_from_file_location("liuhui_video_comprehension", SEARCH_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def normalize_text(value):
    return re.sub(r"\s+", "", str(value or "")).lower()


def normalize_index_text(value):
    return "".join(
        re.findall(r"[\u4e00-\u9fff]+|[a-z0-9]+", str(value or "").lower())
    )


def ngram_hash(value):
    return hashlib.blake2b(value.encode("utf-8"), digest_size=6).hexdigest()


def hashed_ngrams(text, sizes):
    normalized = normalize_index_text(text)
    return {
        ngram_hash(normalized[index : index + size])
        for size in sizes
        for index in range(len(normalized) - size + 1)
    }


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


def audit_video_content(
    video,
    root=ROOT,
    indexed_video_ids=None,
    index_record=None,
    transcript_ngram_sizes=(2, 3),
    require_raw_transcript=False,
):
    video_id = video["video_id"]
    note = video.get("teaching_note") or {}
    failures = []
    if video.get("confidence") == "visual_reviewed":
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

    if source_kind == "visual_review":
        summary = str(note.get("review_summary", "")).strip()
        visual_evidence = note_evidence(note, ("visual_review_evidence",))
        if not summary:
            failures.append("missing_visual_review_summary")
        if not visual_evidence:
            failures.append("missing_visual_review_evidence")
        if video.get("transcript_segments"):
            failures.append("visual_review_contains_transcript_segments")
        if index_record is not None and index_record.get("transcript_ngrams"):
            failures.append("visual_review_contains_transcript_index")
    else:
        quality = video.get("quality") or {}
        transcript_quality = quality.get("transcript") or {}
        evidence_quality = quality.get("automatic_evidence") or {}
        if source_kind == "automatic_transcript":
            if transcript_quality.get("passed") is not True:
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
        if index_record is not None:
            expected_ngrams = hashed_ngrams(
                bundled_transcript, transcript_ngram_sizes
            )
            actual_ngrams = set(index_record.get("transcript_ngrams", []))
            if expected_ngrams != actual_ngrams:
                failures.append("runtime_transcript_index_mismatch")
            expected_length = len(normalize_index_text(bundled_transcript))
            if index_record.get("field_lengths", {}).get("transcript") != expected_length:
                failures.append("runtime_transcript_length_mismatch")

        transcript_file = str(video.get("transcript_file", "")).strip()
        payload = None
        if not transcript_file:
            failures.append("missing_transcript_file_reference")
            raw_transcript_status = "missing_reference"
        else:
            path = root / transcript_file
            if not path.exists():
                raw_transcript_status = "unavailable"
                if require_raw_transcript:
                    failures.append("missing_transcript_file")
            else:
                try:
                    payload = load_json(path)
                except (json.JSONDecodeError, OSError):
                    failures.append("invalid_transcript_file")
                    raw_transcript_status = "invalid"

        full_transcript = transcript_text(payload or {})
        if payload is not None and not full_transcript:
            failures.append("empty_transcript")
            raw_transcript_status = "empty"
        elif full_transcript:
            raw_transcript_status = "verified"
        evidence = note_evidence(note)
        if source_kind == "automatic_transcript" and not evidence:
            failures.append("missing_teaching_evidence")

        if source_kind == "automatic_transcript" and video.get("confidence") != "curated" and full_transcript:
            quality_rules = load_json(QUALITY_RULES_PATH)
            normalized_transcript = normalize_text(
                canonicalize_asr_text(full_transcript, quality_rules)
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
    answer_cases_path=ANSWER_CASES_PATH,
    semantic_top_k=12,
):
    knowledge = load_json(knowledge_path)
    retrieval_index = load_json(retrieval_index_path)
    ready_videos = [
        video for video in knowledge["videos"] if video["processing_status"] == "ready"
    ]
    index_by_id = {
        record["video_id"]: record for record in retrieval_index.get("videos", [])
    }
    indexed_video_ids = set(index_by_id)
    ngram_sizes = retrieval_index.get("transcript_ngram_sizes", [2, 3])
    audits = [
        audit_video_content(
            video,
            root=root,
            indexed_video_ids=indexed_video_ids,
            index_record=index_by_id.get(video["video_id"]),
            transcript_ngram_sizes=ngram_sizes,
            require_raw_transcript=require_raw_transcripts,
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
        "automatic_transcript": source_counts["automatic_transcript"],
        "reviewed_transcript": source_counts["reviewed_transcript"],
        "visual_review_fallback": source_counts["visual_review"],
        "raw_transcript_requirement_enabled": require_raw_transcripts,
        "raw_transcript_files_verified": raw_transcript_counts["verified"],
        "raw_transcript_files_unavailable": raw_transcript_counts["unavailable"],
        "raw_transcript_roundtrip_coverage": (
            raw_transcript_counts["verified"]
            / max(
                1,
                source_counts["automatic_transcript"]
                + source_counts["reviewed_transcript"],
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
    args = parser.parse_args()

    result = evaluate(
        args.knowledge,
        args.retrieval_index,
        run_retrieval_roundtrip=not args.skip_retrieval_roundtrip,
        run_semantic_probes=not args.skip_retrieval_roundtrip,
        require_raw_transcripts=args.require_raw_transcripts,
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
