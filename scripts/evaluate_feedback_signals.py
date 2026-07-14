#!/usr/bin/env python3
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
        matched = (
            case["case_id"] in matched_signal_ids
            and not missing_positive_ids
            and not negative_without_penalty
            and not missing_reminders
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
            }
        )
    return {
        "cases": len(cases),
        "passed": passed,
        "accuracy": passed / len(cases) if cases else 1.0,
        "status": "no_promoted_feedback_yet" if not cases else "evaluated",
        "results": results,
    }


def main():
    result = evaluate()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["accuracy"] < 1.0:
        raise SystemExit("Promoted feedback regression evaluation failed")


if __name__ == "__main__":
    main()
