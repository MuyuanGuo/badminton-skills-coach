#!/usr/bin/env python3
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "evaluate_query_understanding.py"


def load_module():
    spec = importlib.util.spec_from_file_location("query_understanding_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class QueryUnderstandingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_reviewed_registry_routes_all_cases_correctly(self):
        result = self.module.evaluate()
        self.assertEqual(result["reviewed_cases"], 43)
        self.assertEqual(result["adversarial_cases"], 52)
        self.assertEqual(result["cases"], 95)
        self.assertEqual(result["passed"], 95)
        self.assertEqual(result["accuracy"], 1.0)

    def test_negated_positive_topic_is_checked_separately_from_excluded_topic(self):
        registry = self.module.load_json(self.module.CASES_PATH)
        registry["adversarial_cases"][0]["expected_intent"][
            "positive_query_contains"
        ] = ["杀球"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cases.json"
            path.write_text(
                json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            result = self.module.evaluate(path)
        failed = [item for item in result["results"] if not item["matched"]]
        self.assertEqual([item["case_id"] for item in failed], ["QUA001"])
        self.assertIn("positive_query_contains", failed[0]["mismatches"])

    def test_wrong_subproblem_split_is_reported(self):
        registry = self.module.load_json(self.module.CASES_PATH)
        registry["cases"][24]["expected_query_units"] = [
            "双打接发战术和接发握拍应该怎么调整"
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cases.json"
            path.write_text(
                json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            result = self.module.evaluate(path)
        failed = [item for item in result["results"] if not item["matched"]]
        self.assertEqual([item["case_id"] for item in failed], ["AQ025"])
        self.assertEqual(failed[0]["mismatches"], ["query_units"])

    def test_registry_must_cover_every_answer_quality_case(self):
        registry = self.module.load_json(self.module.CASES_PATH)
        registry["cases"] = registry["cases"][:-1]
        answer_registry = self.module.load_json(self.module.ANSWER_CASES_PATH)
        with self.assertRaisesRegex(ValueError, "does not cover: AQ043"):
            self.module.validate_registry(registry, answer_registry)


if __name__ == "__main__":
    unittest.main()
