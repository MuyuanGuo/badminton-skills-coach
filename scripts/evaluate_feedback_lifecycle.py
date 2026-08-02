#!/usr/bin/env python3
"""Audit the machine-enforceable feedback lifecycle and privacy contracts."""

import argparse
import json
from pathlib import Path

import evaluate_feedback_signals


ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = ROOT / "config" / "feedback_rules.json"
SIGNALS_PATH = ROOT / "config" / "feedback_signals.json"
CASES_PATH = ROOT / "data" / "evaluation" / "feedback_relevance_cases.json"
REQUIRED_QUEUE_STATUSES = {
    "pending_review",
    "needs_clarification",
    "accepted",
    "rejected",
    "superseded",
}
PRIVATE_FIELDS = {
    "raw_feedback",
    "question",
    "answer_text",
    "user_context",
    "presented_videos",
}


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def evaluate(
    rules_path=RULES_PATH,
    signals_path=SIGNALS_PATH,
    cases_path=CASES_PATH,
):
    rules = load_json(rules_path)
    signals_payload = load_json(signals_path)
    cases_payload = load_json(cases_path)
    signals = signals_payload.get("signals", [])
    promoted_cases = cases_payload.get("cases", [])
    signals_by_id = {item["signal_id"]: item for item in signals}
    cases_by_id = {item["case_id"]: item for item in promoted_cases}
    leaked_fields = sorted(
        {
            field
            for signal in signals
            for field in PRIVATE_FIELDS
            if field in signal
        }
    )
    missing_provenance = sorted(
        signal["signal_id"]
        for signal in signals
        if not signal.get("source_reference")
        or not signal.get("source_body_sha256")
        or not signal.get("source_reverified_at")
    )
    relevance = evaluate_feedback_signals.evaluate(cases_path)
    checks = {
        "queue_statuses_complete": (
            set(rules.get("queue_statuses", [])) == REQUIRED_QUEUE_STATUSES
        ),
        "promoted_signal_ids_unique": len(signals_by_id) == len(signals),
        "promoted_cases_match_signals": set(signals_by_id) == set(cases_by_id),
        "promoted_payload_has_no_private_fields": not leaked_fields,
        "promoted_sources_are_reverified": not missing_provenance,
        "adversarial_transfer_contracts_pass": (
            relevance["accuracy"] == 1.0
            and relevance["adversarial_contract_checks"] >= 7
        ),
    }
    failures = [name for name, passed in checks.items() if not passed]
    return {
        "status": "pass" if not failures else "fail",
        "queue_statuses": len(rules.get("queue_statuses", [])),
        "promoted_signals": len(signals),
        "promoted_regression_cases": len(promoted_cases),
        "adversarial_contract_checks": relevance["adversarial_contract_checks"],
        "adversarial_contracts_passed": relevance["passed"],
        "contract_accuracy": relevance["accuracy"],
        "leaked_private_fields": leaked_fields,
        "signals_missing_reverified_provenance": missing_provenance,
        "checks": checks,
        "failures": failures,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rules", type=Path, default=RULES_PATH)
    parser.add_argument("--signals", type=Path, default=SIGNALS_PATH)
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    args = parser.parse_args()
    result = evaluate(args.rules, args.signals, args.cases)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["failures"]:
        raise SystemExit(
            "Feedback lifecycle quality gate failed: "
            + ", ".join(result["failures"])
        )


if __name__ == "__main__":
    main()
