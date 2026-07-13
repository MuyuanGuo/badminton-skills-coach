#!/usr/bin/env python3
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEARCH_PATH = (
    ROOT
    / "skills"
    / "liuhui-badminton-coach"
    / "scripts"
    / "search_knowledge.py"
)


def load_search_module():
    spec = importlib.util.spec_from_file_location("liuhui_search_test", SEARCH_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SearchKnowledgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.search_module = load_search_module()

    def test_exhaustive_manifest_paginates_without_overlap(self):
        query = "网前框架怎么做才不会身体僵硬"
        first = self.search_module.search(
            query, manifest_offset=0, manifest_limit=5
        )
        second = self.search_module.search(
            query, manifest_offset=5, manifest_limit=5
        )
        self.assertGreater(first["coverage"]["candidate_count"], 5)
        self.assertEqual(first["coverage"]["next_manifest_offset"], 5)
        self.assertEqual(second["coverage"]["manifest_offset"], 5)
        self.assertEqual(second["results"], [])
        self.assertEqual(first["answer_guidance"]["mode"], "balanced")
        self.assertEqual(second["answer_guidance"]["mode"], "balanced")
        first_ids = {item["video_id"] for item in first["candidate_manifest"]}
        second_ids = {item["video_id"] for item in second["candidate_manifest"]}
        self.assertFalse(first_ids & second_ids)

    def test_video_lookup_returns_stored_evidence(self):
        video_id = "7661940775983482097"
        payload = self.search_module.lookup_videos(
            [video_id], query="网前框架身体僵硬"
        )
        self.assertEqual(payload["missing_video_ids"], [])
        self.assertEqual(payload["results"][0]["video_id"], video_id)
        self.assertIn("teaching_note", payload["results"][0])
        self.assertIn("query_match", payload["results"][0])
        self.assertEqual(payload["answer_guidance"]["mode"], "balanced")

    def test_answer_mode_keeps_text_and_video_obligations(self):
        cases = {
            "双打轮转时什么时候补位": "text_primary",
            "杀球动作怎么发力": "balanced",
            "正手握拍应该怎么握": "video_primary",
        }
        for query, expected_mode in cases.items():
            with self.subTest(query=query):
                guidance = self.search_module.classify_answer_mode(query)
                self.assertEqual(guidance["mode"], expected_mode)
                self.assertGreaterEqual(len(guidance["text_obligations"]), 3)
                self.assertGreaterEqual(len(guidance["video_obligations"]), 3)

    def test_search_never_returns_excluded_videos(self):
        payload = self.search_module.search("训练 方法", manifest_limit=None)
        knowledge, _, _ = self.search_module.load_resources()
        excluded_ids = {
            video["video_id"]
            for video in knowledge["videos"]
            if video["processing_status"] in {"not_teaching", "low_value"}
        }
        result_ids = {item["video_id"] for item in payload["candidate_manifest"]}
        self.assertFalse(excluded_ids & result_ids)


if __name__ == "__main__":
    unittest.main()
