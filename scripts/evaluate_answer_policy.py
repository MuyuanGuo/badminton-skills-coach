#!/usr/bin/env python3
import argparse
import importlib.util
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "data" / "evaluation" / "answer_modality_cases.json"
SEARCH_PATH = (
    ROOT
    / "skills"
    / "liuhui-badminton-coach"
    / "scripts"
    / "search_knowledge.py"
)


def load_search_module():
    spec = importlib.util.spec_from_file_location("liuhui_answer_policy", SEARCH_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def evaluate(cases_path=CASES_PATH):
    cases = json.loads(cases_path.read_text(encoding="utf-8"))["cases"]
    search_module = load_search_module()
    rules = search_module.load_answer_rules()
    results = []
    correct = 0
    for case in cases:
        guidance = search_module.classify_answer_mode(case["query"], rules)
        matched = guidance["mode"] == case["expected_mode"]
        correct += matched
        results.append(
            {
                "query": case["query"],
                "expected_mode": case["expected_mode"],
                "actual_mode": guidance["mode"],
                "matched": matched,
            }
        )

    mode_contracts_complete = all(
        len(config["text_obligations"]) >= 3
        and len(config["video_obligations"]) >= 3
        for config in rules["modes"].values()
    )
    global_contract_complete = (
        len(rules["global_obligations"]) >= 5
        and any("禁止只返回视频链接" in item for item in rules["global_obligations"])
        and any("全部确认直接相关" in item for item in rules["global_obligations"])
    )
    return {
        "cases": len(cases),
        "correct": correct,
        "accuracy": correct / len(cases),
        "expected_mode_counts": dict(
            Counter(case["expected_mode"] for case in cases)
        ),
        "mode_contracts_complete": mode_contracts_complete,
        "global_contract_complete": global_contract_complete,
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate text/video answer allocation for the Skill."
    )
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--min-accuracy", type=float, default=1.0)
    args = parser.parse_args()
    result = evaluate(args.cases)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["accuracy"] < args.min_accuracy:
        raise SystemExit(
            f"Answer-mode accuracy {result['accuracy']:.3f} is below "
            f"{args.min_accuracy:.3f}"
        )
    if not result["mode_contracts_complete"]:
        raise SystemExit("One or more answer modes are missing text/video obligations")
    if not result["global_contract_complete"]:
        raise SystemExit("Global answer contract is incomplete")


if __name__ == "__main__":
    main()
