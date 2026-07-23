#!/usr/bin/env python3
"""Evaluate the diagnostic-answer contract against maintained gold cases."""

import argparse
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "data" / "evaluation" / "diagnostic_answer_cases.json"
CONTINUATION_CASES_PATH = (
    ROOT / "data" / "evaluation" / "diagnostic_answer_continuation_cases.json"
)
RUNTIME_PATH = (
    ROOT
    / "skills"
    / "liuhui-badminton-coach"
    / "scripts"
    / "prepare_answer_context.py"
)


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_runtime():
    spec = importlib.util.spec_from_file_location(
        "liuhui_diagnostic_answer_runtime", RUNTIME_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def hypothesis_by_text(context):
    return {
        item["text"]: item
        for item in context["diagnostic_model"]["user_hypotheses"]
    }


def claim_evidence_ids(context, kind=None):
    return {
        item["evidence_id"]
        for claim in context["claim_evidence_map"]
        if kind is None or claim["kind"] == kind
        for item in claim["evidence"]
    }


def case_mismatches(context, expected):
    mismatches = []
    diagnostic = context["diagnostic_model"]
    clarification = context["clarification_decision"]
    completeness = context["completeness_contract"]

    symptoms = {item["text"] for item in diagnostic["observed_symptoms"]}
    if not set(expected.get("observed_symptoms_contains", [])).issubset(symptoms):
        mismatches.append("observed_symptoms_contains")
    if set(expected.get("observed_symptoms_excludes", [])) & symptoms:
        mismatches.append("observed_symptoms_excludes")
    for axis, values in expected.get("constraints", {}).items():
        if context["question_interpretation"]["constraints"].get(axis) != values:
            mismatches.append(f"constraints:{axis}")

    actual_hypotheses = hypothesis_by_text(context)
    for hypothesis in expected.get("hypotheses", []):
        actual = actual_hypotheses.get(hypothesis["text"])
        if not actual or actual["status"] != hypothesis["status"]:
            mismatches.append(f'hypothesis:{hypothesis["text"]}:status')
            continue
        actual_evidence_ids = {
            item["evidence_id"]
            for claim in context["claim_evidence_map"]
            if claim["claim_id"] == actual["id"]
            for item in claim["evidence"]
        }
        if actual_evidence_ids != set(hypothesis.get("evidence_ids", [])):
            mismatches.append(f'hypothesis:{hypothesis["text"]}:evidence')

    mechanism_ids = {
        item["mechanism_id"] for item in diagnostic["supported_mechanisms"]
    }
    if not set(expected.get("supported_mechanism_ids_contains", [])).issubset(
        mechanism_ids
    ):
        mismatches.append("supported_mechanism_ids_contains")

    branch_by_axis = {
        item["axis"]: item for item in diagnostic["material_branches"]
    }
    if not set(expected.get("branch_axes_contains", [])).issubset(branch_by_axis):
        mismatches.append("branch_axes_contains")
    if set(expected.get("branch_axes_excludes", [])) & set(branch_by_axis):
        mismatches.append("branch_axes_excludes")
    for axis, values in expected.get("branch_values", {}).items():
        actual_values = {
            item["value"] for item in branch_by_axis.get(axis, {}).get("branches", [])
        }
        if set(values) != actual_values:
            mismatches.append(f"branch_values:{axis}")

    if expected.get("clarification_action") != clarification["action"]:
        mismatches.append("clarification_action")
    unknown_types = {item["type"] for item in clarification["material_unknowns"]}
    if not set(expected.get("unknown_types_contains", [])).issubset(unknown_types):
        mismatches.append("unknown_types_contains")
    if len(clarification["questions"]) > clarification["question_limit"]:
        mismatches.append("clarification_question_limit")

    unresolved_texts = {
        item["text"]
        for item in completeness["items"]
        if item["status"] == "unresolved"
    }
    if not set(expected.get("unresolved_texts_contains", [])).issubset(
        unresolved_texts
    ):
        mismatches.append("unresolved_texts_contains")
    must_answer_count = sum(
        item["status"] == "must_answer" for item in completeness["items"]
    )
    if must_answer_count < expected.get("minimum_must_answer_items", 0):
        mismatches.append("minimum_must_answer_items")

    excluded_ids = set(expected.get("query_claim_excluded_evidence_ids", []))
    if excluded_ids & claim_evidence_ids(context, kind="question_unit"):
        mismatches.append("query_claim_excluded_evidence_ids")
    if (
        diagnostic["do_not_claim_unique_cause"]
        != expected.get("do_not_claim_unique_cause")
    ):
        mismatches.append("do_not_claim_unique_cause")
    return mismatches


def continuation_case_mismatches(context, case):
    expected = case["expected"]
    mismatches = []
    state = context["clarification_state"]
    if state["original_query"] != case["original_query"]:
        mismatches.append("original_query")
    if not context["query"].startswith(case["original_query"]):
        mismatches.append("effective_query_preserves_original")
    for text in expected.get("effective_query_excludes", []):
        if text in context["query"]:
            mismatches.append(f"effective_query_excludes:{text}")
    for axis, values in expected.get("constraints", {}).items():
        if context["question_interpretation"]["constraints"].get(axis) != values:
            mismatches.append(f"constraints:{axis}")
    hypotheses = {
        item["text"] for item in context["diagnostic_model"]["user_hypotheses"]
    }
    if not set(expected.get("hypotheses_contains", [])).issubset(hypotheses):
        mismatches.append("hypotheses_contains")
    branch_axes = {
        item["axis"]
        for item in context["diagnostic_model"]["material_branches"]
    }
    if set(expected.get("branch_axes_excludes", [])) & branch_axes:
        mismatches.append("branch_axes_excludes")
    resolved_ids = [
        item["question_id"] for item in state["resolved_answers"]
    ]
    if resolved_ids != expected.get("resolved_question_ids", resolved_ids):
        mismatches.append("resolved_question_ids")
    if state["pending_question_ids"] != expected.get(
        "pending_question_ids", state["pending_question_ids"]
    ):
        mismatches.append("pending_question_ids")
    expected_chain = expected.get("event_chain")
    if expected_chain is not None and (
        context["question_interpretation"]["actor_context"]["event_chain"]
        != expected_chain
    ):
        mismatches.append("event_chain")
    if (
        context["diagnostic_model"]["do_not_claim_unique_cause"]
        != expected.get("do_not_claim_unique_cause")
    ):
        mismatches.append("do_not_claim_unique_cause")
    selected = {item["label"] for item in context["selected_videos"]}
    for claim in context["claim_evidence_map"]:
        if not set(claim["eligible_video_labels"]).issubset(selected):
            mismatches.append(f'claim_allowlist:{claim["claim_id"]}')
    return mismatches


def evaluate(
    cases_path=CASES_PATH,
    continuation_cases_path=CONTINUATION_CASES_PATH,
):
    payload = load_json(cases_path)
    runtime = load_runtime()
    results = []
    for case in payload["cases"]:
        context = runtime.prepare_answer_context(
            case["query"], local_personalization=False
        )
        mismatches = case_mismatches(context, case["expected"])
        results.append(
            {
                "case_id": case["case_id"],
                "query": case["query"],
                "matched": not mismatches,
                "mismatches": mismatches,
            }
        )
    continuation_payload = load_json(continuation_cases_path)
    for case in continuation_payload["cases"]:
        first_context = runtime.prepare_answer_context(
            case["original_query"], local_personalization=False
        )
        context = runtime.prepare_answer_context(
            case["reply"],
            local_personalization=False,
            continue_from=first_context,
            clarification_answers=case.get("answers"),
        )
        mismatches = continuation_case_mismatches(context, case)
        results.append(
            {
                "case_id": case["case_id"],
                "query": case["original_query"],
                "matched": not mismatches,
                "mismatches": mismatches,
            }
        )
    passed = sum(item["matched"] for item in results)
    return {
        "cases": len(results),
        "passed": passed,
        "accuracy": passed / len(results) if results else 0.0,
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument(
        "--continuation-cases",
        type=Path,
        default=CONTINUATION_CASES_PATH,
    )
    args = parser.parse_args()
    result = evaluate(args.cases, args.continuation_cases)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["passed"] != result["cases"]:
        raise SystemExit("Diagnostic answer contract regression")


if __name__ == "__main__":
    main()
