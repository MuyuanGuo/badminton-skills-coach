#!/usr/bin/env python3
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "evaluate_diagnostic_answer_contract.py"


def load_module():
    spec = importlib.util.spec_from_file_location(
        "diagnostic_answer_contract_test", MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DiagnosticAnswerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()
        cls.result = cls.module.evaluate()

    def test_all_gold_cases_pass(self):
        self.assertEqual(self.result["cases"], 10)
        self.assertEqual(self.result["passed"], 10)
        self.assertEqual(self.result["accuracy"], 1.0)

    def test_user_hypothesis_is_not_promoted_to_fact(self):
        case = next(
            item for item in self.result["results"] if item["case_id"] == "DAC001"
        )
        self.assertTrue(case["matched"])

    def test_false_either_or_keeps_both_supported_branches(self):
        runtime = self.module.load_runtime()
        context = runtime.prepare_answer_context(
            "双打接杀挡网总冒高，是拍面还是击球点问题？",
            local_personalization=False,
        )
        hypotheses = self.module.hypothesis_by_text(context)
        self.assertEqual(hypotheses["拍面"]["status"], "conditional")
        self.assertEqual(hypotheses["击球点"]["status"], "conditional")
        self.assertEqual(
            hypotheses["拍面"]["eligible_video_labels"],
            hypotheses["击球点"]["eligible_video_labels"],
        )

    def test_claim_maps_are_subsets_of_the_selected_allowlist(self):
        runtime = self.module.load_runtime()
        context = runtime.prepare_answer_context(
            "我反手高远球总是出界，到底哪里有问题？",
            local_personalization=False,
        )
        selected = {item["label"] for item in context["selected_videos"]}
        for claim in context["claim_evidence_map"]:
            labels = {item["label"] for item in claim["evidence"]}
            self.assertLessEqual(labels, selected)
            self.assertLessEqual(len(labels), 3)
            self.assertEqual(labels, set(claim["eligible_video_labels"]))

    def test_nested_symptom_terms_are_not_repeated(self):
        runtime = self.module.load_runtime()
        search = runtime.load_search_module()
        rules = runtime.load_diagnostic_rules()
        symptoms = runtime.diagnostic_observed_symptoms(
            search,
            "我总是到得太晚",
            {"literal_symptoms": ["到得太晚", "太晚"]},
            [],
            rules,
        )
        self.assertEqual([item["text"] for item in symptoms], ["到得太晚"])

    def test_evaluator_reports_a_changed_expectation(self):
        payload = self.module.load_json(self.module.CASES_PATH)
        payload["cases"][0]["expected"]["clarification_action"] = "ask_first"
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / "cases.json"
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            result = self.module.evaluate(path)
        failed = [item for item in result["results"] if not item["matched"]]
        self.assertEqual([item["case_id"] for item in failed], ["DAC001"])
        self.assertEqual(failed[0]["mismatches"], ["clarification_action"])


if __name__ == "__main__":
    unittest.main()
