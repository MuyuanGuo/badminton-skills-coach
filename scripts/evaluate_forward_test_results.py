#!/usr/bin/env python3
"""Validate blind forward-test results against critical answer regressions."""

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESULTS_PATH = ROOT / "data" / "evaluation" / "forward_test_results.json"
CRITICAL_PATH = ROOT / "data" / "evaluation" / "critical_answer_snapshots.json"
CASES_PATH = ROOT / "data" / "evaluation" / "answer_quality_cases.json"
SKILL_ROOT = Path("skills/liuhui-badminton-coach")
REQUIRED_REVIEW_DIMENSIONS = {
    "question_interpretation",
    "evidence_selection",
    "answer_boundaries",
    "actionability",
}


class ForwardTestValidationError(ValueError):
    pass


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def runtime_fingerprint(root=ROOT):
    digest = hashlib.sha256()
    root = Path(root)
    paths = sorted(
        path
        for path in (root / SKILL_ROOT).rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    )
    for path in paths:
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def validate_forward_results(payload, critical_payload, cases_payload, fingerprint):
    if payload.get("version") != 2:
        raise ForwardTestValidationError("Forward-test result version is unsupported")
    if payload.get("runtime_fingerprint") != fingerprint:
        raise ForwardTestValidationError(
            "Forward-test results are stale for the current Skill runtime"
        )
    critical_ids = {
        item["case_id"] for item in critical_payload.get("required_cases", [])
    }
    cases = {case["case_id"]: case for case in cases_payload.get("cases", [])}
    results = payload.get("results", [])
    result_ids = [item.get("case_id") for item in results]
    if len(result_ids) != len(set(result_ids)):
        raise ForwardTestValidationError("Forward-test case IDs must be unique")
    if set(result_ids) != critical_ids:
        missing = sorted(critical_ids - set(result_ids))
        extra = sorted(set(result_ids) - critical_ids)
        raise ForwardTestValidationError(
            f"Forward-test coverage mismatch; missing={missing}, extra={extra}"
        )

    failures = []
    for result in results:
        if set(result) != {
            "case_id",
            "query",
            "tested_at",
            "validation_mode",
            "reviewer",
            "verdict",
            "observed_evidence_ids",
            "reviewed_dimensions",
            "review_notes",
            "answer_text",
        }:
            raise ForwardTestValidationError(
                f"{result.get('case_id', '<unknown>')} has an invalid result schema"
            )
        case = cases.get(result["case_id"])
        if not case or result["query"] != case["query"]:
            failures.append(f"{result['case_id']}:query_mismatch")
            continue
        if result["validation_mode"] != "blind_fresh_task":
            failures.append(f"{result['case_id']}:not_blind")
        if result["verdict"] != "pass":
            failures.append(f"{result['case_id']}:verdict_not_pass")
        if (
            not result["reviewer"].strip()
            or not result["review_notes"].strip()
            or not result["answer_text"].strip()
        ):
            failures.append(f"{result['case_id']}:review_missing")
        observed_ids = result["observed_evidence_ids"]
        observed = set(observed_ids)
        if len(observed_ids) != len(observed):
            failures.append(f"{result['case_id']}:duplicate_evidence")
        if any(evidence_id not in result["answer_text"] for evidence_id in observed):
            failures.append(f"{result['case_id']}:evidence_not_in_answer")
        gold = case["gold"]
        if not set(gold["required_video_ids"]).issubset(observed):
            failures.append(f"{result['case_id']}:required_evidence_missing")
        if observed & set(gold["irrelevant_video_ids"]):
            failures.append(f"{result['case_id']}:irrelevant_evidence_observed")
        if set(result["reviewed_dimensions"]) != REQUIRED_REVIEW_DIMENSIONS:
            failures.append(f"{result['case_id']}:review_dimensions_incomplete")
        if any(
            claim.casefold() in result["answer_text"].casefold()
            for claim in gold["forbidden_claims"]
        ):
            failures.append(f"{result['case_id']}:forbidden_claim_present")
    if failures:
        raise ForwardTestValidationError(
            "Forward-test quality gate failed: " + ", ".join(failures)
        )
    return {
        "runtime_fingerprint": fingerprint,
        "critical_cases": len(critical_ids),
        "blind_passes": len(results),
        "failed": [],
    }


def main():
    parser = argparse.ArgumentParser(
        description="Validate blind forward tests for the current Skill runtime."
    )
    parser.add_argument("--results", type=Path, default=RESULTS_PATH)
    parser.add_argument("--print-fingerprint", action="store_true")
    args = parser.parse_args()
    fingerprint = runtime_fingerprint()
    if args.print_fingerprint:
        print(fingerprint)
        return
    result = validate_forward_results(
        load_json(args.results),
        load_json(CRITICAL_PATH),
        load_json(CASES_PATH),
        fingerprint,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
