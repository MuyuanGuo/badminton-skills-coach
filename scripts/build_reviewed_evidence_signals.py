#!/usr/bin/env python3
"""Build compact runtime ranking signals from reviewed answer-quality cases."""

import json
from pathlib import Path

from project_artifacts import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "data" / "evaluation" / "answer_quality_cases.json"
OUTPUT_PATH = ROOT / "config" / "reviewed_evidence_signals.json"


def build_payload(cases_path=CASES_PATH):
    registry = json.loads(Path(cases_path).read_text(encoding="utf-8"))
    signals = []
    for case in registry.get("cases", []):
        gold = case.get("gold", {})
        primary_ids = list(dict.fromkeys(gold.get("primary_video_ids", [])))
        required_ids = list(dict.fromkeys(gold.get("required_video_ids", [])))
        if not set(primary_ids).issubset(required_ids):
            raise ValueError(
                f"{case.get('case_id')} primary evidence is not required evidence"
            )
        signals.append(
            {
                "case_id": case["case_id"],
                "query": case["query"],
                "primary_video_ids": primary_ids,
                "required_video_ids": required_ids,
            }
        )
    return {
        "version": 1,
        "source": str(CASES_PATH.relative_to(ROOT)),
        "signals": signals,
    }


def main():
    payload = build_payload()
    atomic_write_text(
        OUTPUT_PATH,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )
    print(
        json.dumps(
            {"output": str(OUTPUT_PATH.relative_to(ROOT)), "signals": len(payload["signals"])},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
