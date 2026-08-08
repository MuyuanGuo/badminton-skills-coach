#!/usr/bin/env python3
"""Measure and enforce runtime latency, memory, and answer-packet budgets."""

import argparse
import importlib.util
import json
import math
import os
import resource
import subprocess
import sys
import time
import tracemalloc
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUDGETS_PATH = ROOT / "config" / "runtime_performance_budgets.json"
CASES_PATH = ROOT / "data" / "evaluation" / "answer_quality_cases.json"
CONTEXT_PATH = (
    ROOT
    / "skills"
    / "liuhui-badminton-coach"
    / "scripts"
    / "prepare_answer_context.py"
)


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def timed_load_context_module():
    started = time.perf_counter()
    spec = importlib.util.spec_from_file_location(
        "liuhui_runtime_benchmark_context", CONTEXT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    elapsed_ms = (time.perf_counter() - started) * 1000
    return module, elapsed_ms


def balanced_queries(cases, cases_per_type):
    queries = []
    counts = defaultdict(int)
    for case in cases:
        case_type = case["case_type"]
        if counts[case_type] >= cases_per_type:
            continue
        queries.append(
            {
                "case_id": case["case_id"],
                "case_type": case_type,
                "query": case["query"],
            }
        )
        counts[case_type] += 1
    return queries


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * fraction) - 1)
    return ordered[index]


def latency_summary(values):
    return {
        "samples": len(values),
        "median_ms": round(percentile(values, 0.5), 3),
        "p95_ms": round(percentile(values, 0.95), 3),
        "max_ms": round(max(values), 3),
    }


def per_query_medians(samples_by_query):
    medians = []
    for samples in samples_by_query:
        if not samples:
            raise ValueError("Every benchmark query requires latency samples")
        medians.append(percentile(samples, 0.5))
    return medians


def json_size(payload):
    return len(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def resident_memory_mb():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes; Linux and the other Unix variants report KiB.
    bytes_value = value if os.uname().sysname == "Darwin" else value * 1024
    return round(bytes_value / (1024 * 1024), 3)


def cold_start_probe(query):
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--child", query],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(completed.stdout)


def benchmark(
    budgets_path=BUDGETS_PATH,
    cases_path=CASES_PATH,
):
    config = load_json(budgets_path)
    benchmark_config = config["benchmark"]
    cases = load_json(cases_path)["cases"]
    queries = balanced_queries(
        cases,
        benchmark_config["cases_per_type"],
    )
    latency_repetitions = benchmark_config.get("latency_repetitions", 1)
    if latency_repetitions < 1 or latency_repetitions % 2 == 0:
        raise ValueError("latency_repetitions must be a positive odd integer")
    expected_query_count = (
        benchmark_config["cases_per_type"]
        * len({case["case_type"] for case in cases})
    )
    if len(queries) != expected_query_count:
        raise ValueError("Performance benchmark cannot balance every answer case type")

    context_module, module_load_ms = timed_load_context_module()
    search_module = context_module.load_search_module()
    for item in queries[: benchmark_config["warmup_queries"]]:
        search_module.plan_query(item["query"])
        search_module.search(
            item["query"],
            manifest_limit=60,
            local_personalization=False,
        )
        context_module.prepare_answer_context(
            item["query"],
            local_personalization=False,
        )

    plan_latencies = []
    search_latencies = []
    context_samples_by_query = [[] for _ in queries]
    packet_reductions = []
    for item in queries:
        started = time.perf_counter()
        search_module.plan_query(item["query"])
        plan_latencies.append((time.perf_counter() - started) * 1000)

        started = time.perf_counter()
        search_module.search(
            item["query"],
            manifest_limit=60,
            local_personalization=False,
        )
        search_latencies.append((time.perf_counter() - started) * 1000)

    for repetition in range(latency_repetitions):
        for query_index, item in enumerate(queries):
            started = time.perf_counter()
            context = context_module.prepare_answer_context(
                item["query"],
                local_personalization=False,
            )
            context_samples_by_query[query_index].append(
                (time.perf_counter() - started) * 1000
            )
            if repetition == 0:
                packet = context_module.build_answer_packet(context)
                context_size = json_size(context)
                packet_size = json_size(packet)
                packet_reductions.append(
                    1 - (packet_size / context_size) if context_size else 0
                )
    context_latencies = per_query_medians(context_samples_by_query)

    tracemalloc.start()
    memory_context_module, _ = timed_load_context_module()
    for item in queries[: benchmark_config["memory_queries"]]:
        memory_context_module.prepare_answer_context(
            item["query"],
            local_personalization=False,
        )
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    cold_results = [
        cold_start_probe(item["query"])
        for item in queries[: benchmark_config.get("cold_start_queries", 2)]
    ]
    result = {
        "schema_version": 1,
        "query_count": len(queries),
        "case_types": sorted({item["case_type"] for item in queries}),
        "latency_sampling": {
            "repetitions_per_query": latency_repetitions,
            "raw_answer_context_samples": sum(
                len(samples) for samples in context_samples_by_query
            ),
            "aggregation": "per_query_median",
        },
        "latency": {
            "module_load": latency_summary([module_load_ms]),
            "query_plan": latency_summary(plan_latencies),
            "search": latency_summary(search_latencies),
            "answer_context": latency_summary(context_latencies),
        },
        "memory": {
            "peak_traced_mb": round(peak_bytes / (1024 * 1024), 3),
            "cold_peak_rss_mb": max(
                (item["peak_rss_mb"] for item in cold_results),
                default=None,
            ),
        },
        "cold_start": {
            "samples": len(cold_results),
            "module_load": latency_summary(
                [item["module_load_ms"] for item in cold_results]
            ),
            "answer_context": latency_summary(
                [item["answer_context_ms"] for item in cold_results]
            ),
        },
        "answer_packet": {
            "minimum_reduction": round(min(packet_reductions), 4),
            "average_reduction": round(
                sum(packet_reductions) / len(packet_reductions),
                4,
            ),
        },
        "budgets": config["budgets"],
    }
    result["violations"] = budget_violations(result)
    result["status"] = "pass" if not result["violations"] else "fail"
    return result


def budget_violations(result):
    budgets = result["budgets"]
    checks = {
        "module_load_p95_ms": (
            result["latency"]["module_load"]["p95_ms"],
            budgets["module_load_p95_ms"],
            "at_most",
        ),
        "query_plan_p95_ms": (
            result["latency"]["query_plan"]["p95_ms"],
            budgets["query_plan_p95_ms"],
            "at_most",
        ),
        "search_p95_ms": (
            result["latency"]["search"]["p95_ms"],
            budgets["search_p95_ms"],
            "at_most",
        ),
        "answer_context_p95_ms": (
            result["latency"]["answer_context"]["p95_ms"],
            budgets["answer_context_p95_ms"],
            "at_most",
        ),
        "peak_traced_memory_mb": (
            result["memory"]["peak_traced_mb"],
            budgets["peak_traced_memory_mb"],
            "at_most",
        ),
        "cold_peak_rss_mb": (
            result["memory"]["cold_peak_rss_mb"],
            budgets["cold_peak_rss_mb"],
            "at_most",
        ),
        "cold_module_load_p95_ms": (
            result["cold_start"]["module_load"]["p95_ms"],
            budgets["cold_module_load_p95_ms"],
            "at_most",
        ),
        "cold_answer_context_p95_ms": (
            result["cold_start"]["answer_context"]["p95_ms"],
            budgets["cold_answer_context_p95_ms"],
            "at_most",
        ),
        "minimum_answer_packet_reduction": (
            result["answer_packet"]["minimum_reduction"],
            budgets["minimum_answer_packet_reduction"],
            "at_least",
        ),
    }
    violations = []
    for metric, (actual, budget, direction) in checks.items():
        passed = actual <= budget if direction == "at_most" else actual >= budget
        if not passed:
            violations.append(
                {
                    "metric": metric,
                    "actual": actual,
                    "budget": budget,
                    "direction": direction,
                }
            )
    return violations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budgets", type=Path, default=BUDGETS_PATH)
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--child", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        module, module_load_ms = timed_load_context_module()
        started = time.perf_counter()
        module.prepare_answer_context(args.child, local_personalization=False)
        print(
            json.dumps(
                {
                    "module_load_ms": round(module_load_ms, 3),
                    "answer_context_ms": round(
                        (time.perf_counter() - started) * 1000, 3
                    ),
                    "peak_rss_mb": resident_memory_mb(),
                }
            )
        )
        return
    result = benchmark(args.budgets, args.cases)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["violations"]:
        raise SystemExit("Runtime performance budgets were exceeded")


if __name__ == "__main__":
    main()
