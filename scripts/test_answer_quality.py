#!/usr/bin/env python3
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "evaluate_answer_quality.py"
RULES_PATH = ROOT / "config" / "answer_quality_rules.json"


def load_module():
    spec = importlib.util.spec_from_file_location("answer_quality_test_module", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AnswerQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()
        cls.rules = cls.module.load_json(RULES_PATH)
        cls.video_id = "7501542236061420859"

    def reviewed_case(self, expert_required=False, status="maintainer_reviewed"):
        review = {
            "status": status,
            "maintainer_reviewer": "maintainer",
            "reviewed_at": "2026-07-14",
        }
        if status == "expert_reviewed":
            review["expert_reviewer"] = "coach"
        return {
            "case_id": "AQ901",
            "query": "双打接发怎么抢主动",
            "case_type": "tactics",
            "expected_mode": "text_primary",
            "expert_review_required": expert_required,
            "provenance": "test",
            "review": review,
            "gold": {
                "primary_video_ids": [self.video_id],
                "required_video_ids": [self.video_id],
                "irrelevant_video_ids": [],
                "required_text_points": [
                    {
                        "point_id": "AQ901-P1",
                        "description": "优先限制对手最快的回球线路",
                        "acceptable_terms": ["最快的位置", "最快线路"],
                        "evidence_video_ids": [self.video_id],
                    }
                ],
                "required_boundary_points": [],
                "forbidden_claims": ["每次都必须扑球"],
            },
        }

    def good_answer(self):
        text = (
            "双打接发首先要把注意力放在对手最快的位置和最快线路上，而不是平均防守所有方向。"
            "站位、拍头和启动都应服务于限制最快出球；慢线路真正出现后再调整。"
            "这不是要求每一拍都冒险抢攻，还要结合发球质量、搭档站位和自身启动能力。"
            "核心示范视频：https://www.douyin.com/video/7501542236061420859 。"
            "视频展示了如何根据对方最快回球安排准备方向，并说明了慢线路为何可以稍后处理。"
        )
        return {
            "case_id": "AQ901",
            "answer_mode": "text_primary",
            "answer_text": text,
            "video_notes": [
                {
                    "video_id": self.video_id,
                    "reason": "直接讲解双打发接发的准备优先级",
                    "watch_focus": "观察准备站位如何覆盖对手最快出球线路",
                }
            ],
            "manual_review": {
                "reviewer": "maintainer",
                "scores": {
                    "source_fidelity": 5,
                    "technical_correctness": 4,
                    "coverage": 5,
                    "text_video_allocation": 5,
                    "clarity_and_boundaries": 4,
                },
            },
        }

    def test_reviewed_nonexpert_case_is_regression_ready(self):
        case = self.reviewed_case()
        registry = {"version": 1, "cases": [case]}
        result = self.module.validate_registry(
            registry, self.rules, {self.video_id}
        )
        self.assertEqual(result["regression_ready"], 1)

    def test_expert_required_case_waits_for_expert(self):
        case = self.reviewed_case(expert_required=True)
        registry = {"version": 1, "cases": [case]}
        result = self.module.validate_registry(
            registry, self.rules, {self.video_id}
        )
        self.assertEqual(result["regression_ready"], 0)
        case["review"]["status"] = "expert_reviewed"
        case["review"]["expert_reviewer"] = "coach"
        result = self.module.validate_registry(
            registry, self.rules, {self.video_id}
        )
        self.assertEqual(result["regression_ready"], 1)

    def test_complete_answer_passes_automatic_and_manual_checks(self):
        result = self.module.evaluate_case_answer(
            self.reviewed_case(),
            self.good_answer(),
            self.rules,
            {self.video_id},
            require_manual_review=True,
        )
        self.assertTrue(result["automatic_pass"])
        self.assertTrue(result["manual_pass"])
        self.assertEqual(result["failures"], [])

    def test_missing_evidence_and_text_are_reported(self):
        answer = {
            "case_id": "AQ901",
            "answer_mode": "video_primary",
            "answer_text": "看这个视频就行。",
            "video_notes": [],
        }
        result = self.module.evaluate_case_answer(
            self.reviewed_case(), answer, self.rules, {self.video_id}
        )
        self.assertFalse(result["automatic_pass"])
        self.assertIn("answer_mode_mismatch", result["failures"])
        self.assertIn("text_too_short", result["failures"])
        self.assertIn("required_video_missing", result["failures"])
        self.assertIn("required_text_point_missing", result["failures"])
        self.assertIn("required_video_note_missing", result["failures"])


if __name__ == "__main__":
    unittest.main()
