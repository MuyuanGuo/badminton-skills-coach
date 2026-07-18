#!/usr/bin/env python3
import argparse
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "data" / "evaluation" / "feedback_relevance_cases.json"
SEARCH_PATH = (
    ROOT
    / "skills"
    / "liuhui-badminton-coach"
    / "scripts"
    / "search_knowledge.py"
)


def load_search_module():
    spec = importlib.util.spec_from_file_location("feedback_signal_search", SEARCH_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_with_signals(search_module, query, signals):
    original_loader = search_module.load_global_feedback_records
    search_module.load_global_feedback_records = lambda: (
        signals,
        {"signal_count": len(signals), "updated_at": "evaluation-fixture"},
    )
    try:
        return search_module.search(
            query,
            manifest_limit=None,
            local_personalization=False,
        )
    finally:
        search_module.load_global_feedback_records = original_loader


def evaluate_check(search_module, case_id, check, signals, check_index=0):
    payload = run_with_signals(search_module, check["query"], signals)
    manifest = {item["video_id"]: item for item in payload["candidate_manifest"]}
    adjustments = {
        video_id: item.get("feedback_adjustment", {})
        for video_id, item in manifest.items()
    }
    missing_positive_ids = [
        video_id
        for video_id in check.get("expected_positive_video_ids", [])
        if adjustments.get(video_id, {}).get("global_delta", 0) <= 0
    ]
    negative_without_penalty = [
        video_id
        for video_id in check.get("expected_negative_video_ids", [])
        if adjustments.get(video_id, {}).get("global_delta", 0) >= 0
    ]
    forbidden_adjustments = [
        video_id
        for video_id in check.get("forbidden_adjustment_video_ids", [])
        if adjustments.get(video_id, {}).get("global_delta", 0) != 0
    ]
    matched_signal_ids = set(
        payload["feedback_guidance"]["global"]["matched_signal_ids"]
    )
    expected_signal_match = check.get("expected_signal_match", True)
    signal_match_wrong = any(signal["signal_id"] in matched_signal_ids for signal in signals) != expected_signal_match
    reminders = set(
        payload["feedback_guidance"]["answer_preferences"]["query_reminders"]
    )
    missing_reminders = sorted(
        set(check.get("expected_answer_reminders", [])) - reminders
    )
    forbidden_reminders = sorted(
        set(check.get("forbidden_answer_reminders", [])) & reminders
    )
    preferences = payload["feedback_guidance"]["answer_preferences"]
    intended_query = check.get("expected_intended_query")
    intended_query_missing = bool(
        intended_query and intended_query not in preferences["query_replan_hints"]
    )
    expected_source_ids = set(check.get("expected_source_issue_video_ids", []))
    missing_source_ids = sorted(
        expected_source_ids - set(preferences["source_recheck_video_ids"])
    )
    passed = not any(
        [
            missing_positive_ids,
            negative_without_penalty,
            forbidden_adjustments,
            signal_match_wrong,
            missing_reminders,
            forbidden_reminders,
            intended_query_missing,
            missing_source_ids,
        ]
    )
    return {
        "check_id": f"{case_id}-{check_index + 1}",
        "query": check["query"],
        "passed": passed,
        "missing_positive_video_ids": missing_positive_ids,
        "negative_without_penalty": negative_without_penalty,
        "forbidden_adjustment_video_ids": forbidden_adjustments,
        "signal_match_wrong": signal_match_wrong,
        "missing_answer_reminders": missing_reminders,
        "forbidden_answer_reminders": forbidden_reminders,
        "intended_query_missing": intended_query_missing,
        "missing_source_recheck_video_ids": missing_source_ids,
    }


def evaluate(cases_path=CASES_PATH):
    payload = json.loads(cases_path.read_text(encoding="utf-8"))
    search_module = load_search_module()
    results = []

    production_signals, _ = search_module.load_global_feedback_records()
    production_by_id = {item["signal_id"]: item for item in production_signals}
    for case in payload.get("cases", []):
        signal = production_by_id.get(case["case_id"])
        if signal is None:
            results.append(
                {
                    "check_id": case["case_id"],
                    "query": case["query"],
                    "passed": False,
                    "missing_promoted_signal": True,
                }
            )
            continue
        results.append(
            evaluate_check(
                search_module,
                case["case_id"],
                {
                    **case,
                    "expected_signal_match": True,
                    "forbidden_adjustment_video_ids": [],
                    "forbidden_answer_reminders": [],
                },
                [signal],
            )
        )

    adversarial_check_count = 0
    for case in payload.get("adversarial_cases", []):
        for index, check in enumerate(case["checks"]):
            adversarial_check_count += 1
            results.append(
                evaluate_check(
                    search_module,
                    case["case_id"],
                    check,
                    [case["signal"]],
                    check_index=index,
                )
            )

    passed = sum(item["passed"] for item in results)
    return {
        "promoted_feedback_cases": len(payload.get("cases", [])),
        "adversarial_contract_checks": adversarial_check_count,
        "total_checks": len(results),
        "passed": passed,
        "accuracy": passed / len(results) if results else None,
        "status": (
            "no_promoted_feedback_yet_adversarial_contract_evaluated"
            if not payload.get("cases")
            else "promoted_and_adversarial_feedback_evaluated"
        ),
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate promoted feedback plus adversarial intent-transfer contracts."
        )
    )
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--require-cases", type=int, default=0)
    parser.add_argument("--require-adversarial-checks", type=int, default=7)
    args = parser.parse_args()
    result = evaluate(args.cases)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["promoted_feedback_cases"] < args.require_cases:
        raise SystemExit(
            f"Only {result['promoted_feedback_cases']} promoted feedback cases exist; "
            f"expected at least {args.require_cases}"
        )
    if result["adversarial_contract_checks"] < args.require_adversarial_checks:
        raise SystemExit(
            "Feedback relevance evaluation lacks enough adversarial contract checks"
        )
    if result["accuracy"] is not None and result["accuracy"] < 1.0:
        raise SystemExit("Feedback relevance evaluation failed")


if __name__ == "__main__":
    main()
