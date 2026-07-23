#!/usr/bin/env python3
"""Validate blind forward-test results against critical answer regressions."""

import argparse
import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESULTS_PATH = ROOT / "data" / "evaluation" / "forward_test_results.json"
CRITICAL_PATH = ROOT / "data" / "evaluation" / "critical_answer_snapshots.json"
CASES_PATH = ROOT / "data" / "evaluation" / "answer_quality_cases.json"
QUERY_CASES_PATH = ROOT / "data" / "evaluation" / "query_understanding_cases.json"
DIAGNOSTIC_CASES_PATH = ROOT / "data" / "evaluation" / "diagnostic_answer_cases.json"
CONTINUATION_CASES_PATH = (
    ROOT / "data" / "evaluation" / "diagnostic_answer_continuation_cases.json"
)
SKILL_ROOT = Path("skills/liuhui-badminton-coach")
MIN_CONSECUTIVE_UNSEEN_ROUNDS = 3
MIN_CASES_PER_UNSEEN_ROUND = 4
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


def normalize_query(query):
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", query.casefold())


def registered_queries(
    cases_payload,
    query_cases_payload,
    diagnostic_cases_payload=None,
    continuation_cases_payload=None,
):
    queries = {
        normalize_query(case["query"])
        for case in cases_payload.get("cases", [])
        if case.get("query")
    }
    queries.update(
        normalize_query(case["query"])
        for case in query_cases_payload.get("cases", [])
        if case.get("query")
    )
    queries.update(
        normalize_query(case["query"])
        for case in (diagnostic_cases_payload or {}).get("cases", [])
        if case.get("query")
    )
    queries.update(
        normalize_query(case["original_query"])
        for case in (continuation_cases_payload or {}).get("cases", [])
        if case.get("original_query")
    )
    return queries


def validate_unseen_rounds(rounds, known_queries):
    if len(rounds) < MIN_CONSECUTIVE_UNSEEN_ROUNDS:
        raise ForwardTestValidationError(
            "At least three consecutive unseen-prompt rounds are required"
        )
    sequences = [round_.get("sequence") for round_ in rounds]
    if sequences != list(range(1, len(rounds) + 1)):
        raise ForwardTestValidationError(
            "Unseen-prompt round sequences must be consecutive and ordered"
        )
    round_ids = [round_.get("round_id") for round_ in rounds]
    if any(not round_id for round_id in round_ids) or len(round_ids) != len(
        set(round_ids)
    ):
        raise ForwardTestValidationError(
            "Unseen-prompt round IDs must be present and unique"
        )

    failures = []
    seen_case_ids = set()
    seen_queries = set()
    unseen_case_count = 0
    round_schema = {
        "round_id",
        "sequence",
        "tested_at",
        "validation_mode",
        "reviewer",
        "independence_disclosure",
        "verdict",
        "cases",
    }
    case_schema = {
        "case_id",
        "query",
        "verdict",
        "reviewed_dimensions",
        "question_interpretation_summary",
        "selected_evidence",
        "review_notes",
    }
    evidence_schema = {"evidence_id", "relevance"}
    for round_ in rounds:
        round_id = round_["round_id"]
        if set(round_) != round_schema:
            raise ForwardTestValidationError(
                f"{round_id} has an invalid unseen-round schema"
            )
        if round_["validation_mode"] != "same_agent_structural_audit":
            failures.append(f"{round_id}:validation_mode_mismatch")
        if round_["verdict"] != "pass":
            failures.append(f"{round_id}:verdict_not_pass")
        if (
            not round_["tested_at"].strip()
            or not round_["reviewer"].strip()
            or not round_["independence_disclosure"].strip()
        ):
            failures.append(f"{round_id}:audit_metadata_missing")
        cases = round_["cases"]
        if len(cases) < MIN_CASES_PER_UNSEEN_ROUND:
            failures.append(f"{round_id}:insufficient_cases")
        for case in cases:
            case_id = case.get("case_id", "<unknown>")
            unseen_case_count += 1
            if set(case) != case_schema:
                raise ForwardTestValidationError(
                    f"{case_id} has an invalid unseen-case schema"
                )
            normalized = normalize_query(case["query"])
            if case_id in seen_case_ids:
                failures.append(f"{case_id}:duplicate_case_id")
            seen_case_ids.add(case_id)
            if not normalized or normalized in known_queries:
                failures.append(f"{case_id}:prompt_not_unseen")
            if normalized in seen_queries:
                failures.append(f"{case_id}:duplicate_prompt")
            seen_queries.add(normalized)
            if case["verdict"] != "pass":
                failures.append(f"{case_id}:verdict_not_pass")
            if set(case["reviewed_dimensions"]) != REQUIRED_REVIEW_DIMENSIONS:
                failures.append(f"{case_id}:review_dimensions_incomplete")
            if (
                not case["question_interpretation_summary"].strip()
                or not case["review_notes"].strip()
            ):
                failures.append(f"{case_id}:review_missing")
            evidence = case["selected_evidence"]
            evidence_ids = []
            if not evidence:
                failures.append(f"{case_id}:selected_evidence_missing")
            for item in evidence:
                if set(item) != evidence_schema:
                    raise ForwardTestValidationError(
                        f"{case_id} has an invalid selected-evidence schema"
                    )
                if not item["evidence_id"].strip() or not item["relevance"].strip():
                    failures.append(f"{case_id}:selected_evidence_incomplete")
                evidence_ids.append(item["evidence_id"])
            if len(evidence_ids) != len(set(evidence_ids)):
                failures.append(f"{case_id}:duplicate_evidence")
    if failures:
        raise ForwardTestValidationError(
            "Unseen-prompt quality gate failed: " + ", ".join(failures)
        )
    return {
        "unseen_rounds": len(rounds),
        "unseen_cases": unseen_case_count,
        "consecutive_passes": len(rounds),
    }


def validate_forward_results(
    payload,
    critical_payload,
    cases_payload,
    query_cases_payload,
    fingerprint,
    diagnostic_cases_payload=None,
    continuation_cases_payload=None,
):
    if payload.get("version") != 3:
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
    unseen_summary = validate_unseen_rounds(
        payload.get("unseen_rounds", []),
        registered_queries(
            cases_payload,
            query_cases_payload,
            diagnostic_cases_payload,
            continuation_cases_payload,
        ),
    )
    return {
        "runtime_fingerprint": fingerprint,
        "critical_cases": len(critical_ids),
        "blind_passes": len(results),
        "failed": [],
        **unseen_summary,
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
        load_json(QUERY_CASES_PATH),
        fingerprint,
        load_json(DIAGNOSTIC_CASES_PATH),
        load_json(CONTINUATION_CASES_PATH),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
