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
        case_ids = sorted(self.module.required_release_case_ids())
        registry = self.module.release_case_registry()
        queries = {case_id: item["query"] for case_id, item in registry.items()}
        cases = []
        for case_id in case_ids:
            answer = f"{case_id} generated answer"
            cases.append(
                {
                    "case_id": case_id,
                    "query": queries[case_id],
                    "answer_text": answer,
                    "answer_sha256": self.module.answer_digest(answer),
                }
            )
        render_path = self.module.RENDER_SCRIPT
        audit_path = self.module.AUDIT_SCRIPT
        return {
            "schema_version": 3,
            "runtime_fingerprint": "a" * 64,
            "answer_runtime_fingerprint": "b" * 64,
            "generated_at": "2026-08-03",
            "generator": {
                "type": self.module.GENERATOR_TYPE,
                "implementation": self.module.relative_runtime_path(render_path),
                "implementation_sha256": self.module.file_digest(render_path),
            },
            "validation": {
                "method": self.module.VALIDATION_METHOD,
                "implementation": self.module.relative_runtime_path(audit_path),
                "implementation_sha256": self.module.file_digest(audit_path),
            },
            "cases": cases,
        }

    def test_valid_current_runtime_fixture_passes_without_rerun(self):
        payload = self.fixture()
        with mock.patch.object(
            self.module, "runtime_fingerprint", return_value="a" * 64
        ), mock.patch.object(
            self.module,
            "answer_runtime_fingerprint",
            return_value="b" * 64,
        ):
            result = self.module.validate_results(payload, rerun_runtime=False)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["critical_cases"], 20)
        self.assertTrue(result["release_eligible"])
        self.assertEqual(result["automatically_validated"], 20)
        self.assertFalse(result["current_runtime_audits_rerun"])

    def test_systematic_runtime_registry_is_balanced_and_nonduplicative(self):
        answer_registry = self.module.release_case_registry()
        payload = self.module.load_json(self.module.SYSTEMATIC_CASES_PATH)
        historical_and_delivery = (
            self.module.required_release_case_ids()
            - {item["case_id"] for item in payload["cases"]}
        )
        case_ids = self.module.validate_systematic_case_registry(
            payload,
            answer_registry,
            excluded_ids=historical_and_delivery,
        )
        self.assertEqual(len(case_ids), 12)
        self.assertTrue(case_ids.isdisjoint(historical_and_delivery))

        underpowered = {**payload, "cases": payload["cases"][:-1]}
        with self.assertRaisesRegex(
            self.module.LiveGenerationValidationError,
            "underpowered",
        ):
            self.module.validate_systematic_case_registry(
                underpowered,
                answer_registry,
            )

        malformed_dimensions = {
            **payload,
            "required_case_types": "technical_action",
        }
        with self.assertRaisesRegex(
            self.module.LiveGenerationValidationError,
            "coverage dimensions",
        ):
            self.module.validate_systematic_case_registry(
                malformed_dimensions,
                answer_registry,
            )

        incomplete_dimensions = {
            **payload,
            "required_answer_modes": payload["required_answer_modes"][:-1],
        }
        with self.assertRaisesRegex(
            self.module.LiveGenerationValidationError,
            "every supported answer mode",
        ):
            self.module.validate_systematic_case_registry(
                incomplete_dimensions,
                answer_registry,
            )

    def test_stale_answer_runtime_is_rejected(self):
        payload = self.fixture()
        with mock.patch.object(
            self.module, "runtime_fingerprint", return_value="a" * 64
        ), mock.patch.object(
            self.module,
            "answer_runtime_fingerprint",
            return_value="c" * 64,
        ), self.assertRaisesRegex(
            self.module.LiveGenerationValidationError, "answer runtime"
        ):
            self.module.validate_results(payload, rerun_runtime=False)

    def test_stale_artifact_runtime_is_rejected(self):
        payload = self.fixture()
        with mock.patch.object(
            self.module, "runtime_fingerprint", return_value="c" * 64
        ), mock.patch.object(
            self.module,
            "answer_runtime_fingerprint",
            return_value="b" * 64,
        ), self.assertRaisesRegex(
            self.module.LiveGenerationValidationError, "artifact runtime"
        ):
            self.module.validate_results(payload, rerun_runtime=False)

    def test_stale_snapshot_integrity_is_preserved_without_current_claim(self):
        payload = self.fixture()
        with mock.patch.object(
            self.module, "runtime_fingerprint", return_value="c" * 64
        ), mock.patch.object(
            self.module,
            "answer_runtime_fingerprint",
            return_value="d" * 64,
        ):
            result = self.module.inspect_generation_snapshot(payload)
        self.assertEqual(result["status"], "valid_generation_snapshot")
        self.assertFalse(result["current_runtime_match"])
        self.assertEqual(
            result["generation_answer_runtime_fingerprint"], "b" * 64
        )
        self.assertEqual(result["current_answer_runtime_fingerprint"], "d" * 64)
        self.assertFalse(result["current_runtime_audits_rerun"])

    def test_untrusted_generator_is_rejected(self):
        payload = self.fixture()
        payload["generator"]["type"] = "untrusted_generator"
        with mock.patch.object(
            self.module, "runtime_fingerprint", return_value="a" * 64
        ), mock.patch.object(
            self.module,
            "answer_runtime_fingerprint",
            return_value="b" * 64,
        ), self.assertRaisesRegex(
            self.module.LiveGenerationValidationError,
            "trusted deterministic renderer",
        ):
            self.module.validate_results(payload, rerun_runtime=False)

    def test_answer_mutation_is_rejected(self):
        payload = self.fixture()
        payload["cases"][0]["answer_text"] += " changed"
        with mock.patch.object(
            self.module, "runtime_fingerprint", return_value="a" * 64
        ), mock.patch.object(
            self.module,
            "answer_runtime_fingerprint",
            return_value="b" * 64,
        ), self.assertRaisesRegex(
            self.module.LiveGenerationValidationError,
            "answer_digest_mismatch",
        ):
            self.module.validate_results(payload, rerun_runtime=False)


if __name__ == "__main__":
    unittest.main()
