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
        cls.context_module = cls.module.load_context_module()
        cls.selection_rules = cls.context_module.load_selection_rules()

    def constraint_decision(self, query, title):
        video = {
            "video_id": "7000000000000000001",
            "title": title,
            "category": "训练与纠错",
            "tags": [],
            "teaching_note": {"topic": title},
        }
        plan = self.search_module.plan_query(query)
        return self.context_module.constraint_decision(
            self.search_module,
            query,
            plan,
            video,
            self.selection_rules,
        )

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

    def test_constraint_axes_reject_opposite_only_sources_in_both_directions(self):
        cases = [
            ("反手高远怎么打", "正手高远教学", "stroke_side"),
            ("正手高远怎么打", "反手高远教学", "stroke_side"),
            ("网前步法怎么练", "后场步法教学", "court_zone"),
            ("后场步法怎么练", "网前步法教学", "court_zone"),
            ("单打防守站位", "双打防守站位", "discipline"),
            ("双打防守站位", "单打防守站位", "discipline"),
            ("发球怎么更隐蔽", "接发球教学", "serve_role"),
            ("接发怎么抢主动", "发球教学", "serve_role"),
            ("发小球怎么更隐蔽", "发后场教学", "serve_trajectory"),
            ("发后场怎么更隐蔽", "发小球教学", "serve_trajectory"),
            ("被动高远怎么打", "主动高远教学", "pressure_state"),
            ("主动高远怎么打", "被动高远教学", "pressure_state"),
            ("进攻站位怎么组织", "防守站位教学", "tactical_phase"),
            ("防守站位怎么组织", "进攻站位教学", "tactical_phase"),
            ("直线高远怎么打", "斜线高远教学", "shot_direction"),
            ("斜线高远怎么打", "直线高远教学", "shot_direction"),
            ("正手高远怎么打", "正手发小球教学", "shot_family"),
            ("杀球怎么打", "吊球教学", "shot_family"),
            ("搓球怎么控制", "勾球教学", "technique_variant"),
        ]
        for query, title, axis in cases:
            with self.subTest(query=query, title=title):
                allowed, failures, _, _, matches = self.constraint_decision(
                    query, title
                )
                self.assertFalse(allowed)
                self.assertIn(f"explicit_constraint_conflict:{axis}", failures)
                self.assertEqual(matches[axis], "conflict")

    def test_constraint_parser_handles_overlap_and_goal_phrases(self):
        receive = self.context_module.query_constraints(
            self.search_module,
            "双打接发球怎么抢主动",
            self.selection_rules,
        )
        self.assertEqual(receive["serve_role"], ["receive"])
        self.assertNotIn("pressure_state", receive)

        serve_target = self.context_module.query_constraints(
            self.search_module,
            "发小球怎么保持隐蔽并偷后场",
            self.selection_rules,
        )
        self.assertNotIn("court_zone", serve_target)
        self.assertEqual(
            serve_target["serve_trajectory"], ["deep_serve", "short_serve"]
        )
        self.assertEqual(
            serve_target["shot_family"], ["deep_serve", "short_serve"]
        )

    def test_mixed_source_is_supporting_for_single_scope_and_exact_for_comparison(self):
        allowed, failures, _, _, matches = self.constraint_decision(
            "反手高远怎么打", "正反手高远的区别"
        )
        self.assertTrue(allowed)
        self.assertEqual(failures, [])
        self.assertEqual(matches["stroke_side"], "mixed_support")

        allowed, failures, _, _, matches = self.constraint_decision(
            "正手和反手高远有什么区别", "正反手高远的区别"
        )
        self.assertTrue(allowed)
        self.assertEqual(failures, [])
        self.assertEqual(matches["stroke_side"], "exact")

    def test_unspecified_scope_is_supporting_not_false_conflict(self):
        allowed, failures, _, _, matches = self.constraint_decision(
            "反手高远怎么打", "高远球放松发力原则"
        )
        self.assertTrue(allowed)
        self.assertEqual(failures, [])
        self.assertEqual(matches["stroke_side"], "unspecified_support")

    def test_primary_metadata_takes_precedence_over_broad_tags(self):
        video = {
            "video_id": "7000000000000000002",
            "title": "单打防守反击",
            "category": "单打战术",
            "tags": ["单打战术", "双打战术"],
            "teaching_note": {"topic": "单打防守反击"},
        }
        plan = self.search_module.plan_query("双打防守站位怎么调整")
        allowed, failures, _, _, matches = self.context_module.constraint_decision(
            self.search_module,
            "双打防守站位怎么调整",
            plan,
            video,
            self.selection_rules,
        )
        self.assertFalse(allowed)
        self.assertIn("explicit_constraint_conflict:discipline", failures)
        self.assertEqual(matches["discipline"], "conflict")

    def test_backhand_passive_clear_excludes_confirmed_forehand_sources(self):
        payload = self.context_module.prepare_answer_context(
            "如何打反手被动高远球？",
            local_personalization=False,
            include_rejected=True,
        )
        selected = {item["video_id"] for item in payload["selected_videos"]}
        rejected = {
            item["video_id"]: item["reasons"]
            for item in payload["rejected_candidates"]
        }
        self.assertIn("7546109410041908538", selected)
        self.assertNotIn("7558912953539071292", selected)
        self.assertNotIn("7153445193713290511", selected)
        self.assertIn(
            "explicit_constraint_conflict:stroke_side",
            rejected["7558912953539071292"],
        )
        self.assertIn(
            "explicit_constraint_conflict:stroke_side",
            rejected["7153445193713290511"],
        )
        self.assertEqual(
            payload["question_interpretation"]["constraints"]["stroke_side"],
            ["backhand"],
        )
        self.assertFalse(payload["selection"]["selection_truncated"])
        self.assertEqual(
            payload["selection"]["eligible_video_count"],
            payload["selection"]["selected_video_count"],
        )
        self.assertTrue(
            any(
                reasons == ["supporting_video_limit_exceeded"]
                for reasons in rejected.values()
            )
        )
        retrieval_queries = payload["question_interpretation"]["retrieval_queries"]
        self.assertIn("反手 被动 高远球", retrieval_queries)
        self.assertTrue(
            any(
                all(term in retrieval_query for term in ["反手", "被动", "挥拍"])
                for retrieval_query in retrieval_queries
            )
        )
        self.assertIn("高远球", retrieval_queries)
        self.assertIn("挥拍", retrieval_queries)

    def test_known_cross_dimension_leaks_are_not_selected(self):
        cases = [
            ("后场步法怎么练", {"7406541084219821312"}),
            (
                "双打防守站位怎么调整",
                {
                    "7602766054809333617",
                    "7586613438625959217",
                    "7376838935164505384",
                },
            ),
        ]
        for query, forbidden_ids in cases:
            with self.subTest(query=query):
                payload = self.context_module.prepare_answer_context(
                    query,
                    local_personalization=False,
                )
                selected = {
                    item["video_id"] for item in payload["selected_videos"]
                }
                self.assertFalse(selected & forbidden_ids)

    def test_negated_conditions_drive_final_constraint_parser(self):
        cases = [
            (
                "不要讲正手，只讲反手被动高远",
                {
                    "stroke_side": ["backhand"],
                    "shot_family": ["clear"],
                    "pressure_state": ["passive"],
                },
            ),
            (
                "单打防守站位，不要讲双打",
                {"discipline": ["singles"], "tactical_phase": ["defense"]},
            ),
            ("只讲接发，不讲发球", {"serve_role": ["receive"]}),
            (
                "发小球，不要偷后场",
                {
                    "shot_family": ["short_serve"],
                    "serve_role": ["serve"],
                    "serve_trajectory": ["short_serve"],
                },
            ),
            ("被动处理，不是主动球", {"pressure_state": ["passive"]}),
            ("防守站位，不讲进攻", {"tactical_phase": ["defense"]}),
            ("只打直线，不打斜线", {"shot_direction": ["straight"]}),
        ]
        for query, expected in cases:
            with self.subTest(query=query):
                plan = self.search_module.plan_query(query)
                positive_query = plan["retrieval_guidance"]["intent_frame"][
                    "positive_query"
                ]
                actual = self.context_module.query_constraints(
                    self.search_module,
                    positive_query,
                    self.selection_rules,
                )
                self.assertEqual(actual, expected)

    def test_shot_family_and_reviewed_signals_do_not_leak_across_questions(self):
        clear = self.context_module.prepare_answer_context(
            "正手高远球的击球姿势是什么样",
            local_personalization=False,
            include_rejected=True,
        )
        clear_ids = {item["video_id"] for item in clear["selected_videos"]}
        self.assertNotIn("7254755365995285812", clear_ids)
        rejected = {
            item["video_id"]: item["reasons"]
            for item in clear["rejected_candidates"]
        }
        self.assertIn(
            "explicit_constraint_conflict:shot_family",
            rejected["7254755365995285812"],
        )

        smash = self.context_module.prepare_answer_context(
            "杀球动作怎么发力",
            local_personalization=False,
        )
        smash_ids = {item["video_id"] for item in smash["selected_videos"]}
        self.assertEqual(
            smash_ids,
            {
                "7052600326116887812",
                "7440406891664133428",
                "7484563688096091449",
                "7567155406117533051",
            },
        )
        self.assertNotIn("7115241358255803683", smash_ids)

    def test_relationship_and_multi_issue_evidence_keep_scoped_roles(self):
        relationship = self.context_module.prepare_answer_context(
            "吊球与杀球配合",
            local_personalization=False,
        )
        by_id = {
            item["video_id"]: item for item in relationship["selected_videos"]
        }
        self.assertEqual(by_id["7115241358255803683"]["role"], "core")
        if "7093706918492917033" in by_id:
            self.assertEqual(
                by_id["7093706918492917033"]["role"], "supporting"
            )

        receive = self.context_module.prepare_answer_context(
            "双打接发战术和接发握拍应该怎么调整",
            local_personalization=False,
        )
        receive_ids = {item["video_id"] for item in receive["selected_videos"]}
        self.assertIn("7053654124042194215", receive_ids)
        self.assertIn("7639306481355832689", receive_ids)
        self.assertLessEqual(
            sum(item["role"] == "supporting" for item in receive["selected_videos"]),
            self.selection_rules["max_supporting_videos"],
        )


if __name__ == "__main__":
    unittest.main()
