#!/usr/bin/env python3
"""Validate independently reviewed, current-runtime answer generations for release."""

import argparse
import hashlib
import importlib.util
import json
import re
from pathlib import Path

from evaluate_forward_test_results import (
    answer_runtime_fingerprint,
    runtime_fingerprint,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS = ROOT / "data" / "evaluation" / "live_generation_results.json"
CASES_PATH = ROOT / "data" / "evaluation" / "answer_quality_cases.json"
CRITICAL_PATH = ROOT / "data" / "evaluation" / "critical_answer_snapshots.json"
QUALITY_RULES_PATH = ROOT / "config" / "answer_quality_rules.json"
CONTEXT_SCRIPT = (
    ROOT
    / "skills"
    / "liuhui-badminton-coach"
    / "scripts"
    / "prepare_answer_context.py"
)
AUDIT_SCRIPT = (
    ROOT / "skills" / "liuhui-badminton-coach" / "scripts" / "audit_answer.py"
)
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")


class LiveGenerationValidationError(ValueError):
    pass


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def answer_digest(answer):
    return hashlib.sha256(answer.encode("utf-8")).hexdigest()


def inspect_review_snapshot(payload, root=ROOT):
    """Validate immutable review evidence without claiming runtime freshness."""

    root = Path(root)
    expected_top_level = {
        "schema_version",
        "runtime_fingerprint",
        "answer_runtime_fingerprint",
        "generated_at",
        "generator",
        "review",
        "cases",
    }
    if set(payload) != expected_top_level or payload.get("schema_version") != 2:
        raise LiveGenerationValidationError(
            "Live-generation results have an unsupported schema"
        )
    current_artifact_fingerprint = runtime_fingerprint(root)
    current_answer_fingerprint = answer_runtime_fingerprint(root)
    if not DATE_PATTERN.fullmatch(payload.get("generated_at", "")):
        raise LiveGenerationValidationError("generated_at must use YYYY-MM-DD")
    generator = payload.get("generator")
    if not isinstance(generator, dict) or set(generator) != {
        "provider",
        "model",
        "model_version",
        "task_id",
    }:
        raise LiveGenerationValidationError("Generator provenance is incomplete")
    if not all(str(value).strip() for value in generator.values()):
        raise LiveGenerationValidationError("Generator provenance contains empty values")
    review = payload.get("review")
    if not isinstance(review, dict) or set(review) != {
        "reviewer",
        "reviewed_at",
        "independent_from_generator",
    }:
        raise LiveGenerationValidationError("Independent review metadata is incomplete")
    if (
        not str(review["reviewer"]).strip()
        or not DATE_PATTERN.fullmatch(review["reviewed_at"])
        or review["independent_from_generator"] is not True
        or review["reviewer"] == generator["task_id"]
    ):
        raise LiveGenerationValidationError(
            "Release generations require a named independent reviewer"
        )

    registry = {case["case_id"]: case for case in load_json(root / CASES_PATH.relative_to(ROOT))["cases"]}
    required_ids = {
        item["case_id"]
        for item in load_json(root / CRITICAL_PATH.relative_to(ROOT))["required_cases"]
    }
    rules = load_json(root / QUALITY_RULES_PATH.relative_to(ROOT))
    dimensions = set(rules["manual_dimensions"])
    passing = rules["manual_score_scale"]["passing"]
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise LiveGenerationValidationError("cases must be a list")
    supplied_ids = [item.get("case_id") for item in cases if isinstance(item, dict)]
    if len(supplied_ids) != len(set(supplied_ids)) or set(supplied_ids) != required_ids:
        raise LiveGenerationValidationError(
            "Live-generation cases must exactly cover the critical release set"
        )

    failures = []
    for item in cases:
        if set(item) != {
            "case_id",
            "query",
            "answer_text",
            "answer_sha256",
            "manual_scores",
            "verdict",
        }:
            raise LiveGenerationValidationError(
                f"{item.get('case_id', '<unknown>')} has an invalid case schema"
            )
        case_id = item["case_id"]
        expected = registry.get(case_id)
        answer = item.get("answer_text")
        if not expected or item.get("query") != expected["query"]:
            failures.append(f"{case_id}:query_mismatch")
        if not isinstance(answer, str) or not answer.strip():
            failures.append(f"{case_id}:answer_missing")
            continue
        if item.get("answer_sha256") != answer_digest(answer):
            failures.append(f"{case_id}:answer_digest_mismatch")
        scores = item.get("manual_scores")
        if (
            not isinstance(scores, dict)
            or set(scores) != dimensions
            or any(
                not isinstance(score, int) or score < passing or score > 5
                for score in scores.values()
            )
        ):
            failures.append(f"{case_id}:manual_quality_below_threshold")
        if item.get("verdict") != "pass":
            failures.append(f"{case_id}:verdict_not_pass")
    if failures:
        raise LiveGenerationValidationError(
            "Live-generation release gate failed: " + ", ".join(failures)
        )
    return {
        "status": "valid_review_snapshot",
        "current_runtime_match": (
            payload["answer_runtime_fingerprint"] == current_answer_fingerprint
        ),
        "reviewed_answer_runtime_fingerprint": payload[
            "answer_runtime_fingerprint"
        ],
        "current_answer_runtime_fingerprint": current_answer_fingerprint,
        "reviewed_artifact_runtime_fingerprint": payload["runtime_fingerprint"],
        "current_artifact_runtime_fingerprint": current_artifact_fingerprint,
        "artifact_runtime_match": (
            payload["runtime_fingerprint"] == current_artifact_fingerprint
        ),
        "critical_cases": len(required_ids),
        "independently_reviewed": len(cases),
        "current_runtime_audits_rerun": False,
    }


def validate_results(payload, root=ROOT, rerun_runtime=True):
    """Fail closed unless independent review belongs to the current runtime."""

    root = Path(root)
    snapshot = inspect_review_snapshot(payload, root=root)
    if not snapshot["current_runtime_match"]:
        raise LiveGenerationValidationError(
            "Live-generation results are stale for the current answer runtime"
        )

    if rerun_runtime:
        registry = {
            case["case_id"]: case
            for case in load_json(root / CASES_PATH.relative_to(ROOT))["cases"]
        }
        context_module = load_module(
            "live_generation_context", root / CONTEXT_SCRIPT.relative_to(ROOT)
        )
        audit_module = load_module(
            "live_generation_audit", root / AUDIT_SCRIPT.relative_to(ROOT)
        )
        failures = []
        for item in payload["cases"]:
            expected = registry[item["case_id"]]
            context = context_module.prepare_answer_context(
                expected["query"], local_personalization=False
            )
            packet = context_module.build_answer_packet(context)
            context_module.validate_answer_packet(packet, context)
            audit = audit_module.audit_answer(
                expected["query"], context, item["answer_text"]
            )
            if not audit["passed"]:
                failures.append(
                    f"{item['case_id']}:current_runtime_audit_failed"
                )
        if failures:
            raise LiveGenerationValidationError(
                "Live-generation release gate failed: " + ", ".join(failures)
            )

    return {
        **snapshot,
        "status": "pass",
        "runtime_fingerprint": snapshot["current_answer_runtime_fingerprint"],
        "current_runtime_match": True,
        "release_eligible": True,
        "current_runtime_audits_rerun": rerun_runtime,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--skip-runtime-rerun", action="store_true")
    args = parser.parse_args()
    try:
        result = validate_results(
            load_json(args.results), rerun_runtime=not args.skip_runtime_rerun
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
