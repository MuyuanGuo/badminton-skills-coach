#!/usr/bin/env python3

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDITOR_PATH = ROOT / "scripts" / "audit_answer.py"
EVALUATOR_PATH = ROOT / "scripts" / "evaluate_answer_audit.py"
CASES_PATH = ROOT / "data" / "evaluation" / "answer_audit_cases.json"


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AnswerAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.auditor = load_module(AUDITOR_PATH, "answer_audit_test")
        cls.evaluator = load_module(EVALUATOR_PATH, "answer_audit_evaluator_test")
        cls.cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
        cls.context = cls.cases["contexts"]["kill_to_net_diagnostic"]
        cls.continuation_context = cls.cases["contexts"][
            "kill_to_net_continuation"
        ]

    def audit_named_answer(self, answer_id):
        return self.auditor.audit_answer(
            self.context["query"],
            self.context,
            self.cases["answers"][answer_id],
        )

    def test_evaluator_accepts_a_small_fixture(self):
        source_case = self.cases["cases"][0]
        payload = {
            "contexts": {
                source_case["context_id"]: self.cases["contexts"][
                    source_case["context_id"]
                ]
            },
            "answers": {
                source_case["answer_id"]: self.cases["answers"][
                    source_case["answer_id"]
                ]
            },
            "cases": [source_case],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cases.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            result = self.evaluator.evaluate(path)
        self.assertEqual(result["cases"], 1)
        self.assertEqual(result["passed"], 1)

    def test_complete_conditional_answer_passes_without_false_positive(self):
        audit = self.audit_named_answer("complete_conditional")
        self.assertTrue(audit["passed"], audit["violations"])
        self.assertEqual(audit["summary"]["completeness_items_covered"], 5)

    def test_claim_level_allowlist_rejects_globally_selected_wrong_video(self):
        audit = self.audit_named_answer("citation_mismatch")
        violations = [
            item
            for item in audit["violations"]
            if item["code"] == "citation_claim_mismatch"
        ]
        self.assertTrue(violations)
        self.assertEqual(violations[0]["claim_id"], "M1")
        self.assertEqual(violations[0]["details"]["eligible_labels"], ["V2"])

    def test_question_context_mismatch_is_reported(self):
        audit = self.auditor.audit_answer(
            "另一个问题",
            self.context,
            self.cases["answers"]["complete_conditional"],
        )
        self.assertIn(
            "question_context_mismatch",
            {item["code"] for item in audit["violations"]},
        )

    def test_evidence_id_must_be_displayed_outside_its_url(self):
        answer = self.cases["answers"]["complete_conditional"].replace(
            "V1｜证据 ID：7000000000000000001",
            "V1",
        )
        audit = self.auditor.audit_answer(
            self.context["query"], self.context, answer
        )
        self.assertIn(
            "missing_citation_evidence_id",
            {item["code"] for item in audit["violations"]},
        )

    def test_continuation_audits_against_original_question(self):
        answer = self.cases["answers"]["continuation_complete"]
        original = self.continuation_context["clarification_state"][
            "original_query"
        ]
        audit = self.auditor.audit_answer(
            original, self.continuation_context, answer
        )
        self.assertTrue(audit["passed"], audit["violations"])
        wrong = self.auditor.audit_answer(
            self.continuation_context["query"],
            self.continuation_context,
            answer,
        )
        self.assertIn(
            "question_context_mismatch",
            {item["code"] for item in wrong["violations"]},
        )

    def test_pending_clarification_requires_a_purpose(self):
        context = copy.deepcopy(self.continuation_context)
        del context["answer_turn_contract"]["pending_clarifications"][0][
            "purpose"
        ]
        audit = self.auditor.audit_answer(
            context["clarification_state"]["original_query"],
            context,
            self.cases["answers"]["continuation_complete"],
        )
        self.assertIn(
            "invalid_clarification_contract",
            {item["code"] for item in audit["violations"]},
        )

    def test_answer_turn_evidence_state_must_match_current_context(self):
        context = copy.deepcopy(self.continuation_context)
        context["answer_turn_contract"]["evidence_state_digest"] = "0" * 64
        audit = self.auditor.audit_answer(
            context["clarification_state"]["original_query"],
            context,
            self.cases["answers"]["continuation_complete"],
        )
        self.assertIn(
            "answer_turn_evidence_state_mismatch",
            {item["code"] for item in audit["violations"]},
        )

    def test_continuation_rejects_prior_turn_labels_and_evidence_ids(self):
        answer = (
            self.cases["answers"]["continuation_complete"]
            + "\n旧轮证据 V1：7000000000000000001"
        )
        audit = self.auditor.audit_answer(
            self.continuation_context["clarification_state"][
                "original_query"
            ],
            self.continuation_context,
            answer,
        )
        codes = {item["code"] for item in audit["violations"]}
        self.assertIn("unmapped_video_label", codes)
        self.assertIn("unmapped_evidence_id", codes)

    def test_cli_returns_nonzero_and_structured_json_for_failed_answer(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            context_path = temporary / "context.json"
            answer_path = temporary / "answer.md"
            context_path.write_text(
                json.dumps(self.context, ensure_ascii=False), encoding="utf-8"
            )
            answer_path.write_text(
                self.cases["answers"]["unsupported_cause"], encoding="utf-8"
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(AUDITOR_PATH),
                    self.context["query"],
                    "--context",
                    str(context_path),
                    "--answer",
                    str(answer_path),
                ],
                cwd=temporary,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["passed"])
        self.assertIn(
            "unsupported_causal_certainty",
            {item["code"] for item in payload["violations"]},
        )


if __name__ == "__main__":
    unittest.main()
