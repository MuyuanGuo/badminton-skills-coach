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

    def test_programmatic_default_manifest_is_bounded_and_paginated(self):
        payload = self.search_module.search(
            "网前框架怎么做才不会身体僵硬",
            local_personalization=False,
        )
        cap = self.search_module.load_resources()[2]["retrieval"][
            "balanced_manifest_limit"
        ]
        self.assertTrue(payload["coverage"]["default_manifest_limit_applied"])
        self.assertLessEqual(len(payload["candidate_manifest"]), cap)
        self.assertEqual(
            payload["coverage"]["next_manifest_offset"],
            len(payload["candidate_manifest"]),
        )

        exhaustive = self.search_module.search(
            "网前框架怎么做才不会身体僵硬",
            manifest_limit=None,
            local_personalization=False,
        )
        self.assertFalse(
            exhaustive["coverage"]["default_manifest_limit_applied"]
        )
        self.assertEqual(
            len(exhaustive["candidate_manifest"]),
            exhaustive["coverage"]["accessible_candidate_count"],
        )

    def test_candidate_manifest_explains_retrieval_and_score(self):
        payload = self.search_module.search(
            "正手握拍应该怎么握",
            manifest_limit=5,
            local_personalization=False,
        )
        candidate = payload["candidate_manifest"][0]
        for key in [
            "category",
            "confidence",
            "processing_status",
            "retrieval_channels",
            "matched_fields",
            "matched_topics",
            "matched_topic_details",
            "ngram_coverage_by_field",
            "score_breakdown",
            "why_retrieved",
        ]:
            self.assertIn(key, candidate)
        self.assertEqual(candidate["processing_status"], "ready")
        self.assertTrue(candidate["retrieval_channels"])
        self.assertTrue(candidate["why_retrieved"])
        self.assertIn(
            "effective_ranking_score", candidate["score_breakdown"]
        )

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
        self.assertIn("transcript_evidence", payload["results"][0])
        self.assertTrue(payload["results"][0]["transcript_evidence"])
        self.assertNotIn("transcript_ngrams", str(payload["results"][0]))
        self.assertGreater(
            payload["results"][0]["retrieval_summary"]["transcript_ngram_count"],
            0,
        )
        self.assertEqual(payload["answer_guidance"]["mode"], "balanced")

    def test_video_lookup_rejects_non_ready_evidence(self):
        video_id = "7387250672263040267"
        payload = self.search_module.lookup_videos(
            [video_id],
            query="谁的杀球更重",
            local_personalization=False,
        )
        self.assertEqual(payload["results"], [])
        self.assertEqual(payload["missing_video_ids"], [])
        self.assertEqual(
            payload["rejected_video_ids"],
            [
                {
                    "video_id": video_id,
                    "title": "你们觉得谁的杀球更重呢",
                    "processing_status": "not_teaching",
                    "reason": "processing_status_not_ready",
                }
            ],
        )

    def test_lookup_recovers_full_transcript_phrase_omitted_from_static_note(self):
        video_id = "7453420876076240188"
        query = "大拇指在发力的状态的时候要贴住中指"
        payload = self.search_module.lookup_videos(
            [video_id],
            query=query,
            local_personalization=False,
        )
        result = payload["results"][0]
        static_note = str(result["teaching_note"])
        transcript_text = "".join(
            item["text"] for item in result["transcript_evidence"]
        )
        self.assertNotIn(query, static_note)
        self.assertIn("贴住中指", transcript_text)
        self.assertTrue(
            any(item["exact_query_match"] for item in result["transcript_evidence"])
        )

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
        video_id = "7656560952972884730"
        payload = self.search_module.lookup_videos(
            [video_id],
            query="发力",
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

    def test_query_plan_uses_the_final_boundary_contract(self):
        text_primary_queries = [
            "练杀球肩膀痛怎么办",
            "打高远球手腕不适怎么处理",
            "练步法把脚踝扭伤了还能练吗",
            "杀球拉伤了该怎么恢复训练",
            "这个Skill是刘辉本人授权的吗",
            "刘辉同意这个训练计划吗",
            "哪款球拍适合我",
        ]
        for query in text_primary_queries:
            with self.subTest(query=query):
                plan = self.search_module.plan_query(query)
                guidance = plan["retrieval_guidance"]
                self.assertEqual(guidance["strategy"], "boundary_first")
                self.assertTrue(guidance["must_state_boundary_first"])
                self.assertEqual(plan["answer_guidance"]["mode"], "text_primary")

        visual = self.search_module.plan_query("我的反手握拍完全正确吗")
        self.assertEqual(
            visual["retrieval_guidance"]["strategy"], "boundary_first"
        )
        self.assertEqual(visual["answer_guidance"]["mode"], "video_primary")

        insufficient = self.search_module.plan_query(
            "只描述杀球下网，唯一原因是什么"
        )
        self.assertEqual(
            insufficient["retrieval_guidance"]["strategy"], "boundary_first"
        )
        self.assertEqual(insufficient["answer_guidance"]["mode"], "balanced")

        normal_training = self.search_module.plan_query("杀球还能不能继续练")
        self.assertEqual(
            normal_training["retrieval_guidance"]["strategy"],
            "focused_evidence",
        )
        self.assertFalse(
            normal_training["retrieval_guidance"]["must_state_boundary_first"]
        )

    def test_pain_variants_are_preserved_as_literal_symptoms(self):
        for symptom in ["痛", "扭伤", "拉伤", "不适", "不舒服"]:
            query = f"练杀球肩膀{symptom}怎么办"
            with self.subTest(symptom=symptom):
                frame = self.search_module.plan_query(query)[
                    "retrieval_guidance"
                ]["intent_frame"]
                self.assertIn(symptom, frame["literal_symptoms"])

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

    def test_query_plan_treats_scenario_only_questions_as_grounded_scopes(self):
        for query in [
            "正手怎么练",
            "反手怎么练",
            "后场怎么练",
            "单打怎么练",
            "进攻怎么练",
        ]:
            with self.subTest(query=query):
                guidance = self.search_module.plan_query(query)[
                    "retrieval_guidance"
                ]
                self.assertEqual(
                    guidance["strategy"], "scenario_focused_evidence"
                )
                self.assertTrue(guidance["require_exhaustive_completion"])
                self.assertFalse(guidance["use_topic_navigation"])

        unknown = self.search_module.plan_query("球感怎么练")[
            "retrieval_guidance"
        ]
        self.assertEqual(unknown["strategy"], "evidence_check")
        self.assertFalse(unknown["require_exhaustive_completion"])

    def test_requested_output_recognizes_contextual_practice_schedules(self):
        for query in [
            "双打新手一个人练接发，每次20分钟怎么安排",
            "有搭档喂球，30分钟如何分配网前搓球训练",
            "帮我做一个15分钟的杀球练习计划",
            "给我一个双打接发训练计划",
        ]:
            with self.subTest(query=query):
                frame = self.search_module.plan_query(query)[
                    "retrieval_guidance"
                ]["intent_frame"]
                self.assertEqual(frame["requested_output"], "practice")

        tactical = self.search_module.plan_query("双打站位怎么安排")[
            "retrieval_guidance"
        ]["intent_frame"]
        self.assertEqual(tactical["requested_output"], "coaching_answer")

        referenced_plan = self.search_module.plan_query(
            "刘辉同意这个训练计划吗"
        )["retrieval_guidance"]["intent_frame"]
        self.assertEqual(
            referenced_plan["requested_output"], "coaching_answer"
        )

    def test_query_plan_preserves_literal_symptom_after_known_concept(self):
        plan = self.search_module.plan_query("杀球总下网怎么办")
        frame = plan["retrieval_guidance"]["intent_frame"]
        self.assertIn("下网", frame["literal_symptoms"])
        self.assertIn("下网", plan["query_expansion"]["query_shards"])

    def test_query_plan_separates_positive_and_excluded_intent(self):
        plan = self.search_module.plan_query("我不想学杀球，只想练吊球")
        frame = plan["retrieval_guidance"]["intent_frame"]
        self.assertNotIn("杀球", frame["positive_query"])
        self.assertIn("吊球", frame["positive_query"])
        self.assertIn("杀球", frame["excluded_terms"])
        self.assertIn("吊球", plan["query_expansion"]["original_terms"])

    def test_negated_topic_is_penalized_out_of_top_results(self):
        ranked, expansion = self.search_module.rank_candidates(
            "双打轮转不要讲防守站位",
            *self.search_module.load_resources(),
        )
        self.assertIn("防守", expansion["intent_frame"]["excluded_terms"])
        self.assertTrue(ranked)
        self.assertTrue(
            all(not item["matched_excluded_seed_terms"] for item in ranked[:3])
        )
        self.assertTrue(all("防守" not in item["title"] for item in ranked[:8]))

    def test_only_requested_topic_outranks_explicitly_excluded_topic(self):
        ranked, _ = self.search_module.rank_candidates(
            "我不想学杀球，只想练吊球",
            *self.search_module.load_resources(),
        )
        self.assertIn("吊球", ranked[0]["title"])
        self.assertTrue(
            all(not item["matched_excluded_seed_terms"] for item in ranked[:5])
        )

    def test_specific_net_skill_does_not_expand_to_every_net_action(self):
        plan = self.search_module.plan_query("网前搓球怎么控制拍面")
        related = {
            item["term"] for item in plan["query_expansion"]["related_terms"]
        }
        self.assertIn("滚网", related)
        self.assertIn("拍面", related)
        self.assertNotIn("扑球", related)
        self.assertNotIn("勾球", related)

    def test_rotation_ranking_prefers_rotation_over_generic_front_back_footwork(self):
        payload = self.search_module.search(
            "双打轮转什么时候补位",
            limit=5,
            manifest_limit=10,
            local_personalization=False,
        )
        titles = [item["title"] for item in payload["results"]]
        self.assertTrue(any("轮转" in title for title in titles[:3]))
        self.assertFalse("正手区前后步法" in titles[0])

    def test_retrieval_index_contains_idf_and_field_length_statistics(self):
        _, retrieval_index, rules = self.search_module.load_resources()
        self.assertIn("term_document_frequency", retrieval_index)
        self.assertIn("average_field_lengths", retrieval_index)
        self.assertGreater(
            retrieval_index["term_document_frequency"]["发力"],
            retrieval_index["term_document_frequency"]["搓球"],
        )
        self.assertNotIn("category", rules["field_weights"])

    def test_visual_reviewed_records_exclude_failed_automatic_transcripts(self):
        knowledge, retrieval_index, _ = self.search_module.load_resources()
        records = {item["video_id"]: item for item in retrieval_index["videos"]}
        visual = [
            video
            for video in knowledge["videos"]
            if video.get("confidence") == "visual_reviewed"
        ]
        reviewed_transcript = [
            video
            for video in knowledge["videos"]
            if video.get("confidence") == "reviewed_transcript"
        ]
        self.assertEqual(len(visual), 19)
        self.assertEqual(len(reviewed_transcript), 5)
        for video in visual:
            with self.subTest(video_id=video["video_id"]):
                self.assertEqual(video["transcript_segments"], [])
                self.assertEqual(records[video["video_id"]]["transcript_ngrams"], [])
                self.assertFalse(
                    {"key_evidence", "error_evidence", "action_cues"}
                    & set(video["teaching_note"])
                )
        self.assertTrue(
            all(video["transcript_segments"] for video in reviewed_transcript)
        )
        mixed_video = next(
            video
            for video in reviewed_transcript
            if video["video_id"] == "7056596925721726220"
        )
        self.assertEqual(mixed_video["category"], "中前场与抽挡")
        self.assertTrue(
            all(segment["end"] <= 21.3 for segment in mixed_video["transcript_segments"])
        )
        scoped_text = "".join(
            segment["text"] for segment in mixed_video["transcript_segments"]
        )
        self.assertIn("正手抽球", scoped_text)
        self.assertNotIn("N68", scoped_text)

    def test_mixed_promotion_video_retrieves_by_teaching_but_not_product_title(self):
        teaching = self.search_module.search(
            "正手抽球旋转发力",
            manifest_limit=None,
            local_personalization=False,
        )
        teaching_ids = {
            item["video_id"] for item in teaching["candidate_manifest"]
        }
        self.assertIn("7056596925721726220", teaching_ids)

        product = self.search_module.search(
            "李宁N68球线",
            manifest_limit=None,
            local_personalization=False,
        )
        product_ids = {item["video_id"] for item in product["candidate_manifest"]}
        self.assertNotIn("7056596925721726220", product_ids)

    def test_transcript_review_overrides_product_wording_in_source_titles(self):
        cases = [
            (
                "双打抓回头直线空档快速抬拍",
                "紫电青霜底胶连钉",
                "7656927370758796145",
            ),
            (
                "反手发力有效顶肘大臂带小臂",
                "华羽新球拍12.6",
                "7577392474555210597",
            ),
        ]
        for teaching_query, product_query, video_id in cases:
            with self.subTest(video_id=video_id):
                teaching = self.search_module.search(
                    teaching_query,
                    manifest_limit=None,
                    local_personalization=False,
                )
                self.assertIn(
                    video_id,
                    {item["video_id"] for item in teaching["candidate_manifest"]},
                )
                product = self.search_module.search(
                    product_query,
                    manifest_limit=None,
                    local_personalization=False,
                )
                self.assertNotIn(
                    video_id,
                    {item["video_id"] for item in product["candidate_manifest"]},
                )

    def test_rejected_song_lyrics_cannot_recall_visual_review_video(self):
        payload = self.search_module.search(
            "第十二槍不時再搖起將軍大姓",
            manifest_limit=None,
            local_personalization=False,
        )
        ids = {item["video_id"] for item in payload["candidate_manifest"]}
        self.assertNotIn("7094813761894223139", ids)

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
        self.assertEqual(
            payload["coverage"]["intrinsic_review_candidate_count"],
            payload["coverage"]["review_candidate_count"]
            + payload["coverage"]["deferred_review_candidate_count"],
        )

    def test_review_budget_never_rewrites_intrinsic_relevance(self):
        ranked, _ = self.search_module.rank_candidates(
            "网前框架怎么做才不会身体僵硬",
            *self.search_module.load_resources(),
        )
        deferred = [
            item for item in ranked if item["review_priority"] == "deferred_review"
        ]
        self.assertTrue(deferred)
        self.assertTrue(
            all(
                item["relevance_tier"] in {"direct", "strong_related"}
                and item["intrinsic_relevance_tier"] == item["relevance_tier"]
                and not item["within_review_budget"]
                for item in deferred
            )
        )

    def test_pain_intent_does_not_promote_generic_kill_videos(self):
        payload = self.search_module.search(
            "练杀球以后肩膀疼，还能不能继续练",
            manifest_limit=None,
            local_personalization=False,
        )
        self.assertEqual(payload["results"], [])
        self.assertEqual(payload["coverage"]["review_candidate_count"], 0)
        self.assertEqual(payload["coverage"]["tier_counts"].get("direct", 0), 0)
        reviewable = [
            item
            for item in payload["candidate_manifest"]
            if item["within_review_budget"]
        ]
        self.assertEqual(reviewable, [])
        self.assertTrue(
            payload["retrieval_policy"]["exhaustive_candidates_preserved"]
        )

    def test_boundary_only_query_does_not_surface_generic_training_videos(self):
        payload = self.search_module.search(
            "你给出的训练建议是不是刘辉本人认可的",
            manifest_limit=None,
            local_personalization=False,
        )
        self.assertEqual(payload["results"], [])
        self.assertEqual(payload["query_expansion"]["focus_shards"], [])
        self.assertGreater(payload["coverage"]["candidate_count"], 0)
        self.assertEqual(payload["coverage"]["eligible_candidate_count"], 0)

    def test_retrieval_policy_preserves_rejected_scenario_candidates_for_audit(
        self,
    ):
        payload = self.search_module.search(
            "正手高远球的击球姿势是什么样",
            manifest_limit=None,
            local_personalization=False,
        )
        surfaced = {item["video_id"] for item in payload["results"]}
        rejected = {
            item["video_id"]: item
            for item in payload["candidate_manifest"]
            if not item["retrieval_policy_eligible"]
        }
        for video_id in {
            "7541623926234811705",
            "7546109410041908538",
            "7558912953539071292",
        }:
            self.assertNotIn(video_id, surfaced)
            self.assertIn(video_id, rejected)
            self.assertFalse(rejected[video_id]["within_review_budget"])

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
