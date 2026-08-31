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

    def test_negated_unique_cause_is_not_hard_certainty(self):
        context = copy.deepcopy(self.context)
        context["claim_evidence_map"][0]["confidence_ceiling"] = "low"
        answer = self.cases["answers"]["complete_conditional"].replace(
            "仅凭文字不能确认唯一原因",
            "仅凭文字不能确认唯一原因。[Q1]",
        )
        audit = self.auditor.audit_answer(context["query"], context, answer)
        self.assertNotIn(
            "confidence_ceiling_exceeded",
            {item["code"] for item in audit["violations"]},
        )

    def test_cannot_lock_unique_cause_is_not_hard_certainty(self):
        context = copy.deepcopy(self.context)
        context["claim_evidence_map"][0]["confidence_ceiling"] = "low"
        answer = self.cases["answers"]["complete_conditional"].replace(
            "杀球后经常来不及上网，可以先按两个分支排查；"
            "仅凭文字不能确认唯一原因，需要连续动作视频确认。[V1]",
            "杀球后经常来不及上网，当前还不能锁定唯一原因。[Q1][V1]",
        )
        audit = self.auditor.audit_answer(context["query"], context, answer)
        self.assertNotIn(
            "confidence_ceiling_exceeded",
            {item["code"] for item in audit["violations"]},
        )

    def test_negated_user_video_request_is_a_valid_scope_boundary(self):
        context = copy.deepcopy(self.context)
        context.setdefault("answer_contract", {})[
            "user_action_video_requests_forbidden"
        ] = True
        answer = self.cases["answers"]["complete_conditional"].replace(
            "需要连续动作视频确认",
            "不需要也不会要求你提供动作视频",
        )
        audit = self.auditor.audit_answer(context["query"], context, answer)
        self.assertNotIn(
            "user_action_video_request_out_of_scope",
            {item["code"] for item in audit["violations"]},
        )

        unsafe = answer.replace(
            "不需要也不会要求你提供动作视频",
            "请提供连续动作视频",
        )
        unsafe_audit = self.auditor.audit_answer(
            context["query"], context, unsafe
        )
        self.assertIn(
            "user_action_video_request_out_of_scope",
            {item["code"] for item in unsafe_audit["violations"]},
        )

    def test_selected_video_from_hard_excluded_scope_is_rejected(self):
        context = copy.deepcopy(self.context)
        context.setdefault("question_interpretation", {}).setdefault(
            "intent_frame", {}
        )["hard_excluded_terms"] = ["接杀"]
        context["selected_videos"][0]["title"] = "反手接杀示范"
        audit = self.auditor.audit_answer(
            context["query"],
            context,
            self.cases["answers"]["complete_conditional"],
        )
        self.assertIn(
            "excluded_scope_video_selected",
            {item["code"] for item in audit["violations"]},
        )

    def test_semantic_hard_exclusion_is_rejected_from_evidence_text(self):
        context = copy.deepcopy(self.context)
        context.setdefault("question_interpretation", {}).setdefault(
            "intent_frame", {}
        )["hard_excluded_terms"] = ["接杀"]
        context["selected_videos"][0]["title"] = "双打被动处理"
        context["selected_videos"][0]["teaching_note"] = {
            "evidence": [
                {"text": "拍面迎接着对手的杀球，再把球挡到直线"}
            ]
        }
        audit = self.auditor.audit_answer(
            context["query"],
            context,
            self.cases["answers"]["complete_conditional"],
        )
        self.assertIn(
            "excluded_scope_video_selected",
            {item["code"] for item in audit["violations"]},
        )

    def test_video_guidance_block_accepts_markdown_emphasis(self):
        answer = (
            "- **V1｜反手被动高远**（证据 ID：7546109410041908538）\n"
            "  **为什么引用：**支持被动反手的条件分支。\n"
            "  **为什么值得看：**可以比较架拍位置。\n"
            "  **重点看：**01:02-01:10。\n"
            "- **V2**｜后场步法（证据 ID：7248074193118547240）\n"
            "  **为什么引用：**支持脚下衔接分支。"
        )
        block = self.auditor.RUNTIME.video_guidance_block(answer, "V1")
        self.assertIn("为什么引用：", block)
        self.assertIn("为什么值得看：", block)
        self.assertIn("重点看：", block)
        self.assertNotIn("V2", block)

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

    def reception_semantic_context(self):
        query = (
            "我是右手持拍的业余中级双打选手，对手杀到反手身体附近时，"
            "我挡网经常冒高。请区分拍面、击球点和到位问题。"
        )
        context = copy.deepcopy(self.context)
        context["query"] = query
        context["question_interpretation"] = {
            "intent_frame": {"literal_symptoms": ["冒高"]},
            "actor_context": {
                "opponent_constraints": {
                    "shot_family": ["smash"],
                    "tactical_phase": ["attack"],
                },
                "target_constraints": {
                    "stroke_side": ["backhand"],
                    "shot_family": ["net_shot", "smash_block"],
                    "technique_variant": ["net_drop"],
                },
                "target_action_query": "反手身体位 接杀挡网",
                "requested_action_scopes": ["smash_block_response"],
                "incoming_shot_constraints": {
                    "shot_family": ["smash"],
                    "tactical_phase": ["attack"],
                },
                "inferred_target_action": {
                    "rule": "smash_to_backhand_body_block_high"
                },
                "event_chain": [
                    {
                        "actor": "opponent_or_feed",
                        "role": "incoming_condition",
                        "term": "杀到反手身体附近",
                    },
                    {
                        "actor": "player",
                        "role": "target_action",
                        "term": "反手身体位 接杀挡网",
                    },
                ],
            },
        }
        return query, context

    def test_semantic_interpretation_contract_accepts_owned_incoming_context(self):
        query, context = self.reception_semantic_context()
        audit = self.auditor.audit_answer(
            query, context, self.cases["answers"]["complete_conditional"]
        )
        semantic_codes = {
            item["code"]
            for item in audit["violations"]
            if item["code"].startswith("semantic_interpretation_")
        }
        self.assertEqual(semantic_codes, set())

    def test_semantic_interpretation_contract_fails_closed_when_corrupted(self):
        query, context = self.reception_semantic_context()
        interpretation = context["question_interpretation"]
        interpretation["intent_frame"]["literal_symptoms"] = []
        actor = interpretation["actor_context"]
        actor["opponent_constraints"]["stroke_side"] = ["backhand"]
        actor["incoming_shot_constraints"] = {}
        actor["event_chain"] = []
        audit = self.auditor.audit_answer(
            query, context, self.cases["answers"]["complete_conditional"]
        )
        codes = {item["code"] for item in audit["violations"]}
        self.assertIn("semantic_interpretation_missing_symptom", codes)
        self.assertIn("semantic_interpretation_wrong_constraint_owner", codes)
        self.assertIn("semantic_interpretation_missing_incoming_scope", codes)
        self.assertIn("semantic_interpretation_missing_event_chain", codes)

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

    def test_pending_clarification_is_not_a_technical_assertion(self):
        context = copy.deepcopy(self.context)
        context.pop("answer_turn_contract", None)
        context.pop("clarification_state", None)
        claim = next(
            item
            for item in context["claim_evidence_map"]
            if item["status"] in {"supported", "conditional"}
        )
        claim["confidence_ceiling"] = "low"
        question = f"{claim['text']}具体是什么情况？"
        context["clarification_decision"] = {
            "action": "answer_conditionally",
            "questions": [question],
        }
        answer = (
            self.cases["answers"]["complete_conditional"]
            + f"\n\n## 仍需确认\n\n- {question}"
        )
        audit = self.auditor.audit_answer(context["query"], context, answer)
        self.assertNotIn(
            "confidence_ceiling_exceeded",
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

    def test_answer_packet_digest_binds_the_audit_context(self):
        visible_labels = self.context.get(
            "answer_visible_video_labels",
            [item["label"] for item in self.context["selected_videos"]],
        )
        packet = {
            "schema_version": 1,
            "packet_type": "liuhui_badminton_answer_packet",
            "audit_context": {
                "digest": self.auditor.canonical_json_digest(self.context)
            },
            "selected_videos": [
                {"label": label} for label in visible_labels
            ],
        }
        self.auditor.validate_packet_binding(packet, self.context)
        packet["audit_context"]["digest"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            self.auditor.validate_packet_binding(packet, self.context)

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

    def test_feedback_prompt_labels_are_not_treated_as_citations(self):
        context = copy.deepcopy(self.context)
        prompt = (
            "反馈可直接回复：V1 最有价值；V3 不相关；"
            "第 2 点结论不对；回答漏了‘……’。"
        )
        context["answer_contract"] = {"feedback_prompt": prompt}
        answer = self.cases["answers"]["complete_conditional"] + "\n" + prompt
        audit = self.auditor.audit_answer(context["query"], context, answer)
        self.assertTrue(audit["passed"], audit["violations"])

        missing = self.auditor.audit_answer(
            context["query"],
            context,
            self.cases["answers"]["complete_conditional"],
        )
        self.assertIn(
            "missing_feedback_prompt",
            {item["code"] for item in missing["violations"]},
        )

    def test_legacy_synthetic_practice_delivery_is_rejected(self):
        context = copy.deepcopy(self.context)
        context["delivery_contract"] = {
            "schema_version": 1,
            "items": [
                {
                    "delivery_id": "D1",
                    "kind": "practice.three_day",
                    "label": "三天纠正进度",
                    "required": True,
                    "parameters": {},
                }
            ],
            "required_ids": ["D1"],
        }
        answer = self.cases["answers"]["complete_conditional"] + "\n[D1]三天纠正。"
        audit = self.auditor.audit_answer(context["query"], context, answer)
        self.assertIn(
            "unsupported_synthetic_practice_delivery",
            {item["code"] for item in audit["violations"]},
        )

    def test_second_day_symptom_report_is_not_a_training_prescription(self):
        context = copy.deepcopy(self.context)
        question = "连续练反手高远后手肘外侧疼，第二天挥拍也疼，但还能打。"
        context["query"] = question
        answer = (
            "你报告的是练后疼痛，而且第二天挥拍仍疼；这不是训练周期建议。"
            "先停止诱发疼痛的动作，若疼痛加重或持续，请寻求专业医疗评估。"
        )
        audit = self.auditor.audit_answer(question, context, answer)
        self.assertNotIn(
            "synthetic_training_prescription",
            {item["code"] for item in audit["violations"]},
        )

    def test_fallback_claim_evidence_requires_a_claim_specific_window(self):
        context = copy.deepcopy(self.context)
        claim = context["claim_evidence_map"][0]
        claim["evidence"][0].pop("claim_windows", None)
        context["answer_plan"] = {
            "claim_directives": [
                {
                    "claim_id": claim["claim_id"],
                    "mode": "compose_from_claim_scoped_source",
                    "evidence_labels": [claim["evidence"][0]["label"]],
                }
            ]
        }
        audit = self.auditor.audit_answer(
            context["query"],
            context,
            self.cases["answers"]["complete_conditional"],
        )
        self.assertIn(
            "claim_evidence_window_missing",
            {item["code"] for item in audit["violations"]},
        )

    def test_cli_returns_nonzero_and_structured_json_for_failed_answer(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            context_path = temporary / "context.json"
            packet_path = temporary / "answer-packet.json"
            answer_path = temporary / "answer.md"
            context_path.write_text(
                json.dumps(self.context, ensure_ascii=False), encoding="utf-8"
            )
            answer_path.write_text(
                self.cases["answers"]["unsupported_cause"], encoding="utf-8"
            )
            packet_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "packet_type": "liuhui_badminton_answer_packet",
                        "audit_context": {
                            "digest": self.auditor.canonical_json_digest(
                                self.context
                            )
                        },
                        "selected_videos": [
                            {"label": item["label"]}
                            for item in self.context["selected_videos"]
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(AUDITOR_PATH),
                    self.context["query"],
                    "--context",
                    str(context_path),
                    "--packet",
                    str(packet_path),
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
