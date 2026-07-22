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
            "version": 3,
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
            "unseen_rounds": [
                self.unseen_round(1),
                self.unseen_round(2),
                self.unseen_round(3),
            ],
        }
        critical = {"required_cases": [{"case_id": "AQ901"}]}
        cases = {"cases": [case]}
        query_cases = {"cases": []}
        return result, critical, cases, query_cases

    def unseen_round(self, sequence):
        return {
            "round_id": f"I{sequence}",
            "sequence": sequence,
            "tested_at": "2026-07-21",
            "validation_mode": "same_agent_structural_audit",
            "reviewer": "maintainer",
            "independence_disclosure": "Same-agent audit; not independent review.",
            "verdict": "pass",
            "cases": [
                {
                    "case_id": f"I{sequence}-{index:02d}",
                    "query": f"未见测试问题 {sequence}-{index}",
                    "verdict": "pass",
                    "reviewed_dimensions": [
                        "question_interpretation",
                        "evidence_selection",
                        "answer_boundaries",
                        "actionability",
                    ],
                    "question_interpretation_summary": "正确识别目标动作。",
                    "selected_evidence": [
                        {
                            "evidence_id": f"source:{sequence}-{index}",
                            "relevance": "直接支持目标动作。",
                        }
                    ],
                    "review_notes": "意图、证据、边界和可执行目标均通过。",
                }
                for index in range(1, 5)
            ],
        }

    def test_current_blind_result_passes(self):
        result, critical, cases, query_cases = self.fixtures()
        summary = self.module.validate_forward_results(
            result, critical, cases, query_cases, "fingerprint"
        )
        self.assertEqual(summary["blind_passes"], 1)
        self.assertEqual(summary["unseen_rounds"], 3)
        self.assertEqual(summary["unseen_cases"], 12)

    def test_stale_runtime_fingerprint_fails(self):
        result, critical, cases, query_cases = self.fixtures()
        with self.assertRaisesRegex(
            self.module.ForwardTestValidationError, "stale"
        ):
            self.module.validate_forward_results(
                result, critical, cases, query_cases, "new-fingerprint"
            )

    def test_irrelevant_observed_evidence_fails(self):
        result, critical, cases, query_cases = self.fixtures()
        result["results"][0]["observed_evidence_ids"].append("source:wrong")
        with self.assertRaisesRegex(
            self.module.ForwardTestValidationError, "irrelevant_evidence"
        ):
            self.module.validate_forward_results(
                result, critical, cases, query_cases, "fingerprint"
            )

    def test_incomplete_review_dimensions_fail(self):
        result, critical, cases, query_cases = self.fixtures()
        result["results"][0]["reviewed_dimensions"] = [
            "question_interpretation"
        ]
        with self.assertRaisesRegex(
            self.module.ForwardTestValidationError, "review_dimensions_incomplete"
        ):
            self.module.validate_forward_results(
                result, critical, cases, query_cases, "fingerprint"
            )

    def test_evidence_missing_from_raw_answer_fails(self):
        result, critical, cases, query_cases = self.fixtures()
        result["results"][0]["answer_text"] = "没有引用来源。"
        with self.assertRaisesRegex(
            self.module.ForwardTestValidationError, "evidence_not_in_answer"
        ):
            self.module.validate_forward_results(
                result, critical, cases, query_cases, "fingerprint"
            )

    def test_two_unseen_rounds_fail(self):
        result, critical, cases, query_cases = self.fixtures()
        result["unseen_rounds"] = result["unseen_rounds"][:2]
        with self.assertRaisesRegex(
            self.module.ForwardTestValidationError, "At least three"
        ):
            self.module.validate_forward_results(
                result, critical, cases, query_cases, "fingerprint"
            )

    def test_registered_prompt_is_not_unseen(self):
        result, critical, cases, query_cases = self.fixtures()
        query_cases["cases"].append(
            {"case_id": "QUA999", "query": "未见测试问题 1-1"}
        )
        with self.assertRaisesRegex(
            self.module.ForwardTestValidationError, "prompt_not_unseen"
        ):
            self.module.validate_forward_results(
                result, critical, cases, query_cases, "fingerprint"
            )

    def test_unseen_round_review_dimensions_are_required(self):
        result, critical, cases, query_cases = self.fixtures()
        result["unseen_rounds"][0]["cases"][0]["reviewed_dimensions"] = [
            "question_interpretation"
        ]
        with self.assertRaisesRegex(
            self.module.ForwardTestValidationError, "review_dimensions_incomplete"
        ):
            self.module.validate_forward_results(
                result, critical, cases, query_cases, "fingerprint"
            )


if __name__ == "__main__":
    unittest.main()
