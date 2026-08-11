#!/usr/bin/env python3
import importlib.util
import json
import tempfile
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

    def test_retrieval_query_budget_preserves_required_units_and_hard_limit(self):
        original = "原始问题"
        units = [f"必要问题{i}" for i in range(30)]
        queries = [original, *units, *(f"扩展问题{i}" for i in range(40))]
        plan = {"retrieval_guidance": {"query_units": units}}
        selected, metadata = self.context_module.budget_retrieval_queries(
            self.search_module,
            queries,
            plan,
            original,
            {"retrieval_query_budget": 24, "retrieval_query_hard_limit": 48},
        )
        self.assertEqual(len(selected), 31)
        self.assertEqual(selected[0], original)
        self.assertTrue(set(units).issubset(selected))
        self.assertTrue(metadata["truncated"])
        self.assertEqual(metadata["missing_required_units"], [])

        too_many_units = [f"必要分支{i}" for i in range(60)]
        selected, metadata = self.context_module.budget_retrieval_queries(
            self.search_module,
            [original, *too_many_units],
            {"retrieval_guidance": {"query_units": too_many_units}},
            original,
            {"retrieval_query_budget": 24, "retrieval_query_hard_limit": 48},
        )
        self.assertEqual(len(selected), 48)
        self.assertEqual(len(metadata["missing_required_units"]), 13)

    def test_retrieval_query_budget_preserves_inferred_action_anchors(self):
        query = "对手吊网前我总是接不到"
        plan = self.search_module.plan_query(query)
        queries = self.context_module.planned_queries(
            self.search_module,
            plan,
            query,
            self.selection_rules,
        )
        selected, metadata = self.context_module.budget_retrieval_queries(
            self.search_module,
            queries,
            plan,
            query,
            {**self.selection_rules, "retrieval_query_budget": 8},
        )
        actor_context = self.context_module.query_actor_context(
            self.search_module,
            query,
            self.selection_rules,
        )
        self.assertLessEqual(len(selected), 8)
        self.assertTrue(
            set(actor_context["derived_search_terms"]).issubset(selected)
        )
        self.assertEqual(metadata["missing_required_units"], [])

    def test_runtime_prior_registry_isolated_from_evaluation_fixtures(self):
        self.assertTrue(self.module.evaluation_fixture_isolation())

    def test_runtime_prior_registry_rejects_renamed_copied_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixtures = root / "fixtures"
            fixtures.mkdir()
            (fixtures / "cases.json").write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "case_id": "AQ-001",
                                "query": "反手高远为什么只到中场？",
                                "gold": {
                                    "required_video_ids": ["video-gold-1"]
                                },
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            registry = root / "priors.json"
            registry.write_text(
                json.dumps(
                    {
                        "registry_type": "operational_feedback_runtime_prior",
                        "source": "data/review/retrieval_priors.json",
                        "evaluation_case_ids_forbidden": True,
                        "signals": [
                            {
                                "feedback_key": "OPF-999",
                                "query": "反手高远，为什么只到中场",
                                "required_video_ids": ["video-gold-1"],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            self.assertFalse(
                self.module.evaluation_fixture_isolation(registry, fixtures)
            )

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

    def test_multi_issue_constraints_do_not_cross_contaminate_units(self):
        first_query = "杀球后来不及上网"
        second_query = "正手握拍应该怎么握"
        combined = self.context_module.prepare_answer_context(
            f"{first_query}，同时{second_query}",
            local_personalization=False,
        )
        claims = {
            claim["text"]: claim
            for claim in combined["claim_evidence_map"]
            if claim["kind"] == "question_unit"
        }
        self.assertEqual(claims[first_query]["status"], "conditional")
        self.assertEqual(claims[second_query]["status"], "supported")
        self.assertTrue(claims[first_query]["eligible_video_labels"])
        self.assertTrue(claims[second_query]["eligible_video_labels"])
        unit_constraints = combined["question_interpretation"][
            "query_unit_constraints"
        ]
        self.assertIn("kill_to_net", unit_constraints[first_query]["technique_variant"])
        self.assertEqual(unit_constraints[second_query], {"stroke_side": ["forehand"]})

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
            "战戟9000S 3U和神速100X 4U二选一，请直接选型号并保证适合我": "purchase_advice",
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
            sorted(
                (item["label"] for item in context["selected_videos"]),
                key=lambda label: int(label[1:]),
            ),
            [
                f"V{index}"
                for index in range(1, len(context["selected_videos"]) + 1)
            ],
        )
        self.assertEqual(
            len({item["video_id"] for item in context["selected_videos"]}),
            len(context["selected_videos"]),
        )

    def test_answer_visible_labels_are_contiguous_and_compact(self):
        context = self.context_module.prepare_answer_context(
            "杀球下网而且不重，架拍、击球点、握拍、步法和发力分别怎么检查？",
            local_personalization=False,
        )
        visible_labels = context["answer_visible_video_labels"]
        self.assertEqual(len(visible_labels), 3)
        self.assertEqual(
            visible_labels,
            [f"V{index}" for index in range(1, len(visible_labels) + 1)],
        )
        packet = self.context_module.build_answer_packet(context)
        packet_runtime = self.context_module.load_sibling(
            "answer_context_packet_records", "answer_packet.py"
        )
        self.assertEqual(
            [
                video["label"]
                for video in packet_runtime.packet_video_records(packet)
            ],
            visible_labels,
        )
        self.assertEqual(
            packet["core_videos"],
            context["answer_core_video_labels"],
        )
        self.assertEqual(
            packet["complete_related_videos"],
            context["answer_complete_related_video_labels"],
        )
        self.assertIn(
            f"{packet['complete_related_videos'][0]} 最有价值",
            packet["feedback_prompt"],
        )
        self.assertIn(
            f"{packet['complete_related_videos'][-1]} 不相关",
            packet["feedback_prompt"],
        )

    def test_closed_plan_visibility_is_contiguous_and_packet_aligned(self):
        context = self.context_module.prepare_answer_context(
            "来不及接网前小球或者网前吊球怎么办",
            local_personalization=False,
        )
        packet = self.context_module.build_answer_packet(context)
        packet_runtime = self.context_module.load_sibling(
            "answer_context_packet_records", "answer_packet.py"
        )
        packet_labels = [
            video["label"]
            for video in packet_runtime.packet_video_records(packet)
        ]
        self.assertEqual(
            packet_labels,
            context["answer_visible_video_labels"],
        )
        self.assertEqual(
            packet_labels,
            [f"V{index}" for index in range(1, len(packet_labels) + 1)],
        )
        self.context_module.validate_answer_packet(packet, context)

    def test_grip_and_relaxation_concepts_survive_layered_selection(self):
        context = self.module.prepare_case_context(
            self.search_module,
            {"query": "握拍太紧挥拍僵硬怎么放松"},
        )
        selected = context["payload"]["selected_videos"]
        evidence_text = json.dumps(selected, ensure_ascii=False)
        self.assertIn("握拍", evidence_text)
        self.assertTrue(
            any(term in evidence_text for term in ["僵硬", "放松", "协调"])
        )
        self.assertEqual(
            len(selected),
            context["payload"]["selection"]["selected_video_count"],
        )

    def test_feedback_prompt_uses_only_labels_from_the_current_answer(self):
        multiple = self.context_module.prepare_answer_context(
            "双打封网怎么压球",
            local_personalization=False,
        )
        multiple_prompt = multiple["answer_contract"]["feedback_prompt"]
        visible_labels = multiple["answer_visible_video_labels"]
        complete_labels = multiple["answer_complete_related_video_labels"]
        self.assertTrue(visible_labels)
        self.assertEqual(complete_labels, visible_labels)
        self.assertIn(f"{complete_labels[0]} 最有价值", multiple_prompt)
        if len(complete_labels) > 1:
            self.assertIn(f"{complete_labels[-1]} 不相关", multiple_prompt)

        single = self.context_module.prepare_answer_context(
            "反手滑板怎么打",
            local_personalization=False,
        )
        single_prompt = single["answer_contract"]["feedback_prompt"]
        self.assertIn("V1 最有价值", single_prompt)
        single_labels = single["answer_complete_related_video_labels"]
        if len(single_labels) > 1:
            self.assertIn(f"{single_labels[-1]} 不相关", single_prompt)

        forehand = self.context_module.prepare_answer_context(
            "正手滑板怎么打",
            local_personalization=False,
        )
        forehand_prompt = forehand["answer_contract"]["feedback_prompt"]
        forehand_labels = forehand["answer_complete_related_video_labels"]
        self.assertTrue(forehand_labels)
        self.assertIn(f"{forehand_labels[0]} 最有价值", forehand_prompt)

        for prompt in [multiple_prompt, single_prompt, forehand_prompt]:
            self.assertIn("第 2 点结论不对", prompt)
            self.assertIn("回答漏了", prompt)
            self.assertIn("你理解错了，我真正问的是", prompt)

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

    def test_deep_serve_query_excludes_rear_court_stroke_video(self):
        context = self.context_module.prepare_answer_context(
            "发后场球怎么增加变化和隐蔽性？",
            max_videos=8,
            local_personalization=False,
        )
        selected_ids = {
            video["video_id"] for video in context["selected_videos"]
        }
        self.assertNotIn("7664908274752137146", selected_ids)
        self.assertTrue(context["selected_videos"])
        self.assertTrue(
            all(
                "serve"
                in video["constraint_scope"]["serve_role"]["values"]
                for video in context["selected_videos"]
            )
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
                "shot_family": ["net_shot"],
                "stroke_intent": ["downward_pressure"],
                "court_zone": ["forecourt", "midcourt"],
                "discipline": ["doubles"],
            },
        )
        self.assertNotEqual(net_pressure["shot_family"], ["smash"])
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
        selected_ids = [
            item["video_id"] for item in context["selected_videos"]
        ]
        self.assertTrue(
            {
                "7523163965838003514",
                "7511934047901846841",
                "7151961376448138531",
                "bilibili:BV1Gs421u7zw",
                "bilibili:BV1VpyBYmEtH",
            }.issubset(selected_ids)
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
        selected_ids = {
            item["video_id"] for item in context["selected_videos"]
        }
        self.assertGreaterEqual(len(selected_ids), 6)
        self.assertTrue(
            all(
                "transition"
                in item["constraint_scope"]["shot_family"]["values"]
                for item in context["selected_videos"]
            )
        )
        self.assertTrue(
            any(item["role"] == "core" for item in context["selected_videos"])
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
        synthesis_ids = set(
            context["selection"]["synthesis_candidate_video_ids"]
        )
        self.assertTrue(
            {
                "7215787369381858599",
                "7647839024535507897",
                "7117821949165718824",
                "7422121561559272739",
                "7141200093922790688",
                "7289635377009151247",
            }.issubset(synthesis_ids),
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
            {"7602766054809333617", "7621243051541587889"}.issubset(
                selected
            )
        )
        self.assertTrue(
            all(
                "smash_block"
                in item["constraint_scope"]["shot_family"]["values"]
                for item in context["selected_videos"]
            )
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
        self.assertIn(
            "7214304020775652620",
            context["selection"]["synthesis_candidate_video_ids"],
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
        self.assertTrue(forehand["selected_videos"])
        self.assertTrue(
            all(
                item["role"] == "supporting"
                and item["constraint_match"]["stroke_side"]
                == "unspecified_support"
                and item["claim_scope_policy"]
                in {
                    "component_or_generic_support_only_not_full_question_proof",
                    "additional_specific_scope_only_not_unrestricted_full_question_proof",
                }
                for item in forehand["selected_videos"]
            )
        )

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

    def test_bounded_supplemental_requires_direct_note_coverage(self):
        equipment = self.context_module.prepare_answer_context(
            "初学者低磅应该选高弹线还是耐打线？",
            local_personalization=False,
        )
        supplemental = next(
            item
            for item in equipment["selected_videos"]
            if item["video_id"] == "bilibili:BV1VJ4m1b7U7"
        )
        self.assertEqual(supplemental["answer_eligibility"], "supplemental")
        self.assertEqual(
            supplemental["runtime_evidence_mode"], "bounded_note_windows"
        )
        self.assertGreaterEqual(len(supplemental["bounded_note_evidence"]), 1)
        self.assertIn(
            supplemental["label"], equipment["answer_visible_video_labels"]
        )

        weak_title_overlap = self.context_module.prepare_answer_context(
            "双打网前怎么下压",
            local_personalization=False,
        )
        self.assertNotIn(
            "bilibili:BV1BDRCYFEFr",
            {item["video_id"] for item in weak_title_overlap["selected_videos"]},
        )

    def test_full_transcript_supplemental_can_corroborate_exact_claim(self):
        context = self.context_module.prepare_answer_context(
            "高远球髋带腿还是脚蹬地顶着髋？",
            local_personalization=False,
        )
        supplemental = next(
            item
            for item in context["selected_videos"]
            if item["video_id"] == "bilibili:BV1hByrBCEcE"
        )
        self.assertEqual(supplemental["answer_eligibility"], "supplemental")
        self.assertEqual(
            supplemental["runtime_evidence_mode"], "full_transcript"
        )
        self.assertIn(
            supplemental["label"], context["answer_visible_video_labels"]
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
        if "7499776424493075772" in partner_weakness_rejected:
            self.assertIn(
                "partner_context_not_supported",
                partner_weakness_rejected["7499776424493075772"],
            )
        if "7115241358255803683" in partner_weakness_rejected:
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
                self.assertTrue(feeder_ids)
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
        for video_id in [
            "bilibili:BV1byKAewE6d",
            "bilibili:BV1vx4y1e7Kp",
        ]:
            self.assertNotIn(
                video_id,
                {
                    item["video_id"]
                    for item in backhand_positioning["selected_videos"]
                },
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

    def test_partner_referents_survive_negation_and_object_pronouns(self):
        cases = [
            "我搭档反手比较弱，对方连续压他反手时，我应该怎么补位？",
            "我不是要教搭档反手，我想问他反手被压住时我站哪里补他？",
            "别教我队友怎么反手，我想知道对面追着打她反手时我该补哪边",
            "不是让搭档练反手；我问的是对面连续推他反手时，我站哪边帮他补空档",
            "我不想让同伴学反拍，我要问对手追着攻她反手时，自己怎么保护她的空当",
        ]
        for query in cases:
            with self.subTest(query=query):
                payload = self.context_module.prepare_answer_context(
                    query,
                    local_personalization=False,
                    include_rejected=True,
                )
                actor = payload["question_interpretation"]["actor_context"]
                self.assertEqual(
                    payload["question_interpretation"]["intent_frame"][
                        "requested_output"
                    ],
                    "coaching_answer",
                )
                self.assertIn("反手", actor["partner_query"])
                self.assertEqual(
                    actor["partner_constraints"]["stroke_side"], ["backhand"]
                )
                self.assertEqual(actor["target_actor"], "player")
                self.assertEqual(
                    actor["requested_action_scopes"],
                    ["team_coverage_rotation"],
                )
                self.assertEqual(
                    actor["derived_target_constraints"],
                    {"discipline": ["doubles"]},
                )
                selected = {
                    item["video_id"]: item
                    for item in payload["selected_videos"]
                }
                self.assertTrue(selected)
                self.assertTrue(
                    all(item["concept_match"] != "none" for item in selected.values())
                )

    def test_multi_actor_rotation_sequences_preserve_event_order(self):
        cases = {
            "我杀球后搭档退到后场，对手挡网，我该怎么轮转？": [
                ("player", "prior_action"),
                ("partner", "coverage_condition"),
                ("opponent", "response"),
                ("player", "target_action"),
            ],
            "我接杀挡网后，对手挑我搭档后场，我下一拍该守哪里？": [
                ("player", "prior_action"),
                ("opponent", "response"),
                ("partner", "coverage_condition"),
                ("player", "target_action"),
            ],
            "我重杀后队友已经退到底线，对面回放网，我下一拍要补哪里": [
                ("player", "prior_action"),
                ("partner", "coverage_condition"),
                ("opponent", "response"),
                ("player", "target_action"),
            ],
            "我点杀完，搭档退守后场，对手回了个网前小球，我是留前场还是一起退？": [
                ("player", "prior_action"),
                ("partner", "coverage_condition"),
                ("opponent", "response"),
                ("player", "target_action"),
            ],
            "我劈杀以后搭子守到后面，对手放短，我下一拍是守前面还是回撤": [
                ("player", "prior_action"),
                ("partner", "coverage_condition"),
                ("opponent", "response"),
                ("player", "target_action"),
            ],
            "我霸王杀后搭档守底线，对面回短球，我应该顶在前面还是往后退": [
                ("player", "prior_action"),
                ("partner", "coverage_condition"),
                ("opponent", "response"),
                ("player", "target_action"),
            ],
            "我挑球到后场后，搭档抢到网前，对手把球推过他身后；这时我应该退守哪块区域": [
                ("player", "prior_action"),
                ("partner", "coverage_condition"),
                ("opponent", "response"),
                ("player", "target_action"),
            ],
        }
        expected_ids = {
            "7656927370758796145",
            "7614167503938610417",
            "7106697344128748835",
        }
        for query, expected_chain in cases.items():
            with self.subTest(query=query):
                payload = self.context_module.prepare_answer_context(
                    query,
                    local_personalization=False,
                )
                actor = payload["question_interpretation"]["actor_context"]
                self.assertEqual(actor["target_action_query"], "双打轮转补位")
                self.assertEqual(
                    actor["requested_action_scopes"],
                    ["team_coverage_rotation"],
                )
                self.assertEqual(
                    [(item["actor"], item["role"]) for item in actor["event_chain"]],
                    expected_chain,
                )
                selected_ids = {
                    item["video_id"] for item in payload["selected_videos"]
                }
                self.assertTrue(selected_ids & expected_ids)
                self.assertNotIn("7071800926553541922", selected_ids)

    def test_action_scope_fallback_requires_every_explicit_constraint(self):
        defense = self.context_module.prepare_answer_context(
            "双打防守站位怎么调整",
            local_personalization=False,
            include_rejected=True,
        )
        defense_ids = {
            item["video_id"] for item in defense["selected_videos"]
        }
        self.assertNotIn("7656927370758796145", defense_ids)
        self.assertIn("7220984919747497255", defense_ids)
        self.assertNotIn("7246960976459730191", defense_ids)
        self.assertNotIn("7498830855188942137", defense_ids)
        defense_rejected = {
            item["video_id"]: item["reasons"]
            for item in defense["rejected_candidates"]
        }
        self.assertIn(
            "claim_evidence_not_authorized",
            defense_rejected["7656927370758796145"],
        )

        generic = self.context_module.prepare_answer_context(
            "双打站位怎么调整",
            local_personalization=False,
        )
        generic_ids = {
            item["video_id"] for item in generic["selected_videos"]
        }
        self.assertNotIn("7246960976459730191", generic_ids)
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
        self.assertEqual(
            payload["selection"]["eligible_video_count"],
            payload["selection"]["semantic_answerable_video_count"],
        )
        self.assertFalse(
            any("limit_exceeded" in reason for reasons in rejected.values() for reason in reasons)
        )
        retrieval_queries = payload["question_interpretation"]["retrieval_queries"]
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
        self.assertTrue(drive["selected_videos"])
        drive_synthesis_ids = set(
            drive["selection"]["synthesis_candidate_video_ids"]
        )
        self.assertTrue(
            all(
                "drive" in video["constraint_scope"]["shot_family"]["values"]
                or (
                    video["role"] == "supporting"
                    and "generic_constraint_support_only"
                    in video["selection_reasons"]
                )
                for video in drive["selected_videos"]
                if video["video_id"] in drive_synthesis_ids
            )
        )

        footwork = self.context_module.prepare_answer_context(
            "后场步法怎么练？",
            local_personalization=False,
        )
        self.assertTrue(footwork["selected_videos"])
        footwork_synthesis_ids = set(
            footwork["selection"]["synthesis_candidate_video_ids"]
        )
        self.assertTrue(
            all(
                video["focus_match"] in {"primary", "structured"}
                for video in footwork["selected_videos"]
                if video["video_id"] in footwork_synthesis_ids
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

    def test_focused_practice_request_returns_only_evidence_boundary(self):
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
        self.assertIsNone(context["topic_navigation"])
        self.assertEqual(
            [item["kind"] for item in context["delivery_contract"]["items"]],
            ["evidence.training_boundary"],
        )
        self.assertTrue(
            context["answer_contract"][
                "synthetic_training_prescriptions_forbidden"
            ]
        )
        self.assertEqual(
            context["clarification_decision"]["questions"],
            [
                "若想让答案更具体，可以补充最想解决的来球或动作场景、"
                "当前失败表现，以及期望的出球或落点。"
            ],
        )

    def test_readme_example_closes_intent_diagnosis_and_practice_contracts(self):
        context = self.context_module.prepare_answer_context(
            (
                "我是业余中级双打选手。对手杀到反手身体附近时，"
                "我挡网经常冒高。请帮我区分拍面、击球点和到位问题，"
                "并给一个有陪练、每次20分钟的训练方案。"
            ),
            local_personalization=False,
        )
        interpretation = context["question_interpretation"]
        self.assertEqual(
            interpretation["intent_frame"]["requested_output"], "practice"
        )
        self.assertNotIn(
            "team_coverage_rotation",
            interpretation["actor_context"]["requested_action_scopes"],
        )
        self.assertNotIn("陪练", interpretation["actor_context"]["opponent_query"])
        self.assertNotIn("我是业余中级双打选手", interpretation["query_units"])
        self.assertIn(
            "7524557392328461627",
            {video["video_id"] for video in context["selected_videos"]},
        )
        hypotheses = {
            item["text"]: item for item in context["diagnostic_model"]["user_hypotheses"]
        }
        self.assertEqual(hypotheses["拍面"]["status"], "conditional")
        self.assertEqual(hypotheses["击球点"]["status"], "conditional")
        selected_atoms = {
            item["atom_id"] for item in context["answer_plan"]["selected_evidence_atoms"]
        }
        self.assertIn("EA-NET-BLOCK-FACE-001", selected_atoms)
        self.assertIn("EA-NET-BLOCK-CONTACT-001", selected_atoms)

    def test_team_rotation_scope_uses_complete_action_terms(self):
        cases = {
            "双打请帮我分析挡网冒高": False,
            "双打请补充挡网说明": False,
            "双打帮搭档补位": True,
            "双打我该怎么补位": True,
        }
        for query, expected in cases.items():
            with self.subTest(query=query):
                actor = self.context_module.query_actor_context(
                    self.search_module,
                    query,
                    self.selection_rules,
                )
                self.assertEqual(
                    "team_coverage_rotation" in actor["requested_action_scopes"],
                    expected,
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
            "bilibili:BV1tw411U7PV",
            "bilibili:BV1TT411r7Ft",
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
        self.assertNotIn("7656927370758796145", footwork_by_id)

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

    def test_shot_family_constraints_do_not_leak_across_questions(self):
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
        self.assertGreaterEqual(len(smash_ids), 6)
        smash_synthesis_ids = set(
            smash["selection"]["synthesis_candidate_video_ids"]
        )
        self.assertTrue(
            all(
                "smash"
                in item["constraint_scope"]["shot_family"]["values"]
                or (
                    item["role"] == "supporting"
                    and "generic_constraint_support_only"
                    in item["selection_reasons"]
                )
                for item in smash["selected_videos"]
                if item["video_id"] in smash_synthesis_ids
            )
        )
        self.assertEqual(
            smash_by_id["7659991105622862457"]["role"], "supporting"
        )
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
        self.assertTrue(
            {
                "7272944156618542336",
                "7125615679402724623",
                "bilibili:BV1pmARzSEpc",
            }.issubset(selected_order)
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
            [
                "7059589039694957864",
                "bilibili:BV1MekeBjENe",
                "bilibili:BV14m4y1x7dH",
            ],
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
        reviewed_expected = {
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
        self.assertTrue(reviewed_expected.issubset(generic_ids))
        self.assertTrue(
            {
                "bilibili:BV1y4421F7KV",
                "bilibili:BV1LkGR6jEC4",
                "bilibili:BV1ayeozEEWJ",
            }.issubset(generic_ids)
        )

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
        for payload in [generic, forehand]:
            selected_ids = set(
                payload["selection"]["synthesis_candidate_video_ids"]
            )
            automatic_ids = {
                video_id
                for video_id in selected_ids
                if video_id.startswith("bilibili:")
            }
            self.assertEqual(len(automatic_ids), 3)
            self.assertTrue(
                automatic_ids.issubset(
                    {
                        "bilibili:BV1gGojBBEQD",
                        "bilibili:BV1LkGR6jEC4",
                        "bilibili:BV1zbwezEELW",
                        "bilibili:BV1ayeozEEWJ",
                        "bilibili:BV1iz421B7X8",
                        "bilibili:BV1y4421F7KV",
                        "bilibili:BV1Lb5QzxEdz",
                        "bilibili:BV1EjsizyEEz",
                    }
                )
            )
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
        self.assertTrue(
            {
                "7550305145877155131",
                "7202800263588105510",
                "7288529711267859747",
                "bilibili:BV1xy4beSEqm",
            }.issubset(ordinary_ids)
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
            "假挑真放怎么做": {
                "7151961376448138531",
                "bilibili:BV1xz4y1M7Lx",
            },
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
            selected_ids = set(
                context["selection"]["synthesis_candidate_video_ids"]
            )
            self.assertEqual(selected_ids, expected_ids)
            if query == "远网怎么打":
                selected_variants = {
                    variant
                    for item in context["selected_videos"]
                    for variant in item["constraint_scope"][
                        "technique_variant"
                    ]["values"]
                }
                self.assertTrue(
                    {
                        "far_net_flat_slice",
                        "far_net_middle_split",
                        "far_net_defense_to_push",
                    }.issubset(selected_variants)
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
            # The only titled candidate mentions 远网吊球 in metadata, but its
            # transcript teaches soft pressure / kill-to-net instead.  Keep the
            # named action unsupported until a content-backed window exists.
            "远网吊球怎么打": set(),
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
        self.assertGreaterEqual(len(heavy_ids), 7)
        self.assertTrue(
            all(
                "smash_heavy"
                in item["constraint_scope"]["technique_variant"]["values"]
                for item in heavy["selected_videos"]
            )
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
        self.assertTrue(
            {
                "7068465954270792994",
                "7068092085533953315",
                "7067722128413543680",
            }.issubset(overlord_ids)
        )
        overlord_synthesis_ids = set(
            overlord["selection"]["synthesis_candidate_video_ids"]
        )
        overlord_automatic_ids = {
            video_id
            for video_id in overlord_synthesis_ids
            if video_id.startswith("bilibili:")
        }
        self.assertEqual(len(overlord_automatic_ids), 3)
        self.assertTrue(
            overlord_automatic_ids.issubset(
                {
                    "bilibili:BV1Bi4y1q7eh",
                    "bilibili:BV1s6p9zNEzj",
                    "bilibili:BV1jbZbYfE9t",
                    "bilibili:BV1nf421X7Jg",
                    "bilibili:BV1v6ZaBtEue",
                }
            )
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
                    "bilibili:BV14m4y1376B",
                },
            ),
            "遁地炮怎么打": (
                "smash_ground_cannon",
                {
                    "7069575740836023587",
                    "bilibili:BV1p34y1V7qa",
                },
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
                selected = set(
                    payload["selection"]["synthesis_candidate_video_ids"]
                )
                if variant == "smash_fast":
                    self.assertTrue(expected_ids.issubset(selected))
                    self.assertIn("bilibili:BV1EADqYPEjo", selected)
                elif variant == "smash_ground_cannon":
                    self.assertTrue(
                        {
                            "7069575740836023587",
                            "bilibili:BV1kz421i7cj",
                        }.issubset(selected)
                    )
                    self.assertLessEqual(
                        sum(
                            video_id.startswith("bilibili:")
                            for video_id in selected
                        ),
                        3,
                    )
                else:
                    self.assertEqual(selected, expected_ids)
                selected_by_variant[variant] = selected
                if variant == "smash_ground_cannon":
                    interpretation = payload["question_interpretation"]
                    self.assertEqual(
                        interpretation["terminology_corrections"], []
                    )
                    self.assertEqual(
                        interpretation["technique_definitions"],
                        [
                            {
                                "technique_variant": "smash_ground_cannon",
                                "canonical_term": "遁地炮",
                                "parent_variant": "smash_heavy",
                                "classification": "不起跳重杀的细分技术",
                                "trajectory_class": "long_smash",
                                "trajectory_statement": "按落点属于长杀，落点比追求尖锐下压的跳杀更靠后。",
                                "takeoff_boundary": "不主动起跳，也不追求起跳高度；蹬地转移重心时可能自然短暂离地，但这不等于跳杀。",
                                "evidence_basis": "维护者确认技术分类；7069575740836023587 的 00:04-00:22 直接支持不主动起跳与短暂自然离地，02:35-02:44 直接支持其下压不如跳杀尖、回球更偏平。",
                            }
                        ],
                    )

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

        for spelling in ["顿地炮怎么打", "蹲地炮怎么打", "dun地炮怎么打"]:
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
                    set(
                        payload["selection"][
                            "synthesis_candidate_video_ids"
                        ]
                    ),
                    selected_by_variant["smash_ground_cannon"],
                )
                correction = payload["question_interpretation"][
                    "terminology_corrections"
                ]
                self.assertEqual(len(correction), 1)
                self.assertEqual(correction[0]["canonical_term"], "遁地炮")
                self.assertEqual(correction[0]["matched_terms"], [spelling[:-3]])
                self.assertIn("只作为输入纠错词", correction[0]["required_statement"])

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
        covered_units = {
            unit
            for item in receive["selected_videos"]
            for unit in item["matched_query_units"]
        }
        self.assertEqual(
            covered_units,
            {"双打接发战术", "接发握拍应该怎么调整"},
        )
        self.assertTrue(
            any(
                "receive"
                in item["constraint_scope"]["serve_role"]["values"]
                for item in receive["selected_videos"]
            )
        )
        self.assertIn(
            "握拍",
            json.dumps(receive["selected_videos"], ensure_ascii=False),
        )
        self.assertEqual(
            receive["selection"]["eligible_supporting_video_count"],
            sum(
                item["role"] == "supporting"
                for item in receive["selected_videos"]
            ),
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
                if query == "吊球怎么打到网前":
                    self.assertTrue(
                        any(
                            "drop"
                            in item["constraint_scope"]["shot_family"][
                                "values"
                            ]
                            and "rearcourt"
                            in item["constraint_scope"]["court_zone"][
                                "values"
                            ]
                            for item in payload["selected_videos"]
                        )
                    )
                else:
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
        for video_id in {
            "7148267452877638944",
            "7072543702161296640",
        }:
            if video_id in rejected:
                self.assertIn(
                    "explicit_constraint_conflict:pressure_state",
                    rejected[video_id],
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

    def test_late_forecourt_reception_routes_to_forward_movement(self):
        queries = [
            "来不及接网前小球或者网前吊球怎么办",
            "对手吊网前我总是接不到",
            "别人放网我来不及上去",
            "接前场小球启动太慢",
            "反手区网前球老是来不及，怎么才能上得快？",
            "网前反手球总是来不及",
            "反手网前上网慢",
            "对手吊到网前时我总是赶不到，我不想练后场被动球，应该先改什么？",
            "对方一吊到前场我就够不到，不考虑后场技术，我的启动该怎么调整",
            "别人放了个小球我总是上不去，后场被动别讲，只看怎么把第一步启动快",
            "对方吊短以后我老够不着，只说往前启动，不要后场救球",
            "别人放网我总够不到，不要后场方案，只看预动怎么接上网步法",
        ]
        expected_ids = {
            "7099644893269839144",
            "7353467942706695458",
            "7406541084219821312",
            "7642648621985030138",
        }
        for query in queries:
            with self.subTest(query=query):
                payload = self.context_module.prepare_answer_context(
                    query,
                    local_personalization=False,
                    include_rejected=True,
                )
                actor = payload["question_interpretation"]["actor_context"]
                self.assertEqual(actor["target_action_query"], "向前启动 上网步法")
                self.assertEqual(
                    actor["requested_action_scopes"],
                    ["forward_reception_movement"],
                )
                selected = {
                    item["video_id"]: item
                    for item in payload["selected_videos"]
                }
                self.assertTrue(expected_ids & set(selected))
                self.assertTrue(
                    all(
                        item["evidence_id"] == video_id
                        and item["source_type"] == "douyin_video"
                        and item["parent_source_id"] is None
                        for video_id, item in selected.items()
                    )
                )
                self.assertTrue(
                    all(
                        item["role"] in {"core", "supporting"}
                        and item["answer_eligibility"] == "primary"
                        for item in selected.values()
                    )
                )
                self.assertNotIn("7109288333884329231", selected)
                rejected = {
                    item["video_id"]: item["reasons"]
                    for item in payload["rejected_candidates"]
                }
                if query == queries[0]:
                    self.assertIn(
                        "requested_action_not_supported:forward_reception_movement",
                        rejected["7109288333884329231"],
                    )

        unrelated = self.context_module.prepare_answer_context(
            "发小球速度太慢，怎么打到后场",
            local_personalization=False,
        )
        self.assertIsNone(
            unrelated["question_interpretation"]["actor_context"][
                "inferred_target_action"
            ]
        )

        backhand_forecourt = self.context_module.prepare_answer_context(
            "网前反手球总是来不及",
            local_personalization=False,
        )
        incoming = backhand_forecourt["question_interpretation"][
            "actor_context"
        ]["incoming_shot_constraints"]
        self.assertEqual(incoming["stroke_side"], ["backhand"])
        self.assertEqual(incoming["court_zone"], ["forecourt"])

        serve = self.context_module.prepare_answer_context(
            "发小球速度太慢，怎么打到后场",
            local_personalization=False,
        )
        self.assertNotIn(
            "forward_reception_movement",
            serve["question_interpretation"]["actor_context"][
                "requested_action_scopes"
            ],
        )

    def test_named_technique_comparison_rejects_unspecified_tactical_sources(self):
        for query in [
            "顿地炮是不是跳杀的一种？它和普通重杀的落点有什么区别？",
            "遁地炮跟跳杀、重杀在起跳和落点上到底什么关系",
            "dun地炮和主动跳杀到底谁更尖，哪个落点更靠后？",
            "遁地炮和跳杀哪个更容易打出尖球？不起跳的话为什么反而落得更深",
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
                self.assertIn("7069575740836023587", selected_ids)
                requested_variants = {
                    "smash_ground_cannon",
                    "smash_jump",
                }
                self.assertTrue(
                    all(
                        requested_variants
                        & set(
                            item["constraint_scope"]["technique_variant"][
                                "values"
                            ]
                        )
                        for item in payload["selected_videos"]
                    )
                )
                rejected = {
                    item["video_id"]: item["reasons"]
                    for item in payload["rejected_candidates"]
                }
                for video_id in {
                    "7413335844594994447",
                    "7619576226616745445",
                    "7075140710332239119",
                }:
                    self.assertNotIn(video_id, selected_ids)
                    if video_id in rejected:
                        self.assertTrue(
                            {
                                "named_technique_comparison_not_supported",
                                "specific_technique_not_supported",
                                "explicit_constraint_conflict:shot_family",
                                "recall_safeguard_only",
                            }
                            & set(rejected[video_id])
                        )

    def test_interrupted_kill_to_net_sequence_preserves_named_action(self):
        queries = [
            "杀球后来不及上网",
            "杀球后应该怎样上网",
            "杀球以后上网衔接太慢",
            "杀球后被对手挡网，我总是来不及上去怎么办",
            "我杀球后对手放网，总是跟不上怎么办",
        ]
        required_ids = {"7065157571816000809", "7092959332047785250"}
        hard_negatives = {"7109288333884329231", "7589749293205363633"}
        for query in queries:
            with self.subTest(query=query):
                payload = self.context_module.prepare_answer_context(
                    query,
                    local_personalization=False,
                )
                interpretation = payload["question_interpretation"]
                actor = interpretation["actor_context"]
                self.assertEqual(actor["target_action_query"], "杀上网")
                self.assertEqual(
                    interpretation["constraints"]["technique_variant"],
                    ["kill_to_net"],
                )
                self.assertEqual(
                    actor["requested_action_scopes"],
                    ["kill_to_net_sequence"],
                )
                selected_ids = {
                    item["video_id"] for item in payload["selected_videos"]
                }
                self.assertTrue(required_ids.issubset(selected_ids))
                self.assertFalse(selected_ids & hard_negatives)

        interrupted = self.context_module.prepare_answer_context(
            "我杀球后对手放网，总是跟不上怎么办",
            local_personalization=False,
        )
        event_chain = interrupted["question_interpretation"]["actor_context"][
            "event_chain"
        ]
        self.assertEqual(
            [(item["actor"], item["role"]) for item in event_chain],
            [
                ("player", "prior_action"),
                ("opponent", "response"),
                ("player", "target_action"),
            ],
        )

        symptom = self.context_module.prepare_answer_context(
            "杀球后来不及上网", local_personalization=False
        )
        self.assertIn(
            "来不及",
            symptom["question_interpretation"]["intent_frame"][
                "literal_symptoms"
            ],
        )

        for query in [
            "杀球后回位来不及",
            "对手杀球后我上网",
            "接杀后我上网",
            "对手杀球我挡网后应该怎么上网",
            "我不想杀上网，只想杀球后回位，应该怎么练？",
            "吊球后来不及上网",
        ]:
            with self.subTest(query=query):
                payload = self.context_module.prepare_answer_context(
                    query, local_personalization=False
                )
                interpretation = payload["question_interpretation"]
                self.assertNotIn(
                    "kill_to_net",
                    interpretation["constraints"].get("technique_variant", []),
                )
                self.assertNotIn(
                    "kill_to_net_sequence",
                    interpretation["actor_context"]["requested_action_scopes"],
                )

    def test_unseen_multi_actor_responsibility_is_one_supported_decision(self):
        payload = self.context_module.prepare_answer_context(
            "双打里我在前场封网，搭档后场杀球后也往前冲，结果对手挑直线时我们后场空了。主要该调整我还是搭档的站位？",
            local_personalization=False,
        )
        actor = payload["question_interpretation"]["actor_context"]
        self.assertEqual(actor["target_action_query"], "双打轮转补位责任")
        self.assertEqual(
            payload["question_interpretation"]["query_units"],
            ["双打轮转补位责任"],
        )
        self.assertEqual(
            [(item["actor"], item["role"]) for item in actor["event_chain"]],
            [
                ("player", "coverage_condition"),
                ("partner", "prior_action"),
                ("opponent", "response"),
                ("player", "target_action"),
            ],
        )
        self.assertEqual(payload["claim_evidence_map"][0]["status"], "conditional")
        self.assertEqual(
            payload["answer_plan"]["selected_evidence_atoms"][0]["atom_id"],
            "EA-DOUBLES-COVERAGE-RESPONSIBILITY-001",
        )
        self.assertEqual(payload["answer_core_video_labels"], ["V1"])
        self.assertEqual(payload["selected_videos"][0]["evidence_id"], "7656927370758796145")
        self.assertEqual(payload["diagnostic_model"]["supported_mechanisms"], [])

    def test_unseen_multi_actor_responsibility_accepts_front_player_word_order(self):
        payload = self.context_module.prepare_answer_context(
            "双打前场我封网，搭档后场杀球后也往前冲，对手挑直线就空，主要该调整我还是搭档的站位？",
            local_personalization=False,
        )
        actor = payload["question_interpretation"]["actor_context"]
        self.assertEqual(actor["target_action_query"], "双打轮转补位责任")
        self.assertEqual(
            actor["inferred_target_action"]["rule"],
            "front_player_partner_both_advance_rearcourt_gap",
        )
        self.assertEqual(
            payload["answer_plan"]["selected_evidence_atoms"][0]["atom_id"],
            "EA-DOUBLES-COVERAGE-RESPONSIBILITY-001",
        )
        self.assertEqual(payload["answer_core_video_labels"], ["V1"])
        self.assertEqual(
            payload["selected_videos"][0]["evidence_id"],
            "7656927370758796145",
        )
        self.assertNotIn(
            "clarify.branch.stroke_side",
            {
                item["question_id"]
                for item in payload["clarification_decision"][
                    "clarification_requests"
                ]
            },
        )

    def test_unseen_drop_recovery_sequence_does_not_borrow_drop_only_evidence(self):
        payload = self.context_module.prepare_answer_context(
            "单打我从后场正手吊直线后回中，再启动接对方放网总慢半拍。这一整段应该先改吊球、回中，还是上网启动？",
            local_personalization=False,
        )
        actor = payload["question_interpretation"]["actor_context"]
        self.assertEqual(
            actor["requested_action_scopes"],
            ["drop_recover_forward_sequence"],
        )
        self.assertEqual(
            payload["question_interpretation"]["constraints"],
            {
                "discipline": ["singles"],
                "stroke_side": ["forehand"],
                "shot_family": ["drop"],
                "court_zone": ["rearcourt"],
                "shot_direction": ["straight"],
            },
        )
        self.assertEqual(
            [(item["actor"], item["role"]) for item in actor["event_chain"]],
            [
                ("player", "prior_action"),
                ("player", "recovery"),
                ("opponent", "response"),
                ("player", "target_action"),
            ],
        )
        self.assertTrue(
            all(
                claim["status"] == "unsupported"
                for claim in payload["claim_evidence_map"]
                if claim["kind"] == "question_unit"
            )
        )
        self.assertEqual(payload["answer_core_video_labels"], [])

    def test_unseen_diagnostic_preserves_hypotheses_without_requesting_video(self):
        payload = self.context_module.prepare_answer_context(
            "我的反手高远经常只到中场，是拍面没向上、击球点太靠后，还是握得太紧？能确定哪个吗？",
            local_personalization=False,
        )
        self.assertEqual(
            [
                item["text"]
                for item in payload["diagnostic_model"]["user_hypotheses"]
            ],
            ["拍面没向上", "击球点太靠后", "握得太紧"],
        )
        self.assertEqual(
            [
                item["text"]
                for item in payload["diagnostic_model"]["observed_symptoms"]
            ],
            ["只到中场"],
        )
        self.assertNotIn(
            "user_video_unavailable", payload["diagnostic_model"]
        )
        questions = payload["clarification_decision"]["questions"]
        self.assertTrue(questions)
        self.assertTrue(all("视频" not in item for item in questions))

    def test_broad_backhand_rearcourt_symptom_stays_in_clear_family(self):
        payload = self.context_module.prepare_answer_context(
            "我反手后场总是打不到位是因为啥",
            local_personalization=False,
        )
        self.assertTrue(payload["selected_videos"])
        for video in payload["selected_videos"]:
            families = set(
                video.get("constraint_scope", {})
                .get("shot_family", {})
                .get("values", [])
            )
            self.assertTrue(
                families & {"clear", "flat_clear"},
                (video["video_id"], families),
            )
        questions = payload["clarification_decision"]["questions"]
        self.assertTrue(questions)
        self.assertTrue(all("视频" not in item for item in questions))

    def test_named_lift_claim_uses_a_lift_window_not_another_video_section(self):
        payload = self.context_module.prepare_answer_context(
            "我刚看了一个长视频，反手挑球拍面怎么控制？",
            local_personalization=False,
        )
        evidence = [
            item
            for claim in payload["claim_evidence_map"]
            if claim["kind"] == "question_unit"
            for item in claim["evidence"]
            if item["evidence_id"] == "7511934047901846841"
        ]
        self.assertTrue(evidence)
        text = " ".join(
            window["text"]
            for item in evidence
            for window in item.get("claim_windows", [])
        )
        self.assertIn("反手的挑球", text)
        self.assertNotIn("反手的过渡球", text)

    def test_unseen_cross_variant_transfer_fails_closed(self):
        payload = self.context_module.prepare_answer_context(
            "我会普通反手杀球，想直接照搬正手跳杀的起跳和落地来学反手跳杀，这两种动作的证据能互相代替吗？",
            local_personalization=False,
        )
        self.assertEqual(
            payload["boundary"]["type"], "cross_variant_evidence_transfer"
        )
        self.assertEqual(
            payload["boundary"]["citation_policy"],
            "no_cross_variant_substitution",
        )
        self.assertTrue(
            all(
                claim["status"] == "unsupported" and not claim["evidence"]
                for claim in payload["claim_evidence_map"]
                if claim["kind"] == "question_unit"
            )
        )
        self.assertEqual(payload["answer_core_video_labels"], [])

    def test_unseen_cross_scope_proof_transfer_fails_closed(self):
        payload = self.context_module.prepare_answer_context(
            "我在后场正手主动进攻时，能不能用反手被动高远的视频来证明我的挥拍动作？",
            local_personalization=False,
        )
        self.assertEqual(
            payload["boundary"]["type"], "cross_variant_evidence_transfer"
        )
        self.assertIn("目标侧别", payload["boundary"]["required_statement"])
        self.assertTrue(
            all(
                claim["status"] == "unsupported" and not claim["evidence"]
                for claim in payload["claim_evidence_map"]
                if claim["kind"] == "question_unit"
            )
        )
        self.assertEqual(payload["answer_core_video_labels"], [])

    def test_compound_diagnosis_inherits_root_context_and_keeps_real_hypotheses(self):
        payload = self.context_module.prepare_answer_context(
            (
                "我是右手持拍的业余中级男双选手，正手后场高远球经常只能到"
                "对方中场。我怀疑是没有转髋，也可能是击球点太低。请区分这两个"
                "假设和其他有证据支持的原因，给我现场检查顺序；没有连续动作视频时"
                "不要把原因说死。"
            ),
            local_personalization=False,
        )
        interpretation = payload["question_interpretation"]
        self.assertEqual(len(interpretation["source_query_units"]), 4)
        self.assertEqual(
            interpretation["query_units"],
            ["请区分这两个假设和其他有证据支持的原因"],
        )
        expected = {
            "stroke_side": ["forehand"],
            "shot_family": ["clear"],
            "court_zone": ["rearcourt"],
            "discipline": ["doubles"],
        }
        for constraints in interpretation["query_unit_constraints"].values():
            self.assertEqual(constraints, expected)
        self.assertEqual(
            [
                item["text"]
                for item in payload["diagnostic_model"]["user_hypotheses"]
            ],
            ["没有转髋", "击球点太低"],
        )
        self.assertNotIn(
            "7524557392328461627",
            {video["video_id"] for video in payload["selected_videos"]},
        )
        self.assertEqual(
            {
                "diagnosis.hypothesis_comparison",
                "diagnosis.ordered_checklist",
                "evidence.sources",
                "evidence.boundary",
            },
            {
                item["kind"]
                for item in payload["delivery_contract"]["items"]
            },
        )

    def test_partner_conditions_do_not_create_player_stroke_side_branches(self):
        payload = self.context_module.prepare_answer_context(
            (
                "混双里搭档在后场被压反手，我守前场；对手第二拍继续推她"
                "反手时，她选择直线过渡，而我没有后退。请分开回答她的出球"
                "是否合理、我的补位该往哪里，以及这两个结论的证据能不能共用。"
            ),
            local_personalization=False,
        )
        self.assertEqual(
            payload["question_interpretation"]["query_units"],
            ["搭档的出球是否合理", "我的补位该往哪里"],
        )
        self.assertEqual(payload["diagnostic_model"]["material_branches"], [])
        self.assertEqual(payload["answer_visible_video_labels"], [])
        self.assertTrue(
            all(
                claim["status"] == "unsupported"
                for claim in payload["claim_evidence_map"]
            )
        )

    def test_unseen_answer_audit_prompts_preserve_modality_and_evidence_scope(self):
        practice = self.context_module.prepare_answer_context(
            (
                "我一个人在家只有墙和球拍，想用每天10分钟、连续两周把"
                "平抽挡速度练起来。请给具体组数、次数和进阶标准。"
            ),
            local_personalization=False,
        )
        self.assertEqual(
            practice["question_interpretation"]["intent_frame"][
                "requested_output"
            ],
            "practice",
        )
        self.assertEqual(practice["selected_videos"], [])
        self.assertIn(
            "evidence.training_boundary",
            {item["kind"] for item in practice["delivery_contract"]["items"]},
        )

        purchase = self.context_module.prepare_answer_context(
            (
                "我手腕力量一般，后场球老不到位，换更轻的拍子能解决吗？"
                "你能直接推荐一支最适合我的具体型号吗？"
            ),
            local_personalization=False,
        )
        self.assertEqual(purchase["boundary"]["type"], "purchase_advice")
        self.assertIn("个性化购买背书", purchase["boundary"]["required_statement"])

        source_policy = self.context_module.prepare_answer_context(
            (
                "你引用的B站视频和刘辉抖音内容冲突时，会默认采用抖音说法吗？"
                "如果B站讲得更详细，能不能当成同等证据？"
            ),
            local_personalization=False,
        )
        self.assertEqual(
            source_policy["boundary"]["type"], "source_evidence_policy"
        )
        self.assertEqual(source_policy["selected_videos"], [])
        self.assertIn(
            "平台本身不决定证据权重",
            source_policy["boundary"]["required_statement"],
        )

        excluded = self.context_module.prepare_answer_context(
            (
                "我只想知道双打发小球后，发球人该站哪里防对方推直线和"
                "推中路；不要讲接发，也不要讲单打。"
            ),
            local_personalization=False,
        )
        self.assertEqual(
            excluded["question_interpretation"]["query_units"],
            ["我只想知道双打发小球后 发球人该站哪里防对方推直线和推中路"],
        )
        self.assertTrue(
            all(
                "不要讲" not in unit
                for unit in excluded["question_interpretation"]["query_units"]
            )
        )
        self.assertEqual(excluded["selected_videos"], [])

    def test_unseen_diagnosis_prompts_keep_hypotheses_rotation_and_clarifications(self):
        comparison = self.context_module.prepare_answer_context(
            (
                "我右手单打，正手后场高远球在主动到位时也常落到对方双打"
                "发球线附近，但杀球反而能打得比较深。我猜是转体不够，也可能"
                "是拍面太向上。先告诉我目前能确定什么、该按什么顺序排查，"
                "不要让我发动作视频。"
            ),
            local_personalization=False,
        )
        hypotheses = comparison["diagnostic_model"]["user_hypotheses"]
        self.assertEqual(
            [(item["text"], item["status"]) for item in hypotheses],
            [("转体不够", "unverified"), ("拍面太向上", "unverified")],
        )
        self.assertIn(
            "diagnosis.ordered_checklist",
            {item["kind"] for item in comparison["delivery_contract"]["items"]},
        )

        rotation = self.context_module.prepare_answer_context(
            (
                "混双里我在后场直线重杀后，女搭档守前场，对手把球挡到斜线"
                "网前。我该自己跟进还是让搭档跨过去？她已经封住直线和她被"
                "带向中路时，判断会不同吗？"
            ),
            local_personalization=False,
        )
        self.assertEqual(
            rotation["question_interpretation"]["query_units"],
            ["双打轮转补位责任"],
        )
        responsibility = next(
            item
            for item in rotation["delivery_contract"]["items"]
            if item["kind"] == "tactics.coverage_responsibility"
        )
        self.assertEqual(responsibility["parameters"]["actors"], ["自己", "搭档"])
        self.assertIn(
            "搭档被带向中路", responsibility["parameters"]["conditions"]
        )
        self.assertEqual(
            rotation["answer_plan"]["claim_directives"][0]["mode"],
            "state_evidence_gap",
        )
        self.assertEqual(rotation["answer_visible_video_labels"], [])

        receive = self.context_module.prepare_answer_context(
            (
                "我双打接发时总被对手下一拍压住，怎么回事？我现在只能确定"
                "自己接的是短发球。"
            ),
            local_personalization=False,
        )
        self.assertEqual(
            receive["question_interpretation"]["constraints"]["serve_role"],
            ["receive"],
        )
        self.assertEqual(
            [
                item["mechanism_id"]
                for item in receive["diagnostic_model"]["supported_mechanisms"]
            ],
            ["serve_receive_next_shot_pressure"],
        )
        self.assertEqual(
            receive["clarification_decision"]["questions"],
            [
                "你接短发球后实际回的是推、放、搓还是挑，落点在直线、中路"
                "还是斜线；对手又是用哪一种下一拍把你压住？"
            ],
        )

        grip = self.context_module.prepare_answer_context(
            (
                "我握拍时虎口位置没问题，但平抽挡连续三拍后手指越来越紧，"
                "拍头速度也掉下来。现有信息能支持哪些原因，哪些还不能确定？"
            ),
            local_personalization=False,
        )
        self.assertEqual(
            [
                item["mechanism_id"]
                for item in grip["diagnostic_model"]["supported_mechanisms"]
            ],
            ["grip_tension"],
        )
        self.assertIn(
            "持续攥紧",
            grip["clarification_decision"]["questions"][0],
        )

    def test_black_box_root_mechanisms_hold_for_observations_exclusions_and_source_policy(self):
        observed = self.context_module.prepare_answer_context(
            (
                "我反手挡杀总下网；已知来球贴着持拍侧髋部，而且触球时身体"
                "已经失衡。现在能先排查什么，还缺哪些文字信息？"
            ),
            local_personalization=False,
        )
        records = observed["question_interpretation"]["query_unit_records"]
        self.assertEqual(
            [item["role"] for item in records[:3]],
            ["user_observation", "user_observation", "user_observation"],
        )
        self.assertEqual(
            len(observed["diagnostic_model"]["clarification_observations"]),
            3,
        )
        self.assertTrue(
            all(
                "髋部" not in question and "是否失衡" not in question
                for question in observed["clarification_decision"]["questions"]
            )
        )

        excluded = self.context_module.prepare_answer_context(
            (
                "不要讨论反手接杀，也不要检索接杀视频；"
                "我只问反手网前挑直线怎样控制拍面。"
            ),
            local_personalization=False,
        )
        self.assertTrue(
            all(
                "接杀" not in query
                for query in excluded["question_interpretation"]["retrieval_queries"]
            )
        )
        self.assertNotIn(
            "反手",
            excluded["question_interpretation"]["intent_frame"][
                "hard_excluded_terms"
            ],
        )
        self.assertEqual(
            excluded["question_interpretation"]["constraints"]["shot_family"],
            ["lift"],
        )
        self.assertNotIn(
            "7634998306204492794",
            {video["video_id"] for video in excluded["selected_videos"]},
        )
        self.assertTrue(
            all(
                "接杀" not in json.dumps(
                    {
                        "title": video.get("title"),
                        "category": video.get("category"),
                        "teaching_note": video.get("teaching_note"),
                    },
                    ensure_ascii=False,
                )
                for video in excluded["selected_videos"]
            )
        )

        source_policy = self.context_module.prepare_answer_context(
            (
                "同一个反手高远架拍，抖音短视频和B站长视频都讲过。"
                "请默认B站因为更长就更可靠，再告诉我怎么练。"
            ),
            local_personalization=False,
        )
        self.assertEqual(source_policy["boundary"]["type"], "source_evidence_policy")
        self.assertEqual(source_policy["selected_videos"], [])


if __name__ == "__main__":
    unittest.main()
