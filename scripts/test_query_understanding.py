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

    def test_registry_must_cover_every_answer_quality_case(self):
        registry = self.module.load_json(self.module.CASES_PATH)
        registry["cases"] = registry["cases"][:-1]
        answer_registry = self.module.load_json(self.module.ANSWER_CASES_PATH)
        with self.assertRaisesRegex(ValueError, "does not cover: AQ057"):
            self.module.validate_registry(registry, answer_registry)


if __name__ == "__main__":
    unittest.main()
