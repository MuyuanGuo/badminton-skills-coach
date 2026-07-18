#!/usr/bin/env python3
import argparse
import importlib.util
import json
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_PATH = ROOT / "data" / "knowledge" / "douyin_knowledge_base.json"
RETRIEVAL_INDEX_PATH = ROOT / "data" / "knowledge" / "retrieval_index.json"
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
    require_raw_transcript=False,
):
    video_id = video["video_id"]
    note = video.get("teaching_note") or {}
    failures = []
    source_kind = (
        "visual_review"
        if video.get("confidence") == "visual_reviewed"
        else "transcript"
    )
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
        probe = summary or (visual_evidence[0]["text"] if visual_evidence else "")
    else:
        quality = video.get("quality") or {}
        transcript_quality = quality.get("transcript") or {}
        evidence_quality = quality.get("automatic_evidence") or {}
        if transcript_quality.get("passed") is not True:
            failures.append("transcript_quality_not_passed")
        if evidence_quality.get("passed") is not True:
            failures.append("automatic_evidence_quality_not_passed")

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
        if not evidence:
            failures.append("missing_teaching_evidence")

        if video.get("confidence") != "curated" and full_transcript:
            normalized_transcript = normalize_text(full_transcript)
            for item in note_evidence(note, TRANSCRIPT_EVIDENCE_FIELDS):
                if normalize_text(item["text"]) not in normalized_transcript:
                    failures.append(
                        f"evidence_not_in_transcript:{item['role']}:{item['timestamp']}"
                    )
        probe = evidence[0]["text"] if evidence else ""

    if not normalize_text(probe):
        failures.append("missing_retrieval_probe")
    return {
        "video_id": video_id,
        "source_kind": source_kind,
        "raw_transcript_status": raw_transcript_status,
        "probe": probe,
        "failures": failures,
    }


def evaluate(
    knowledge_path=KNOWLEDGE_PATH,
    retrieval_index_path=RETRIEVAL_INDEX_PATH,
    root=ROOT,
    run_retrieval_roundtrip=True,
    require_raw_transcripts=False,
):
    knowledge = load_json(knowledge_path)
    retrieval_index = load_json(retrieval_index_path)
    ready_videos = [
        video for video in knowledge["videos"] if video["processing_status"] == "ready"
    ]
    indexed_video_ids = {
        record["video_id"] for record in retrieval_index.get("videos", [])
    }
    audits = [
        audit_video_content(
            video,
            root=root,
            indexed_video_ids=indexed_video_ids,
            require_raw_transcript=require_raw_transcripts,
        )
        for video in ready_videos
    ]
    audit_by_id = {audit["video_id"]: audit for audit in audits}

    runtime_lookup_count = 0
    recalled_count = 0
    ranks = []
    if run_retrieval_roundtrip:
        search_module = load_search_module()
        runtime_knowledge, runtime_index, runtime_rules = search_module.load_resources()
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

        for audit in audits:
            if not audit["probe"]:
                continue
            ranked, _ = search_module.rank_candidates(
                audit["probe"], runtime_knowledge, runtime_index, runtime_rules
            )
            rank = next(
                (
                    index
                    for index, candidate in enumerate(ranked, start=1)
                    if candidate["video_id"] == audit["video_id"]
                ),
                None,
            )
            if rank is None:
                audit["failures"].append("evidence_probe_not_recalled")
            else:
                recalled_count += 1
                ranks.append(rank)
                audit["retrieval_rank"] = rank

    source_counts = Counter(audit["source_kind"] for audit in audits)
    raw_transcript_counts = Counter(
        audit["raw_transcript_status"]
        for audit in audits
        if audit["source_kind"] == "transcript"
    )
    failure_items = [audit for audit in audits if audit["failures"]]
    understood = len(audits) - len(failure_items)
    denominator = max(1, len(audits))
    return {
        "ready_videos": len(audits),
        "understood_videos": understood,
        "understanding_coverage": understood / denominator,
        "transcript_backed": source_counts["transcript"],
        "visual_review_fallback": source_counts["visual_review"],
        "raw_transcript_requirement_enabled": require_raw_transcripts,
        "raw_transcript_files_verified": raw_transcript_counts["verified"],
        "raw_transcript_files_unavailable": raw_transcript_counts["unavailable"],
        "raw_transcript_roundtrip_coverage": (
            raw_transcript_counts["verified"] / max(1, source_counts["transcript"])
        ),
        "runtime_lookup_coverage": (
            runtime_lookup_count / denominator if run_retrieval_roundtrip else None
        ),
        "evidence_probe_candidate_recall": (
            recalled_count / denominator if run_retrieval_roundtrip else None
        ),
        "evidence_probe_rank_counts": {
            "top_1": sum(rank <= 1 for rank in ranks),
            "top_5": sum(rank <= 5 for rank in ranks),
            "top_10": sum(rank <= 10 for rank in ranks),
            "top_20": sum(rank <= 20 for rank in ranks),
            "max_rank": max(ranks) if ranks else None,
        },
        "failure_count": len(failure_items),
        "failures": failure_items,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Audit whether every ready video has understandable source evidence."
    )
    parser.add_argument("--knowledge", type=Path, default=KNOWLEDGE_PATH)
    parser.add_argument("--retrieval-index", type=Path, default=RETRIEVAL_INDEX_PATH)
    parser.add_argument("--require-ready", type=int, default=350)
    parser.add_argument("--min-understanding-coverage", type=float, default=1.0)
    parser.add_argument("--min-runtime-lookup-coverage", type=float, default=1.0)
    parser.add_argument("--min-evidence-probe-recall", type=float, default=1.0)
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
        require_raw_transcripts=args.require_raw_transcripts,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["ready_videos"] < args.require_ready:
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
            result["evidence_probe_candidate_recall"]
            < args.min_evidence_probe_recall
        ):
            raise SystemExit("Evidence-probe candidate recall is below the required threshold")


if __name__ == "__main__":
    main()
