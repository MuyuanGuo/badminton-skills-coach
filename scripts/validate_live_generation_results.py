#!/usr/bin/env python3
"""Validate reproducible, current-runtime release answers."""

import argparse
import hashlib
import importlib.util
import json
import re
from collections import Counter
from pathlib import Path

from evaluate_forward_test_results import (
    answer_runtime_fingerprint,
    runtime_fingerprint,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS = ROOT / "data" / "evaluation" / "live_generation_results.json"
CASES_PATH = ROOT / "data" / "evaluation" / "answer_quality_cases.json"
CRITICAL_PATH = ROOT / "data" / "evaluation" / "critical_answer_snapshots.json"
DELIVERY_CASES_PATH = (
    ROOT / "data" / "evaluation" / "delivery_release_cases.json"
)
SYSTEMATIC_CASES_PATH = (
    ROOT / "data" / "evaluation" / "runtime_generation_cases.json"
)
CONTEXT_SCRIPT = (
    ROOT
    / "skills"
    / "liuhui-badminton-coach"
    / "scripts"
    / "prepare_answer_context.py"
)
RENDER_SCRIPT = (
    ROOT / "skills" / "liuhui-badminton-coach" / "scripts" / "render_answer.py"
)
AUDIT_SCRIPT = (
    ROOT / "skills" / "liuhui-badminton-coach" / "scripts" / "audit_answer.py"
)
GENERATOR_TYPE = "deterministic_answer_renderer"
VALIDATION_METHOD = "current_runtime_full_context_audit"
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
MINIMUM_SYSTEMATIC_RUNTIME_CASES = 12
REQUIRED_SYSTEMATIC_CASE_TYPES = {
    "technical_action",
    "diagnosis",
    "tactics",
    "training_plan",
    "evidence_boundary",
}
REQUIRED_SYSTEMATIC_ANSWER_MODES = {
    "text_primary",
    "balanced",
    "video_primary",
}


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


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def relative_runtime_path(path, root=ROOT):
    return Path(path).relative_to(Path(root)).as_posix()


def release_case_registry(root=ROOT):
    root = Path(root)
    registry = {
        case["case_id"]: case
        for case in load_json(root / CASES_PATH.relative_to(ROOT))["cases"]
    }
    delivery_payload = load_json(root / DELIVERY_CASES_PATH.relative_to(ROOT))
    if delivery_payload.get("schema_version") != 1:
        raise LiveGenerationValidationError(
            "Delivery release cases have an unsupported schema"
        )
    for case in delivery_payload.get("cases", []):
        case_id = case.get("case_id")
        if not case_id or case_id in registry:
            raise LiveGenerationValidationError(
                "Delivery release case IDs must be present and unique"
            )
        registry[case_id] = case
    return registry


def validate_systematic_case_registry(payload, answer_registry, excluded_ids=()):
    expected_fields = {
        "schema_version",
        "description",
        "minimum_case_count",
        "required_case_types",
        "required_answer_modes",
        "cases",
    }
    if set(payload) != expected_fields or payload.get("schema_version") != 1:
        raise LiveGenerationValidationError(
            "Systematic runtime cases have an unsupported schema"
        )
    minimum = payload.get("minimum_case_count")
    cases = payload.get("cases")
    if (
        not isinstance(minimum, int)
        or isinstance(minimum, bool)
        or minimum < MINIMUM_SYSTEMATIC_RUNTIME_CASES
        or not isinstance(cases, list)
        or len(cases) < minimum
    ):
        raise LiveGenerationValidationError(
            "Systematic runtime generation coverage is underpowered"
        )
    case_ids = []
    covered_types = set()
    covered_modes = set()
    for item in cases:
        if not isinstance(item, dict) or set(item) != {
            "case_id",
            "coverage_reason",
        }:
            raise LiveGenerationValidationError(
                "Systematic runtime case has an invalid schema"
            )
        case_id = item.get("case_id")
        source_case = (
            answer_registry.get(case_id)
            if isinstance(case_id, str)
            else None
        )
        if (
            not isinstance(case_id, str)
            or not case_id
            or source_case is None
            or not isinstance(item.get("coverage_reason"), str)
            or not item["coverage_reason"].strip()
        ):
            raise LiveGenerationValidationError(
                "Systematic runtime case is unknown or undocumented"
            )
        review = source_case.get("review", {})
        if (
            review.get("status") != "maintainer_reviewed"
            or review.get("maintainer_decision") != "approved"
        ):
            raise LiveGenerationValidationError(
                f"Systematic runtime case {case_id} is not maintainer-approved"
            )
        case_ids.append(case_id)
        covered_types.add(source_case.get("case_type"))
        covered_modes.add(source_case.get("expected_mode"))
    if len(case_ids) != len(set(case_ids)):
        raise LiveGenerationValidationError(
            "Systematic runtime case IDs must be unique"
        )
    overlap = set(case_ids) & set(excluded_ids)
    if overlap:
        raise LiveGenerationValidationError(
            "Systematic runtime cases must expand rather than duplicate the "
            "critical release set: " + ", ".join(sorted(overlap))
        )
    required_type_items = payload.get("required_case_types")
    required_mode_items = payload.get("required_answer_modes")
    if (
        not isinstance(required_type_items, list)
        or not required_type_items
        or any(
            not isinstance(item, str) or not item.strip()
            for item in required_type_items
        )
        or not isinstance(required_mode_items, list)
        or not required_mode_items
        or any(
            not isinstance(item, str) or not item.strip()
            for item in required_mode_items
        )
    ):
        raise LiveGenerationValidationError(
            "Systematic runtime coverage dimensions must be non-empty lists"
        )
    required_types = set(required_type_items)
    required_modes = set(required_mode_items)
    if required_types != REQUIRED_SYSTEMATIC_CASE_TYPES:
        raise LiveGenerationValidationError(
            "Systematic runtime cases must require every supported case type"
        )
    if required_modes != REQUIRED_SYSTEMATIC_ANSWER_MODES:
        raise LiveGenerationValidationError(
            "Systematic runtime cases must require every supported answer mode"
        )
    if not required_types.issubset(covered_types):
        raise LiveGenerationValidationError(
            "Systematic runtime cases do not cover every required case type"
        )
    if not required_modes.issubset(covered_modes):
        raise LiveGenerationValidationError(
            "Systematic runtime cases do not cover every required answer mode"
        )
    return set(case_ids)


def required_release_case_ids(root=ROOT):
    root = Path(root)
    historical = {
        item["case_id"]
        for item in load_json(root / CRITICAL_PATH.relative_to(ROOT))[
            "required_cases"
        ]
    }
    delivery = {
        item["case_id"]
        for item in load_json(root / DELIVERY_CASES_PATH.relative_to(ROOT))[
            "cases"
        ]
    }
    registry = release_case_registry(root)
    systematic = validate_systematic_case_registry(
        load_json(root / SYSTEMATIC_CASES_PATH.relative_to(ROOT)),
        registry,
        excluded_ids=historical | delivery,
    )
    return historical | delivery | systematic


def delivery_case_failures(case, context, answer, audit_module):
    if "required_delivery_kind_counts" not in case:
        return []
    failures = []
    actual_kinds = Counter(
        item.get("kind")
        for item in context.get("delivery_contract", {}).get("items", [])
    )
    expected_kinds = Counter(case["required_delivery_kind_counts"])
    if actual_kinds != expected_kinds:
        failures.append("delivery_kind_counts")
    missing_terms = [
        term for term in case.get("required_output_terms", []) if term not in answer
    ]
    if missing_terms:
        failures.append("required_output_terms")
    evidence_units = context.get("question_interpretation", {}).get(
        "query_units", []
    )
    if len(evidence_units) != case.get("required_evidence_unit_count"):
        failures.append("evidence_unit_count")
    expected_constraints = case.get("inherited_constraints", {})
    unit_constraints = context.get("question_interpretation", {}).get(
        "query_unit_constraints", {}
    )
    if expected_constraints and any(
        not all(
            set(values).issubset(set(constraints.get(axis, [])))
            for axis, values in expected_constraints.items()
        )
        for constraints in unit_constraints.values()
    ):
        failures.append("inherited_constraints")
    selected_ids = {
        item.get("video_id") for item in context.get("selected_videos", [])
    }
    if selected_ids & set(case.get("forbidden_selected_video_ids", [])):
        failures.append("forbidden_selected_video")
    for item in context.get("delivery_contract", {}).get("items", []):
        marker = f"[{item['delivery_id']}]"
        mutated = "\n".join(
            line for line in answer.splitlines() if not line.startswith(marker)
        )
        negative = audit_module.audit_answer(case["query"], context, mutated)
        if negative["passed"] or "missing_delivery_item" not in {
            violation["code"] for violation in negative["violations"]
        }:
            failures.append(
                f"negative_control_{item['delivery_id']}"
            )
    return failures


def inspect_generation_snapshot(payload, root=ROOT):
    """Validate immutable generation evidence without claiming freshness."""

    root = Path(root)
    expected_top_level = {
        "schema_version",
        "runtime_fingerprint",
        "answer_runtime_fingerprint",
        "generated_at",
        "generator",
        "validation",
        "cases",
    }
    if set(payload) != expected_top_level or payload.get("schema_version") != 3:
        raise LiveGenerationValidationError(
            "Live-generation results have an unsupported schema"
        )

    reviewed_artifact_fingerprint = payload.get("runtime_fingerprint", "")
    reviewed_answer_fingerprint = payload.get("answer_runtime_fingerprint", "")
    if not SHA256_PATTERN.fullmatch(reviewed_artifact_fingerprint):
        raise LiveGenerationValidationError("Artifact runtime fingerprint is invalid")
    if not SHA256_PATTERN.fullmatch(reviewed_answer_fingerprint):
        raise LiveGenerationValidationError("Answer runtime fingerprint is invalid")
    if not DATE_PATTERN.fullmatch(payload.get("generated_at", "")):
        raise LiveGenerationValidationError("generated_at must use YYYY-MM-DD")

    render_path = root / RENDER_SCRIPT.relative_to(ROOT)
    audit_path = root / AUDIT_SCRIPT.relative_to(ROOT)
    generator = payload.get("generator")
    expected_generator = {
        "type",
        "implementation",
        "implementation_sha256",
    }
    if not isinstance(generator, dict) or set(generator) != expected_generator:
        raise LiveGenerationValidationError("Generator provenance is incomplete")
    if (
        generator["type"] != GENERATOR_TYPE
        or generator["implementation"]
        != relative_runtime_path(render_path, root=root)
        or not SHA256_PATTERN.fullmatch(generator["implementation_sha256"])
    ):
        raise LiveGenerationValidationError(
            "Release answers require the trusted deterministic renderer"
        )

    validation = payload.get("validation")
    expected_validation = {
        "method",
        "implementation",
        "implementation_sha256",
    }
    if not isinstance(validation, dict) or set(validation) != expected_validation:
        raise LiveGenerationValidationError("Validation provenance is incomplete")
    if (
        validation["method"] != VALIDATION_METHOD
        or validation["implementation"]
        != relative_runtime_path(audit_path, root=root)
        or not SHA256_PATTERN.fullmatch(validation["implementation_sha256"])
    ):
        raise LiveGenerationValidationError(
            "Release answers require the trusted full-context auditor"
        )

    current_artifact_fingerprint = runtime_fingerprint(root)
    current_answer_fingerprint = answer_runtime_fingerprint(root)
    registry = release_case_registry(root)
    required_ids = required_release_case_ids(root)
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
    if failures:
        raise LiveGenerationValidationError(
            "Live-generation release gate failed: " + ", ".join(failures)
        )

    artifact_runtime_match = (
        reviewed_artifact_fingerprint == current_artifact_fingerprint
    )
    answer_runtime_match = reviewed_answer_fingerprint == current_answer_fingerprint
    generator_implementation_match = (
        generator["implementation_sha256"] == file_digest(render_path)
    )
    validator_implementation_match = (
        validation["implementation_sha256"] == file_digest(audit_path)
    )
    return {
        "status": "valid_generation_snapshot",
        "current_runtime_match": (
            artifact_runtime_match
            and answer_runtime_match
            and generator_implementation_match
            and validator_implementation_match
        ),
        "current_answer_runtime_match": answer_runtime_match,
        "current_artifact_runtime_match": artifact_runtime_match,
        "generation_answer_runtime_fingerprint": reviewed_answer_fingerprint,
        "current_answer_runtime_fingerprint": current_answer_fingerprint,
        "generation_artifact_runtime_fingerprint": reviewed_artifact_fingerprint,
        "current_artifact_runtime_fingerprint": current_artifact_fingerprint,
        "generator_implementation_match": generator_implementation_match,
        "validator_implementation_match": validator_implementation_match,
        "critical_cases": len(required_ids),
        "generated_answers": len(cases),
        "current_runtime_audits_rerun": False,
        "current_renderer_reproduced": False,
    }


def validate_results(payload, root=ROOT, rerun_runtime=True):
    """Fail closed unless reproducible answers belong to the current runtime."""

    root = Path(root)
    snapshot = inspect_generation_snapshot(payload, root=root)
    if not snapshot["current_answer_runtime_match"]:
        raise LiveGenerationValidationError(
            "Live-generation results are stale for the current answer runtime"
        )
    if not snapshot["current_artifact_runtime_match"]:
        raise LiveGenerationValidationError(
            "Live-generation results are stale for the current artifact runtime"
        )
    if not snapshot["generator_implementation_match"]:
        raise LiveGenerationValidationError(
            "Live-generation results use a stale deterministic renderer"
        )
    if not snapshot["validator_implementation_match"]:
        raise LiveGenerationValidationError(
            "Live-generation results use a stale full-context auditor"
        )

    if rerun_runtime:
        registry = release_case_registry(root)
        context_module = load_module(
            "live_generation_context", root / CONTEXT_SCRIPT.relative_to(ROOT)
        )
        renderer_module = load_module(
            "live_generation_renderer", root / RENDER_SCRIPT.relative_to(ROOT)
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
            rendered_answer = renderer_module.render_answer(packet)
            if rendered_answer != item["answer_text"]:
                failures.append(
                    f"{item['case_id']}:current_renderer_output_mismatch"
                )
                continue
            audit = audit_module.audit_answer(
                expected["query"], context, item["answer_text"]
            )
            if not audit["passed"]:
                failures.append(f"{item['case_id']}:current_runtime_audit_failed")
                continue
            failures.extend(
                f"{item['case_id']}:{failure}"
                for failure in delivery_case_failures(
                    expected,
                    context,
                    item["answer_text"],
                    audit_module,
                )
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
        "automatically_validated": snapshot["critical_cases"],
        "automated_audit_pass_rate": 1.0,
        "current_runtime_audits_rerun": rerun_runtime,
        "current_renderer_reproduced": rerun_runtime,
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
