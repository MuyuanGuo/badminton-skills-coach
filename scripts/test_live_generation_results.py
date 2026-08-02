#!/usr/bin/env python3
import importlib.util
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "validate_live_generation_results.py"


def load_module():
    spec = importlib.util.spec_from_file_location("live_generation_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LiveGenerationResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def fixture(self):
        case_ids = ["AQ055", "AQ056", "AQ057"]
        registry = self.module.load_json(self.module.CASES_PATH)
        queries = {item["case_id"]: item["query"] for item in registry["cases"]}
        dimensions = self.module.load_json(self.module.QUALITY_RULES_PATH)[
            "manual_dimensions"
        ]
        cases = []
        for case_id in case_ids:
            answer = f"{case_id} generated answer"
            cases.append(
                {
                    "case_id": case_id,
                    "query": queries[case_id],
                    "answer_text": answer,
                    "answer_sha256": self.module.answer_digest(answer),
                    "manual_scores": {dimension: 4 for dimension in dimensions},
                    "verdict": "pass",
                }
            )
        return {
            "schema_version": 2,
            "runtime_fingerprint": "reviewed-artifact",
            "answer_runtime_fingerprint": "current-answer",
            "generated_at": "2026-07-26",
            "generator": {
                "provider": "test",
                "model": "test-model",
                "model_version": "1",
                "task_id": "generator-task",
            },
            "review": {
                "reviewer": "independent-reviewer",
                "reviewed_at": "2026-07-26",
                "independent_from_generator": True,
            },
            "cases": cases,
        }

    def test_valid_independently_reviewed_fixture_passes(self):
        payload = self.fixture()
        with mock.patch.object(
            self.module, "runtime_fingerprint", return_value="current-artifact"
        ), mock.patch.object(
            self.module,
            "answer_runtime_fingerprint",
            return_value="current-answer",
        ):
            result = self.module.validate_results(payload, rerun_runtime=False)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["critical_cases"], 3)
        self.assertFalse(result["artifact_runtime_match"])
        self.assertTrue(result["release_eligible"])

    def test_stale_runtime_is_rejected(self):
        payload = self.fixture()
        with mock.patch.object(
            self.module, "runtime_fingerprint", return_value="current-artifact"
        ), mock.patch.object(
            self.module,
            "answer_runtime_fingerprint",
            return_value="new-answer-runtime",
        ), self.assertRaisesRegex(
            self.module.LiveGenerationValidationError, "stale"
        ):
            self.module.validate_results(payload, rerun_runtime=False)

    def test_stale_snapshot_integrity_is_preserved_without_current_claim(self):
        payload = self.fixture()
        with mock.patch.object(
            self.module, "runtime_fingerprint", return_value="current-artifact"
        ), mock.patch.object(
            self.module,
            "answer_runtime_fingerprint",
            return_value="new-answer-runtime",
        ):
            result = self.module.inspect_review_snapshot(payload)
        self.assertEqual(result["status"], "valid_review_snapshot")
        self.assertFalse(result["current_runtime_match"])
        self.assertEqual(
            result["reviewed_answer_runtime_fingerprint"], "current-answer"
        )
        self.assertEqual(
            result["current_answer_runtime_fingerprint"],
            "new-answer-runtime",
        )
        self.assertFalse(result["current_runtime_audits_rerun"])

    def test_same_generator_and_reviewer_is_rejected(self):
        payload = self.fixture()
        payload["review"]["reviewer"] = payload["generator"]["task_id"]
        with mock.patch.object(
            self.module, "runtime_fingerprint", return_value="current-artifact"
        ), mock.patch.object(
            self.module,
            "answer_runtime_fingerprint",
            return_value="current-answer",
        ), self.assertRaisesRegex(
            self.module.LiveGenerationValidationError, "independent"
        ):
            self.module.validate_results(payload, rerun_runtime=False)

    def test_answer_mutation_and_low_scores_are_rejected(self):
        payload = self.fixture()
        payload["cases"][0]["answer_text"] += " changed"
        payload["cases"][1]["manual_scores"]["technical_correctness"] = 3
        with mock.patch.object(
            self.module, "runtime_fingerprint", return_value="current-artifact"
        ), mock.patch.object(
            self.module,
            "answer_runtime_fingerprint",
            return_value="current-answer",
        ), self.assertRaisesRegex(
            self.module.LiveGenerationValidationError,
            "answer_digest_mismatch.*manual_quality_below_threshold",
        ):
            self.module.validate_results(payload, rerun_runtime=False)


if __name__ == "__main__":
    unittest.main()
