#!/usr/bin/env python3
"""Run core evaluators once and persist results for report generation."""

import argparse
import json
import sys
from pathlib import Path

import generate_evaluation_report


ROOT = Path(__file__).resolve().parents[1]


def build_payload(root=ROOT, workers=1, timings=None):
    return {
        "schema_version": generate_evaluation_report.EVALUATION_RESULTS_SCHEMA_VERSION,
        "build": generate_evaluation_report.fingerprint_paths(root),
        "evaluations": generate_evaluation_report.collect_evaluations(
            root,
            workers=workers,
            timings=timings,
        ),
    }


def main():
    generate_evaluation_report.ensure_deterministic_hash_seed()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--timings-output", type=Path)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    timings = {}
    payload = build_payload(workers=args.workers, timings=timings)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    timing_payload = {
        "schema_version": 1,
        "workers": args.workers,
        "suites": {
            name: {"duration_seconds": round(timings[name], 3)}
            for name in generate_evaluation_report.EVALUATION_SUITE_ORDER
        },
        "total_suite_seconds": round(sum(timings.values()), 3),
    }
    if args.timings_output:
        args.timings_output.parent.mkdir(parents=True, exist_ok=True)
        args.timings_output.write_text(
            json.dumps(timing_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(timing_payload, ensure_ascii=False), file=sys.stderr)


if __name__ == "__main__":
    main()
