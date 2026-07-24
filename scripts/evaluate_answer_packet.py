#!/usr/bin/env python3
"""Validate compact answer packets against full authoritative contexts."""

import argparse
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "data" / "evaluation" / "answer_packet_cases.json"
RUNTIME_PATH = (
    ROOT
    / "skills"
    / "liuhui-badminton-coach"
    / "scripts"
    / "prepare_answer_context.py"
)
SKILL_PATH = ROOT / "skills" / "liuhui-badminton-coach" / "SKILL.md"


def load_runtime():
    spec = importlib.util.spec_from_file_location("answer_packet_eval", RUNTIME_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def encoded_size(payload):
    return len(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    )


def evaluate(cases_path=CASES_PATH):
    registry = json.loads(Path(cases_path).read_text(encoding="utf-8"))
    if registry.get("schema_version") != 1:
        raise ValueError("unsupported answer packet case schema_version")
    runtime = load_runtime()
    skill_instruction_bytes = len(SKILL_PATH.read_bytes())
    results = []
    for case in registry["cases"]:
        context = runtime.prepare_answer_context(
            case["query"], local_personalization=False
        )
        packet = runtime.build_answer_packet(context, "context.json")
        runtime.validate_answer_packet(packet, context)
        full_bytes = encoded_size(context)
        packet_bytes = encoded_size(packet)
        reduction = 1 - packet_bytes / full_bytes
        results.append(
            {
                "case_id": case["case_id"],
                "full_context_bytes": full_bytes,
                "answer_packet_bytes": packet_bytes,
                "byte_reduction": round(reduction, 6),
                "reviewed_atom_count": len(
                    packet["answer_plan"]["selected_evidence_atoms"]
                ),
                "projection_valid": True,
            }
        )
    average = sum(item["byte_reduction"] for item in results) / len(results)
    minimum = min(item["byte_reduction"] for item in results)
    passed = (
        skill_instruction_bytes <= registry["maximum_skill_instruction_bytes"]
        and average >= registry["minimum_average_byte_reduction"]
        and minimum >= registry["minimum_case_byte_reduction"]
    )
    return {
        "schema_version": 1,
        "cases": len(results),
        "passed": passed,
        "skill_instruction_bytes": skill_instruction_bytes,
        "maximum_skill_instruction_bytes": registry[
            "maximum_skill_instruction_bytes"
        ],
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
