#!/usr/bin/env python3
"""Build compact runtime priors only from promoted operational feedback."""

import json
from pathlib import Path

from project_artifacts import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
PRIORS_PATH = ROOT / "data" / "review" / "retrieval_priors.json"
OUTPUT_PATH = ROOT / "config" / "reviewed_evidence_signals.json"


def build_payload(priors_path=PRIORS_PATH):
    registry = json.loads(Path(priors_path).read_text(encoding="utf-8"))
    if (
        registry.get("registry_type")
        != "operational_feedback_runtime_prior"
        or registry.get("evaluation_case_ids_forbidden") is not True
    ):
        raise ValueError("runtime priors must be isolated from evaluation gold")
    signals = []
    for signal in registry.get("signals", []):
        primary_ids = list(dict.fromkeys(signal.get("primary_video_ids", [])))
        required_ids = list(dict.fromkeys(signal.get("required_video_ids", [])))
        if not set(primary_ids).issubset(required_ids):
            raise ValueError(
                f"{signal.get('signal_id')} primary evidence is not required evidence"
            )
        signal_id = signal.get("signal_id")
        if (
            not isinstance(signal_id, str)
            or not signal_id.startswith("OPF-")
            or any(key in signal for key in ("case_id", "source_case_id"))
        ):
            raise ValueError("runtime prior IDs must be operational-feedback IDs")
        signals.append(
            {
                "signal_id": signal_id,
                "query": signal["query"],
                "primary_video_ids": primary_ids,
                "required_video_ids": required_ids,
            }
        )
    return {
        "version": 3,
        "registry_type": "operational_feedback_runtime_prior",
        "evaluation_case_ids_forbidden": True,
        "source": str(priors_path.relative_to(ROOT)),
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
