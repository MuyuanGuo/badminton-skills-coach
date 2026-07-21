#!/usr/bin/env python3
"""Evaluate semantic invariants across paraphrase and symptom-query families."""

import argparse
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "data" / "evaluation" / "query_equivalence_cases.json"
CONTEXT_PATH = (
    ROOT
    / "skills"
    / "liuhui-badminton-coach"
    / "scripts"
    / "prepare_answer_context.py"
)


def load_context_module():
    spec = importlib.util.spec_from_file_location(
        "liuhui_query_equivalence_context", CONTEXT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_registry(path=CASES_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_registry(registry):
    if registry.get("version") != 2:
        raise ValueError("query-equivalence registry version is unsupported")
    families = registry.get("families", [])
    if not families:
        raise ValueError("query-equivalence registry has no families")
    family_ids = []
    for family in families:
        required = {
            "family_id",
            "description",
            "expected_target_actor",
            "canonical_target_action_query",
            "expected_constraints_subset",
            "expected_requested_action_scopes",
            "required_shared_selected_video_ids",
            "minimum_shared_selected_video_ids",
            "forbidden_selected_video_ids",
            "variants",
            "negative_controls",
        }
        if set(family) != required:
            raise ValueError(
                f"{family.get('family_id', '<unknown>')} has an invalid schema"
            )
        family_ids.append(family["family_id"])
        if len(family["variants"]) < 2:
            raise ValueError(f"{family['family_id']} needs at least two variants")
        if family["minimum_shared_selected_video_ids"] < 1:
            raise ValueError(f"{family['family_id']} has an invalid overlap threshold")
        for variant in family["variants"]:
            if set(variant) != {
                "query",
                "role",
                "expected_literal_symptoms_contains",
            }:
                raise ValueError(f"{family['family_id']} has an invalid variant")
        for control in family["negative_controls"]:
            if set(control) != {
                "query",
                "expected_target_actor",
                "forbidden_technique_variants",
                "forbidden_action_scopes",
                "forbidden_selected_video_ids",
            }:
                raise ValueError(f"{family['family_id']} has an invalid negative control")
    if len(family_ids) != len(set(family_ids)):
        raise ValueError("query-equivalence family IDs must be unique")
    return families


def _contains_constraint_subset(actual, expected):
    return all(set(values).issubset(actual.get(axis, [])) for axis, values in expected.items())


def evaluate(cases_path=CASES_PATH):
    families = validate_registry(load_registry(cases_path))
    context_module = load_context_module()
    family_results = []
    variant_count = 0
    negative_control_count = 0

    for family in families:
        variants = []
        selected_sets = []
        family_failures = []
        forbidden_selected = set(family["forbidden_selected_video_ids"])
        for variant in family["variants"]:
            payload = context_module.prepare_answer_context(
                variant["query"],
                local_personalization=False,
            )
            interpretation = payload["question_interpretation"]
            actor = interpretation["actor_context"]
            selected_ids = {
                item["video_id"] for item in payload["selected_videos"]
            }
            checks = {
                "target_actor": actor["target_actor"]
                == family["expected_target_actor"],
                "canonical_target_action": actor["target_action_query"]
                == family["canonical_target_action_query"],
                "constraint_subset": _contains_constraint_subset(
                    interpretation["constraints"],
                    family["expected_constraints_subset"],
                ),
                "action_scopes": set(family["expected_requested_action_scopes"])
                == set(actor["requested_action_scopes"]),
                "literal_symptoms_preserved": set(
                    variant["expected_literal_symptoms_contains"]
                ).issubset(interpretation["intent_frame"]["literal_symptoms"]),
                "hard_negatives_excluded": not (selected_ids & forbidden_selected),
            }
            failures = [name for name, passed in checks.items() if not passed]
            if failures:
                family_failures.append(
                    {"query": variant["query"], "failures": failures}
                )
            variants.append(
                {
                    "query": variant["query"],
                    "role": variant["role"],
                    "matched": not failures,
                    "failures": failures,
                    "selected_video_ids": sorted(selected_ids),
                }
            )
            selected_sets.append(selected_ids)
            variant_count += 1

        shared_ids = set.intersection(*selected_sets)
        required_shared = set(family["required_shared_selected_video_ids"])
        if not required_shared.issubset(shared_ids):
            family_failures.append(
                {
                    "invariant": "required_shared_selected_video_ids",
                    "missing": sorted(required_shared - shared_ids),
                }
            )
        if len(shared_ids) < family["minimum_shared_selected_video_ids"]:
            family_failures.append(
                {
                    "invariant": "minimum_shared_selected_video_ids",
                    "actual": len(shared_ids),
                }
            )

        controls = []
        for control in family["negative_controls"]:
            payload = context_module.prepare_answer_context(
                control["query"], local_personalization=False
            )
            interpretation = payload["question_interpretation"]
            actor = interpretation["actor_context"]
            actual_variants = set(
                interpretation["constraints"].get("technique_variant", [])
            )
            actual_scopes = set(actor["requested_action_scopes"])
            selected_ids = {
                item["video_id"] for item in payload["selected_videos"]
            }
            checks = {
                "target_actor": actor["target_actor"]
                == control["expected_target_actor"],
                "technique_variant_not_overgeneralized": not (
                    actual_variants & set(control["forbidden_technique_variants"])
                ),
                "action_scope_not_overgeneralized": not (
                    actual_scopes & set(control["forbidden_action_scopes"])
                ),
                "forbidden_evidence_not_selected": not (
                    selected_ids & set(control["forbidden_selected_video_ids"])
                ),
            }
            failures = [name for name, passed in checks.items() if not passed]
            if failures:
                family_failures.append(
                    {"query": control["query"], "failures": failures}
                )
            controls.append(
                {
                    "query": control["query"],
                    "matched": not failures,
                    "failures": failures,
                    "selected_video_ids": sorted(selected_ids),
                }
            )
            negative_control_count += 1

        family_results.append(
            {
                "family_id": family["family_id"],
                "matched": not family_failures,
                "failures": family_failures,
                "shared_selected_video_ids": sorted(shared_ids),
                "variants": variants,
                "negative_controls": controls,
            }
        )

    failed_families = [
        item["family_id"] for item in family_results if not item["matched"]
    ]
    return {
        "families": len(families),
        "variants": variant_count,
        "negative_controls": negative_control_count,
        "passed_families": len(families) - len(failed_families),
        "failed_families": failed_families,
        "results": family_results,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Validate semantic invariants across related user queries."
    )
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    args = parser.parse_args()
    result = evaluate(args.cases)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["failed_families"]:
        raise SystemExit(
            "Query-equivalence quality gates failed: "
            + ", ".join(result["failed_families"])
        )


if __name__ == "__main__":
    main()
