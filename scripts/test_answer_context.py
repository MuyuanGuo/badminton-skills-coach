#!/usr/bin/env python3
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "evaluate_answer_context.py"


def load_module():
    spec = importlib.util.spec_from_file_location("answer_context_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AnswerContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()
        cls.search_module = cls.module.load_search_module()

    def test_multi_issue_plan_searches_every_subproblem(self):
        case = {
            "query": "双打接发战术和接发握拍应该怎么调整",
        }
        context = self.module.prepare_case_context(self.search_module, case)
        self.assertEqual(
            context["query_units"],
            [
                "双打接发战术",
                "接发握拍应该怎么调整",
            ],
        )
        self.assertIn("握拍", context["retrieval_queries"])
        self.assertIn("7053654124042194215", context["candidate_ids"])

    def test_full_pre_answer_context_registry_passes_quality_gates(self):
        result = self.module.evaluate()
        self.assertEqual(result["cases"], 30)
        self.assertEqual(result["candidate_recall"], 1.0)
        self.assertGreaterEqual(result["selected_video_recall"], 0.95)
        self.assertGreaterEqual(result["primary_selected_rate"], 0.95)
        self.assertEqual(result["answer_mode_accuracy"], 1.0)
        self.assertEqual(result["context_evidence_coverage"], 1.0)
        self.assertEqual(result["hard_negative_selected_violations"], 0)

    def test_boundary_questions_do_not_leak_generic_coaching_videos(self):
        pain = self.module.prepare_case_context(
            self.search_module,
            {"query": "练杀球以后肩膀疼，还能不能继续练"},
        )
        endorsement = self.module.prepare_case_context(
            self.search_module,
            {"query": "你给出的训练建议是不是刘辉本人认可的"},
        )
        self.assertEqual(pain["selected_ids"], [])
        self.assertEqual(endorsement["selected_ids"], [])

    def test_selected_videos_have_stable_contiguous_labels(self):
        context = self.module.prepare_case_context(
            self.search_module,
            {"query": "正手握拍应该怎么握"},
        )["payload"]
        self.assertEqual(
            [item["label"] for item in context["selected_videos"]],
            [
                f"V{index}"
                for index in range(1, len(context["selected_videos"]) + 1)
            ],
        )
        self.assertEqual(
            len({item["video_id"] for item in context["selected_videos"]}),
            len(context["selected_videos"]),
        )


if __name__ == "__main__":
    unittest.main()
