#!/usr/bin/env python3
import copy
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PATH = (
    ROOT
    / "skills"
    / "liuhui-badminton-coach"
    / "scripts"
    / "prepare_answer_context.py"
)


def load_runtime():
    spec = importlib.util.spec_from_file_location(
        "clarification_continuation_tested", RUNTIME_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ClarificationStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = load_runtime()
        cls.search = cls.runtime.load_search_module()
        cls.rules = cls.runtime.load_diagnostic_rules()

    def prior_context(self, requests=None):
        requests = requests or [
            {
                "question_id": "clarify.branch.discipline",
                "unknown_type": "branch_axis:discipline",
                "question": "这是单打还是双打场景？",
                "query_label": "比赛项目",
                "answer_cues": ["单打", "双打"],
            }
        ]
        context = {
            "query": "我杀球后总来不及上网，是不是步法太慢？",
            "clarification_decision": {
                "clarification_requests": requests,
            },
        }
        context["clarification_state"] = (
            self.runtime.build_clarification_state(context)
        )
        return context

    def test_trajectory_questions_ask_for_observable_frames(self):
        mechanisms = {
            item["id"]: item for item in self.rules["mechanisms"]
        }
        racket_question = mechanisms["racket_face_control"][
            "observation_question"
        ]
        trajectory_question = mechanisms["trajectory_control"][
            "observation_question"
        ]
        self.assertIn("球刚离开拍面时", racket_question)
        self.assertIn("球的最高点", trajectory_question)
        self.assertIn(
            "离拍时就带有过大的向上角度",
            mechanisms["racket_face_control"]["observation_purpose"],
        )
        self.assertNotIn("过网后才继续抬升", racket_question)
        self.assertNotIn("从一开始就向上飞", racket_question)

    def test_single_pending_question_binds_a_natural_reply(self):
        effective, continuation = self.runtime.resolve_continuation(
            self.search,
            "是双打",
            self.prior_context(),
            None,
            self.rules,
        )
        self.assertIn("补充说明（比赛项目）：是双打", effective)
        self.assertNotIn("这是单打还是双打场景", effective)
        self.assertEqual(
            continuation["resolved_answers"][0]["question_id"],
            "clarify.branch.discipline",
        )

    def test_multiple_questions_require_explicit_binding(self):
        requests = [
            self.prior_context()["clarification_decision"][
                "clarification_requests"
            ][0],
            {
                "question_id": "clarify.mechanism.movement_transition",
                "unknown_type": "user_movement_observation",
                "question": "杀球落地后重心在哪里？",
                "query_label": "上一拍后的重心与衔接路线",
                "answer_cues": ["向前", "原地", "向后"],
            },
        ]
        with self.assertRaisesRegex(ValueError, "structured answers"):
            self.runtime.resolve_continuation(
                self.search,
                "双打，落地后停在原地",
                self.prior_context(requests),
                None,
                self.rules,
            )

    def test_structured_answers_preserve_original_and_bind_each_question(self):
        requests = [
            self.prior_context()["clarification_decision"][
                "clarification_requests"
            ][0],
            {
                "question_id": "clarify.mechanism.movement_transition",
                "unknown_type": "user_movement_observation",
                "question": "杀球落地后重心在哪里？",
                "query_label": "上一拍后的重心与衔接路线",
                "answer_cues": ["向前", "原地", "向后"],
            },
        ]
        prior = self.prior_context(requests)
        effective, continuation = self.runtime.resolve_continuation(
            self.search,
            "双打，落地后停在原地",
            prior,
            {
                "clarify.branch.discipline": "双打",
                "clarify.mechanism.movement_transition": "停在原地",
            },
            self.rules,
        )
        self.assertTrue(effective.startswith(prior["query"]))
        self.assertIn("补充说明（比赛项目）：双打", effective)
        self.assertIn("补充说明（上一拍后的重心与衔接路线）：停在原地", effective)
        self.assertEqual(len(continuation["turns"]), 2)
        self.assertEqual(len(continuation["resolved_answers"]), 2)

    def test_tampered_and_stale_states_are_rejected(self):
        tampered = copy.deepcopy(self.prior_context())
        tampered["clarification_state"]["original_query"] = "另一个问题"
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            self.runtime.resolve_continuation(
                self.search, "双打", tampered, None, self.rules
            )

        stale = copy.deepcopy(self.prior_context())
        stale["clarification_state"]["pending_question_ids"] = []
        stale["clarification_state"]["state_digest"] = (
            self.runtime.clarification_state_digest(
                stale["clarification_state"]
            )
        )
        with self.assertRaisesRegex(ValueError, "stale"):
            self.runtime.resolve_continuation(
                self.search, "双打", stale, None, self.rules
            )

        changed_request = copy.deepcopy(self.prior_context())
        changed_request["clarification_decision"]["clarification_requests"] = (
            copy.deepcopy(
                changed_request["clarification_decision"][
                    "clarification_requests"
                ]
            )
        )
        changed_request["clarification_decision"]["clarification_requests"][0][
            "query_label"
        ] = "被修改的标签"
        with self.assertRaisesRegex(ValueError, "request semantics"):
            self.runtime.resolve_continuation(
                self.search, "双打", changed_request, None, self.rules
            )

    def test_unknown_duplicate_empty_and_inconclusive_answers_are_rejected(self):
        prior = self.prior_context()
        invalid_payloads = [
            {"clarify.unknown": "双打"},
            [
                {
                    "question_id": "clarify.branch.discipline",
                    "answer": "双打",
                },
                {
                    "question_id": "clarify.branch.discipline",
                    "answer": "单打",
                },
            ],
            {"clarify.branch.discipline": ""},
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.runtime.resolve_continuation(
                    self.search, "补充", prior, payload, self.rules
                )
        with self.assertRaisesRegex(ValueError, "does not resolve"):
            self.runtime.resolve_continuation(
                self.search, "不知道", prior, None, self.rules
            )
        with self.assertRaisesRegex(ValueError, "does not resolve"):
            self.runtime.resolve_continuation(
                self.search, "今天天气不错", prior, None, self.rules
            )

    def test_excessive_turn_count_is_rejected(self):
        prior = self.prior_context()
        prior["clarification_state"]["turns"] = [
            {
                "turn": index,
                "role": "user",
                "kind": "clarification_reply",
                "text": f"turn {index}",
                "answered_question_ids": [],
            }
            for index in range(1, self.rules["max_clarification_turns"] + 1)
        ]
        prior["clarification_state"]["state_digest"] = (
            self.runtime.clarification_state_digest(
                prior["clarification_state"]
            )
        )
        with self.assertRaisesRegex(ValueError, "maximum clarification turns"):
            self.runtime.resolve_continuation(
                self.search, "双打", prior, None, self.rules
            )


class ClarificationIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = load_runtime()
        cls.original_query = "我杀球后经常来不及上网，是不是步法太慢？"
        cls.first_context = cls.runtime.prepare_answer_context(
            cls.original_query,
            max_videos=6,
            local_personalization=False,
        )
        cls.continued_context = cls.runtime.prepare_answer_context(
            "双打，落地后停在原地，上一拍是重杀直线",
            max_videos=6,
            local_personalization=False,
            continue_from=cls.first_context,
            clarification_answers={
                "clarify.branch.discipline": "双打",
                "clarify.mechanism.movement_transition": "落地后重心停在原地",
                "clarify.mechanism.shot_choice_and_recovery_time": (
                    "上一拍是重杀，走直线"
                ),
            },
        )

    def test_first_turn_has_stable_machine_readable_requests(self):
        request_ids = [
            item["question_id"]
            for item in self.first_context["clarification_decision"][
                "clarification_requests"
            ]
        ]
        self.assertEqual(
            request_ids,
            [
                "clarify.branch.discipline",
                "clarify.mechanism.movement_transition",
                "clarify.mechanism.shot_choice_and_recovery_time",
            ],
        )
        self.assertEqual(
            request_ids,
            self.first_context["clarification_state"]["pending_question_ids"],
        )

    def test_continuation_replans_without_losing_the_original_problem(self):
        context = self.continued_context
        self.assertEqual(
            context["clarification_state"]["original_query"],
            self.original_query,
        )
        self.assertIn(self.original_query, context["query"])
        self.assertEqual(
            context["question_interpretation"]["constraints"]["discipline"],
            ["doubles"],
        )
        hypotheses = {
            item["text"]
            for item in context["diagnostic_model"]["user_hypotheses"]
        }
        self.assertEqual(hypotheses, {"步法太慢"})
        self.assertNotIn(
            "discipline",
            {
                item["axis"]
                for item in context["diagnostic_model"]["material_branches"]
            },
        )
        self.assertEqual(
            context["clarification_state"]["pending_question_ids"], []
        )

    def test_continuation_keeps_unique_cause_boundary(self):
        diagnostic = self.continued_context["diagnostic_model"]
        self.assertTrue(diagnostic["do_not_claim_unique_cause"])
        self.assertTrue(
            diagnostic["unique_cause_confirmation_requires_user_video"]
        )


if __name__ == "__main__":
    unittest.main()
