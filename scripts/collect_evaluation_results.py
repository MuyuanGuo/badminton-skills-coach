#!/usr/bin/env python3
"""Run core evaluators once and persist results for report generation."""

import argparse
import json
from pathlib import Path

import generate_evaluation_report


ROOT = Path(__file__).resolve().parents[1]


def build_payload(root=ROOT):
    return {
        "schema_version": generate_evaluation_report.EVALUATION_RESULTS_SCHEMA_VERSION,
        "build": generate_evaluation_report.fingerprint_paths(root),
        "evaluations": generate_evaluation_report.collect_evaluations(root),
    }


def main():
    generate_evaluation_report.ensure_deterministic_hash_seed()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = build_payload()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
