#!/usr/bin/env python3
import importlib.util
import json
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
        cls.runtime = cls.module.load_runtime()
        cls.source_case = cls.module.load_json(cls.module.CASES_PATH)["cases"][0]
        cls.source_context = cls.runtime.prepare_answer_context(
            cls.source_case["query"], local_personalization=False
        )

    def test_user_hypothesis_is_not_promoted_to_fact(self):
        self.assertEqual(
            self.module.case_mismatches(
                self.source_context,
                self.source_case["expected"],
            ),
            [],
        )

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

    def test_enumerated_diagnostic_request_preserves_each_hypothesis(self):
        runtime = self.module.load_runtime()
        context = runtime.prepare_answer_context(
            "请帮我区分拍面、击球点和到位问题。",
            local_personalization=False,
        )
        hypotheses = self.module.hypothesis_by_text(context)
        self.assertEqual(set(hypotheses), {"拍面", "击球点", "到位"})
        self.assertEqual(hypotheses["拍面"]["status"], "conditional")
        self.assertEqual(hypotheses["击球点"]["status"], "conditional")
        self.assertIn(hypotheses["到位"]["status"], {"conditional", "unverified"})

    def test_mechanism_claim_requires_same_window_requested_action_scope(self):
        runtime = self.module.load_runtime()
        context = runtime.prepare_answer_context(
            "我正手高远总出界但反手正常，是不是拍面问题？",
            local_personalization=False,
        )
        hypothesis = self.module.hypothesis_by_text(context)["拍面"]
        self.assertEqual(hypothesis["status"], "unverified")
        hypothesis_claim = next(
            claim
            for claim in context["claim_evidence_map"]
            if claim["kind"] == "user_hypothesis"
            and claim["text"] == "拍面"
        )
        self.assertEqual(hypothesis_claim["evidence"], [])
        claim_ids = {
            item["evidence_id"]
            for claim in context["claim_evidence_map"]
            for item in claim["evidence"]
        }
        self.assertNotIn("7453420876076240188", claim_ids)
        self.assertNotIn("7112628690395106560", claim_ids)

    def test_claim_maps_are_subsets_of_the_selected_allowlist(self):
        runtime = self.module.load_runtime()
        context = runtime.prepare_answer_context(
            "我反手高远球总是出界，到底哪里有问题？",
            local_personalization=False,
        )
        selected = {item["label"] for item in context["selected_videos"]}
        directives = {
            item["claim_id"]: item
            for item in context["answer_plan"]["claim_directives"]
        }
        atoms = {
            item["atom_id"]: item
            for item in context["answer_plan"]["selected_evidence_atoms"]
        }
        for claim in context["claim_evidence_map"]:
            labels = {item["label"] for item in claim["evidence"]}
            self.assertLessEqual(labels, selected)
            self.assertEqual(labels, set(claim["eligible_video_labels"]))
            directive = directives[claim["claim_id"]]
            synthesis_labels = set(directive.get("evidence_labels", []))
            synthesis_labels.update(
                atoms[atom_id]["video_label"]
                for atom_id in directive.get("atom_ids", [])
                if atom_id in atoms
            )
            self.assertLessEqual(synthesis_labels, labels)
            self.assertLessEqual(len(synthesis_labels), 3)

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
        expected = json.loads(json.dumps(self.source_case["expected"]))
        expected["clarification_action"] = "ask_first"
        self.assertEqual(
            self.module.case_mismatches(self.source_context, expected),
            ["clarification_action"],
        )


if __name__ == "__main__":
    unittest.main()
