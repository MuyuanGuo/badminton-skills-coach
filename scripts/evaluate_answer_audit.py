#!/usr/bin/env python3
"""Evaluate the final-answer auditor against maintained gold cases."""

import argparse
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "data" / "evaluation" / "answer_audit_cases.json"
AUDITOR_PATH = ROOT / "scripts" / "audit_answer.py"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_auditor():
    spec = importlib.util.spec_from_file_location("answer_audit_evaluator", AUDITOR_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def evaluate(cases_path=CASES_PATH):
    payload = load_json(cases_path)
    auditor = load_auditor()
    results = []
    expected_violation_count = 0
    detected_expected_violations = 0
    for case in payload["cases"]:
        context = payload["contexts"][case["context_id"]]
        answer = payload["answers"][case["answer_id"]]
        question = case.get(
            "question",
            context.get("answer_turn_contract", {}).get(
                "original_query", context["query"]
            ),
        )
        audit = auditor.audit_answer(question, context, answer)
        actual_codes = {item["code"] for item in audit["violations"]}
        expected_codes = set(case.get("expected_violation_codes_contains", []))
        expected_violation_count += len(expected_codes)
        detected_expected_violations += len(expected_codes & actual_codes)
        mismatches = []
        if audit["passed"] != case["expected_pass"]:
            mismatches.append("expected_pass")
        if not expected_codes.issubset(actual_codes):
            mismatches.append("expected_violation_codes_contains")
        forbidden = set(case.get("expected_violation_codes_excludes", []))
        if forbidden & actual_codes:
            mismatches.append("expected_violation_codes_excludes")
        results.append(
            {
                "case_id": case["case_id"],
                "matched": not mismatches,
                "expected_pass": case["expected_pass"],
                "actual_pass": audit["passed"],
                "violation_codes": sorted(actual_codes),
                "mismatches": mismatches,
            }
        )
    passed = sum(item["matched"] for item in results)
    return {
        "cases": len(results),
        "passed": passed,
        "accuracy": passed / len(results) if results else 0.0,
        "expected_violations": expected_violation_count,
        "expected_violations_detected": detected_expected_violations,
        "violation_detection_rate": (
            detected_expected_violations / expected_violation_count
            if expected_violation_count
            else 1.0
        ),
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    args = parser.parse_args()
    result = evaluate(args.cases)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["passed"] != result["cases"]:
        raise SystemExit("Final-answer audit regression")


if __name__ == "__main__":
    main()
