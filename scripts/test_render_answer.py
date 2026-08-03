#!/usr/bin/env python3

import importlib.util
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_SCRIPTS = ROOT / "skills" / "liuhui-badminton-coach" / "scripts"


def load(name):
    path = SKILL_SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RenderAnswerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = load("prepare_answer_context")
        cls.renderer = load("render_answer")
        cls.auditor = load("audit_answer")
        cls.context = cls.runtime.prepare_answer_context(
            "双打接杀挡网总冒高，是拍面还是击球点问题？",
            local_personalization=False,
        )
        cls.packet = cls.runtime.build_answer_packet(cls.context)

    def test_default_render_uses_only_bound_atoms_and_exact_feedback(self):
        answer = self.renderer.render_answer(self.packet)
        for atom in self.packet["answer_plan"]["selected_evidence_atoms"]:
            self.assertIn(atom["verbalizable_claim"], answer)
        self.assertTrue(answer.rstrip().endswith(self.packet["feedback_prompt"]))
        for video in self.packet["selected_videos"]:
            if video["label"] not in self.packet["display_videos"]:
                self.assertNotIn(f"{video['label']} 不相关", answer)

    def test_every_rendered_citation_has_a_displayed_source(self):
        context = self.runtime.prepare_answer_context(
            "我的反手高远经常只到中场，是拍面没向上、击球点太靠后，还是握得太紧？没有连续动作视频时能确定哪个吗？",
            local_personalization=False,
        )
        packet = self.runtime.build_answer_packet(context)
        answer = self.renderer.render_answer(packet)
        cited = set(re.findall(r"\[(V\d+)\]", answer))
        self.assertTrue(cited)
        self.assertTrue(cited.issubset(set(packet["display_videos"])))
        draft = self.renderer.default_draft(packet)
        windows = packet["evidence_windows"]
        window_by_claim = {
            block["claim_id"]: windows[block["window_id"]]["text"]
            for block in draft["blocks"]
            if block["type"] == "claim_window"
        }
        self.assertIn("拍面摊开向上", window_by_claim["H1"])
        self.assertIn("位置和框架一定要契合", window_by_claim["H2"])
        self.assertEqual(set(packet["display_videos"]), cited)

    def test_diagnostic_gap_render_states_unique_cause_boundary(self):
        context = self.runtime.prepare_answer_context(
            "单打我从后场正手吊直线后回中，再启动接对方放网总慢半拍。这一整段应该先改吊球、回中，还是上网启动？",
            local_personalization=False,
        )
        answer = self.renderer.render_answer(
            self.runtime.build_answer_packet(context)
        )
        self.assertIn("不能确认你个人动作的唯一原因", answer)

    def test_free_technical_suffix_field_fails_closed(self):
        draft = self.renderer.default_draft(self.packet)
        draft["blocks"][0]["suffix"] = "所以一定要猛甩手腕"
        with self.assertRaisesRegex(ValueError, "free or missing fields"):
            self.renderer.render_answer(self.packet, draft)

    def test_cross_claim_atom_fails_closed(self):
        draft = self.renderer.default_draft(self.packet)
        atom_blocks = [item for item in draft["blocks"] if item["type"] == "claim_atom"]
        if len(atom_blocks) < 2:
            self.skipTest("fixture needs two atom-backed claims")
        atom_blocks[0]["atom_id"] = atom_blocks[-1]["atom_id"]
        with self.assertRaisesRegex(ValueError, "not authorized"):
            self.renderer.render_answer(self.packet, draft)

    def test_missing_claim_fails_closed(self):
        draft = self.renderer.default_draft(self.packet)
        draft["blocks"] = draft["blocks"][:-1]
        with self.assertRaisesRegex(ValueError, "omits claims"):
            self.renderer.render_answer(self.packet, draft)

    def test_continuation_render_acknowledges_resolved_clarification(self):
        first = self.runtime.prepare_answer_context(
            "后场被动来不及架拍怎么把球打到底线",
            local_personalization=False,
        )
        continued = self.runtime.prepare_answer_context(
            "发生在反手侧",
            local_personalization=False,
            continue_from=first,
            clarification_answers={
                "clarify.branch.stroke_side": "反手侧"
            },
        )
        packet = self.runtime.build_answer_packet(continued)
        answer = self.renderer.render_answer(packet)
        self.assertIn("你已补充：击球侧：反手侧。", answer)

    def test_inferred_forecourt_target_and_scope_boundary_are_rendered(self):
        query = "来不及接网前小球或者网前吊球怎么办"
        context = self.runtime.prepare_answer_context(
            query, local_personalization=False
        )
        packet = self.runtime.build_answer_packet(context)
        answer = self.renderer.render_answer(packet)
        self.assertIn("本题按“向前启动 上网步法”处理", answer)
        self.assertIn("不是用户自己打吊球", answer)
        self.assertIn("杀上网是另一种特定衔接", answer)
        self.assertIn("反手被动高远也不能证明本题", answer)
        self.assertIn("途中要让跑动节奏匹配来球速度", answer)
        self.assertNotIn("杀球落地后重心", answer)
        self.assertTrue(self.auditor.audit_answer(query, context, answer)["passed"])

    def test_kill_to_net_branch_markers_and_event_chain_audit_cleanly(self):
        short_query = "杀球后来不及上网"
        chain_query = "杀球后被对手挡网，我总是来不及上去怎么办"
        answers = {}
        for query in (short_query, chain_query):
            context = self.runtime.prepare_answer_context(
                query, local_personalization=False
            )
            packet = self.runtime.build_answer_packet(context)
            answer = self.renderer.render_answer(packet)
            audit = self.auditor.audit_answer(query, context, answer)
            self.assertTrue(audit["passed"], audit["violations"])
            self.assertNotIn("conditional条件", answer)
            self.assertIn("落地后的第一步", answer)
            self.assertIn("停止前冲或转守", answer)
            self.assertIn("反手被动高远", answer)
            self.assertIn("动态低架", answer)
            self.assertNotIn("visual_review_no_timestamp", answer)
            self.assertIn("视觉复核片段（无精确时间点）", answer)
            answers[query] = answer
        self.assertNotEqual(answers[short_query], answers[chain_query])
        self.assertIn("对手：挡网", answers[chain_query])
        self.assertIn("杀球后被对手挡网", answers[chain_query])


if __name__ == "__main__":
    unittest.main()
