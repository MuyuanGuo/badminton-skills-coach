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
        insufficient = self.module.prepare_case_context(
            self.search_module,
            {
                "query": (
                    "我只描述杀球总下网，不给动作视频，"
                    "能不能确定唯一原因"
                )
            },
        )
        self.assertEqual(pain["selected_ids"], [])
        self.assertEqual(endorsement["selected_ids"], [])
        self.assertEqual(insufficient["selected_ids"], [])

    def test_boundary_planning_and_final_classification_are_consistent(self):
        cases = {
            "练杀球肩膀痛怎么办": "pain_or_injury",
            "打高远球手腕不舒服怎么处理": "pain_or_injury",
            "这个Skill是刘辉本人授权的吗": "endorsement_or_authorship",
            "刘辉同意这个训练计划吗": "endorsement_or_authorship",
            "哪款球拍适合我": "purchase_advice",
            "我的反手握拍完全正确吗": "visual_confirmation",
            "只描述杀球下网，唯一原因是什么": "insufficient_observation",
        }
        for query, expected_boundary in cases.items():
            with self.subTest(query=query):
                context = self.context_module.prepare_answer_context(
                    query,
                    max_videos=1,
                    local_personalization=False,
                )
                self.assertEqual(
                    context["question_interpretation"]["strategy"],
                    "boundary_first",
                )
                self.assertEqual(context["boundary"]["type"], expected_boundary)
                self.assertIsNotNone(context["boundary"]["required_statement"])

        endorsement = self.context_module.prepare_answer_context(
            "刘辉同意这个训练计划吗",
            max_videos=1,
            local_personalization=False,
        )
        self.assertEqual(
            endorsement["question_interpretation"]["intent_frame"][
                "requested_output"
            ],
            "coaching_answer",
        )
        self.assertIsNone(endorsement["topic_navigation"])

        pain_practice = self.context_module.prepare_answer_context(
            "肩膀痛，现在怎么练杀球",
            max_videos=1,
            local_personalization=False,
        )
        self.assertEqual(
            pain_practice["question_interpretation"]["intent_frame"][
                "requested_output"
            ],
            "practice",
        )
        self.assertEqual(pain_practice["boundary"]["type"], "pain_or_injury")
        self.assertIsNone(pain_practice["topic_navigation"])

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

    def test_query_actor_context_separates_opponent_and_player_actions(self):
        backhand = self.context_module.query_actor_context(
            self.search_module,
            "对手反手弱，应该怎么针对",
            self.selection_rules,
        )
        self.assertEqual(backhand["player_constraints"], {})
        self.assertEqual(
            backhand["opponent_constraints"],
            {"stroke_side": ["backhand"]},
        )

        deep_serve = self.context_module.query_actor_context(
            self.search_module,
            "对手发高远球，我怎么接",
            self.selection_rules,
        )
        self.assertEqual(
            deep_serve["player_constraints"], {"serve_role": ["receive"]}
        )
        self.assertEqual(
            deep_serve["opponent_constraints"],
            {
                "shot_family": ["deep_serve"],
                "serve_role": ["serve"],
                "serve_trajectory": ["deep_serve"],
            },
        )
        self.assertEqual(deep_serve["derived_search_terms"], ["接发"])

        smash = self.context_module.query_actor_context(
            self.search_module,
            "对方正手杀球很重，我怎么防守",
            self.selection_rules,
        )
        self.assertEqual(
            smash["player_constraints"],
            {"tactical_phase": ["defense"]},
        )
        self.assertEqual(
            smash["opponent_constraints"],
            {
                "stroke_side": ["forehand"],
                "shot_family": ["smash"],
                "tactical_phase": ["attack"],
            },
        )

        straight_drop = self.context_module.query_actor_context(
            self.search_module,
            "对手吊直线，我怎么防",
            self.selection_rules,
        )
        self.assertEqual(
            straight_drop["player_constraints"],
            {"tactical_phase": ["defense"]},
        )
        self.assertEqual(
            straight_drop["opponent_constraints"],
            {"shot_family": ["drop"], "shot_direction": ["straight"]},
        )
        self.assertEqual(straight_drop["derived_search_terms"], ["防守"])

        own_serve = self.context_module.query_actor_context(
            self.search_module,
            "我发高远球，对手总抢攻，怎么改",
            self.selection_rules,
        )
        self.assertIn("怎么改", own_serve["player_query"])
        self.assertNotIn("怎么改", own_serve["opponent_query"])
        self.assertEqual(own_serve["player_constraints"]["serve_role"], ["serve"])

    def test_opponent_conditions_select_response_not_player_action_evidence(self):
        context = self.context_module.prepare_answer_context(
            "对手发高远球，我怎么接",
            max_videos=4,
            local_personalization=False,
        )
        interpretation = context["question_interpretation"]
        self.assertEqual(interpretation["constraints"], {"serve_role": ["receive"]})
        self.assertIn("接发", interpretation["retrieval_queries"])
        selected = {item["video_id"] for item in context["selected_videos"]}
        self.assertIn("7639306481355832689", selected)
        self.assertNotIn("7517867684509420857", selected)
        self.assertNotIn("7508222669708463420", selected)

        targeting = self.context_module.prepare_answer_context(
            "对手反手弱，应该怎么针对",
            local_personalization=False,
            include_rejected=True,
        )
        targeting_ids = {
            item["video_id"] for item in targeting["selected_videos"]
        }
        for video_id in [
            "7151961376448138531",
            "7081831033515117865",
            "7499776424493075772",
        ]:
            self.assertNotIn(video_id, targeting_ids)
        rejected = {
            item["video_id"]: item["reasons"]
            for item in targeting["rejected_candidates"]
        }
        self.assertIn(
            "opponent_condition_misread_as_player_action:stroke_side",
            rejected["7499776424493075772"],
        )

        straight_drop = self.context_module.prepare_answer_context(
            "对手吊直线，我怎么防",
            local_personalization=False,
            include_rejected=True,
        )
        straight_drop_ids = {
            item["video_id"] for item in straight_drop["selected_videos"]
        }
        self.assertIn("7449702119076072764", straight_drop_ids)
        self.assertNotIn("7593661008519810289", straight_drop_ids)
        self.assertNotIn("7065871561915485440", straight_drop_ids)

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
        self.assertNotIn("7117821949165718824", selected)
        self.assertIn(
            "explicit_constraint_conflict:stroke_side",
            rejected["7558912953539071292"],
        )
        self.assertIn(
            "explicit_constraint_conflict:stroke_side",
            rejected["7153445193713290511"],
        )
        self.assertIn(
            "explicit_constraint_conflict:shot_family",
            rejected["7117821949165718824"],
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

        receive = self.context_module.prepare_answer_context(
            "反手接杀应该怎么处理？",
            local_personalization=False,
        )
        self.assertIn(
            "7117821949165718824",
            {item["video_id"] for item in receive["selected_videos"]},
        )

    def test_structured_shot_family_mismatch_is_a_conflict(self):
        video = {
            "video_id": "7000000000000000003",
            "title": "反手区接被动球",
            "category": "训练与纠错",
            "tags": [],
            "teaching_note": {
                "topic": "反手区接被动球",
                "evidence": [
                    {"text": "反手区接杀步法，用于处理对方杀球"}
                ],
            },
        }
        plan = self.search_module.plan_query("反手被动高远怎么打")
        allowed, failures, _, _, matches = (
            self.context_module.constraint_decision(
                self.search_module,
                "反手被动高远怎么打",
                plan,
                video,
                self.selection_rules,
            )
        )
        self.assertFalse(allowed)
        self.assertIn("explicit_constraint_conflict:shot_family", failures)
        self.assertEqual(matches["shot_family"], "conflict")

    def test_generic_questions_reject_or_demote_narrow_evidence(self):
        backhand_clear = self.context_module.prepare_answer_context(
            "反手高远球怎么发力？",
            local_personalization=False,
        )
        self.assertTrue(backhand_clear["selected_videos"])
        for video in backhand_clear["selected_videos"]:
            if video["role"] == "core":
                self.assertEqual(video["unrequested_constraint_scope"], {})
        passive = next(
            (
                video
                for video in backhand_clear["selected_videos"]
                if video["video_id"] == "7546109410041908538"
            ),
            None,
        )
        if passive is not None:
            self.assertEqual(passive["role"], "supporting")
            self.assertIn(
                "pressure_state", passive["unrequested_constraint_scope"]
            )

        clear = self.context_module.prepare_answer_context(
            "高远球怎么打？",
            local_personalization=False,
            include_rejected=True,
        )
        self.assertNotIn(
            "7291120515530493184",
            {video["video_id"] for video in clear["selected_videos"]},
        )
        clear_rejected = {
            item["video_id"]: item["reasons"]
            for item in clear["rejected_candidates"]
        }
        self.assertIn(
            "explicit_cross_axis_conflict:shot_family_vs_serve_role",
            clear_rejected["7291120515530493184"],
        )
        drive = self.context_module.prepare_answer_context(
            "平抽挡怎么提高连续速度",
            local_personalization=False,
        )
        self.assertIn(
            "7652440366436945017",
            {video["video_id"] for video in drive["selected_videos"]},
        )

        footwork = self.context_module.prepare_answer_context(
            "后场步法怎么练？",
            local_personalization=False,
        )
        self.assertTrue(footwork["selected_videos"])
        self.assertTrue(
            all(
                video["focus_match"] in {"primary", "structured"}
                for video in footwork["selected_videos"]
            )
        )
        self.assertNotIn(
            "7508222669708463420",
            {video["video_id"] for video in footwork["selected_videos"]},
        )

        drop = self.context_module.prepare_answer_context(
            "吊球怎么打？",
            local_personalization=False,
            include_rejected=True,
        )
        self.assertNotIn(
            "7055130343476710667",
            {video["video_id"] for video in drop["selected_videos"]},
        )
        drop_rejected = {
            item["video_id"]: item["reasons"]
            for item in drop["rejected_candidates"]
        }
        self.assertIn(
            "incomplete_series_fragment",
            drop_rejected["7055130343476710667"],
        )

        spin = self.context_module.prepare_answer_context(
            "搓球怎么打？",
            local_personalization=False,
            include_rejected=True,
        )
        self.assertNotIn(
            "7052252250189696267",
            {video["video_id"] for video in spin["selected_videos"]},
        )
        spin_rejected = {
            item["video_id"]: item["reasons"]
            for item in spin["rejected_candidates"]
        }
        self.assertIn(
            "incomplete_series_fragment",
            spin_rejected["7052252250189696267"],
        )

    def test_generic_training_keeps_roles_and_locations_distinct(self):
        rearcourt = self.context_module.prepare_answer_context(
            "后场怎么练？",
            local_personalization=False,
            include_rejected=True,
        )
        rearcourt_ids = {
            video["video_id"] for video in rearcourt["selected_videos"]
        }
        self.assertIn("7124871920230632745", rearcourt_ids)
        self.assertNotIn("7508222669708463420", rearcourt_ids)
        rearcourt_rejected = {
            item["video_id"]: item["reasons"]
            for item in rearcourt["rejected_candidates"]
        }
        self.assertIn(
            "explicit_cross_axis_conflict:court_zone_vs_serve_role",
            rearcourt_rejected["7508222669708463420"],
        )

        serve = self.context_module.prepare_answer_context(
            "发球怎么练？",
            local_personalization=False,
            include_rejected=True,
        )
        self.assertNotIn(
            "7118192644957818127",
            {video["video_id"] for video in serve["selected_videos"]},
        )
        serve_rejected = {
            item["video_id"]: item["reasons"]
            for item in serve["rejected_candidates"]
        }
        self.assertIn(
            "explicit_constraint_conflict:serve_role",
            serve_rejected["7118192644957818127"],
        )

        smash = self.context_module.prepare_answer_context(
            "杀球怎么练？",
            local_personalization=False,
        )
        smash_by_id = {
            video["video_id"]: video for video in smash["selected_videos"]
        }
        self.assertIn("7567155406117533051", smash_by_id)
        self.assertEqual(
            smash_by_id["7567155406117533051"]["role"], "core"
        )
        self.assertNotIn("7067722128413543680", smash_by_id)

    def test_generic_answers_keep_actor_and_prerequisite_scope(self):
        defense = self.context_module.prepare_answer_context(
            "防守怎么练？",
            local_personalization=False,
            include_rejected=True,
        )
        self.assertNotIn(
            "7258462271670586658",
            {video["video_id"] for video in defense["selected_videos"]},
        )
        defense_rejected = {
            item["video_id"]: item["reasons"]
            for item in defense["rejected_candidates"]
        }
        self.assertIn(
            "explicit_constraint_conflict:tactical_phase",
            defense_rejected["7258462271670586658"],
        )

        backhand = self.context_module.prepare_answer_context(
            "反手怎么练？",
            local_personalization=False,
        )
        backhand_ids = [
            video["video_id"] for video in backhand["selected_videos"]
        ]
        self.assertLess(
            backhand_ids.index("7060717442825309480"),
            backhand_ids.index("7499776424493075772"),
        )

        drop = self.context_module.prepare_answer_context(
            "吊球怎么练？",
            local_personalization=False,
            include_rejected=True,
        )
        self.assertNotIn(
            "7054395778814561575",
            {video["video_id"] for video in drop["selected_videos"]},
        )
        drop_rejected = {
            item["video_id"]: item["reasons"]
            for item in drop["rejected_candidates"]
        }
        self.assertIn(
            "incomplete_series_fragment",
            drop_rejected["7054395778814561575"],
        )

    def test_focused_practice_request_returns_personalized_adaptation(self):
        context = self.context_module.prepare_answer_context(
            "双打新手一个人每天十五分钟怎么练接发",
            max_videos=1,
            local_personalization=False,
        )
        interpretation = context["question_interpretation"]
        self.assertEqual(
            interpretation["intent_frame"]["requested_output"], "practice"
        )
        self.assertEqual(interpretation["strategy"], "focused_evidence")
        navigation = context["topic_navigation"]
        self.assertIsNotNone(navigation)
        self.assertEqual(navigation["user_context"]["level"], "beginner")
        self.assertEqual(navigation["user_context"]["discipline"], "doubles")
        self.assertEqual(navigation["user_context"]["practice_setup"], "solo")
        self.assertEqual(navigation["user_context"]["session_minutes"], 15)
        self.assertEqual(
            sum(navigation["practice_adaptation"]["minute_allocation"].values()),
            15,
        )
        self.assertIn(
            "不要把需要稳定喂球的练习写成可独自完成",
            navigation["practice_adaptation"]["setup_adaptation"],
        )

    def test_generic_questions_condition_additional_specific_scope(self):
        backhand = self.context_module.prepare_answer_context(
            "反手怎么练？",
            local_personalization=False,
        )
        backhand_by_id = {
            item["video_id"]: item for item in backhand["selected_videos"]
        }
        self.assertEqual(
            backhand["question_interpretation"]["strategy"],
            "scenario_focused_evidence",
        )
        self.assertEqual(
            backhand_by_id["7060717442825309480"]["claim_scope_policy"],
            "exact_question_scope",
        )
        for video_id in [
            "7499776424493075772",
            "7098897570482670888",
            "7535400692573211962",
        ]:
            self.assertEqual(
                backhand_by_id[video_id]["claim_scope_policy"],
                "additional_specific_scope_only_not_unrestricted_full_question_proof",
            )
            self.assertTrue(
                backhand_by_id[video_id][
                    "additional_scope_requires_conditioning"
                ]
            )

        footwork = self.context_module.prepare_answer_context(
            "步法怎么练？",
            local_personalization=False,
        )
        footwork_by_id = {
            item["video_id"]: item for item in footwork["selected_videos"]
        }
        self.assertEqual(
            footwork_by_id["7214304020775652620"]["claim_scope_policy"],
            "additional_specific_scope_only_not_unrestricted_full_question_proof",
        )
        self.assertEqual(
            footwork_by_id["7656927370758796145"]["claim_scope_policy"],
            "additional_specific_scope_only_not_unrestricted_full_question_proof",
        )

        jump_smash = self.context_module.prepare_answer_context(
            "反手跳杀怎么练？",
            local_personalization=False,
        )
        jump_smash_by_id = {
            item["video_id"]: item
            for item in jump_smash["selected_videos"]
        }
        self.assertEqual(
            jump_smash_by_id["7499776424493075772"]["role"], "core"
        )
        self.assertEqual(
            jump_smash_by_id["7499776424493075772"][
                "claim_scope_policy"
            ],
            "exact_question_scope",
        )

    def test_direct_instruction_survives_broad_canonical_concepts(self):
        short_serve = self.context_module.prepare_answer_context(
            "发小球怎么练？",
            local_personalization=False,
        )
        short_serve_by_id = {
            item["video_id"]: item for item in short_serve["selected_videos"]
        }
        for video_id in ["7589590613499595185", "7254755365995285812"]:
            self.assertEqual(short_serve_by_id[video_id]["role"], "core")
            self.assertEqual(
                short_serve_by_id[video_id]["concept_match"], "exact_question"
            )

        defense = self.context_module.prepare_answer_context(
            "防守怎么练？",
            local_personalization=False,
        )
        defense_by_id = {
            item["video_id"]: item for item in defense["selected_videos"]
        }
        for video_id in ["7586613438625959217", "7054025391601650948"]:
            self.assertEqual(defense_by_id[video_id]["role"], "core")
            self.assertEqual(
                defense_by_id[video_id]["concept_match"], "exact_question"
            )
        self.assertNotIn(
            "7387233755057949987",
            {
                item["video_id"]
                for item in defense["selected_videos"]
                if item["role"] == "core"
            },
        )

        net_drop = self.context_module.prepare_answer_context(
            "放网怎么打？",
            local_personalization=False,
        )
        net_drop_by_id = {
            item["video_id"]: item for item in net_drop["selected_videos"]
        }
        self.assertEqual(
            net_drop_by_id["7524557392328461627"]["role"], "core"
        )
        self.assertEqual(
            net_drop_by_id["7092959332047785250"]["role"], "supporting"
        )

        net_push = self.context_module.prepare_answer_context(
            "推球怎么练？",
            local_personalization=False,
        )
        net_push_by_id = {
            item["video_id"]: item for item in net_push["selected_videos"]
        }
        self.assertEqual(
            net_push_by_id["7131178146023427328"]["role"], "core"
        )

        net_pounce = self.context_module.prepare_answer_context(
            "扑球怎么练？",
            local_personalization=False,
        )
        self.assertEqual(net_pounce["selected_videos"], [])

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
        smash_by_id = {
            item["video_id"]: item for item in smash["selected_videos"]
        }
        smash_ids = set(smash_by_id)
        self.assertEqual(
            smash_ids,
            {
                "7052600326116887812",
                "7440406891664133428",
                "7484563688096091449",
                "7550305145877155131",
                "7567155406117533051",
                "7659991105622862457",
            },
        )
        self.assertEqual(
            smash_by_id["7550305145877155131"]["role"], "supporting"
        )
        self.assertEqual(
            smash_by_id["7659991105622862457"]["role"], "supporting"
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

    def test_target_zones_and_colloquial_net_shots_keep_the_right_evidence(self):
        cases = [
            (
                "后场吊网前怎么练",
                {"7520190707093654844"},
                {
                    "7486788550298471739",
                    "7054395778814561575",
                    "7071800926553541922",
                    "7509355373729762619",
                },
            ),
            (
                "吊球怎么打到网前",
                {"7306709804234444072"},
                {
                    "7054786188086955276",
                    "7406541084219821312",
                    "7661940775983482097",
                },
            ),
            (
                "网前勾对角怎么控制",
                {"7150847019320429839"},
                {"7071800926553541922", "7509355373729762619"},
            ),
            (
                "双打接发推后场怎么打",
                {"7131178146023427328", "7639306481355832689"},
                {
                    "7065491791167999232",
                    "7074399231259266344",
                    "7414339897990843663",
                    "7504391919716273468",
                    "7505345719160933692",
                    "7619576226616745445",
                },
            ),
        ]
        for query, required_ids, forbidden_ids in cases:
            with self.subTest(query=query):
                payload = self.context_module.prepare_answer_context(
                    query,
                    local_personalization=False,
                )
                selected = {
                    item["video_id"] for item in payload["selected_videos"]
                }
                self.assertTrue(required_ids.issubset(selected))
                self.assertFalse(forbidden_ids & selected)

    def test_opponent_and_goal_language_do_not_prove_player_pressure_state(self):
        payload = self.context_module.prepare_answer_context(
            "反手主动高远球怎么打",
            local_personalization=False,
            include_rejected=True,
        )
        selected = {item["video_id"] for item in payload["selected_videos"]}
        self.assertNotIn("7148267452877638944", selected)
        self.assertNotIn("7072543702161296640", selected)
        rejected = {
            item["video_id"]: item["reasons"]
            for item in payload["rejected_candidates"]
        }
        self.assertIn(
            "explicit_constraint_conflict:pressure_state",
            rejected["7148267452877638944"],
        )
        self.assertIn(
            "explicit_constraint_conflict:pressure_state",
            rejected["7072543702161296640"],
        )

    def test_opponent_focus_and_promotional_titles_do_not_pollute_answers(self):
        grip = self.context_module.prepare_answer_context(
            "握拍变化怎么练",
            local_personalization=False,
        )
        grip_by_id = {
            item["video_id"]: item for item in grip["selected_videos"]
        }
        self.assertNotIn("7475440958130097466", grip_by_id)
        self.assertEqual(
            grip_by_id["7656927370758796145"]["title"],
            "双打抓回头：站位、轮转、握拍、锁腕和步法",
        )

        finger_power = self.context_module.prepare_answer_context(
            "正手手指发力怎么练",
            local_personalization=False,
        )
        power_by_id = {
            item["video_id"]: item for item in finger_power["selected_videos"]
        }
        self.assertEqual(
            power_by_id["7056596925721726220"]["title"],
            "正手抽球：架拍与腰腹到手腕的旋转发力",
        )


if __name__ == "__main__":
    unittest.main()
