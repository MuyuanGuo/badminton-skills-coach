#!/usr/bin/env python3

import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_PATH = ROOT / "scripts" / "evaluate_answer_packet.py"
CASES_PATH = ROOT / "data" / "evaluation" / "answer_packet_cases.json"
SOURCE_CASES_PATH = (
    ROOT / "data" / "evaluation" / "answer_quality_cases.json"
)


def load_evaluator():
    spec = importlib.util.spec_from_file_location(
        "answer_packet_evaluator", EVALUATOR_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AnswerPacketEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evaluator = load_evaluator()
        cls.registry = json.loads(CASES_PATH.read_text(encoding="utf-8"))
        cls.source_registry = json.loads(
            SOURCE_CASES_PATH.read_text(encoding="utf-8")
        )

    def test_registry_reuses_at_least_twenty_approved_queries(self):
        resolved = self.evaluator.resolve_case_registry(
            self.registry, self.source_registry
        )
        self.assertGreaterEqual(len(resolved), 20)
        self.assertEqual(
            len(resolved), self.registry["minimum_case_count"]
        )
        self.assertTrue(all(item["query"].strip() for item in resolved))
        self.assertTrue(
            all(
                set(item) == {"case_id", "source_case_id"}
                for item in self.registry["cases"]
            )
        )

    def test_registry_rejects_an_underpowered_sample(self):
        registry = copy.deepcopy(self.registry)
        registry["cases"] = registry["cases"][:-1]
        with self.assertRaisesRegex(ValueError, "fewer cases"):
            self.evaluator.resolve_case_registry(
                registry, self.source_registry
            )

    def test_registry_rejects_embedded_semantic_gold(self):
        registry = copy.deepcopy(self.registry)
        registry["cases"][0]["gold"] = {"required_text_points": []}
        with self.assertRaisesRegex(ValueError, "only case_id and source_case_id"):
            self.evaluator.resolve_case_registry(
                registry, self.source_registry
            )

    def test_registry_rejects_unreviewed_source_query(self):
        source_registry = copy.deepcopy(self.source_registry)
        source_id = self.registry["cases"][0]["source_case_id"]
        source_case = next(
            item
            for item in source_registry["cases"]
            if item["case_id"] == source_id
        )
        source_case["review"]["maintainer_decision"] = "pending"
        with self.assertRaisesRegex(ValueError, "not maintainer-approved"):
            self.evaluator.resolve_case_registry(
                self.registry, source_registry
            )

    def test_measurement_summary_reports_n_max_and_nearest_rank_p95(self):
        summary = self.evaluator.measurement_summary(list(range(1, 21)))
        self.assertEqual(summary, {"n": 20, "max": 20, "p95": 19})

    def test_p95_limit_cannot_exceed_hard_cap(self):
        registry = copy.deepcopy(self.registry)
        registry["maximum_p95_answer_packet_bytes"] = (
            registry["maximum_answer_packet_bytes"] + 1
        )
        with self.assertRaisesRegex(ValueError, "cannot exceed"):
            self.evaluator.resolve_case_registry(
                registry, self.source_registry
            )


if __name__ == "__main__":
    unittest.main()
