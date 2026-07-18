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


def evaluate():
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]
    search_module = load_search_module()
    results = []
    passed = 0
    for case in cases:
        payload = search_module.search(
            case["query"],
            manifest_limit=None,
            local_personalization=False,
        )
        manifest = {item["video_id"]: item for item in payload["candidate_manifest"]}
        missing_positive_ids = [
            video_id
            for video_id in case["expected_positive_video_ids"]
            if video_id not in manifest
            or manifest[video_id].get("feedback_adjustment", {}).get("global_delta", 0)
            <= 0
        ]
        negative_without_penalty = [
            video_id
            for video_id in case["expected_negative_video_ids"]
            if video_id in manifest
            and manifest[video_id].get("feedback_adjustment", {}).get("global_delta", 0)
            >= 0
        ]
        matched_signal_ids = set(
            payload["feedback_guidance"]["global"]["matched_signal_ids"]
        )
        reminders = set(
            payload["feedback_guidance"]["answer_preferences"]["query_reminders"]
        )
        missing_reminders = sorted(
            set(case["expected_answer_reminders"]) - reminders
        )
        preferences = payload["feedback_guidance"]["answer_preferences"]
        expected_intended_query = case.get("expected_intended_query")
        intended_query_missing = bool(
            expected_intended_query
            and expected_intended_query not in preferences["query_replan_hints"]
        )
        missing_source_recheck_ids = sorted(
            set(case.get("expected_source_issue_video_ids", []))
            - set(preferences["source_recheck_video_ids"])
        )
        matched = (
            case["case_id"] in matched_signal_ids
            and not missing_positive_ids
            and not negative_without_penalty
            and not missing_reminders
            and not intended_query_missing
            and not missing_source_recheck_ids
        )
        passed += int(matched)
        results.append(
            {
                "case_id": case["case_id"],
                "query": case["query"],
                "matched": matched,
                "missing_positive_video_ids": missing_positive_ids,
                "negative_without_penalty": negative_without_penalty,
                "missing_answer_reminders": missing_reminders,
                "intended_query_missing": intended_query_missing,
                "missing_source_recheck_video_ids": missing_source_recheck_ids,
            }
        )
    return {
        "cases": len(cases),
        "passed": passed,
        "accuracy": passed / len(cases) if cases else None,
        "status": "no_promoted_feedback_yet" if not cases else "evaluated",
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate promoted public feedback signals against regression cases."
    )
    parser.add_argument("--require-cases", type=int, default=0)
    args = parser.parse_args()
    result = evaluate()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["cases"] < args.require_cases:
        raise SystemExit(
            f"Only {result['cases']} promoted feedback cases exist; "
            f"expected at least {args.require_cases}"
        )
    if result["accuracy"] is not None and result["accuracy"] < 1.0:
        raise SystemExit("Promoted feedback regression evaluation failed")


if __name__ == "__main__":
    main()
