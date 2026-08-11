#!/usr/bin/env python3
import argparse
import importlib.util
import json
import re
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
RUNTIME_PRIORS_PATH = ROOT / "config" / "reviewed_evidence_signals.json"
EVALUATION_DIR = ROOT / "data" / "evaluation"
_MODULE_CACHE = {}


def load_module(name, path):
    cache_key = str(Path(path).resolve())
    if cache_key in _MODULE_CACHE:
        return _MODULE_CACHE[cache_key]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _MODULE_CACHE[cache_key] = module
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
    captured = {}
    original_merge = runtime.merge_candidates

    def capture_merged_candidates(payloads, queries):
        merged = original_merge(payloads, queries)
        captured["candidate_ids"] = set(merged)
        return merged

    runtime.merge_candidates = capture_merged_candidates
    try:
        payload = runtime.prepare_answer_context(
            case["query"],
            local_personalization=False,
        )
    finally:
        runtime.merge_candidates = original_merge
    selected_ids = [item["video_id"] for item in payload["selected_videos"]]
    label_to_video_id = {
        item["label"]: item["video_id"]
        for item in payload["selected_videos"]
    }

    def video_ids_for_labels(labels):
        return {
            label_to_video_id[label]
            for label in labels
            if label in label_to_video_id
        }

    claim_labels = {
        evidence["label"]
        for claim in payload["claim_evidence_map"]
        for evidence in claim.get("evidence", [])
    }
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
        "candidate_ids": captured.get("candidate_ids", set()),
        "semantic_answerable_ids": set(
            payload["selection"]["semantic_answerable_video_ids"]
        ),
        "synthesis_candidate_ids": set(
            payload["selection"]["synthesis_candidate_video_ids"]
        ),
        "selected_ids": selected_ids,
        "claim_mapped_ids": video_ids_for_labels(claim_labels),
        "synthesis_ids": video_ids_for_labels(
            payload["answer_synthesis_video_labels"]
        ),
        "audit_only_ids": video_ids_for_labels(
            payload.get("answer_audit_only_related_video_labels", [])
        ),
        "complete_related_ids": video_ids_for_labels(
            payload["answer_complete_related_video_labels"]
        ),
        "core_ids": video_ids_for_labels(
            payload["answer_core_video_labels"]
        ),
        "top_ids": selected_ids,
        "evidence_ready_ids": evidence_ready_ids,
    }


def _normalized_fixture_text(value):
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", str(value).lower())


def _fixture_signatures(evaluation_dir):
    query_keys = {"query", "question", "user_query", "original_query"}
    evidence_keys = {
        "required_video_ids",
        "primary_video_ids",
        "relevant_video_ids",
        "expected_video_ids",
        "evidence_ids",
    }
    queries = set()
    evidence_sets = set()

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in query_keys and isinstance(value, str):
                    normalized = _normalized_fixture_text(value)
                    if normalized:
                        queries.add(normalized)
                if key in evidence_keys and isinstance(value, list):
                    identifiers = frozenset(
                        str(item) for item in value if str(item).strip()
                    )
                    if identifiers:
                        evidence_sets.add(identifiers)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for fixture_path in sorted(Path(evaluation_dir).glob("*.json")):
        try:
            walk(json.loads(fixture_path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            return set(), set(), False
    return queries, evidence_sets, True


def evaluation_fixture_isolation(
    path=RUNTIME_PRIORS_PATH, evaluation_dir=EVALUATION_DIR
):
    """Confirm that runtime ranking priors cannot contain evaluation fixtures."""

    registry = json.loads(Path(path).read_text(encoding="utf-8"))
    signals = registry.get("signals", [])
    fixture_queries, fixture_evidence_sets, fixtures_valid = (
        _fixture_signatures(evaluation_dir)
    )
    if not (
        fixtures_valid
        and registry.get("registry_type")
        == "operational_feedback_runtime_prior"
        and registry.get("evaluation_case_ids_forbidden") is True
        and isinstance(signals, list)
        and not any("case_id" in signal for signal in signals)
        and "data/evaluation/" not in str(registry.get("source", ""))
    ):
        return False
    query_keys = {"query", "question", "user_query", "original_query"}
    evidence_keys = {
        "required_video_ids",
        "primary_video_ids",
        "relevant_video_ids",
        "expected_video_ids",
        "evidence_ids",
    }
    for signal in signals:
        signal_queries = {
            _normalized_fixture_text(signal.get(key, ""))
            for key in query_keys
            if isinstance(signal.get(key), str)
        } - {""}
        if signal_queries & fixture_queries:
            return False
        signal_evidence = {
            str(item)
            for key in evidence_keys
            for item in (
                signal.get(key, [])
                if isinstance(signal.get(key), list)
                else []
            )
        }
        if any(
            fixture_ids.issubset(signal_evidence)
            for fixture_ids in fixture_evidence_sets
        ):
            return False
    return True


def evaluate(cases_path=CASES_PATH, top_k=12):
    cases = json.loads(cases_path.read_text(encoding="utf-8"))["cases"]
    search_module = load_search_module()
    expected_total = 0
    candidate_recalled_total = 0
    semantic_answerable_recalled_total = 0
    selected_recalled_total = 0
    claim_mapped_recalled_total = 0
    synthesis_recalled_total = 0
    complete_related_recalled_total = 0
    synthesis_display_expected_total = 0
    core_recalled_total = 0
    primary_cases = 0
    primary_selected = 0
    selected_video_total = 0
    selected_video_ready = 0
    layer_counts = {
        "candidate": 0,
        "semantic_answerable": 0,
        "synthesis_candidate": 0,
        "selected": 0,
        "claim_mapped": 0,
        "synthesis": 0,
        "audit_only": 0,
        "complete_related": 0,
        "core": 0,
    }
    results = []
    for case in cases:
        context = prepare_case_context(search_module, case, top_k=top_k)
        gold = case["gold"]
        expected = set(gold["required_video_ids"])
        primary = set(gold["primary_video_ids"])
        irrelevant = set(gold["irrelevant_video_ids"])
        missing_candidates = sorted(expected - context["candidate_ids"])
        missing_semantic_answerable = sorted(
            expected - context["semantic_answerable_ids"]
        )
        missing_selected = sorted(expected - set(context["selected_ids"]))
        missing_claim_mapped = sorted(expected - context["claim_mapped_ids"])
        missing_synthesis = sorted(expected - context["synthesis_ids"])
        missing_complete_related = sorted(
            context["synthesis_ids"] - context["complete_related_ids"]
        )
        missing_core = sorted(expected - context["core_ids"])
        expected_total += len(expected)
        candidate_recalled_total += len(expected) - len(missing_candidates)
        semantic_answerable_recalled_total += len(expected) - len(
            missing_semantic_answerable
        )
        selected_recalled_total += len(expected) - len(missing_selected)
        claim_mapped_recalled_total += len(expected) - len(missing_claim_mapped)
        synthesis_recalled_total += len(expected) - len(missing_synthesis)
        synthesis_display_expected_total += len(context["synthesis_ids"])
        complete_related_recalled_total += len(context["synthesis_ids"]) - len(
            missing_complete_related
        )
        core_recalled_total += len(expected) - len(missing_core)
        for layer in layer_counts:
            key = "candidate_ids" if layer == "candidate" else f"{layer}_ids"
            layer_counts[layer] += len(context[key])
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
                "missing_semantic_answerable_video_ids": (
                    missing_semantic_answerable
                ),
                "missing_selected_video_ids": missing_selected,
                "missing_claim_mapped_video_ids": missing_claim_mapped,
                "missing_synthesis_video_ids": missing_synthesis,
                "missing_complete_related_video_ids": missing_complete_related,
                "missing_core_video_ids": missing_core,
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
                "semantic_answerable_video_count": len(
                    context["semantic_answerable_ids"]
                ),
                "claim_mapped_video_count": len(context["claim_mapped_ids"]),
                "synthesis_video_count": len(context["synthesis_ids"]),
                "audit_only_video_count": len(context["audit_only_ids"]),
                "complete_related_video_count": len(
                    context["complete_related_ids"]
                ),
                "core_video_count": len(context["core_ids"]),
                "selection_truncated": context["payload"]["selection"][
                    "selection_truncated"
                ],
                "retrieval_query_budget": context["payload"][
                    "question_interpretation"
                ]["retrieval_query_budget"],
            }
        )

    mode_accuracy = sum(item["answer_mode_matched"] for item in results) / max(
        1, len(results)
    )
    return {
        "stage": "production_budgeted_layered_answer_evidence_selection",
        "cases": len(results),
        "expected_videos": expected_total,
        "candidate_recall": candidate_recalled_total / max(1, expected_total),
        "semantic_answerable_video_recall": (
            semantic_answerable_recalled_total / max(1, expected_total)
        ),
        "selected_video_recall": selected_recalled_total / max(1, expected_total),
        "claim_mapped_video_recall": claim_mapped_recalled_total
        / max(1, expected_total),
        "synthesis_video_recall": synthesis_recalled_total
        / max(1, expected_total),
        "complete_related_video_recall": complete_related_recalled_total
        / max(1, synthesis_display_expected_total),
        "synthesis_display_expected_videos": synthesis_display_expected_total,
        "core_video_recall": core_recalled_total / max(1, expected_total),
        "mean_video_count_by_layer": {
            layer: count / max(1, len(results))
            for layer, count in layer_counts.items()
        },
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
        "retrieval_query_budget_truncated_cases": sum(
            item["retrieval_query_budget"]["truncated"] for item in results
        ),
        "retrieval_query_omitted_count": sum(
            item["retrieval_query_budget"]["omitted_query_count"]
            for item in results
        ),
        "evaluation_fixture_isolation": evaluation_fixture_isolation(),
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
    parser.add_argument(
        "--min-semantic-answerable-recall", type=float, default=1.0
    )
    parser.add_argument("--min-selected-video-recall", type=float, default=1.0)
    parser.add_argument(
        "--min-claim-mapped-video-recall", type=float, default=1.0
    )
    parser.add_argument(
        "--min-complete-related-video-recall", type=float, default=1.0
    )
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
    layered_gates = [
        (
            "semantic answerable video recall",
            result["semantic_answerable_video_recall"],
            args.min_semantic_answerable_recall,
        ),
        (
            "selected video recall",
            result["selected_video_recall"],
            args.min_selected_video_recall,
        ),
        (
            "claim-mapped video recall",
            result["claim_mapped_video_recall"],
            args.min_claim_mapped_video_recall,
        ),
        (
            "complete-related video recall",
            result["complete_related_video_recall"],
            args.min_complete_related_video_recall,
        ),
        (
            "primary selected rate",
            result["primary_selected_rate"],
            args.min_primary_selected_rate,
        ),
    ]
    failed.extend(
        name
        for name, actual, required in layered_gates
        if actual < required
    )
    if not result["evaluation_fixture_isolation"]:
        failed.append("evaluation fixture isolation")
    if (
        result["hard_negative_selected_violations"]
        > args.max_hard_negative_selected_violations
    ):
        failed.append("hard-negative selected violations")
    if failed:
        raise SystemExit("Answer-context quality gates failed: " + ", ".join(failed))


if __name__ == "__main__":
    main()
