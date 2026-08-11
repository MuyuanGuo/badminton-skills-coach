#!/usr/bin/env python3
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "evaluate_query_understanding.py"


def load_module():
    spec = importlib.util.spec_from_file_location("query_understanding_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class QueryUnderstandingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()
        cls.search = cls.module.load_search_module()
        cls.context = cls.module.load_context_module()
        cls.rules = cls.context.load_selection_rules()
        cls.registry = cls.module.load_json(cls.module.CASES_PATH)

    def adversarial_case(self, case_id):
        return next(
            case
            for case in self.registry["adversarial_cases"]
            if case["case_id"] == case_id
        )

    def test_ambiguous_sequence_is_reported(self):
        case = self.adversarial_case("QUA085")
        plan = self.search.plan_query(case["query"])
        actor_query = plan["retrieval_guidance"]["intent_frame"]["actor_query"]
        ambiguities = self.context.query_ambiguities(
            self.search, actor_query, self.rules
        )
        self.assertEqual(
            [item["name"] for item in ambiguities],
            ["drop_then_smash_or_smash_receive"],
        )

    def test_doubles_actor_chain_is_preserved(self):
        case = self.adversarial_case("QUA086")
        plan = self.search.plan_query(case["query"])
        actor_query = plan["retrieval_guidance"]["intent_frame"]["actor_query"]
        actor = self.context.query_actor_context(
            self.search, actor_query, self.rules
        )
        self.assertEqual(
            [(item["actor"], item["role"]) for item in actor["event_chain"]],
            [
                ("player", "prior_action"),
                ("partner", "coverage_condition"),
                ("opponent", "response"),
                ("player", "target_action"),
            ],
        )

    def test_incoming_smash_target_side_is_owned_by_the_player(self):
        case = self.adversarial_case("QUA087")
        plan = self.search.plan_query(case["query"])
        intent = plan["retrieval_guidance"]["intent_frame"]
        actor = self.context.query_actor_context(
            self.search, intent["actor_query"], self.rules
        )
        self.assertIn("冒高", intent["literal_symptoms"])
        self.assertEqual(
            actor["incoming_shot_constraints"],
            case["expected_incoming_shot_constraints"],
        )
        self.assertEqual(
            actor["opponent_constraints"],
            case["expected_opponent_constraints"],
        )
        self.assertEqual(
            actor["player_constraints"],
            case["expected_player_constraints"],
        )
        self.assertEqual(actor["event_chain"], case["expected_event_chain"])

    def test_opponent_court_landing_is_an_outcome_not_an_actor_location(self):
        query = "反手被动回球最后落在对手中场"
        plan = self.search.plan_query(query)
        intent = plan["retrieval_guidance"]["intent_frame"]
        actor = self.context.query_actor_context(
            self.search, intent["actor_query"], self.rules
        )
        self.assertEqual(actor["opponent_query"], "")
        self.assertEqual(actor["opponent_constraints"], {})
        self.assertNotIn("court_zone", actor["player_constraints"])
        self.assertIn("落在中场", actor["player_query"])

    def test_negated_positive_topic_is_checked_separately_from_excluded_topic(self):
        registry = self.module.load_json(self.module.CASES_PATH)
        case = registry["adversarial_cases"][0]
        contract = json.loads(json.dumps(case["expected_intent"]))
        contract["positive_query_contains"] = ["杀球"]
        intent = self.search.plan_query(case["query"])["retrieval_guidance"][
            "intent_frame"
        ]
        checks = self.module.evaluate_intent_contract(intent, contract)
        self.assertFalse(checks["positive_query_contains"])

    def test_wrong_subproblem_split_is_reported(self):
        actual = self.search.plan_query(
            "双打接发战术和接发握拍应该怎么调整"
        )["retrieval_guidance"]["query_units"]
        self.assertNotEqual(
            actual,
            ["双打接发战术和接发握拍应该怎么调整"],
        )

    def test_confirmed_condition_is_preserved_but_not_retrieved_as_a_question(self):
        plan = self.search.plan_query(
            (
                "我右手双打前场反手勾对角经常球路太高，被对手直接扑死；"
                "触球时我已经到位。是拍面变化太早，还是手臂动作太大？"
            )
        )["retrieval_guidance"]
        self.assertIn("触球时我已经到位", plan["source_query_units"])
        self.assertNotIn("触球时我已经到位", plan["query_units"])

    def test_incoming_destination_belongs_to_player_not_opponent(self):
        query = (
            "我只有在被对手快速推到反手后场、触球点已经落到体侧时，"
            "回高远才只到半场；这是引拍太深还是被动架拍位置不对？"
        )
        plan = self.search.plan_query(query)
        intent = plan["retrieval_guidance"]["intent_frame"]
        actor = self.context.query_actor_context(
            self.search, intent["actor_query"], self.rules
        )
        self.assertEqual(actor["player_constraints"]["stroke_side"], ["backhand"])
        self.assertEqual(actor["player_constraints"]["court_zone"], ["rearcourt"])
        self.assertNotIn("stroke_side", actor["opponent_constraints"])
        self.assertNotIn("court_zone", actor["opponent_constraints"])
        self.assertEqual(
            [item["actor"] for item in actor["event_chain"]],
            ["opponent_or_feed", "player"],
        )

    def test_negative_scope_keeps_shared_side_but_hard_excludes_shot(self):
        query = (
            "不要讨论反手接杀，也不要检索接杀视频；"
            "我只问反手网前挑直线怎样控制拍面。"
        )
        intent = self.search.plan_query(query)["retrieval_guidance"]["intent_frame"]
        self.assertNotIn("反手", intent["hard_excluded_terms"])
        self.assertIn("接杀", intent["hard_excluded_terms"])
        self.assertIn("挡杀", intent["hard_excluded_terms"])

    def test_compound_negative_scope_keeps_conjunction_semantics(self):
        intent = self.search.plan_query(
            "对手吊网前我赶不到，不想练后场被动球，先改什么"
        )["retrieval_guidance"]["intent_frame"]
        self.assertEqual(
            intent["hard_excluded_scope_groups"],
            [["后场", "被动"]],
        )
        self.assertNotIn(["来不及"], intent["hard_excluded_scope_groups"])

    def test_named_excluded_hypotheses_remain_separate_exact_scopes(self):
        intent = self.search.plan_query(
            "我怀疑是转髋还是握拍；别把“击球点低”和“抡大臂”当支持原因"
        )["retrieval_guidance"]["intent_frame"]
        self.assertEqual(
            intent["hard_excluded_scope_groups"],
            [["击球点低"], ["抡大臂"]],
        )

    def test_named_frame_comparison_is_not_split_at_and(self):
        guidance = self.search.plan_query(
            "反手被动高远时，高架拍和低架拍分别适合什么击球位置"
        )["retrieval_guidance"]
        self.assertEqual(len(guidance["source_query_units"]), 1)
        self.assertIn("高架拍和低架拍", guidance["source_query_units"][0])

    def test_elliptical_lift_direction_is_still_an_action_constraint(self):
        query = "不要讨论反手接杀；我只问反手网前挑直线怎样控制拍面。"
        plan = self.search.plan_query(query)
        intent = plan["retrieval_guidance"]["intent_frame"]
        constraints = self.context.query_constraints(
            self.search,
            intent["actor_query"],
            self.rules,
        )
        self.assertEqual(constraints["shot_family"], ["lift"])
        self.assertEqual(constraints["shot_direction"], ["straight"])

    def test_registry_must_cover_every_answer_quality_case(self):
        registry = self.module.load_json(self.module.CASES_PATH)
        registry["cases"] = registry["cases"][:-1]
        answer_registry = self.module.load_json(self.module.ANSWER_CASES_PATH)
        with self.assertRaisesRegex(ValueError, "does not cover: AQ057"):
            self.module.validate_registry(registry, answer_registry)


if __name__ == "__main__":
    unittest.main()
