#!/usr/bin/env python3
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "evaluate_answer_quality.py"
APPLY_PATH = ROOT / "scripts" / "apply_answer_quality_review_notes.py"
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
        apply_spec = importlib.util.spec_from_file_location(
            "answer_quality_apply_test_module", APPLY_PATH
        )
        cls.apply_module = importlib.util.module_from_spec(apply_spec)
        apply_spec.loader.exec_module(cls.apply_module)
        cls.rules = cls.module.load_json(RULES_PATH)
        cls.video_id = "7501542236061420859"

    def reviewed_case(self, status="maintainer_reviewed"):
        review = {
            "status": status,
            "maintainer_decision": "approved",
            "maintainer_reviewer": "maintainer",
            "reviewed_at": "2026-07-14",
        }
        return {
            "case_id": "AQ901",
            "query": "双打接发怎么抢主动",
            "case_type": "tactics",
            "expected_mode": "text_primary",
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

    def test_maintainer_reviewed_case_is_regression_ready(self):
        case = self.reviewed_case()
        registry = {"version": 1, "cases": [case]}
        result = self.module.validate_registry(
            registry, self.rules, {self.video_id}
        )
        self.assertEqual(result["regression_ready"], 1)

    def test_draft_case_waits_for_source_review(self):
        case = self.reviewed_case(status="draft")
        case["review"] = {"status": "draft"}
        registry = {"version": 1, "cases": [case]}
        result = self.module.validate_registry(
            registry, self.rules, {self.video_id}
        )
        self.assertEqual(result["regression_ready"], 0)

    def test_rejected_review_never_enters_regression(self):
        case = self.reviewed_case()
        case["review"]["maintainer_decision"] = "rejected"
        registry = {"version": 1, "cases": [case]}
        result = self.module.validate_registry(
            registry, self.rules, {self.video_id}
        )
        self.assertEqual(result["regression_ready"], 0)

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

    def test_partial_snapshot_set_reports_coverage_without_fabricating_answers(self):
        first = self.reviewed_case()
        second = self.reviewed_case()
        second["case_id"] = "AQ902"
        second["query"] = "双打接发如何限制最快线路"
        registry = {"version": 1, "cases": [first, second]}
        result = self.module.evaluate_answers(
            registry,
            {"answers": [self.good_answer()]},
            self.rules,
            {self.video_id},
        )
        self.assertEqual(result["approved_cases"], 2)
        self.assertEqual(result["answers_supplied"], 1)
        self.assertEqual(result["snapshot_coverage"], 0.5)
        self.assertEqual(result["missing_case_ids"], ["AQ902"])
        self.assertEqual(result["automatic_pass_rate"], 1.0)

    def test_critical_snapshot_requirements_are_explicit_and_validated(self):
        registry = {"cases": [self.reviewed_case()]}
        required = self.module.validate_snapshot_requirements(
            {
                "version": 1,
                "required_cases": [
                    {
                        "case_id": "AQ901",
                        "reason": "A real user report exposed this regression.",
                    }
                ],
            },
            registry,
        )
        self.assertEqual(required, {"AQ901"})

        with self.assertRaisesRegex(
            self.module.RegistryValidationError, "unknown case"
        ):
            self.module.validate_snapshot_requirements(
                {
                    "version": 1,
                    "required_cases": [
                        {"case_id": "AQ999", "reason": "Unknown"}
                    ],
                },
                registry,
            )

    def test_source_neutral_url_and_evidence_id_are_supported(self):
        evidence_id = "live:2026-07-21:clip-003"
        case = self.reviewed_case()
        case["gold"]["primary_video_ids"] = [evidence_id]
        case["gold"]["required_video_ids"] = [evidence_id]
        case["gold"]["required_text_points"][0]["evidence_video_ids"] = [
            evidence_id
        ]
        answer = self.good_answer()
        source_url = "https://example.test/live/2026-07-21?t=315"
        answer["answer_text"] = answer["answer_text"].replace(
            "https://www.douyin.com/video/7501542236061420859",
            source_url,
        )
        answer["video_notes"] = [
            {
                "evidence_id": evidence_id,
                "reason": "直接讲解直播中的双打发接发准备优先级",
                "watch_focus": "观察切片内如何覆盖对手最快出球线路",
            }
        ]
        result = self.module.evaluate_case_answer(
            case,
            answer,
            self.rules,
            {evidence_id},
            evidence_urls={source_url: evidence_id},
        )
        self.assertTrue(result["automatic_pass"])
        self.assertEqual(result["linked_video_ids"], [evidence_id])

    def review_markdown(self, data):
        return (
            "## AQ901 · 双打接发怎么抢主动\n\n"
            "### Review notes\n\n"
            "```json\n"
            + json.dumps(data, ensure_ascii=False, indent=2)
            + "\n```\n"
        )

    def approved_review_data(self):
        return {
            "maintainer_decision": "approved",
            "maintainer_reviewer": "maintainer",
            "maintainer_reviewed_at": "2026-07-17",
            "primary_video_ids": [self.video_id],
            "required_video_ids": [self.video_id],
            "irrelevant_video_ids": [],
            "required_text_points": [
                {
                    "description": "优先限制对手最快的回球线路",
                    "acceptable_terms": ["最快的位置", "最快线路"],
                    "evidence_video_ids": [self.video_id],
                }
            ],
            "required_boundary_points": [
                {
                    "description": "不能脱离发球质量和自身能力",
                    "acceptable_terms": ["发球质量", "自身能力"],
                }
            ],
            "forbidden_claims": ["每次都必须扑球"],
            "notes": "已核对来源视频。",
        }

    def test_structured_review_notes_apply_to_registry(self):
        case = self.reviewed_case()
        case["review"] = {"status": "draft"}
        registry = {"version": 1, "cases": [case]}
        updated = self.apply_module.apply_review_markdown(
            self.review_markdown(self.approved_review_data()),
            registry,
            self.rules,
            {self.video_id},
        )
        applied = updated["cases"][0]
        self.assertEqual(applied["review"]["status"], "maintainer_reviewed")
        self.assertEqual(
            applied["gold"]["required_text_points"][0]["point_id"],
            "AQ901-P1",
        )
        self.assertEqual(
            applied["gold"]["required_boundary_points"][0]["point_id"],
            "AQ901-B1",
        )

    def test_legacy_bare_json_review_is_migratable_without_data_loss(self):
        case = self.reviewed_case()
        case["review"] = {"status": "draft"}
        registry = {"version": 1, "cases": [case]}
        data = self.approved_review_data()
        markdown = (
            "## AQ901 · 双打接发怎么抢主动\n\n"
            "### Review notes\n\n"
            + json.dumps(data, ensure_ascii=False, indent=2)
            + "\n"
        )
        blocks = self.apply_module.extract_review_blocks(markdown)
        self.assertEqual(json.loads(blocks["AQ901"]), data)
        updated = self.apply_module.apply_review_markdown(
            markdown, registry, self.rules, {self.video_id}
        )
        self.assertEqual(
            updated["cases"][0]["review"]["status"], "maintainer_reviewed"
        )

    def test_invalid_review_is_rejected_without_mutating_registry(self):
        case = self.reviewed_case()
        case["review"] = {"status": "draft"}
        registry = {"version": 1, "cases": [case]}
        invalid = self.approved_review_data()
        invalid["required_video_ids"] = ["123"]
        with self.assertRaisesRegex(
            self.apply_module.ReviewApplicationError, "invalid video IDs"
        ):
            self.apply_module.apply_review_markdown(
                self.review_markdown(invalid),
                registry,
                self.rules,
                {self.video_id},
            )
        self.assertEqual(registry["cases"][0]["review"]["status"], "draft")


if __name__ == "__main__":
    unittest.main()
