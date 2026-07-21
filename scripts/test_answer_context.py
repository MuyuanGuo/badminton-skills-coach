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
        self.assertEqual(result["cases"], 54)
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

    def test_downward_pressure_is_not_silently_parsed_as_smash(self):
        net_pressure = self.context_module.query_constraints(
            self.search_module,
            "双打封网怎么压球",
            self.selection_rules,
        )
        self.assertEqual(
            net_pressure,
            {
                "stroke_intent": ["downward_pressure"],
                "court_zone": ["forecourt", "midcourt"],
                "discipline": ["doubles"],
            },
        )
        self.assertNotIn("shot_family", net_pressure)
        self.assertNotIn("tactical_phase", net_pressure)

        ambiguous = self.context_module.prepare_answer_context(
            "压球怎么打",
            local_personalization=False,
        )
        self.assertEqual(
            [
                item["name"]
                for item in ambiguous["question_interpretation"][
                    "ambiguities"
                ]
            ],
            ["downward_pressure_context"],
        )
        smash = self.context_module.prepare_answer_context(
            "杀球怎么打",
            local_personalization=False,
        )
        self.assertEqual(smash["question_interpretation"]["ambiguities"], [])
        self.assertEqual(
            smash["question_interpretation"]["constraints"]["shot_family"],
            ["smash"],
        )

    def test_lift_is_a_distinct_action_with_direct_evidence(self):
        constraints = self.context_module.query_constraints(
            self.search_module,
            "反手挑球怎么打",
            self.selection_rules,
        )
        self.assertEqual(
            constraints,
            {
                "stroke_side": ["backhand"],
                "shot_family": ["lift"],
            },
        )
        context = self.context_module.prepare_answer_context(
            "反手挑球怎么打",
            local_personalization=False,
        )
        self.assertEqual(
            [item["video_id"] for item in context["selected_videos"]],
            [
                "7523163965838003514",
                "7511934047901846841",
                "7151961376448138531",
            ],
        )
        self.assertFalse(
            {
                "7499776424493075772",
                "7541623926234811705",
                "7447084061371272507",
                "7226178331408928038",
            }
            & {item["video_id"] for item in context["selected_videos"]}
        )
        self.assertEqual(
            self.context_module.required_constraint_support_failures(
                {"shot_family": ["lift"]},
                {"shot_family": "incidental_support"},
                self.selection_rules,
            ),
            ["specific_lift_shot_family_not_supported"],
        )

    def test_transition_is_a_distinct_action_with_direct_evidence(self):
        constraints = self.context_module.query_constraints(
            self.search_module,
            "反手过渡球怎么打",
            self.selection_rules,
        )
        self.assertEqual(
            constraints,
            {
                "stroke_side": ["backhand"],
                "shot_family": ["transition"],
            },
        )
        context = self.context_module.prepare_answer_context(
            "反手过渡球怎么打",
            local_personalization=False,
        )
        self.assertEqual(
            {item["video_id"] for item in context["selected_videos"]},
            {
                "7515625891511995706",
                "7393550140465777960",
                "7563513758061114875",
                "7060717442825309480",
                "7344186576013905187",
                "7511934047901846841",
            },
        )
        self.assertFalse(
            {
                "7535400692573211962",
                "7541623926234811705",
                "7550305145877155131",
                "7499776424493075772",
                "7523163965838003514",
            }
            & {item["video_id"] for item in context["selected_videos"]}
        )
        self.assertEqual(
            self.context_module.required_constraint_support_failures(
                {"shot_family": ["transition"]},
                {"shot_family": "incidental_support"},
                self.selection_rules,
            ),
            ["specific_transition_shot_family_not_supported"],
        )

    def test_smash_block_is_a_distinct_action_with_direct_evidence(self):
        constraints = self.context_module.query_constraints(
            self.search_module,
            "反手挡杀怎么打",
            self.selection_rules,
        )
        self.assertEqual(
            constraints,
            {
                "stroke_side": ["backhand"],
                "shot_family": ["smash_block"],
            },
        )
        context = self.context_module.prepare_answer_context(
            "反手挡杀怎么打",
            local_personalization=False,
        )
        self.assertEqual(
            [item["video_id"] for item in context["selected_videos"]],
            [
                "7215787369381858599",
                "7647839024535507897",
                "7117821949165718824",
                "7422121561559272739",
                "7141200093922790688",
                "7289635377009151247",
            ],
        )
        self.assertFalse(
            {
                "7499776424493075772",
                "7115241358255803683",
                "7497098752897879355",
                "7056596925721726220",
                "7254755365995285812",
                "7523163965838003514",
            }
            & {item["video_id"] for item in context["selected_videos"]}
        )
        self.assertEqual(
            self.context_module.required_constraint_support_failures(
                {"shot_family": ["smash_block"]},
                {"shot_family": "incidental_support"},
                self.selection_rules,
            ),
            ["specific_smash_block_shot_family_not_supported"],
        )

    def test_smash_block_scope_preserves_receive_to_counterattack_sources(self):
        context = self.context_module.prepare_answer_context(
            "接杀以后怎么防守反击",
            local_personalization=False,
        )
        selected = {
            item["video_id"] for item in context["selected_videos"]
        }
        self.assertTrue(
            {
                "7602766054809333617",
                "7621243051541587889",
                "7127470220309957923",
            }.issubset(selected)
        )
        self.assertEqual(
            context["question_interpretation"]["constraints"]["shot_family"],
            ["smash_block"],
        )

    def test_backhand_slide_drop_requires_the_specific_variant(self):
        constraints = self.context_module.query_constraints(
            self.search_module,
            "反手滑板怎么打",
            self.selection_rules,
        )
        self.assertEqual(
            constraints,
            {
                "stroke_side": ["backhand"],
                "shot_family": ["drop"],
                "technique_variant": ["drop_reverse_slice"],
            },
        )
        context = self.context_module.prepare_answer_context(
            "反手滑板怎么打",
            local_personalization=False,
        )
        self.assertEqual(
            [item["video_id"] for item in context["selected_videos"]],
            ["7214304020775652620"],
        )
        self.assertFalse(
            {
                "7068835198938516777",
                "7499776424493075772",
                "7115241358255803683",
                "7306709804234444072",
                "7520190707093654844",
                "7093706918492917033",
            }
            & {item["video_id"] for item in context["selected_videos"]}
        )
        self.assertEqual(
            self.context_module.required_constraint_support_failures(
                {"technique_variant": ["drop_reverse_slice"]},
                {"technique_variant": "unspecified_support"},
                self.selection_rules,
            ),
            ["specific_technique_not_supported"],
        )
        forehand = self.context_module.prepare_answer_context(
            "正手滑板怎么打",
            local_personalization=False,
        )
        self.assertEqual(forehand["selected_videos"], [])

    def test_slice_drop_and_basic_drop_do_not_cross_prove_each_other(self):
        slice_constraints = self.context_module.query_constraints(
            self.search_module,
            "劈吊怎么打",
            self.selection_rules,
        )
        self.assertEqual(
            slice_constraints,
            {
                "shot_family": ["drop"],
                "technique_variant": ["drop_slice"],
            },
        )
        slice_context = self.context_module.prepare_answer_context(
            "劈吊怎么打",
            local_personalization=False,
        )
        slice_selected = {
            item["video_id"] for item in slice_context["selected_videos"]
        }
        self.assertIn("7306709804234444072", slice_selected)
        self.assertFalse(
            {
                "7214304020775652620",
                "7520190707093654844",
                "7115241358255803683",
            }
            & slice_selected
        )

        basic_context = self.context_module.prepare_answer_context(
            "普通吊球怎么打",
            local_personalization=False,
        )
        self.assertEqual(
            basic_context["question_interpretation"]["constraints"],
            {
                "shot_family": ["drop"],
                "technique_variant": ["drop_basic"],
            },
        )
        basic_selected = {
            item["video_id"] for item in basic_context["selected_videos"]
        }
        self.assertIn("7520190707093654844", basic_selected)
        self.assertFalse(
            {"7306709804234444072", "7214304020775652620"}
            & basic_selected
        )

    def test_doubles_net_pressure_keeps_front_sources_and_rejects_smashes(self):
        context = self.context_module.prepare_answer_context(
            "双打封网怎么压球",
            local_personalization=False,
            include_rejected=True,
        )
        selected = {
            item["video_id"] for item in context["selected_videos"]
        }
        self.assertEqual(
            selected,
            {"7077740726926298402", "7607852875611759802"},
        )
        hard_negatives = [
            "7445495930280856892",
            "7506362888166083897",
            "7659991105622862457",
        ]
        for video_id in hard_negatives:
            self.assertNotIn(video_id, selected)

        rejected = {
            item["video_id"]: item["reasons"]
            for item in context["rejected_candidates"]
        }
        for video_id in hard_negatives:
            self.assertTrue(
                any(
                    reason.startswith("explicit_constraint_conflict:")
                    or reason == "specific_stroke_intent_not_supported"
                    or reason == "recall_safeguard_only"
                    for reason in rejected[video_id]
                )
            )

        midcourt = self.context_module.prepare_answer_context(
            "中前场怎么把球压下去",
            local_personalization=False,
        )
        self.assertEqual(
            {item["video_id"] for item in midcourt["selected_videos"]},
            {"7193151905139395872", "7607852875611759802"},
        )

        forecourt = self.context_module.prepare_answer_context(
            "双打网前怎么下压",
            local_personalization=False,
            include_rejected=True,
        )
        self.assertEqual(
            {item["video_id"] for item in forecourt["selected_videos"]},
            {"7077740726926298402", "7607852875611759802"},
        )
        forecourt_rejected = {
            item["video_id"]: item["reasons"]
            for item in forecourt["rejected_candidates"]
        }
        for video_id in [
            "7205399670959459623",
            "7322291358931127592",
        ]:
            self.assertIn(
                "specific_pressure_court_zone_not_supported",
                forecourt_rejected[video_id],
            )

        rearcourt = self.context_module.prepare_answer_context(
            "后场怎么下压",
            local_personalization=False,
        )
        self.assertNotIn(
            "7205399670959459623",
            {item["video_id"] for item in rearcourt["selected_videos"]},
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

        pronoun_serve = self.context_module.query_actor_context(
            self.search_module,
            "他总发高远球，我怎么接",
            self.selection_rules,
        )
        self.assertEqual(
            pronoun_serve["player_constraints"], {"serve_role": ["receive"]}
        )
        self.assertEqual(
            pronoun_serve["opponent_constraints"],
            {
                "shot_family": ["deep_serve"],
                "serve_role": ["serve"],
                "serve_trajectory": ["deep_serve"],
            },
        )

        pronoun_smash = self.context_module.query_actor_context(
            self.search_module,
            "他总杀我反手位，我怎么防",
            self.selection_rules,
        )
        self.assertEqual(
            pronoun_smash["player_constraints"],
            {"stroke_side": ["backhand"], "tactical_phase": ["defense"]},
        )
        self.assertEqual(
            pronoun_smash["opponent_constraints"],
            {"shot_family": ["smash"], "tactical_phase": ["attack"]},
        )

        pronoun_drop = self.context_module.query_actor_context(
            self.search_module,
            "她总吊我正手位，我怎么防",
            self.selection_rules,
        )
        self.assertEqual(
            pronoun_drop["player_constraints"],
            {"stroke_side": ["forehand"], "tactical_phase": ["defense"]},
        )
        self.assertEqual(
            pronoun_drop["opponent_constraints"],
            {"shot_family": ["drop"]},
        )

        other_backhand = self.context_module.query_actor_context(
            self.search_module,
            "其他反手问题怎么处理",
            self.selection_rules,
        )
        self.assertEqual(
            other_backhand["player_constraints"], {"stroke_side": ["backhand"]}
        )
        self.assertEqual(other_backhand["opponent_constraints"], {})

        partner_weakness = self.context_module.query_actor_context(
            self.search_module,
            "搭档反手弱，我应该怎么补位",
            self.selection_rules,
        )
        self.assertEqual(partner_weakness["target_actor"], "player")
        self.assertEqual(
            partner_weakness["target_constraints"],
            {"discipline": ["doubles"]},
        )
        self.assertEqual(
            partner_weakness["derived_target_constraints"],
            {"discipline": ["doubles"]},
        )
        self.assertEqual(
            partner_weakness["partner_constraints"],
            {"stroke_side": ["backhand"]},
        )

        partner_serve = self.context_module.query_actor_context(
            self.search_module,
            "队友发球总被扑，我怎么站位",
            self.selection_rules,
        )
        self.assertEqual(partner_serve["target_actor"], "player")
        self.assertEqual(partner_serve["player_constraints"], {})
        self.assertEqual(
            partner_serve["target_constraints"],
            {"discipline": ["doubles"]},
        )
        self.assertEqual(
            partner_serve["partner_constraints"],
            {"serve_role": ["serve"]},
        )

        partner_target = self.context_module.query_actor_context(
            self.search_module,
            "我的反手弱，搭档应该怎么补位",
            self.selection_rules,
        )
        self.assertEqual(partner_target["target_actor"], "partner")
        self.assertEqual(
            partner_target["target_constraints"],
            {"discipline": ["doubles"]},
        )
        self.assertEqual(
            partner_target["player_constraints"],
            {"stroke_side": ["backhand"]},
        )

        partner_pronoun = self.context_module.query_actor_context(
            self.search_module,
            "队友反手弱，他应该怎么站位",
            self.selection_rules,
        )
        self.assertEqual(partner_pronoun["target_actor"], "partner")
        self.assertEqual(partner_pronoun["opponent_query"], "")
        self.assertIn("他应该怎么站位", partner_pronoun["partner_query"])
        self.assertEqual(
            partner_pronoun["target_constraints"],
            {
                "stroke_side": ["backhand"],
                "discipline": ["doubles"],
            },
        )

        feeder = self.context_module.query_actor_context(
            self.search_module,
            "陪练给我发高远球，我怎么接",
            self.selection_rules,
        )
        self.assertEqual(feeder["target_actor"], "player")
        self.assertEqual(feeder["player_constraints"], {"serve_role": ["receive"]})
        self.assertEqual(
            feeder["opponent_constraints"],
            {
                "shot_family": ["deep_serve"],
                "serve_role": ["serve"],
                "serve_trajectory": ["deep_serve"],
            },
        )

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

        pronoun_serve = self.context_module.prepare_answer_context(
            "他总发高远球，我怎么接",
            max_videos=4,
            local_personalization=False,
        )
        pronoun_serve_ids = {
            item["video_id"] for item in pronoun_serve["selected_videos"]
        }
        self.assertIn("7639306481355832689", pronoun_serve_ids)
        self.assertNotIn("7517867684509420857", pronoun_serve_ids)
        self.assertNotIn("7508222669708463420", pronoun_serve_ids)
        for item in pronoun_serve["selected_videos"]:
            self.assertIn(
                "receive",
                item["constraint_scope"]["serve_role"]["values"],
            )

        pronoun_smash = self.context_module.prepare_answer_context(
            "他总杀我反手位，我怎么防",
            local_personalization=False,
            include_rejected=True,
        )
        self.assertTrue(pronoun_smash["selected_videos"])
        for item in pronoun_smash["selected_videos"]:
            self.assertIn(
                "defense",
                item["constraint_scope"]["tactical_phase"]["values"],
            )
        pronoun_smash_rejected = {
            item["video_id"]: item["reasons"]
            for item in pronoun_smash["rejected_candidates"]
        }
        self.assertIn(
            "derived_player_constraint_not_supported:tactical_phase",
            pronoun_smash_rejected["7499776424493075772"],
        )

        partner_weakness = self.context_module.prepare_answer_context(
            "搭档反手弱，我应该怎么补位",
            local_personalization=False,
            include_rejected=True,
        )
        partner_weakness_ids = {
            item["video_id"] for item in partner_weakness["selected_videos"]
        }
        self.assertIn("7074399231259266344", partner_weakness_ids)
        self.assertNotIn("7499776424493075772", partner_weakness_ids)
        partner_weakness_rejected = {
            item["video_id"]: item["reasons"]
            for item in partner_weakness["rejected_candidates"]
        }
        self.assertIn(
            "partner_context_not_supported",
            partner_weakness_rejected["7499776424493075772"],
        )
        self.assertIn(
            "explicit_constraint_conflict:discipline",
            partner_weakness_rejected["7115241358255803683"],
        )
        for item in partner_weakness["selected_videos"]:
            self.assertNotEqual(
                item["constraint_scope"]["discipline"]["values"],
                ["singles"],
            )

        partner_serve = self.context_module.prepare_answer_context(
            "队友发球总被扑，我怎么站位",
            local_personalization=False,
            include_rejected=True,
        )
        partner_serve_ids = {
            item["video_id"] for item in partner_serve["selected_videos"]
        }
        self.assertIn("7656927370758796145", partner_serve_ids)
        self.assertNotIn("7489412105641168187", partner_serve_ids)

        partner_target = self.context_module.prepare_answer_context(
            "我的反手弱，搭档应该怎么补位",
            local_personalization=False,
            include_rejected=True,
        )
        self.assertEqual(
            partner_target["question_interpretation"]["actor_context"][
                "target_actor"
            ],
            "partner",
        )
        partner_target_ids = {
            item["video_id"] for item in partner_target["selected_videos"]
        }
        self.assertNotIn("7499776424493075772", partner_target_ids)

        partner_pronoun = self.context_module.prepare_answer_context(
            "队友反手弱，他应该怎么站位",
            local_personalization=False,
            include_rejected=True,
        )
        self.assertEqual(
            partner_pronoun["question_interpretation"]["actor_context"][
                "target_actor"
            ],
            "partner",
        )
        partner_pronoun_ids = {
            item["video_id"] for item in partner_pronoun["selected_videos"]
        }
        self.assertIn("7656927370758796145", partner_pronoun_ids)
        self.assertNotIn("7115241358255803683", partner_pronoun_ids)
        self.assertNotIn("7475440958130097466", partner_pronoun_ids)

        for query in [
            "陪练给我发高远球，我怎么接",
            "发球机给我发高远球，我怎么接",
        ]:
            with self.subTest(query=query):
                feeder = self.context_module.prepare_answer_context(
                    query,
                    max_videos=6,
                    local_personalization=False,
                )
                feeder_ids = {
                    item["video_id"] for item in feeder["selected_videos"]
                }
                self.assertIn("7639306481355832689", feeder_ids)
                self.assertNotIn("7517867684509420857", feeder_ids)
                self.assertNotIn("7508222669708463420", feeder_ids)
                for item in feeder["selected_videos"]:
                    self.assertIn(
                        "receive",
                        item["constraint_scope"]["serve_role"]["values"],
                    )

    def test_target_conditions_do_not_replace_requested_positioning_actions(self):
        backhand_positioning = self.context_module.prepare_answer_context(
            "我反手弱，应该怎么站位",
            local_personalization=False,
            include_rejected=True,
        )
        actor_context = backhand_positioning["question_interpretation"][
            "actor_context"
        ]
        self.assertEqual(actor_context["target_action_query"], "应该怎么站位")
        self.assertEqual(actor_context["target_condition_query"], "我反手弱")
        self.assertEqual(actor_context["target_action_constraints"], {})
        self.assertEqual(
            actor_context["target_condition_constraints"],
            {"stroke_side": ["backhand"]},
        )
        self.assertEqual(actor_context["requested_action_scopes"], ["positioning"])
        self.assertEqual(backhand_positioning["selected_videos"], [])
        backhand_rejected = {
            item["video_id"]: item["reasons"]
            for item in backhand_positioning["rejected_candidates"]
        }
        self.assertIn(
            "requested_action_wrong_actor:positioning",
            backhand_rejected["7115241358255803683"],
        )

        backhand_practice = self.context_module.prepare_answer_context(
            "我反手弱，应该怎么练",
            max_videos=8,
            local_personalization=False,
        )
        self.assertIn(
            "7060717442825309480",
            {item["video_id"] for item in backhand_practice["selected_videos"]},
        )
        self.assertEqual(
            backhand_practice["question_interpretation"]["actor_context"][
                "requested_action_scopes"
            ],
            [],
        )

        serve_positioning = self.context_module.prepare_answer_context(
            "我发球总被扑，应该怎么站位",
            max_videos=12,
            local_personalization=False,
            include_rejected=True,
        )
        serve_positioning_ids = {
            item["video_id"] for item in serve_positioning["selected_videos"]
        }
        self.assertIn("7475440958130097466", serve_positioning_ids)
        self.assertIn("7252154554828033295", serve_positioning_ids)
        self.assertNotIn("7489412105641168187", serve_positioning_ids)
        self.assertNotIn("7413335844594994447", serve_positioning_ids)

        smash_positioning = self.context_module.prepare_answer_context(
            "我杀球后回不来，应该怎么站位",
            local_personalization=False,
            include_rejected=True,
        )
        self.assertEqual(smash_positioning["selected_videos"], [])
        smash_rejected = {
            item["video_id"]: item
            for item in smash_positioning["rejected_candidates"]
        }
        self.assertEqual(
            smash_rejected["7130069152592645411"]["constraint_match"][
                "tactical_phase"
            ],
            "conflict",
        )

        backreferenced_positioning = self.context_module.prepare_answer_context(
            "我站位总偏，应该怎么改",
            max_videos=10,
            local_personalization=False,
            include_rejected=True,
        )
        backreferenced_actor = backreferenced_positioning[
            "question_interpretation"
        ]["actor_context"]
        self.assertTrue(
            backreferenced_actor["target_action_backreferences_condition"]
        )
        self.assertEqual(
            backreferenced_actor["requested_action_scopes"], ["positioning"]
        )
        backreferenced_ids = {
            item["video_id"]
            for item in backreferenced_positioning["selected_videos"]
        }
        self.assertIn("7220984919747497255", backreferenced_ids)
        self.assertNotIn("7115241358255803683", backreferenced_ids)
        self.assertNotIn("7063638911301520680", backreferenced_ids)

        rotation = self.context_module.prepare_answer_context(
            "我双打轮转总慢，应该怎么改",
            max_videos=10,
            local_personalization=False,
        )
        rotation_ids = {
            item["video_id"] for item in rotation["selected_videos"]
        }
        self.assertIn("7614167503938610417", rotation_ids)
        self.assertIn("7656927370758796145", rotation_ids)
        self.assertNotIn("7072543702161296640", rotation_ids)
        self.assertNotIn("7501542236061420859", rotation_ids)

    def test_action_scope_fallback_requires_every_explicit_constraint(self):
        defense = self.context_module.prepare_answer_context(
            "双打防守站位怎么调整",
            local_personalization=False,
            include_rejected=True,
        )
        defense_ids = {
            item["video_id"] for item in defense["selected_videos"]
        }
        self.assertIn("7656927370758796145", defense_ids)
        self.assertIn("7220984919747497255", defense_ids)
        self.assertNotIn("7246960976459730191", defense_ids)
        self.assertNotIn("7498830855188942137", defense_ids)

        generic = self.context_module.prepare_answer_context(
            "双打站位怎么调整",
            local_personalization=False,
        )
        generic_ids = {
            item["video_id"] for item in generic["selected_videos"]
        }
        self.assertIn("7246960976459730191", generic_ids)
        self.assertIn("7498830855188942137", generic_ids)

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

    def test_source_actor_mentions_do_not_prove_player_serving_role(self):
        synthetic_cases = [
            "发球机连续送球练防守",
            "对着墙发球发高一点练网前控球",
            "你给我发球，我打你任意两个点",
            "陪练发球以后我练接发",
        ]
        for evidence in synthetic_cases:
            with self.subTest(evidence=evidence):
                video = {
                    "video_id": "7000000000000000004",
                    "title": "训练示范",
                    "category": "发球与接发",
                    "tags": [],
                    "teaching_note": {
                        "topic": "训练示范",
                        "key_evidence": [{"text": evidence}],
                    },
                }
                plan = self.search_module.plan_query("发球怎么练")
                allowed, failures, _, scope, matches = (
                    self.context_module.constraint_decision(
                        self.search_module,
                        "发球怎么练",
                        plan,
                        video,
                        self.selection_rules,
                    )
                )
                self.assertFalse(allowed)
                self.assertIn(
                    "explicit_constraint_conflict:serve_role", failures
                )
                self.assertEqual(matches["serve_role"], "conflict")
                self.assertNotIn("serve", scope["serve_role"]["values"])
                self.assertIn(
                    "serve", scope["serve_role"]["suppressed_values"]
                )

    def test_broad_net_category_does_not_prove_every_specific_technique(self):
        video = {
            "video_id": "7000000000000000005",
            "title": "网前框架练习",
            "category": "网前技术",
            "tags": [],
            "teaching_note": {
                "topic": "网前框架练习",
                "key_evidence": [{"text": "保持身体放松并提前伸拍"}],
            },
        }
        scope = self.context_module.video_constraint_scope(
            self.search_module,
            video,
            self.selection_rules,
        )
        self.assertEqual(scope["technique_variant"]["values"], [])
        self.assertEqual(
            scope["technique_variant"]["source"], "unspecified"
        )

        push = self.context_module.prepare_answer_context(
            "推球怎么打",
            local_personalization=False,
        )
        push_by_id = {
            item["video_id"]: item for item in push["selected_videos"]
        }
        self.assertIn("7054786188086955276", push_by_id)
        direct = push_by_id["7054786188086955276"]
        self.assertEqual(
            direct["constraint_scope"]["technique_variant"]["values"],
            ["net_push"],
        )
        self.assertEqual(
            direct["constraint_scope"]["technique_variant"]["source"],
            "structured_evidence",
        )
        self.assertEqual(
            direct["constraint_match"]["technique_variant"],
            "incidental_support",
        )
        self.assertNotIn("7661940775983482097", push_by_id)

    def test_real_feeder_and_machine_videos_do_not_enter_serve_answers(self):
        invalid_ids = {
            "7078487171803467042",
            "7275536378321014051",
            "7276646497377176872",
            "7491244893893938492",
        }
        retained_direct_ids = {
            "7072543702161296640",
            "7522041413614816570",
        }
        for query in [
            "发球怎么发得更稳定",
            "反手发球怎么练",
            "发小球怎么发",
        ]:
            with self.subTest(query=query):
                payload = self.context_module.prepare_answer_context(
                    query,
                    local_personalization=False,
                    include_rejected=True,
                )
                selected_ids = {
                    item["video_id"] for item in payload["selected_videos"]
                }
                self.assertTrue(invalid_ids.isdisjoint(selected_ids))
                self.assertTrue(retained_direct_ids & selected_ids)

                if query == "反手发球怎么练":
                    self.assertNotIn("7499776424493075772", selected_ids)

        generic = self.context_module.prepare_answer_context(
            "发球怎么发得更稳定",
            local_personalization=False,
            include_rejected=True,
        )
        rejected = {
            item["video_id"]: item["reasons"]
            for item in generic["rejected_candidates"]
        }
        for video_id in invalid_ids:
            self.assertIn(
                "explicit_constraint_conflict:serve_role",
                rejected[video_id],
            )

        backhand = self.context_module.prepare_answer_context(
            "反手发球怎么练",
            local_personalization=False,
            include_rejected=True,
        )
        backhand_rejected = {
            item["video_id"]: item["reasons"]
            for item in backhand["rejected_candidates"]
        }
        self.assertIn(
            "explicit_cross_axis_conflict:serve_role_vs_shot_family",
            backhand_rejected["7499776424493075772"],
        )

        receive = self.context_module.prepare_answer_context(
            "接发球怎么准备",
            local_personalization=False,
        )
        receive_ids = {
            item["video_id"] for item in receive["selected_videos"]
        }
        self.assertIn("7501542236061420859", receive_ids)
        self.assertIn("7124871920230632745", receive_ids)
        self.assertNotIn("7275536378321014051", receive_ids)
        self.assertNotIn("7276646497377176872", receive_ids)

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
        for video_id in [
            "7060717442825309480",
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
            jump_smash["question_interpretation"]["constraints"],
            {
                "stroke_side": ["backhand"],
                "shot_family": ["smash"],
                "technique_variant": ["smash_jump_backhand"],
                "tactical_phase": ["attack"],
            },
        )
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
        self.assertNotIn("7092959332047785250", net_drop_by_id)

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
                "7485692231404342586",
                "7484563688096091449",
                "7567155406117533051",
                "7659991105622862457",
                "7445495930280856892",
            },
        )
        self.assertEqual(
            smash_by_id["7659991105622862457"]["role"], "supporting"
        )
        self.assertNotIn("7550305145877155131", smash_ids)
        self.assertNotIn("7115241358255803683", smash_ids)

    def test_point_smash_requires_direct_variant_evidence(self):
        payload = self.context_module.prepare_answer_context(
            "点杀怎么打",
            local_personalization=False,
            include_rejected=True,
        )
        self.assertEqual(
            payload["question_interpretation"]["constraints"],
            {
                "shot_family": ["smash"],
                "technique_variant": ["smash_point"],
                "tactical_phase": ["attack"],
            },
        )
        selected_order = [
            item["video_id"] for item in payload["selected_videos"]
        ]
        self.assertEqual(
            selected_order,
            [
                "7272944156618542336",
                "7093706918492917033",
                "7125615679402724623",
            ],
        )
        selected = set(selected_order)
        hard_negatives = {
            "7611635851789771721",
            "7659348110628345210",
            "7506362888166083897",
            "7659991105622862457",
            "7550305145877155131",
            "7055491154288102667",
            "7193151905139395872",
            "7148990784363138344",
            "7069575740836023587",
        }
        self.assertFalse(selected & hard_negatives)

    def test_basic_and_slice_smashes_require_the_named_variant(self):
        basic = self.context_module.prepare_answer_context(
            "普通杀球怎么打",
            local_personalization=False,
            include_rejected=True,
        )
        self.assertEqual(
            basic["question_interpretation"]["constraints"],
            {
                "shot_family": ["smash"],
                "technique_variant": ["smash_basic"],
                "tactical_phase": ["attack"],
            },
        )
        basic_ids = {
            item["video_id"] for item in basic["selected_videos"]
        }
        self.assertEqual(
            basic_ids,
            {
                "7229506261136526647",
                "7567155406117533051",
                "7485692231404342586",
                "7052519937125911846",
                "7052600326116887812",
                "7659348110628345210",
                "7453420876076240188",
            },
        )
        self.assertFalse(
            basic_ids
            & {
                "7659991105622862457",
                "7272944156618542336",
                "7055491154288102667",
                "7550305145877155131",
                "7059589039694957864",
                "7068465954270792994",
                "7098897570482670888",
            }
        )

        sliced = self.context_module.prepare_answer_context(
            "劈杀怎么打",
            local_personalization=False,
            include_rejected=True,
        )
        self.assertEqual(
            sliced["question_interpretation"]["constraints"],
            {
                "shot_family": ["smash"],
                "technique_variant": ["smash_slice"],
                "tactical_phase": ["attack"],
            },
        )
        self.assertEqual(
            [item["video_id"] for item in sliced["selected_videos"]],
            ["7059589039694957864"],
        )
        self.assertFalse(
            {
                "7306709804234444072",
                "7174229898238676228",
                "7118192644957818127",
                "7229889111706848544",
                "7511934047901846841",
                "7485692231404342586",
                "7659991105622862457",
            }
            & {item["video_id"] for item in sliced["selected_videos"]}
        )

    def test_jump_smash_requires_direct_forehand_variant_evidence(self):
        generic = self.context_module.prepare_answer_context(
            "跳杀怎么打",
            local_personalization=False,
            include_rejected=True,
        )
        self.assertEqual(
            generic["question_interpretation"]["constraints"],
            {
                "shot_family": ["smash"],
                "technique_variant": ["smash_jump"],
                "tactical_phase": ["attack"],
            },
        )
        expected = {
            "7161980324409363712",
            "7055491154288102667",
            "7138604160051612969",
            "7634016952800880570",
            "7606560547489149691",
            "7561558424342056250",
            "7506362888166083897",
        }
        generic_ids = {
            item["video_id"] for item in generic["selected_videos"]
        }
        self.assertEqual(generic_ids, expected)

        forehand = self.context_module.prepare_answer_context(
            "正手跳杀怎么打",
            local_personalization=False,
        )
        self.assertEqual(
            forehand["question_interpretation"]["constraints"],
            {
                "stroke_side": ["forehand"],
                "shot_family": ["smash"],
                "technique_variant": ["smash_jump"],
                "tactical_phase": ["attack"],
            },
        )
        forehand_ids = {
            item["video_id"] for item in forehand["selected_videos"]
        }
        self.assertEqual(forehand_ids, expected)
        hard_negatives = {
            "7499776424493075772",
            "7069575740836023587",
            "7068835198938516777",
            "7083684012513840424",
            "7097413480747191587",
            "7567860375287303035",
            "7096301894984846632",
            "7246960976459730191",
        }
        self.assertFalse(generic_ids & hard_negatives)
        self.assertFalse(forehand_ids & hard_negatives)

    def test_backhand_smash_variants_require_matching_direct_segments(self):
        ordinary = self.context_module.prepare_answer_context(
            "反手杀球怎么打",
            local_personalization=False,
            include_rejected=True,
        )
        self.assertEqual(
            ordinary["question_interpretation"]["constraints"],
            {
                "stroke_side": ["backhand"],
                "shot_family": ["smash"],
                "technique_variant": ["smash_backhand_basic"],
                "tactical_phase": ["attack"],
            },
        )
        ordinary_ids = {
            item["video_id"] for item in ordinary["selected_videos"]
        }
        self.assertEqual(
            ordinary_ids,
            {
                "7550305145877155131",
                "7202800263588105510",
                "7288529711267859747",
            },
        )

        spinning = self.context_module.prepare_answer_context(
            "反手转圈杀怎么打",
            local_personalization=False,
            include_rejected=True,
        )
        self.assertEqual(
            spinning["question_interpretation"]["constraints"],
            {
                "stroke_side": ["backhand"],
                "shot_family": ["smash"],
                "technique_variant": ["smash_backhand_spin"],
                "tactical_phase": ["attack"],
            },
        )
        spinning_ids = {
            item["video_id"] for item in spinning["selected_videos"]
        }
        self.assertEqual(
            spinning_ids,
            {"7098897570482670888", "7202800263588105510"},
        )

        jumping = self.context_module.prepare_answer_context(
            "反手跳杀怎么打",
            local_personalization=False,
        )
        jumping_ids = {
            item["video_id"] for item in jumping["selected_videos"]
        }
        self.assertEqual(jumping_ids, {"7499776424493075772"})
        self.assertEqual(
            ordinary_ids & spinning_ids,
            {"7202800263588105510"},
        )
        self.assertFalse(ordinary_ids & jumping_ids)
        self.assertFalse(spinning_ids & jumping_ids)

        alias = self.context_module.prepare_answer_context(
            "转圈杀怎么打",
            local_personalization=False,
        )
        self.assertEqual(
            alias["question_interpretation"]["constraints"],
            {
                "shot_family": ["smash"],
                "technique_variant": ["smash_backhand_spin"],
                "tactical_phase": ["attack"],
            },
        )
        self.assertEqual(
            {item["video_id"] for item in alias["selected_videos"]},
            spinning_ids,
        )

    def test_named_missing_actions_use_direct_sources_and_preserve_boundaries(self):
        expected = {
            "平高球怎么打": {
                "7498295344284093755",
                "7125615679402724623",
            },
            "假挑真放怎么做": {"7151961376448138531"},
            "动态低架怎么做": {"7589749293205363633"},
            "远网怎么打": {
                "7411850466457292084",
                "7262546080133401890",
                "7076257912192060707",
                "7258462271670586658",
            },
            "杀上网怎么练": {
                "7065157571816000809",
                "7092959332047785250",
                "7087759120761228578",
                "7093706918492917033",
            },
        }
        contexts = {}
        for query, expected_ids in expected.items():
            context = self.context_module.prepare_answer_context(
                query,
                local_personalization=False,
                include_rejected=True,
            )
            contexts[query] = context
            self.assertEqual(
                {item["video_id"] for item in context["selected_videos"]},
                expected_ids,
            )

        flat_clear_rejected = {
            item["video_id"]
            for item in contexts["平高球怎么打"]["rejected_candidates"]
        }
        self.assertTrue(
            {
                "7066596981992394025",
                "7193151905139395872",
                "7064753436809514281",
                "7105205741954321699",
                "7055130343476710667",
                "7054025391601650948",
            }.issubset(flat_clear_rejected)
        )

        fake_rejected = {
            item["video_id"]
            for item in contexts["假挑真放怎么做"]["rejected_candidates"]
        }
        self.assertIn("7151589626031901992", fake_rejected)

        far_net = contexts["远网怎么打"]
        self.assertEqual(
            [item["name"] for item in far_net["question_interpretation"]["ambiguities"]],
            ["far_net_context"],
        )

        kill_to_net_rejected = {
            item["video_id"]
            for item in contexts["杀上网怎么练"]["rejected_candidates"]
        }
        self.assertTrue(
            {
                "7142313105324870950",
                "7099644893269839144",
                "7445495930280856892",
                "7195014413932367116",
                "7659348110628345210",
                "7252154554828033295",
            }.issubset(kill_to_net_rejected)
        )

    def test_far_net_subtypes_are_mutually_scoped(self):
        cases = {
            "平搓远网怎么打": {"7411850466457292084"},
            "中路远网怎么处理": {
                "7262546080133401890",
                "7076257912192060707",
            },
            "防远网转推怎么练": {"7258462271670586658"},
            "远网吊球怎么打": {"7093706918492917033"},
        }
        for query, expected_ids in cases.items():
            context = self.context_module.prepare_answer_context(
                query,
                local_personalization=False,
            )
            self.assertEqual(
                {item["video_id"] for item in context["selected_videos"]},
                expected_ids,
            )
            self.assertEqual(context["question_interpretation"]["ambiguities"], [])

    def test_heavy_and_overlord_smashes_require_direct_variant_evidence(self):
        heavy = self.context_module.prepare_answer_context(
            "重杀怎么打",
            local_personalization=False,
            include_rejected=True,
        )
        self.assertEqual(
            heavy["question_interpretation"]["constraints"],
            {
                "shot_family": ["smash"],
                "technique_variant": ["smash_heavy"],
                "tactical_phase": ["attack"],
            },
        )
        heavy_ids = {
            item["video_id"] for item in heavy["selected_videos"]
        }
        self.assertEqual(
            heavy_ids,
            {
                "7551459420703837498",
                "7659991105622862457",
                "7484563688096091449",
                "7383154379915906319",
                "7506362888166083897",
                "7125615679402724623",
                "7445495930280856892",
            },
        )

        overlord = self.context_module.prepare_answer_context(
            "霸王杀怎么打",
            local_personalization=False,
            include_rejected=True,
        )
        self.assertEqual(
            overlord["question_interpretation"]["constraints"],
            {
                "shot_family": ["smash"],
                "technique_variant": ["smash_overlord"],
                "tactical_phase": ["attack"],
            },
        )
        overlord_ids = {
            item["video_id"] for item in overlord["selected_videos"]
        }
        self.assertEqual(
            overlord_ids,
            {
                "7068465954270792994",
                "7068092085533953315",
                "7067722128413543680",
            },
        )
        hard_negatives = {
            "7656560952972884730",
            "7611635851789771721",
            "7606412946096327978",
            "7573211923485260537",
            "7486788550298471739",
            "7272944156618542336",
            "7161980324409363712",
            "7499776424493075772",
        }
        self.assertFalse(overlord_ids & hard_negatives)

    def test_fast_ground_stationary_and_light_smashes_keep_variant_boundaries(self):
        expected_constraints = {
            "shot_family": ["smash"],
            "tactical_phase": ["attack"],
        }
        cases = {
            "快杀怎么打": (
                "smash_fast",
                {
                    "7551459420703837498",
                    "7606412946096327978",
                    "7611635851789771721",
                    "7506362888166083897",
                },
            ),
            "遁地炮怎么打": (
                "smash_ground_cannon",
                {"7069575740836023587"},
            ),
            "定杀怎么打": (
                "smash_stationary",
                {"7069575740836023587"},
            ),
            "轻杀怎么打": (
                "smash_light",
                {"7093706918492917033"},
            ),
        }
        selected_by_variant = {}
        for query, (variant, expected_ids) in cases.items():
            with self.subTest(query=query):
                payload = self.context_module.prepare_answer_context(
                    query,
                    local_personalization=False,
                    include_rejected=True,
                )
                self.assertEqual(
                    payload["question_interpretation"]["constraints"],
                    {
                        **expected_constraints,
                        "technique_variant": [variant],
                    },
                )
                selected = {
                    item["video_id"] for item in payload["selected_videos"]
                }
                self.assertEqual(selected, expected_ids)
                selected_by_variant[variant] = selected

        variants = list(selected_by_variant)
        for index, left in enumerate(variants):
            for right in variants[index + 1 :]:
                shared = selected_by_variant[left] & selected_by_variant[right]
                if {left, right} == {
                    "smash_ground_cannon",
                    "smash_stationary",
                }:
                    self.assertEqual(shared, {"7069575740836023587"})
                else:
                    self.assertFalse(shared)

        for spelling in ["顿地炮怎么打", "蹲地炮怎么打"]:
            with self.subTest(spelling=spelling):
                payload = self.context_module.prepare_answer_context(
                    spelling,
                    local_personalization=False,
                )
                self.assertEqual(
                    payload["question_interpretation"]["constraints"],
                    {
                        **expected_constraints,
                        "technique_variant": ["smash_ground_cannon"],
                    },
                )
                self.assertEqual(
                    [item["video_id"] for item in payload["selected_videos"]],
                    ["7069575740836023587"],
                )

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
