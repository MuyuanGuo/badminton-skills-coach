#!/usr/bin/env python3
import argparse
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "data" / "evaluation" / "answer_quality_cases.json"
SEARCH_PATH = (
    ROOT
    / "skills"
    / "liuhui-badminton-coach"
    / "scripts"
    / "search_knowledge.py"
)
CONTEXT_PATH = (
    ROOT
    / "skills"
    / "liuhui-badminton-coach"
    / "scripts"
    / "prepare_answer_context.py"
)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_search_module():
    return load_module("liuhui_answer_context_search", SEARCH_PATH)


def load_context_module():
    return load_module("liuhui_answer_context_runtime", CONTEXT_PATH)


def planned_queries(search_module, plan, original_query):
    return load_context_module().planned_queries(
        search_module, plan, original_query
    )


def prepare_case_context(search_module, case, top_k=12):
    del search_module, top_k
    runtime = load_context_module()
    payload = runtime.prepare_answer_context(
        case["query"],
        local_personalization=False,
        include_rejected=True,
    )
    selected_ids = [item["video_id"] for item in payload["selected_videos"]]
    rejected_ids = [
        item["video_id"] for item in payload["rejected_candidates"]
    ]
    unselected_eligible_ids = [
        item["video_id"]
        for item in payload["unselected_eligible_candidates"]
    ]
    evidence_ready_ids = {
        item["video_id"]
        for item in payload["selected_videos"]
        if item.get("teaching_note")
    }
    return {
        "payload": payload,
        "plan": {
            "answer_guidance": payload["answer_guidance"],
            "retrieval_guidance": {
                **payload["question_interpretation"],
                "intent_frame": payload["question_interpretation"][
                    "intent_frame"
                ],
            },
        },
        "query_units": payload["question_interpretation"]["query_units"],
        "retrieval_queries": payload["question_interpretation"][
            "retrieval_queries"
        ],
        "candidate_ids": (
            set(selected_ids) | set(rejected_ids) | set(unselected_eligible_ids)
        ),
        "selected_ids": selected_ids,
        "top_ids": selected_ids,
        "evidence_ready_ids": evidence_ready_ids,
    }


def evaluate(cases_path=CASES_PATH, top_k=12):
    cases = json.loads(cases_path.read_text(encoding="utf-8"))["cases"]
    search_module = load_search_module()
    expected_total = 0
    candidate_recalled_total = 0
    selected_recalled_total = 0
    primary_cases = 0
    primary_selected = 0
    selected_video_total = 0
    selected_video_ready = 0
    results = []
    for case in cases:
        context = prepare_case_context(search_module, case, top_k=top_k)
        gold = case["gold"]
        expected = set(gold["required_video_ids"])
        primary = set(gold["primary_video_ids"])
        irrelevant = set(gold["irrelevant_video_ids"])
        missing_candidates = sorted(expected - context["candidate_ids"])
        missing_selected = sorted(expected - set(context["selected_ids"]))
        expected_total += len(expected)
        candidate_recalled_total += len(expected) - len(missing_candidates)
        selected_recalled_total += len(expected) - len(missing_selected)
        if primary:
            primary_cases += 1
            if primary & set(context["selected_ids"]):
                primary_selected += 1
        selected_video_total += len(context["selected_ids"])
        selected_video_ready += len(context["evidence_ready_ids"])
        results.append(
            {
                "case_id": case["case_id"],
                "query": case["query"],
                "answer_mode_matched": (
                    context["payload"]["answer_guidance"]["mode"]
                    == case["expected_mode"]
                ),
                "boundary_type": context["payload"]["boundary"]["type"],
                "query_units": context["query_units"],
                "retrieval_queries": context["retrieval_queries"],
                "missing_candidate_video_ids": missing_candidates,
                "missing_selected_video_ids": missing_selected,
                "primary_selected": (
                    not primary or bool(primary & set(context["selected_ids"]))
                ),
                "irrelevant_selected_video_ids": sorted(
                    irrelevant & set(context["selected_ids"])
                ),
                "selected_videos_without_evidence": sorted(
                    set(context["selected_ids"])
                    - context["evidence_ready_ids"]
                ),
                "selected_video_count": len(context["selected_ids"]),
                "selection_truncated": context["payload"]["selection"][
                    "selection_truncated"
                ],
            }
        )

    mode_accuracy = sum(item["answer_mode_matched"] for item in results) / max(
        1, len(results)
    )
    return {
        "stage": "deterministic_pre_answer_context_and_finalist_selection",
        "cases": len(results),
        "expected_videos": expected_total,
        "candidate_recall": candidate_recalled_total / max(1, expected_total),
        "selected_video_recall": selected_recalled_total / max(1, expected_total),
        "primary_selected_rate": primary_selected / max(1, primary_cases),
        "answer_mode_accuracy": mode_accuracy,
        "context_evidence_coverage": selected_video_ready
        / max(1, selected_video_total),
        "hard_negative_selected_violations": sum(
            len(item["irrelevant_selected_video_ids"]) for item in results
        ),
        "selection_truncated_cases": sum(
            item["selection_truncated"] for item in results
        ),
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate deterministic planning, multi-query recall, finalist "
            "selection, and evidence lookup before answer generation."
        )
    )
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--top-k", type=int, default=12)
    parser.add_argument("--min-candidate-recall", type=float, default=1.0)
    parser.add_argument("--min-selected-video-recall", type=float, default=0.95)
    parser.add_argument("--min-primary-selected-rate", type=float, default=0.95)
    parser.add_argument("--min-answer-mode-accuracy", type=float, default=1.0)
    parser.add_argument("--min-context-evidence-coverage", type=float, default=1.0)
    parser.add_argument(
        "--max-hard-negative-selected-violations", type=int, default=0
    )
    args = parser.parse_args()
    result = evaluate(args.cases, top_k=args.top_k)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    gates = [
        ("candidate recall", result["candidate_recall"], args.min_candidate_recall),
        (
            "selected video recall",
            result["selected_video_recall"],
            args.min_selected_video_recall,
        ),
        (
            "primary selected rate",
            result["primary_selected_rate"],
            args.min_primary_selected_rate,
        ),
        (
            "answer mode accuracy",
            result["answer_mode_accuracy"],
            args.min_answer_mode_accuracy,
        ),
        (
            "context evidence coverage",
            result["context_evidence_coverage"],
            args.min_context_evidence_coverage,
        ),
    ]
    failed = [name for name, actual, required in gates if actual < required]
    if (
        result["hard_negative_selected_violations"]
        > args.max_hard_negative_selected_violations
    ):
        failed.append("hard-negative selected violations")
    if failed:
        raise SystemExit("Answer-context quality gates failed: " + ", ".join(failed))


if __name__ == "__main__":
    main()
