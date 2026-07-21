#!/usr/bin/env python3
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "evaluate_forward_test_results.py"


def load_module():
    spec = importlib.util.spec_from_file_location("forward_test_results", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ForwardTestResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def fixtures(self):
        case = {
            "case_id": "AQ901",
            "query": "测试问题",
            "gold": {
                "primary_video_ids": ["source:clip-1"],
                "required_video_ids": ["source:clip-1"],
                "irrelevant_video_ids": ["source:wrong"],
                "required_text_points": [{"point_id": "AQ901-P1"}],
                "required_boundary_points": [{"point_id": "AQ901-B1"}],
                "forbidden_claims": ["错误结论"],
            },
        }
        result = {
            "version": 2,
            "runtime_fingerprint": "fingerprint",
            "results": [
                {
                    "case_id": "AQ901",
                    "query": "测试问题",
                    "tested_at": "2026-07-21",
                    "validation_mode": "blind_fresh_task",
                    "reviewer": "maintainer",
                    "verdict": "pass",
                    "observed_evidence_ids": ["source:clip-1"],
                    "reviewed_dimensions": [
                        "question_interpretation",
                        "evidence_selection",
                        "answer_boundaries",
                        "actionability",
                    ],
                    "review_notes": "目标、证据和边界均正确。",
                    "answer_text": "回答正文，证据 source:clip-1。",
                }
            ],
        }
        critical = {"required_cases": [{"case_id": "AQ901"}]}
        cases = {"cases": [case]}
        return result, critical, cases

    def test_current_blind_result_passes(self):
        result, critical, cases = self.fixtures()
        summary = self.module.validate_forward_results(
            result, critical, cases, "fingerprint"
        )
        self.assertEqual(summary["blind_passes"], 1)

    def test_stale_runtime_fingerprint_fails(self):
        result, critical, cases = self.fixtures()
        with self.assertRaisesRegex(
            self.module.ForwardTestValidationError, "stale"
        ):
            self.module.validate_forward_results(
                result, critical, cases, "new-fingerprint"
            )

    def test_irrelevant_observed_evidence_fails(self):
        result, critical, cases = self.fixtures()
        result["results"][0]["observed_evidence_ids"].append("source:wrong")
        with self.assertRaisesRegex(
            self.module.ForwardTestValidationError, "irrelevant_evidence"
        ):
            self.module.validate_forward_results(
                result, critical, cases, "fingerprint"
            )

    def test_incomplete_review_dimensions_fail(self):
        result, critical, cases = self.fixtures()
        result["results"][0]["reviewed_dimensions"] = [
            "question_interpretation"
        ]
        with self.assertRaisesRegex(
            self.module.ForwardTestValidationError, "review_dimensions_incomplete"
        ):
            self.module.validate_forward_results(
                result, critical, cases, "fingerprint"
            )

    def test_evidence_missing_from_raw_answer_fails(self):
        result, critical, cases = self.fixtures()
        result["results"][0]["answer_text"] = "没有引用来源。"
        with self.assertRaisesRegex(
            self.module.ForwardTestValidationError, "evidence_not_in_answer"
        ):
            self.module.validate_forward_results(
                result, critical, cases, "fingerprint"
            )


if __name__ == "__main__":
    unittest.main()
