#!/usr/bin/env python3
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "benchmark_runtime.py"


def load_module():
    spec = importlib.util.spec_from_file_location(
        "runtime_benchmark_test", MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RuntimeBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_percentile_uses_nearest_rank(self):
        self.assertEqual(self.module.percentile([1, 2, 3, 4], 0.95), 4)
        self.assertEqual(self.module.percentile([4, 1, 3, 2], 0.5), 2)

    def test_balanced_queries_cover_every_case_type(self):
        cases = self.module.load_json(self.module.CASES_PATH)["cases"]
        queries = self.module.balanced_queries(cases, 2)
        self.assertEqual(len(queries), 10)
        self.assertEqual(len({item["case_type"] for item in queries}), 5)

    def test_budget_violations_report_both_directions(self):
        result = {
            "budgets": {
                "module_load_p95_ms": 10,
                "query_plan_p95_ms": 10,
                "search_p95_ms": 10,
                "answer_context_p95_ms": 10,
                "peak_traced_memory_mb": 10,
                "cold_peak_rss_mb": 10,
                "cold_module_load_p95_ms": 10,
                "cold_answer_context_p95_ms": 10,
                "minimum_answer_packet_reduction": 0.5,
            },
            "latency": {
                key: {"p95_ms": 11}
                for key in (
                    "module_load",
                    "query_plan",
                    "search",
                    "answer_context",
                )
            },
            "cold_start": {
                "module_load": {"p95_ms": 11},
                "answer_context": {"p95_ms": 11},
            },
            "memory": {"peak_traced_mb": 11, "cold_peak_rss_mb": 11},
            "answer_packet": {"minimum_reduction": 0.4},
        }
        violations = self.module.budget_violations(result)
        self.assertEqual(len(violations), 9)


if __name__ == "__main__":
    unittest.main()
