#!/usr/bin/env python3
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "evaluate_retrieval.py"


def load_module():
    spec = importlib.util.spec_from_file_location(
        "evaluate_retrieval_tested", MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RetrievalEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_projected_index_remaps_postings_and_statistics(self):
        index = {
            "indexable_video_count": 3,
            "evidence_fields": ["title"],
            "ngram_vocabulary": ["a", "b"],
            "ngram_postings": [[[0, 1], [2, 4]], [[1, 2]]],
            "term_postings": {"term": [0, 2], "removed": [1]},
            "topic_postings": {"topic": [1, 2]},
            "topics": [{"topic_id": "topic", "video_count": 2}],
            "videos": [
                {"video_id": "one", "field_lengths": {"title": 2}},
                {"video_id": "two", "field_lengths": {"title": 4}},
                {"video_id": "three", "field_lengths": {"title": 6}},
            ],
        }
        projected = self.module.project_retrieval_index(
            index, {"one", "three"}
        )
        self.assertEqual(projected["indexable_video_count"], 2)
        self.assertEqual(
            [item["video_id"] for item in projected["videos"]],
            ["one", "three"],
        )
        self.assertEqual(projected["ngram_postings"], [[[0, 1], [1, 4]]])
        self.assertEqual(projected["term_postings"], {"term": [0, 1]})
        self.assertEqual(projected["topic_postings"], {"topic": [1]})
        self.assertEqual(projected["term_document_frequency"], {"term": 2})
        self.assertEqual(projected["average_field_lengths"], {"title": 4.0})
        self.assertEqual(projected["topics"][0]["video_count"], 1)

    def test_dual_track_keeps_production_observation_and_stable_gate_separate(self):
        result = self.module.evaluate(12)
        stable = result["stable_regression"]
        exposure = result["unjudged_new_source_exposure"]

        self.assertEqual(result["candidate_recall"], 1.0)
        self.assertEqual(result["hard_negative_top_k_violations"], 0)
        self.assertEqual(stable["candidate_recall"], 1.0)
        self.assertEqual(stable["hard_negative_top_k_violations"], 0)
        self.assertGreater(stable["mean_ndcg_at_k"], result["mean_ndcg_at_k"])
        knowledge = json.loads(
            (
                ROOT
                / "data"
                / "knowledge"
                / "douyin_knowledge_base.json"
            ).read_text(encoding="utf-8")
        )
        expected_new_source_videos = sum(
            video.get("processing_status") == "ready"
            and video.get("retrieval_cohort") == "automatic_expansion"
            for video in knowledge["videos"]
        )
        self.assertEqual(
            exposure["candidate_videos"],
            expected_new_source_videos,
        )
        limits = exposure["limits"]
        self.assertLessEqual(
            exposure["top_k_rate"], limits["max_top_k_rate"]
        )
        self.assertLessEqual(
            exposure["max_top_k_per_case"],
            limits["max_top_k_per_case"],
        )
        self.assertLessEqual(
            exposure["review_rate"], limits["max_review_rate"]
        )
        self.assertLessEqual(
            exposure["max_review_per_case"],
            limits["max_review_per_case"],
        )


if __name__ == "__main__":
    unittest.main()
