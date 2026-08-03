#!/usr/bin/env python3
"""Evaluate answer-context invariants under harmless user-language transformations."""

import argparse
import importlib.util
import json
import os
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "data" / "evaluation" / "answer_quality_cases.json"
CONTEXT_PATH = (
    ROOT
    / "skills"
    / "liuhui-badminton-coach"
    / "scripts"
    / "prepare_answer_context.py"
)
DEFAULT_CASES_PER_TYPE = 3


def load_context_module():
    spec = importlib.util.spec_from_file_location(
        "liuhui_metamorphic_context", CONTEXT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_cases(path=CASES_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8"))["cases"]


def harmless_variants(query):
    clean = str(query).strip().rstrip("？?。！!")
    return [
        {
            "transformation": "polite_prefix",
            "query": f"请问，{clean}",
        },
        {
            "transformation": "conversational_suffix",
            "query": f"{clean}？谢谢",
        },
    ]


def select_balanced_cases(cases, cases_per_type=DEFAULT_CASES_PER_TYPE):
    selected = []
    counts = Counter()
    for case in cases:
        case_type = case["case_type"]
        if counts[case_type] >= cases_per_type:
            continue
        selected.append(case)
        counts[case_type] += 1
    return selected


def interpretation_signature(context):
    interpretation = context["question_interpretation"]
    actor = interpretation["actor_context"]
    return {
        "answer_mode": context["answer_guidance"]["mode"],
        "target_actor": actor["target_actor"],
        "target_action_query": actor["target_action_query"],
        "requested_action_scopes": sorted(actor["requested_action_scopes"]),
        "constraints": {
            key: sorted(values)
            for key, values in interpretation["constraints"].items()
            if values
        },
    }


def selected_video_ids(context):
    """Return the observable retrieval result used by metamorphic checks."""

    return {item["video_id"] for item in context["selected_videos"]}


def evaluate(cases_path=CASES_PATH, cases_per_type=DEFAULT_CASES_PER_TYPE):
    os.environ.setdefault("LIUHUI_RETRIEVAL_EVAL_MODE", "unassisted")
    context_module = load_context_module()
    selected_cases = select_balanced_cases(
        load_cases(cases_path),
        cases_per_type=cases_per_type,
    )
    results = []
    failure_counts = Counter()
    selected_by_type = defaultdict(int)

    for case in selected_cases:
        selected_by_type[case["case_type"]] += 1
        baseline = context_module.prepare_answer_context(
            case["query"],
            local_personalization=False,
        )
        baseline_signature = interpretation_signature(baseline)
        baseline_selected_ids = selected_video_ids(baseline)
        irrelevant_ids = set(case["gold"]["irrelevant_video_ids"])

        for variant in harmless_variants(case["query"]):
            context = context_module.prepare_answer_context(
                variant["query"],
                local_personalization=False,
            )
            signature = interpretation_signature(context)
            target_action_is_structured = bool(
                baseline_signature["requested_action_scopes"]
                or baseline_signature["constraints"]
            )
            selected_ids = selected_video_ids(context)
            checks = {
                "answer_mode_changed": (
                    signature["answer_mode"] == baseline_signature["answer_mode"]
                ),
                "target_actor_changed": (
                    signature["target_actor"] == baseline_signature["target_actor"]
                ),
                "target_action_changed": (
                    not target_action_is_structured
                    or signature["target_action_query"]
                    == baseline_signature["target_action_query"]
                ),
                "action_scope_changed": (
                    signature["requested_action_scopes"]
                    == baseline_signature["requested_action_scopes"]
                ),
                "constraint_changed": (
                    signature["constraints"] == baseline_signature["constraints"]
                ),
                # This suite tests invariance under harmless wording changes.
                # Gold relevance belongs to the independent retrieval suite;
                # comparing against it here leaked evaluation fixtures into a
                # second gate and mislabeled ordinary misses as instability.
                "selected_evidence_changed": (
                    selected_ids == baseline_selected_ids
                ),
                "hard_negative_selected": not bool(irrelevant_ids & selected_ids),
            }
            failures = [name for name, passed in checks.items() if not passed]
            failure_counts.update(failures)
            results.append(
                {
                    "case_id": case["case_id"],
                    "case_type": case["case_type"],
                    "transformation": variant["transformation"],
                    "query": variant["query"],
                    "passed": not failures,
                    "failures": failures,
                }
            )

    passed = sum(item["passed"] for item in results)
    return {
        "base_cases": len(selected_cases),
        "variants": len(results),
        "case_types": dict(sorted(selected_by_type.items())),
        "passed": passed,
        "pass_rate": passed / len(results) if results else None,
        "failure_taxonomy": dict(sorted(failure_counts.items())),
        "failed": [item for item in results if not item["passed"]],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument(
        "--cases-per-type",
        type=int,
        default=DEFAULT_CASES_PER_TYPE,
    )
    parser.add_argument("--min-base-cases", type=int, default=15)
    parser.add_argument("--min-variants", type=int, default=30)
    parser.add_argument("--min-pass-rate", type=float, default=1.0)
    args = parser.parse_args()
    result = evaluate(args.cases, cases_per_type=args.cases_per_type)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["base_cases"] < args.min_base_cases:
        raise SystemExit("Metamorphic evaluation has too few balanced base cases")
    if result["variants"] < args.min_variants:
        raise SystemExit("Metamorphic evaluation has too few transformed variants")
    if result["pass_rate"] is None or result["pass_rate"] < args.min_pass_rate:
        raise SystemExit(
            "Metamorphic robustness gate failed: "
            f"{result['pass_rate'] or 0:.3f} < {args.min_pass_rate:.3f}"
        )


if __name__ == "__main__":
    main()
