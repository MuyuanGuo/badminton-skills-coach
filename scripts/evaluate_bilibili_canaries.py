#!/usr/bin/env python3
"""Validate Bilibili retrieval, claim-window admission, and packet projection."""

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "data" / "evaluation" / "bilibili_canary_cases.json"
SKILL_SCRIPTS = ROOT / "skills" / "liuhui-badminton-coach" / "scripts"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def evaluate(cases_path=CASES_PATH):
    registry = json.loads(Path(cases_path).read_text(encoding="utf-8"))
    if registry.get("schema_version") != 2:
        raise ValueError("Unsupported Bilibili positive-gold schema")
    cases = registry.get("cases")
    if (
        not isinstance(cases, list)
        or len(cases) < registry.get("minimum_case_count", 30)
        or registry.get("runtime_use_forbidden") is not True
    ):
        raise ValueError("Bilibili positive gold is underpowered or not isolated")
    if any(
        set(case) != {"id", "query", "expected_evidence_id", "review"}
        or case.get("review", {}).get("status") != "source_reviewed"
        or case.get("review", {}).get("basis")
        != "transcript_and_title_alignment"
        or not str(case.get("expected_evidence_id", "")).startswith("bilibili:")
        for case in cases
    ):
        raise ValueError("Bilibili positive gold contains an unreviewed case")
    thresholds = registry["thresholds"]
    search = load_module(
        "bilibili_canary_search",
        SKILL_SCRIPTS / "search_knowledge.py",
    )
    context_runtime = load_module(
        "bilibili_canary_context",
        SKILL_SCRIPTS / "prepare_answer_context.py",
    )
    results = []
    failures = []
    for case in cases:
        query = case["query"]
        expected = case["expected_evidence_id"]
        retrieval = search.search(
            query,
            limit=thresholds["retrieval_top_k"],
            local_personalization=False,
        )
        top_ids = [item["video_id"] for item in retrieval["results"]]
        context = context_runtime.prepare_answer_context(
            query,
            local_personalization=False,
        )
        mapped = [
            evidence
            for claim in context["claim_evidence_map"]
            for evidence in claim.get("evidence", [])
            if evidence.get("evidence_id") == expected
        ]
        packet = context_runtime.build_answer_packet(context)
        packet_video = next(
            (
                item
                for item in packet["selected_videos"]
                if item.get("evidence_id") == expected
            ),
            None,
        )
        packet_bytes = len(
            json.dumps(packet, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        )
        case_failures = []
        if expected not in top_ids:
            case_failures.append("expected_evidence_not_in_top_k")
        if not mapped:
            case_failures.append("expected_evidence_not_mapped_to_claim")
        elif max(
            int(item.get("window_support", {}).get("rank") or 0)
            for item in mapped
        ) < thresholds["minimum_claim_window_rank"]:
            case_failures.append("claim_window_quality_below_threshold")
        packet_window_ids = (
            packet_video.get("window_ids", []) if packet_video else []
        )
        if (
            not packet_window_ids
            or any(
                window_id not in packet.get("evidence_windows", {})
                for window_id in packet_window_ids
            )
        ):
            case_failures.append("expected_evidence_missing_from_packet")
        if packet_bytes > thresholds["maximum_packet_bytes"]:
            case_failures.append("packet_exceeds_absolute_byte_budget")
        result = {
            "id": case["id"],
            "query": query,
            "expected_evidence_id": expected,
            "retrieval_top_ids": top_ids,
            "claim_mapped": bool(mapped),
            "packet_window_count": len(packet_window_ids),
            "packet_bytes": packet_bytes,
            "failures": case_failures,
        }
        results.append(result)
        failures.extend(
            {"case_id": case["id"], "reason": reason}
            for reason in case_failures
        )
    pass_rate = (len(results) - len({item["case_id"] for item in failures})) / max(1, len(results))
    report = {
        "schema_version": 2,
        "measurement_type": "source_reviewed_positive_retrieval_gold",
        "runtime_use_forbidden": True,
        "source_type": "bilibili_video",
        "case_count": len(results),
        "passed": pass_rate >= thresholds["minimum_pass_rate"],
        "pass_rate": round(pass_rate, 6),
        "retrieval_hit_rate_at_k": round(
            sum(item["expected_evidence_id"] in item["retrieval_top_ids"] for item in results)
            / max(1, len(results)),
            6,
        ),
        "claim_mapping_rate": round(
            sum(item["claim_mapped"] for item in results) / max(1, len(results)),
            6,
        ),
        "failure_count": len(failures),
        "thresholds": thresholds,
        "results": results,
        "failures": failures,
    }
    return report


def main():
    try:
        report = evaluate()
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
