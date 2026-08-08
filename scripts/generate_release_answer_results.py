#!/usr/bin/env python3
"""Generate reproducible release answers for every critical answer case."""

import argparse
import json
from datetime import date
from pathlib import Path

from evaluate_forward_test_results import (
    answer_runtime_fingerprint,
    runtime_fingerprint,
)
from project_artifacts import atomic_write_text
from validate_live_generation_results import (
    AUDIT_SCRIPT,
    CASES_PATH,
    CONTEXT_SCRIPT,
    CRITICAL_PATH,
    DEFAULT_RESULTS,
    GENERATOR_TYPE,
    RENDER_SCRIPT,
    ROOT,
    VALIDATION_METHOD,
    answer_digest,
    file_digest,
    load_json,
    load_module,
    relative_runtime_path,
    validate_results,
)


def build_results(root=ROOT, generated_at=None):
    root = Path(root)
    registry = {
        case["case_id"]: case
        for case in load_json(root / CASES_PATH.relative_to(ROOT))["cases"]
    }
    required_ids = [
        item["case_id"]
        for item in load_json(root / CRITICAL_PATH.relative_to(ROOT))[
            "required_cases"
        ]
    ]
    context_path = root / CONTEXT_SCRIPT.relative_to(ROOT)
    render_path = root / RENDER_SCRIPT.relative_to(ROOT)
    audit_path = root / AUDIT_SCRIPT.relative_to(ROOT)
    context_module = load_module("release_generation_context", context_path)
    renderer_module = load_module("release_generation_renderer", render_path)
    audit_module = load_module("release_generation_audit", audit_path)

    cases = []
    failures = []
    for case_id in required_ids:
        case = registry[case_id]
        query = case["query"]
        context = context_module.prepare_answer_context(
            query, local_personalization=False
        )
        packet = context_module.build_answer_packet(context)
        context_module.validate_answer_packet(packet, context)
        answer = renderer_module.render_answer(packet)
        audit = audit_module.audit_answer(query, context, answer)
        if not audit["passed"]:
            failures.append(f"{case_id}:current_runtime_audit_failed")
        cases.append(
            {
                "case_id": case_id,
                "query": query,
                "answer_text": answer,
                "answer_sha256": answer_digest(answer),
            }
        )
    if failures:
        raise ValueError("Release answer generation failed: " + ", ".join(failures))

    payload = {
        "schema_version": 3,
        "runtime_fingerprint": runtime_fingerprint(root),
        "answer_runtime_fingerprint": answer_runtime_fingerprint(root),
        "generated_at": generated_at or date.today().isoformat(),
        "generator": {
            "type": GENERATOR_TYPE,
            "implementation": relative_runtime_path(render_path, root=root),
            "implementation_sha256": file_digest(render_path),
        },
        "validation": {
            "method": VALIDATION_METHOD,
            "implementation": relative_runtime_path(audit_path, root=root),
            "implementation_sha256": file_digest(audit_path),
        },
        "cases": cases,
    }
    validate_results(payload, root=root, rerun_runtime=True)
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--generated-at")
    args = parser.parse_args()
    try:
        payload = build_results(generated_at=args.generated_at)
        atomic_write_text(
            args.output,
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise SystemExit(str(error)) from error
    print(
        json.dumps(
            {
                "status": "generated",
                "output": str(args.output),
                "cases": len(payload["cases"]),
                "runtime_fingerprint": payload["runtime_fingerprint"],
                "answer_runtime_fingerprint": payload[
                    "answer_runtime_fingerprint"
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
