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

    def test_contract_atomizes_practice_and_tactics_deliveries(self):
        interpretation = {
            "intent_frame": {"requested_output": "practice"},
            "source_query_units": ["给20分钟计划并说明直线和斜线条件"],
        }
        navigation = {
            "practice_adaptation": {
                "session_minutes": 20,
                "minute_allocation": {
                    "warm_up": 4,
                    "isolated_cue": 7,
                    "pressure_or_decision": 6,
                    "self_check": 3,
                },
            }
        }
        contract = self.module.build_delivery_contract(
            "给20分钟计划，包含三天、两周和成功标准；什么时候打直线或斜线？",
            interpretation,
            {"user_hypotheses": [], "supported_mechanisms": []},
            navigation,
        )
        kinds = [item["kind"] for item in contract["items"]]
        self.assertIn("practice.session", kinds)
        self.assertIn("practice.three_day", kinds)
        self.assertIn("practice.two_week", kinds)
        self.assertIn("practice.success_criteria", kinds)
        self.assertEqual(kinds.count("tactics.direction_branch"), 2)


if __name__ == "__main__":
    unittest.main()
