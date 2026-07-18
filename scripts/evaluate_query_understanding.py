#!/usr/bin/env python3
import argparse
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "data" / "evaluation" / "query_understanding_cases.json"
ANSWER_CASES_PATH = ROOT / "data" / "evaluation" / "answer_quality_cases.json"
SEARCH_PATH = (
    ROOT
    / "skills"
    / "liuhui-badminton-coach"
    / "scripts"
    / "search_knowledge.py"
)


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_search_module():
    spec = importlib.util.spec_from_file_location("liuhui_query_understanding", SEARCH_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_registry(registry, answer_registry):
    cases = registry.get("cases", [])
    if not cases:
        raise ValueError("query-understanding registry has no cases")

    answer_cases = {
        case["case_id"]: case for case in answer_registry.get("cases", [])
    }
    seen = set()
    required_fields = {
        "case_id",
        "query",
        "intent_summary",
        "expected_answer_mode",
        "expected_strategy",
        "expected_query_units",
        "expected_must_state_boundary_first",
    }
    for case in cases:
        missing = required_fields - set(case)
        if missing:
            raise ValueError(
                f"{case.get('case_id', '<unknown>')} missing fields: {sorted(missing)}"
            )
        case_id = case["case_id"]
        if case_id in seen:
            raise ValueError(f"duplicate query-understanding case: {case_id}")
        seen.add(case_id)
        if not case["intent_summary"].strip():
            raise ValueError(f"{case_id} has no reviewed intent summary")
        if not case["expected_query_units"]:
            raise ValueError(f"{case_id} has no expected query units")
        answer_case = answer_cases.get(case_id)
        if not answer_case:
            raise ValueError(f"{case_id} does not exist in answer-quality cases")
        if answer_case["query"] != case["query"]:
            raise ValueError(f"{case_id} query differs from answer-quality case")
        if answer_case["expected_mode"] != case["expected_answer_mode"]:
            raise ValueError(f"{case_id} answer mode differs from answer-quality case")

    missing_case_ids = set(answer_cases) - seen
    if missing_case_ids:
        raise ValueError(
            "query-understanding registry does not cover: "
            + ", ".join(sorted(missing_case_ids))
        )
    return cases


def evaluate(cases_path=CASES_PATH, answer_cases_path=ANSWER_CASES_PATH):
    registry = load_json(cases_path)
    answer_registry = load_json(answer_cases_path)
    cases = validate_registry(registry, answer_registry)
    search_module = load_search_module()
    results = []

    for case in cases:
        plan = search_module.plan_query(case["query"])
        actual = {
            "answer_mode": plan["answer_guidance"]["mode"],
            "strategy": plan["retrieval_guidance"]["strategy"],
            "query_units": plan["retrieval_guidance"]["query_units"],
            "must_state_boundary_first": plan["retrieval_guidance"][
                "must_state_boundary_first"
            ],
        }
        expected = {
            "answer_mode": case["expected_answer_mode"],
            "strategy": case["expected_strategy"],
            "query_units": case["expected_query_units"],
            "must_state_boundary_first": case[
                "expected_must_state_boundary_first"
            ],
        }
        mismatches = [
            field for field in expected if actual[field] != expected[field]
        ]
        results.append(
            {
                "case_id": case["case_id"],
                "query": case["query"],
                "intent_summary": case["intent_summary"],
                "matched": not mismatches,
                "mismatches": mismatches,
                "expected": expected,
                "actual": actual,
            }
        )

    passed = sum(result["matched"] for result in results)
    return {
        "cases": len(results),
        "passed": passed,
        "accuracy": passed / len(results),
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate whether the Skill routes reviewed user intents correctly."
    )
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--answer-cases", type=Path, default=ANSWER_CASES_PATH)
    parser.add_argument("--require-cases", type=int, default=30)
    parser.add_argument("--min-accuracy", type=float, default=1.0)
    args = parser.parse_args()

    result = evaluate(args.cases, args.answer_cases)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["cases"] < args.require_cases:
        raise SystemExit(
            f"Only {result['cases']} query-understanding cases; "
            f"requires {args.require_cases}"
        )
    if result["accuracy"] < args.min_accuracy:
        failed_ids = [
            item["case_id"] for item in result["results"] if not item["matched"]
        ]
        raise SystemExit(
            f"Query-understanding accuracy {result['accuracy']:.3f} is below "
            f"{args.min_accuracy:.3f}; failed: {', '.join(failed_ids)}"
        )


if __name__ == "__main__":
    main()
