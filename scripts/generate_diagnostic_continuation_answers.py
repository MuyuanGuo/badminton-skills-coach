#!/usr/bin/env python3
"""Regenerate current-runtime continuation answer snapshots."""

import argparse
import importlib.util
import json
from pathlib import Path

from project_artifacts import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = (
    ROOT / "data/evaluation/diagnostic_answer_continuation_cases.json"
)
RUNTIME_PATH = (
    ROOT
    / "skills/liuhui-badminton-coach/scripts/prepare_answer_context.py"
)
RENDERER_PATH = (
    ROOT / "skills/liuhui-badminton-coach/scripts/render_answer.py"
)
SNAPSHOT_FIELD = "gold_answer_v8"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def regenerate(path=DEFAULT_CASES):
    path = Path(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    runtime = load_module("continuation_answer_runtime", RUNTIME_PATH)
    renderer = load_module("continuation_answer_renderer", RENDERER_PATH)
    for case in payload["cases"]:
        first = runtime.prepare_answer_context(
            case["original_query"], local_personalization=False
        )
        continued = runtime.prepare_answer_context(
            case["reply"],
            local_personalization=False,
            continue_from=first,
            clarification_answers=case.get("answers"),
        )
        packet = runtime.build_answer_packet(continued)
        case[SNAPSHOT_FIELD] = renderer.render_answer(packet)
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    args = parser.parse_args()
    payload = regenerate(args.cases)
    atomic_write_text(
        args.cases,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )
    print(
        json.dumps(
            {
                "status": "generated",
                "cases": len(payload["cases"]),
                "snapshot_field": SNAPSHOT_FIELD,
                "output": str(args.cases),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
