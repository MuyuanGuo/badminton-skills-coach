#!/usr/bin/env python3
"""Evaluate mechanical Bilibili wiring canaries against the current Skill."""

import argparse
import importlib.util
import json
from collections import Counter
from pathlib import Path

from bilibili_wiring_canary import evaluate_registry


ROOT = Path(__file__).resolve().parents[1]
SKILL_SCRIPTS = ROOT / "skills" / "liuhui-badminton-coach" / "scripts"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registry", type=Path)
    parser.add_argument(
        "--details-output",
        type=Path,
        help="Optionally persist the complete per-case result JSON.",
    )
    args = parser.parse_args()
    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    search = load_module(
        "bilibili_mechanical_canary_search",
        SKILL_SCRIPTS / "search_knowledge.py",
    )
    context_runtime = load_module(
        "bilibili_mechanical_canary_context",
        SKILL_SCRIPTS / "prepare_answer_context.py",
    )
    result = evaluate_registry(registry, search, context_runtime)
    if args.details_output:
        from project_artifacts import atomic_write_text

        atomic_write_text(
            args.details_output,
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        )
    summary = {
        key: value
        for key, value in result.items()
        if key not in {"results", "failures"}
    }
    summary["surface_disposition_counts"] = dict(
        sorted(
            Counter(
                item["retrieval_surface_disposition"]
                for item in result["results"]
            ).items()
        )
    )
    summary["transcript_anchor_probe_lookup_passed"] = sum(
        item["transcript_anchor_probe_lookup_hit"]
        for item in result["results"]
    )
    summary["failure_count"] = len(result["failures"])
    summary["failures"] = result["failures"]
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if result["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
