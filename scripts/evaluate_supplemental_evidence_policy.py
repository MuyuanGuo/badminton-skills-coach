#!/usr/bin/env python3
"""Evaluate primary-first selection and bounded supplemental evidence use."""

import importlib.util
import json
from pathlib import Path

from project_artifacts import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
CONTEXT_PATH = (
    ROOT
    / "skills/liuhui-badminton-coach/scripts/prepare_answer_context.py"
)
GRAPH_PATH = ROOT / "data/knowledge/evidence_graph.json"
KNOWLEDGE_PATH = ROOT / "data/knowledge/douyin_knowledge_base.json"
OUTPUT_PATH = ROOT / "data/evaluation/supplemental_evidence_report.json"
POSITIVE_ID = "bilibili:BV1VJ4m1b7U7"
WEAK_OVERLAP_ID = "bilibili:BV1BDRCYFEFr"
PRIMARY_COVERED_ID = "bilibili:BV13U411S7AM"


def load_context_module():
    spec = importlib.util.spec_from_file_location(
        "supplemental_evidence_context", CONTEXT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def selected_by_id(context):
    return {item["video_id"]: item for item in context["selected_videos"]}


def evaluate():
    runtime = load_context_module()
    positive = runtime.prepare_answer_context(
        "初学者低磅应该选高弹线还是耐打线？",
        local_personalization=False,
    )
    weak = runtime.prepare_answer_context(
        "双打网前怎么下压",
        local_personalization=False,
    )
    primary_covered = runtime.prepare_answer_context(
        "点杀卸力怎么做？手指和手腕分别怎么配合？",
        local_personalization=False,
    )
    positive_selected = selected_by_id(positive)
    positive_item = positive_selected.get(POSITIVE_ID)
    weak_ids = set(selected_by_id(weak))
    packet = runtime.build_answer_packet(positive)
    packet_bytes = len(
        json.dumps(packet, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    )
    contexts = [positive, weak, primary_covered]
    maximum_supplemental_synthesis_candidates = max(
        sum(
            item.get("answer_eligibility") == "supplemental"
            and item["video_id"]
            in set(context["selection"]["synthesis_candidate_video_ids"])
            for item in context["selected_videos"]
        )
        for context in contexts
    )
    failures = []
    if not positive_item:
        failures.append("direct_bounded_supplemental_not_selected")
    else:
        if positive_item.get("runtime_evidence_mode") != "bounded_note_windows":
            failures.append("positive_source_not_bounded_note_mode")
        if not positive_item.get("bounded_note_evidence"):
            failures.append("positive_source_has_no_matched_note_window")
        if positive_item["label"] not in positive["answer_visible_video_labels"]:
            failures.append("positive_source_not_mapped_to_claim")
    if WEAK_OVERLAP_ID in weak_ids:
        failures.append("weak_note_overlap_selected")
    if PRIMARY_COVERED_ID in set(
        primary_covered["selection"]["synthesis_candidate_video_ids"]
    ):
        failures.append(
            "supplemental_synthesis_candidate_despite_sufficient_primary_evidence"
        )
    if maximum_supplemental_synthesis_candidates > 2:
        failures.append("supplemental_synthesis_limit_exceeded")
    if packet_bytes > 32 * 1024:
        failures.append("answer_packet_byte_budget_exceeded")

    graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    graph_counts = graph["counts"]
    knowledge = json.loads(KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    expected_primary = sum(
        item.get("answer_eligibility") == "primary"
        for item in knowledge.get("videos", [])
    )
    expected_supplemental = sum(
        item.get("answer_eligibility") == "supplemental"
        for item in knowledge.get("videos", [])
    )
    if graph_counts["primary_videos"] != expected_primary:
        failures.append("graph_primary_count_mismatch")
    if graph_counts["supplemental_videos"] != expected_supplemental:
        failures.append("graph_supplemental_count_mismatch")
    return {
        "schema_version": 1,
        "status": "pass" if not failures else "fail",
        "corpus": {
            "primary": graph_counts["primary_videos"],
            "supplemental": graph_counts["supplemental_videos"],
            "graph_edges": graph_counts["total_edges"],
        },
        "positive_bounded_case": {
            "query": positive["query"],
            "selected": bool(positive_item),
            "claim_visible": bool(
                positive_item
                and positive_item["label"]
                in positive["answer_visible_video_labels"]
            ),
            "matched_window_count": len(
                (positive_item or {}).get("bounded_note_evidence", [])
            ),
        },
        "weak_overlap_rejected": WEAK_OVERLAP_ID not in weak_ids,
        "primary_preferred_for_synthesis": PRIMARY_COVERED_ID
        not in set(
            primary_covered["selection"]["synthesis_candidate_video_ids"]
        ),
        "maximum_supplemental_synthesis_candidates": (
            maximum_supplemental_synthesis_candidates
        ),
        "answer_packet_bytes": packet_bytes,
        "failures": failures,
    }


def main():
    report = evaluate()
    atomic_write_text(
        OUTPUT_PATH,
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
