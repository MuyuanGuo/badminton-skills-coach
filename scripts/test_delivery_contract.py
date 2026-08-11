#!/usr/bin/env python3

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT
    / "skills"
    / "liuhui-badminton-coach"
    / "scripts"
    / "delivery_contract.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location(
        "delivery_contract_tested", MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DeliveryContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_delivery_instructions_are_removed_from_evidence_queries(self):
        records = self.module.analyze_query_units(
            [
                "正手高远球只能到中场",
                "请区分转髋和击球点，并给我现场检查顺序",
                "没有连续动作视频时不要把原因说死",
            ]
        )
        self.assertEqual(
            [record["evidence_query"] for record in records],
            ["正手高远球只能到中场", "请区分转髋和击球点", ""],
        )
        self.assertEqual(records[-1]["role"], "delivery_instruction")

    def test_punctuation_paraphrase_preserves_evidence_query(self):
        comma = self.module.analyze_query_units(
            ["请区分转髋和击球点，给现场检查顺序"]
        )
        semicolon = self.module.analyze_query_units(
            ["请区分转髋和击球点；请给现场检查顺序。"]
        )
        self.assertEqual(comma[0]["evidence_query"], "请区分转髋和击球点")
        self.assertEqual(
            comma[0]["evidence_query"], semicolon[0]["evidence_query"]
        )
        self.assertEqual(comma[0]["role"], semicolon[0]["role"])

    def test_known_conditions_and_reported_symptoms_are_observations(self):
        records = self.module.analyze_query_units(
            [
                "已知来球贴着持拍侧髋部",
                "触球时身体已经失衡",
                "我反手挡杀总下网",
                "现在能先排查什么",
            ]
        )
        self.assertEqual(
            [item["role"] for item in records],
            [
                "user_observation",
                "user_observation",
                "user_observation",
                "evidence_question",
            ],
        )
        self.assertTrue(all(item["evidence_query"] for item in records))

    def test_explicit_two_problem_request_promotes_both_symptoms(self):
        records = self.module.analyze_query_units(
            [
                "我反手后场被压时常回到对方半场",
                "我正手网前挑球又总出界",
                "请把两个问题分开解释，并告诉我哪些视频分别支持哪一部分，不要给训练计划",
            ]
        )
        self.assertEqual(
            [record["role"] for record in records],
            ["evidence_question", "evidence_question", "delivery_instruction"],
        )

    def test_explicit_actor_subquestions_are_split_and_actor_bound(self):
        records = self.module.analyze_query_units(
            [
                "男双里我点杀，搭档已经守住网前中路",
                "对手挡到斜线网前，我启动时重心仍在前脚",
                "请把“我该不该自己跟进”和“搭档是否需要横移”分开回答",
                "不要把搭档已守中路当成待证明问题",
            ]
        )
        explicit = [
            item for item in records if item["role"] == "explicit_subquestion"
        ]
        self.assertEqual(
            [item["evidence_query"] for item in explicit],
            ["我该不该自己跟进", "搭档是否需要横移"],
        )
        self.assertTrue(
            all(
                not self.module.should_inherit_root_context({}, item["role"])
                for item in explicit
            )
        )

    def test_named_comparison_items_are_not_collapsed_into_delivery_text(self):
        records = self.module.analyze_query_units(
            [
                "单打我吊直线后已回中，对手放斜线网前",
                "请分开回答上一拍吊球质量、回中位置、启动时机，现有信息各能确认什么",
            ]
        )
        self.assertEqual(
            [
                item["evidence_query"]
                for item in records
                if item["role"] == "explicit_subquestion"
            ],
            [
                "上一拍吊球质量现有信息能确认什么",
                "回中位置现有信息能确认什么",
                "启动时机现有信息能确认什么",
            ],
        )

    def test_evidence_sharing_request_is_delivery_not_a_technical_claim(self):
        records = self.module.analyze_query_units(
            ["这两个结论的证据能不能共用"]
        )
        self.assertEqual(records[0]["role"], "delivery_instruction")
        contract = self.module.build_delivery_contract(
            "她选择直线过渡。请分开回答她的出球和我的补位，"
            "以及这两个结论的证据能不能共用。",
            {"intent_frame": {}, "source_query_units": ["两项分开回答"]},
            {"user_hypotheses": [], "supported_mechanisms": []},
        )
        kinds = [item["kind"] for item in contract["items"]]
        self.assertIn("evidence.claim_separation", kinds)
        self.assertNotIn("tactics.direction_branch", kinds)

    def test_elliptical_comparison_followup_inherits_root_context(self):
        record = self.module.analyze_query_units(
            ["如果来球改到反手肩部，排查顺序会一样吗"]
        )[0]
        self.assertEqual(record["role"], "contextual_followup")
        self.assertTrue(
            self.module.should_inherit_root_context(
                {"stroke_side": ["backhand"]}, record["role"]
            )
        )

    def test_child_constraints_inherit_root_without_overwriting_branch(self):
        inherited = self.module.merge_constraints(
            {
                "stroke_side": ["backhand"],
                "shot_family": ["drive"],
                "discipline": ["doubles"],
            },
            {"shot_direction": ["straight"]},
        )
        self.assertEqual(inherited["stroke_side"], ["backhand"])
        self.assertEqual(inherited["shot_family"], ["drive"])
        self.assertEqual(inherited["discipline"], ["doubles"])
        self.assertEqual(inherited["shot_direction"], ["straight"])

    def test_child_inherits_root_action_scope_and_evidence_boundary(self):
        inherited = self.module.inherit_actor_context(
            {
                "target_constraints": {"shot_family": ["smash_block"]},
                "requested_action_scopes": ["smash_block_response"],
                "scope_boundary_statements": ["只接受接杀挡网证据"],
                "derived_search_terms": ["接杀挡网 拍面"],
            },
            {
                "target_constraints": {},
                "requested_action_scopes": [],
                "scope_boundary_statements": [],
                "derived_search_terms": [],
            },
        )
        self.assertEqual(
            inherited["requested_action_scopes"], ["smash_block_response"]
        )
        self.assertEqual(
            inherited["scope_boundary_statements"], ["只接受接杀挡网证据"]
        )

    def test_independent_scoped_unit_does_not_inherit_unrelated_root(self):
        self.assertFalse(
            self.module.should_inherit_root_context(
                {"stroke_side": ["forehand"]},
                "evidence_question",
            )
        )
        self.assertTrue(
            self.module.should_inherit_root_context(
                {"shot_direction": ["straight"]},
                "mixed",
            )
        )

    def test_contract_bounds_training_and_atomizes_tactics_deliveries(self):
        interpretation = {
            "intent_frame": {"requested_output": "practice"},
            "source_query_units": ["给20分钟计划并说明直线和斜线条件"],
        }
        contract = self.module.build_delivery_contract(
            "给20分钟计划，包含三天、两周和成功标准；什么时候打直线或斜线？",
            interpretation,
            {"user_hypotheses": [], "supported_mechanisms": []},
            None,
        )
        kinds = [item["kind"] for item in contract["items"]]
        self.assertEqual(kinds.count("evidence.training_boundary"), 1)
        self.assertFalse(any(kind.startswith("practice.") for kind in kinds))
        self.assertEqual(kinds.count("tactics.direction_branch"), 2)


if __name__ == "__main__":
    unittest.main()
