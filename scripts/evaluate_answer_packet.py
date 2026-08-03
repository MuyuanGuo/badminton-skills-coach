#!/usr/bin/env python3
"""Validate compact answer packets against full authoritative contexts."""

import argparse
import importlib.util
import json
import math
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "data" / "evaluation" / "answer_packet_cases.json"
ANSWER_QUALITY_CASES_PATH = (
    ROOT / "data" / "evaluation" / "answer_quality_cases.json"
)
ANSWER_QUALITY_CASES_REFERENCE = "data/evaluation/answer_quality_cases.json"
MEASUREMENT_SCOPE = "answer_packet_projection_size_and_construction"
REQUIRED_MINIMUM_CASE_COUNT = 20
RUNTIME_PATH = (
    ROOT
    / "skills"
    / "liuhui-badminton-coach"
    / "scripts"
    / "prepare_answer_context.py"
)
SKILL_PATH = ROOT / "skills" / "liuhui-badminton-coach" / "SKILL.md"
TOKEN_BUDGET_PATH = (
    ROOT
    / "skills"
    / "liuhui-badminton-coach"
    / "scripts"
    / "token_budget.py"
)


def load_runtime():
    spec = importlib.util.spec_from_file_location("answer_packet_eval", RUNTIME_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_token_budget():
    spec = importlib.util.spec_from_file_location(
        "answer_packet_token_budget", TOKEN_BUDGET_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def encoded_size(payload):
    return len(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    )


def nearest_rank_percentile(values, percentile):
    if not values:
        raise ValueError("cannot summarize an empty measurement set")
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * percentile) - 1)]


def measurement_summary(values):
    if not values:
        raise ValueError("cannot summarize an empty measurement set")
    return {
        "n": len(values),
        "max": max(values),
        "p95": nearest_rank_percentile(values, 0.95),
    }


def resolve_case_registry(registry, source_registry):
    expected_registry_fields = {
        "schema_version",
        "measurement_scope",
        "query_source_registry",
        "minimum_case_count",
        "maximum_skill_instruction_bytes",
        "maximum_skill_instruction_tokens",
        "maximum_answer_packet_bytes",
        "maximum_p95_answer_packet_bytes",
        "maximum_answer_packet_tokens",
        "maximum_p95_answer_packet_tokens",
        "token_estimator",
        "minimum_average_byte_reduction",
        "minimum_case_byte_reduction",
        "cases",
    }
    if set(registry) != expected_registry_fields:
        raise ValueError("answer packet registry contains unexpected fields")
    if registry.get("schema_version") != 2:
        raise ValueError("unsupported answer packet case schema_version")
    if registry.get("measurement_scope") != MEASUREMENT_SCOPE:
        raise ValueError("answer packet measurement_scope is invalid")
    if (
        registry.get("query_source_registry")
        != ANSWER_QUALITY_CASES_REFERENCE
    ):
        raise ValueError("answer packet query source registry is invalid")

    minimum_case_count = registry.get("minimum_case_count")
    if (
        not isinstance(minimum_case_count, int)
        or isinstance(minimum_case_count, bool)
        or minimum_case_count < REQUIRED_MINIMUM_CASE_COUNT
    ):
        raise ValueError(
            "answer packet minimum_case_count must be at least "
            f"{REQUIRED_MINIMUM_CASE_COUNT}"
        )

    cases = registry.get("cases")
    if not isinstance(cases, list) or len(cases) < minimum_case_count:
        raise ValueError(
            "answer packet registry has fewer cases than minimum_case_count"
        )
    if source_registry.get("version") != 1:
        raise ValueError("unsupported answer quality case schema version")
    source_cases = {
        case["case_id"]: case for case in source_registry.get("cases", [])
    }

    resolved = []
    case_ids = []
    source_case_ids = []
    for case in cases:
        if not isinstance(case, dict) or set(case) != {
            "case_id",
            "source_case_id",
        }:
            raise ValueError(
                "answer packet cases must contain only case_id and source_case_id"
            )
        case_id = case["case_id"]
        source_case_id = case["source_case_id"]
        if (
            not isinstance(case_id, str)
            or not case_id
            or not isinstance(source_case_id, str)
            or not source_case_id
        ):
            raise ValueError("answer packet case IDs must be non-empty strings")
        source_case = source_cases.get(source_case_id)
        if source_case is None:
            raise ValueError(
                f"answer packet case {case_id} has an unknown source case"
            )
        review = source_case.get("review", {})
        if (
            review.get("status") != "maintainer_reviewed"
            or review.get("maintainer_decision") != "approved"
        ):
            raise ValueError(
                f"answer packet case {case_id} is not maintainer-approved"
            )
        query = source_case.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError(
                f"answer packet source case {source_case_id} has an empty query"
            )
        case_ids.append(case_id)
        source_case_ids.append(source_case_id)
        resolved.append(
            {
                "case_id": case_id,
                "source_case_id": source_case_id,
                "query": query,
                "case_type": source_case.get("case_type", "unspecified"),
            }
        )

    if len(case_ids) != len(set(case_ids)):
        raise ValueError("answer packet case IDs must be unique")
    if len(source_case_ids) != len(set(source_case_ids)):
        raise ValueError("answer packet source case IDs must be unique")

    positive_limits = [
        "maximum_skill_instruction_bytes",
        "maximum_skill_instruction_tokens",
        "maximum_answer_packet_bytes",
        "maximum_p95_answer_packet_bytes",
        "maximum_answer_packet_tokens",
        "maximum_p95_answer_packet_tokens",
    ]
    if any(
        not isinstance(registry.get(field), int)
        or isinstance(registry.get(field), bool)
        or registry[field] <= 0
        for field in positive_limits
    ):
        raise ValueError("answer packet byte limits must be positive integers")
    if (
        registry["maximum_p95_answer_packet_bytes"]
        > registry["maximum_answer_packet_bytes"]
    ):
        raise ValueError("answer packet P95 limit cannot exceed the hard cap")
    if (
        registry["maximum_p95_answer_packet_tokens"]
        > registry["maximum_answer_packet_tokens"]
    ):
        raise ValueError("answer packet token P95 limit cannot exceed the hard cap")
    if registry.get("token_estimator") != "codex-conservative-unicode-v1":
        raise ValueError("answer packet token estimator is unsupported")
    for field in [
        "minimum_average_byte_reduction",
        "minimum_case_byte_reduction",
    ]:
        value = registry.get(field)
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not 0 <= value <= 1
        ):
            raise ValueError(
                f"answer packet threshold {field} must be between zero and one"
            )
    return resolved


def load_case_registry(cases_path=CASES_PATH):
    registry = json.loads(Path(cases_path).read_text(encoding="utf-8"))
    source_registry = json.loads(
        ANSWER_QUALITY_CASES_PATH.read_text(encoding="utf-8")
    )
    return registry, resolve_case_registry(registry, source_registry)


def evaluate(cases_path=CASES_PATH):
    registry, cases = load_case_registry(cases_path)
    runtime = load_runtime()
    token_budget = load_token_budget()
    skill_instruction_bytes = len(SKILL_PATH.read_bytes())
    skill_instruction_tokens = token_budget.estimate_text_tokens(
        SKILL_PATH.read_text(encoding="utf-8")
    )
    results = []
    for case in cases:
        started = time.perf_counter()
        context = runtime.prepare_answer_context(
            case["query"], local_personalization=False
        )
        packet = runtime.build_answer_packet(context, "context.json")
        runtime.validate_answer_packet(packet, context)
        construction_ms = (time.perf_counter() - started) * 1000
        full_bytes = encoded_size(context)
        packet_bytes = encoded_size(packet)
        full_tokens = token_budget.estimate_json_tokens(context)
        packet_tokens = token_budget.estimate_json_tokens(packet)
        reduction = 1 - packet_bytes / full_bytes
        results.append(
            {
                "case_id": case["case_id"],
                "source_case_id": case["source_case_id"],
                "full_context_bytes": full_bytes,
                "answer_packet_bytes": packet_bytes,
                "full_context_estimated_tokens": full_tokens,
                "answer_packet_estimated_tokens": packet_tokens,
                "case_type": case["case_type"],
                "byte_reduction": round(reduction, 6),
                "construction_ms": round(construction_ms, 3),
                "reviewed_atom_count": len(
                    packet["answer_plan"]["selected_evidence_atoms"]
                ),
                "projection_valid": True,
            }
        )
    average = sum(item["byte_reduction"] for item in results) / len(results)
    minimum = min(item["byte_reduction"] for item in results)
    packet_measurements = measurement_summary(
        [item["answer_packet_bytes"] for item in results]
    )
    construction_measurements = measurement_summary(
        [item["construction_ms"] for item in results]
    )
    packet_token_measurements = measurement_summary(
        [item["answer_packet_estimated_tokens"] for item in results]
    )
    token_measurements_by_case_type = {
        case_type: measurement_summary(
            [
                item["answer_packet_estimated_tokens"]
                for item in results
                if item["case_type"] == case_type
            ]
        )
        for case_type in sorted({item["case_type"] for item in results})
    }
    minimum_case_count = registry["minimum_case_count"]
    hard_cap = registry["maximum_answer_packet_bytes"]
    p95_cap = registry["maximum_p95_answer_packet_bytes"]
    token_hard_cap = registry["maximum_answer_packet_tokens"]
    token_p95_cap = registry["maximum_p95_answer_packet_tokens"]
    sample_count_passed = packet_measurements["n"] >= minimum_case_count
    hard_cap_passed = packet_measurements["max"] <= hard_cap
    p95_passed = packet_measurements["p95"] <= p95_cap
    token_hard_cap_passed = packet_token_measurements["max"] <= token_hard_cap
    token_p95_passed = packet_token_measurements["p95"] <= token_p95_cap
    passed = (
        skill_instruction_bytes <= registry["maximum_skill_instruction_bytes"]
        and skill_instruction_tokens
        <= registry["maximum_skill_instruction_tokens"]
        and sample_count_passed
        and hard_cap_passed
        and p95_passed
        and token_hard_cap_passed
        and token_p95_passed
        and average >= registry["minimum_average_byte_reduction"]
        and minimum >= registry["minimum_case_byte_reduction"]
    )
    return {
        "schema_version": 1,
        "measurement_scope": registry["measurement_scope"],
        "n": packet_measurements["n"],
        "cases": len(results),
        "passed": passed,
        "sample_count_passed": sample_count_passed,
        "hard_cap_passed": hard_cap_passed,
        "p95_passed": p95_passed,
        "token_hard_cap_passed": token_hard_cap_passed,
        "token_p95_passed": token_p95_passed,
        "minimum_case_count": minimum_case_count,
        "skill_instruction_bytes": skill_instruction_bytes,
        "skill_instruction_estimated_tokens": skill_instruction_tokens,
        "maximum_skill_instruction_bytes": registry[
            "maximum_skill_instruction_bytes"
        ],
        "maximum_skill_instruction_tokens": registry[
            "maximum_skill_instruction_tokens"
        ],
        "token_estimator": token_budget.ESTIMATOR_ID,
        "answer_packet_hard_cap_bytes": hard_cap,
        "maximum_answer_packet_bytes": registry[
            "maximum_answer_packet_bytes"
        ],
        "maximum_p95_answer_packet_bytes": registry[
            "maximum_p95_answer_packet_bytes"
        ],
        "answer_packet_maximum_bytes": packet_measurements["max"],
        "answer_packet_p95_bytes": packet_measurements["p95"],
        "maximum_answer_packet_tokens": token_hard_cap,
        "maximum_p95_answer_packet_tokens": token_p95_cap,
        "answer_packet_maximum_estimated_tokens": packet_token_measurements[
            "max"
        ],
        "answer_packet_p95_estimated_tokens": packet_token_measurements[
            "p95"
        ],
        "answer_packet_tokens_by_case_type": token_measurements_by_case_type,
        "construction_maximum_ms": round(
            construction_measurements["max"], 3
        ),
        "construction_p95_ms": round(construction_measurements["p95"], 3),
        "average_byte_reduction": round(average, 6),
        "minimum_byte_reduction": round(minimum, 6),
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    args = parser.parse_args()
    result = evaluate(args.cases)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
