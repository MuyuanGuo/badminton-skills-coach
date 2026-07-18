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
            query,
            manifest_offset=0,
            manifest_limit=5,
            local_personalization=False,
        )
        second = self.search_module.search(
            query,
            manifest_offset=5,
            manifest_limit=5,
            local_personalization=False,
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

    def test_balanced_mode_stops_at_its_cap_while_exhaustive_continues(self):
        query = "网前框架怎么做才不会身体僵硬"
        balanced = self.search_module.search(
            query,
            recall_mode="balanced",
            manifest_offset=40,
            manifest_limit=20,
            local_personalization=False,
        )
        exhaustive = self.search_module.search(
            query,
            recall_mode="exhaustive",
            manifest_offset=40,
            manifest_limit=20,
            local_personalization=False,
        )
        self.assertEqual(balanced["coverage"]["accessible_candidate_count"], 60)
        self.assertTrue(balanced["coverage"]["selection_truncated"])
        self.assertIsNone(balanced["coverage"]["next_manifest_offset"])
        self.assertGreater(
            exhaustive["coverage"]["accessible_candidate_count"],
            balanced["coverage"]["accessible_candidate_count"],
        )
        self.assertEqual(exhaustive["coverage"]["next_manifest_offset"], 60)
        self.assertFalse(exhaustive["coverage"]["selection_truncated"])

    def test_invalid_manifest_arguments_fail_fast(self):
        with self.assertRaisesRegex(ValueError, "non-negative"):
            self.search_module.search("握拍", manifest_offset=-1)
        with self.assertRaisesRegex(ValueError, "positive"):
            self.search_module.search("握拍", manifest_limit=0)

    def test_video_lookup_returns_stored_evidence(self):
        video_id = "7661940775983482097"
        payload = self.search_module.lookup_videos(
            [video_id],
            query="网前框架身体僵硬",
            local_personalization=False,
        )
        self.assertEqual(payload["missing_video_ids"], [])
        self.assertEqual(payload["results"][0]["video_id"], video_id)
        self.assertIn("teaching_note", payload["results"][0])
        self.assertIn("summary", payload["results"][0]["teaching_note"])
        self.assertIn("evidence", payload["results"][0]["teaching_note"])
        self.assertIn("query_match", payload["results"][0])
        self.assertIn("quality", payload["results"][0])
        self.assertIn("retrieval_summary", payload["results"][0])
        self.assertNotIn("transcript_ngrams", str(payload["results"][0]))
        self.assertGreater(
            payload["results"][0]["retrieval_summary"]["transcript_ngram_count"],
            0,
        )
        self.assertEqual(payload["answer_guidance"]["mode"], "balanced")

    def test_video_lookup_debug_is_explicit(self):
        video_id = "7661940775983482097"
        payload = self.search_module.lookup_videos(
            [video_id],
            query="网前框架",
            local_personalization=False,
            debug=True,
        )
        result = payload["results"][0]
        self.assertIn("debug_retrieval_index", result)
        self.assertIn("transcript_ngrams", result["debug_retrieval_index"])
        self.assertIn("debug_ranked_candidate", result)
        self.assertIn("debug_stored_teaching_note", result)

    def test_compact_lookup_merges_duplicate_evidence_without_dropping_roles(self):
        video_id = "7060717442825309480"
        payload = self.search_module.lookup_videos(
            [video_id],
            query="反手击球",
            local_personalization=False,
        )
        evidence = payload["results"][0]["teaching_note"]["evidence"]
        markers = [(item["timestamp"], item["text"]) for item in evidence]
        self.assertEqual(len(markers), len(set(markers)))
        self.assertTrue(any(len(item["roles"]) > 1 for item in evidence))

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

    def test_query_plan_routes_systematic_learning_through_topic_navigation(self):
        plan = self.search_module.plan_query("我想从零开始系统学习双打轮转")
        guidance = plan["retrieval_guidance"]
        self.assertEqual(guidance["strategy"], "topic_first_systematic")
        self.assertTrue(guidance["use_topic_navigation"])
        self.assertTrue(guidance["require_exhaustive_completion"])
        self.assertEqual(guidance["query_units"], [])

    def test_query_plan_splits_distinct_subproblems(self):
        plan = self.search_module.plan_query("杀球总下网，而且回动不及时")
        guidance = plan["retrieval_guidance"]
        self.assertEqual(guidance["strategy"], "split_multi_issue")
        self.assertEqual(guidance["query_units"], ["杀球总下网", "回动不及时"])
        self.assertTrue(guidance["require_exhaustive_completion"])

    def test_query_plan_splits_distinct_subproblems_joined_by_and(self):
        plan = self.search_module.plan_query("双打接发战术和接发握拍应该怎么调整")
        guidance = plan["retrieval_guidance"]
        self.assertEqual(guidance["strategy"], "split_multi_issue")
        self.assertEqual(
            guidance["query_units"], ["双打接发战术", "接发握拍应该怎么调整"]
        )

    def test_query_plan_keeps_relational_and_query_together(self):
        plan = self.search_module.plan_query("吊球和杀球怎么配合")
        guidance = plan["retrieval_guidance"]
        self.assertEqual(guidance["strategy"], "focused_evidence")
        self.assertEqual(guidance["query_units"], ["吊球和杀球怎么配合"])

    def test_query_plan_puts_safety_boundary_before_retrieval(self):
        plan = self.search_module.plan_query("练杀球以后肩膀疼，还能不能继续练")
        guidance = plan["retrieval_guidance"]
        self.assertEqual(guidance["strategy"], "boundary_first")
        self.assertTrue(guidance["must_state_boundary_first"])

    def test_query_plan_puts_text_only_action_claim_behind_evidence_boundary(self):
        plan = self.search_module.plan_query(
            "只看文字说明，能不能确认我的正手握拍完全正确"
        )
        guidance = plan["retrieval_guidance"]
        self.assertEqual(plan["answer_guidance"]["mode"], "video_primary")
        self.assertEqual(guidance["strategy"], "boundary_first")
        self.assertTrue(guidance["must_state_boundary_first"])

    def test_query_plan_keeps_focused_questions_focused(self):
        plan = self.search_module.plan_query("正手握拍应该怎么握")
        guidance = plan["retrieval_guidance"]
        self.assertEqual(guidance["strategy"], "focused_evidence")
        self.assertFalse(guidance["use_topic_navigation"])
        self.assertEqual(guidance["query_units"], ["正手握拍应该怎么握"])

    def test_search_never_returns_excluded_videos(self):
        payload = self.search_module.search(
            "训练 方法",
            manifest_limit=None,
            local_personalization=False,
        )
        knowledge, _, _ = self.search_module.load_resources()
        excluded_ids = {
            video["video_id"]
            for video in knowledge["videos"]
            if video["processing_status"] in {"not_teaching", "low_value"}
        }
        result_ids = {item["video_id"] for item in payload["candidate_manifest"]}
        self.assertFalse(excluded_ids & result_ids)

    def test_kill_power_query_ranks_specific_evidence_above_generic_training(self):
        payload = self.search_module.search(
            "杀球不重没有威胁怎么办",
            manifest_limit=None,
            local_personalization=False,
        )
        self.assertEqual(payload["results"][0]["video_id"], "7659348110628345210")
        recovery = next(
            item
            for item in payload["candidate_manifest"]
            if item["video_id"] == "7432633273060314408"
        )
        self.assertNotEqual(recovery["relevance_tier"], "direct")

    def test_single_concept_query_has_a_bounded_review_set(self):
        payload = self.search_module.search(
            "正手握拍应该怎么握",
            manifest_limit=None,
            local_personalization=False,
        )
        self.assertLessEqual(payload["coverage"]["review_candidate_count"], 24)
        self.assertLessEqual(payload["coverage"]["tier_counts"].get("direct", 0), 20)

    def test_pain_intent_does_not_promote_generic_kill_videos(self):
        payload = self.search_module.search(
            "练杀球以后肩膀疼，还能不能继续练",
            manifest_limit=None,
            local_personalization=False,
        )
        self.assertLessEqual(payload["coverage"]["review_candidate_count"], 4)
        self.assertEqual(payload["coverage"]["tier_counts"].get("direct", 0), 0)
        reviewable = [
            item
            for item in payload["candidate_manifest"]
            if item["relevance_tier"] in {"direct", "strong_related"}
        ]
        self.assertTrue(reviewable)
        self.assertTrue(
            all("pain_or_injury" in item["matched_required_intents"] for item in reviewable)
        )
        self.assertIn(
            "pain_or_injury",
            payload["results"][0]["matched_required_intents"],
        )

    def test_screening_tags_are_not_ranked_as_evidence_fields(self):
        video = {
            "title": "网前框架",
            "category": "网前技术",
            "tags": ["握拍与基本动作"],
            "teaching_note": {"topic": "网前框架"},
        }
        score, terms, fields = self.search_module.match_fields(
            video,
            {"握拍": 1.0},
            {"title": 4.0, "category": 0.75, "teaching_note": 1.5},
        )
        self.assertEqual(score, 0.0)
        self.assertEqual(terms, [])
        self.assertEqual(fields, {})


if __name__ == "__main__":
    unittest.main()
