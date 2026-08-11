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
                "evidence_focus": {
                    "kind": "branch_axis",
                    "id": "discipline",
                },
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

    def test_passive_rearcourt_baseline_goal_implies_clear_only_when_unspecified(
        self,
    ):
        selection_rules = self.runtime.load_selection_rules()
        inferred = self.runtime.query_constraints(
            self.search,
            "后场被动来不及架拍怎么把球打到底线",
            selection_rules,
        )
        self.assertEqual(inferred["shot_family"], ["clear"])
        explicit = self.runtime.query_constraints(
            self.search,
            "后场被动时怎么挑球回到底线",
            selection_rules,
        )
        self.assertEqual(explicit["shot_family"], ["lift"])

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
        self.assertIn("用户补充：是双打", continuation["semantic_query"])
        self.assertNotIn("比赛项目", continuation["semantic_query"])
        self.assertEqual(
            continuation["resolved_answers"][0]["question_id"],
            "clarify.branch.discipline",
        )
        self.assertEqual(
            continuation["resolved_answers"][0]["evidence_focus"],
            {"kind": "branch_axis", "id": "discipline"},
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
        self.assertNotIn("比赛项目", continuation["semantic_query"])
        self.assertNotIn(
            "上一拍后的重心与衔接路线",
            continuation["semantic_query"],
        )

    def test_any_assistant_label_is_isolated_from_hard_focus(self):
        selection_rules = self.runtime.load_selection_rules()
        labels = [
            "握拍松紧",
            "拍面角度",
            "步法与站位",
            "击球点与节奏",
        ]
        for label in labels:
            with self.subTest(label=label):
                request = {
                    "question_id": "clarify.synthetic",
                    "unknown_type": "user_reported_observation",
                    "question": "请补充你观察到的情况。",
                    "query_label": label,
                    "answer_cues": ["身后"],
                }
                prior = self.prior_context([request])
                _, continuation = self.runtime.resolve_continuation(
                    self.search,
                    "发生在身后",
                    prior,
                    None,
                    self.rules,
                )
                self.assertNotIn(label, continuation["semantic_query"])
                plan, _ = self.runtime.continuation_query_plan(
                    self.search,
                    continuation["semantic_query"],
                    continuation,
                )
                focus_query = plan["retrieval_guidance"][
                    "required_focus_query"
                ]
                original_focus = self.search.plan_query(prior["query"])[
                    "retrieval_guidance"
                ]["intent_frame"]["positive_query"]
                self.assertEqual(focus_query, original_focus)
                self.assertEqual(
                    self.runtime.required_focus_groups(
                        self.search, focus_query, selection_rules
                    ),
                    self.runtime.required_focus_groups(
                        self.search, original_focus, selection_rules
                    ),
                )

    def test_focus_matching_ignores_chinese_function_words(self):
        selection_rules = self.runtime.load_selection_rules()
        groups = self.runtime.required_focus_groups(
            self.search, "击球点为什么太低", selection_rules
        )
        self.assertTrue(
            self.runtime.video_supports_required_focus(
                self.search,
                {
                    "title": "被动反手击球的位置与框架",
                    "category": "反手被动球",
                    "teaching_note": {},
                },
                groups,
                selection_rules,
            )
        )

    def test_observation_reply_does_not_change_requested_output_type(self):
        request = {
            "question_id": "clarify.synthetic",
            "unknown_type": "user_reported_observation",
            "question": "请补充触球位置。",
            "query_label": "击球点",
            "answer_cues": ["身前", "身后"],
        }
        prior = self.prior_context([request])
        _, continuation = self.runtime.resolve_continuation(
            self.search,
            "身前还是身后不太确定",
            prior,
            None,
            self.rules,
        )
        plan, _ = self.runtime.continuation_query_plan(
            self.search,
            continuation["semantic_query"],
            continuation,
        )
        requested_output = plan["retrieval_guidance"]["intent_frame"][
            "requested_output"
        ]
        original_output = self.search.plan_query(prior["query"])[
            "retrieval_guidance"
        ]["intent_frame"]["requested_output"]
        self.assertEqual(requested_output, original_output)

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

    def test_legacy_v1_state_is_migrated_without_losing_user_replies(self):
        prior = self.prior_context()
        legacy = copy.deepcopy(prior)
        state = legacy["clarification_state"]
        state["schema_version"] = 1
        state.pop("semantic_query", None)
        state["state_digest"] = self.runtime.clarification_state_digest(state)
        _, continuation = self.runtime.resolve_continuation(
            self.search,
            "是双打",
            legacy,
            None,
            self.rules,
        )
        self.assertEqual(continuation["semantic_query"], prior["query"] + "\n用户补充：是双打")

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
        contract = self.first_context["answer_turn_contract"]
        self.assertEqual(contract["turn_number"], 1)
        self.assertEqual(contract["pending_clarifications"], self.first_context[
            "clarification_decision"
        ]["clarification_requests"])
        self.assertTrue(
            all(item["purpose"] for item in contract["pending_clarifications"])
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
        contract = context["answer_turn_contract"]
        self.assertEqual(contract["original_query"], self.original_query)
        self.assertEqual(contract["effective_query"], context["query"])
        self.assertEqual(contract["turn_number"], 2)
        self.assertEqual(len(contract["resolved_clarifications"]), 3)
        self.assertEqual(contract["pending_clarifications"], [])
        self.assertEqual(
            contract["evidence_state_digest"],
            self.runtime.canonical_json_digest(contract["evidence_state"]),
        )

    def test_clarification_metadata_does_not_become_new_query_units(self):
        context = self.continued_context
        self.assertEqual(
            context["question_interpretation"]["query_units"],
            [self.original_query],
        )
        self.assertNotIn(
            "比赛项目", context["question_interpretation"]["intent_frame"]["positive_query"]
        )
        self.assertNotIn(
            "上一拍后的重心与衔接路线",
            context["question_interpretation"]["intent_frame"]["positive_query"],
        )
        self.assertEqual(
            [
                item["text"]
                for item in context["claim_evidence_map"]
                if item["kind"] == "question_unit"
            ],
            [self.original_query],
        )

    def test_continuation_exposes_an_honest_evidence_gap(self):
        context = self.continued_context
        # Related component evidence may remain available for bounded mechanism
        # claims. It must not silently upgrade the user's full question into a
        # supported claim.
        self.assertTrue(context["selected_videos"])
        question_claim = next(
            item
            for item in context["claim_evidence_map"]
            if item["kind"] == "question_unit"
        )
        self.assertEqual(question_claim["status"], "supported")
        self.assertTrue(question_claim["evidence"])
        self.assertTrue(
            all(
                item["scope"]
                == "component_or_generic_support_only_not_full_question_proof"
                for item in question_claim["evidence"]
            )
        )
        hypothesis_claim = next(
            item
            for item in context["claim_evidence_map"]
            if item["kind"] == "user_hypothesis"
        )
        self.assertEqual(hypothesis_claim["status"], "unverified")
        self.assertEqual(hypothesis_claim["evidence"], [])
        completeness = {
            item["item_id"]: item
            for item in context["completeness_contract"]["items"]
        }
        self.assertEqual(
            completeness[hypothesis_claim["claim_id"]]["status"],
            "unresolved",
        )

    def test_continuation_keeps_unique_cause_boundary(self):
        diagnostic = self.continued_context["diagnostic_model"]
        self.assertTrue(diagnostic["do_not_claim_unique_cause"])
        self.assertTrue(diagnostic["additional_information_can_improve_answer"])
        self.assertNotIn(
            "unique_cause_confirmation_requires_user_video", diagnostic
        )


class ClarificationMechanismRetentionIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = load_runtime()
        cls.first = cls.runtime.prepare_answer_context(
            "反手打不到位是因为啥",
            max_videos=10,
            local_personalization=False,
        )
        cls.second = cls.runtime.prepare_answer_context(
            "发生时是被动、球最后落在对手中场，而且我怀疑击球点不对",
            max_videos=10,
            local_personalization=False,
            continue_from=cls.first,
        )
        cls.third = cls.runtime.prepare_answer_context(
            "已经到了身后，触球点相较正常位置偏低",
            max_videos=10,
            local_personalization=False,
            continue_from=cls.second,
        )

    def test_assistant_label_never_becomes_machine_focus(self):
        self.assertIn(
            "补充说明（击球点的高度与前后位置）",
            self.third["query"],
        )
        semantic = self.third["semantic_query"]
        self.assertNotIn("击球点的高度与前后位置", semantic)
        self.assertNotIn(
            "击球点的高度与前后位置",
            self.third["question_interpretation"]["intent_frame"][
                "positive_query"
            ],
        )

    def test_resolved_mechanism_is_structured_not_label_inferred(self):
        resolved = self.third["clarification_state"]["resolved_answers"]
        contact = next(
            item
            for item in resolved
            if item["question_id"] == "clarify.mechanism.contact_point"
        )
        self.assertEqual(
            contact["evidence_focus"],
            {"kind": "mechanism", "id": "contact_point"},
        )
        mechanisms = {
            item["mechanism_id"]: item
            for item in self.third["diagnostic_model"]["supported_mechanisms"]
        }
        self.assertIn("contact_point", mechanisms)
        self.assertTrue(mechanisms["contact_point"]["eligible_video_labels"])

    def test_conditional_evidence_survives_the_complete_three_turn_path(self):
        selected_ids = {
            item["video_id"] for item in self.third["selected_videos"]
        }
        self.assertIn("7546109410041908538", selected_ids)
        self.assertGreater(
            self.third["selection"]["semantic_answerable_video_count"], 0
        )
        question_claim = next(
            item
            for item in self.third["claim_evidence_map"]
            if item["kind"] == "question_unit"
        )
        self.assertEqual(question_claim["status"], "supported")
        self.assertTrue(question_claim["evidence"])
        self.assertTrue(
            self.third["diagnostic_model"]["do_not_claim_unique_cause"]
        )

    def test_landing_outcome_is_not_opponent_location(self):
        actor = self.third["question_interpretation"]["actor_context"]
        self.assertEqual(actor["opponent_query"], "")
        self.assertEqual(actor["opponent_constraints"], {})
        self.assertNotIn("court_zone", actor["target_constraints"])

    def test_generic_context_answer_does_not_reask_a_covered_mechanism(self):
        continued = self.runtime.prepare_answer_context(
            "一般是被动，球落在对手中场，触球点已经在身体后面",
            max_videos=10,
            local_personalization=False,
            continue_from=self.first,
        )
        pending_ids = set(
            continued["clarification_state"]["pending_question_ids"]
        )
        self.assertNotIn("clarify.mechanism.contact_point", pending_ids)
        contact = next(
            item
            for item in continued["diagnostic_model"]["supported_mechanisms"]
            if item["mechanism_id"] == "contact_point"
        )
        self.assertTrue(contact["eligible_video_labels"])


if __name__ == "__main__":
    unittest.main()
