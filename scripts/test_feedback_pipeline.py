#!/usr/bin/env python3
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FEEDBACK_PATH = (
    ROOT
    / "skills"
    / "liuhui-badminton-coach"
    / "scripts"
    / "feedback.py"
)
CASES_PATH = ROOT / "data" / "evaluation" / "feedback_parser_cases.json"


def load_feedback_module():
    spec = importlib.util.spec_from_file_location("liuhui_feedback_test", FEEDBACK_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FeedbackPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.feedback = load_feedback_module()
        cls.cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
        cls.video_specs = [
            f"{reference}={video_id}"
            for reference, video_id in cls.cases["video_map"].items()
        ]

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.queue_dir = Path(self.temporary_directory.name)
        self.answer = self.feedback.create_answer_context(
            question="双打轮转时应该什么时候补位？",
            video_specs=self.video_specs,
            core_refs=["V1"],
            answer_mode="text_primary",
            user_context=["双打", "业余中级"],
            queue_dir=self.queue_dir,
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_answer_context_uses_contiguous_stable_labels(self):
        self.assertEqual(
            [video["ref"] for video in self.answer["videos"]],
            ["V1", "V2", "V3"],
        )
        self.assertTrue(self.answer["videos"][0]["core"])
        self.assertEqual(self.answer["skill_version"], "1.1.0-dev.2")
        self.assertEqual(
            set(self.feedback.extract_video_refs(self.answer["feedback_hint"])),
            {"V1", "V3"},
        )
        saved_path = (
            self.queue_dir / "answers" / f"{self.answer['answer_id']}.json"
        )
        self.assertTrue(saved_path.exists())

    def test_answer_context_rejects_gaps_and_duplicate_video_ids(self):
        with self.assertRaisesRegex(ValueError, "contiguous"):
            self.feedback.create_answer_context(
                question="测试",
                video_specs=[
                    "V1=7661940775983482097",
                    "V3=7659991105622862457",
                ],
                queue_dir=self.queue_dir,
            )
        with self.assertRaisesRegex(ValueError, "multiple references"):
            self.feedback.create_answer_context(
                question="测试",
                video_specs=[
                    "V1=7661940775983482097",
                    "V2=7661940775983482097",
                ],
                queue_dir=self.queue_dir,
            )

    def test_parser_regression_cases(self):
        _, rules = self.feedback.load_resources()
        answer_payload = {
            key: value
            for key, value in self.answer.items()
            if key != "feedback_hint"
        }
        for case in self.cases["cases"]:
            with self.subTest(case=case["name"]):
                parsed = self.feedback.parse_feedback_text(
                    case["feedback"], answer_payload, rules
                )
                signals = parsed["signals"]
                self.assertEqual(parsed["status"], case["expected_status"])
                self.assertEqual(signals["helpful_video_refs"], case["helpful_refs"])
                self.assertEqual(
                    signals["irrelevant_video_refs"], case["irrelevant_refs"]
                )
                self.assertEqual(
                    signals["text_issue_types"], case["text_issue_types"]
                )
                if "missing_video_ids" in case:
                    self.assertEqual(
                        signals["missing_video_ids"], case["missing_video_ids"]
                    )
                if "outcome" in case:
                    self.assertEqual(signals["outcome"], case["outcome"])

    def test_submit_and_human_review_preserve_audit_history(self):
        queued = self.feedback.submit_feedback(
            answer_id=self.answer["answer_id"],
            feedback_text="V2 最有价值；V3 不相关。",
            queue_dir=self.queue_dir,
        )
        self.assertEqual(queued["status"], "pending_review")
        self.assertEqual(queued["promotion_status"], "not_promoted")

        reviewed = self.feedback.review_feedback(
            feedback_id=queued["feedback_id"],
            decision="accepted",
            note="已核对问题和两条视频的原始证据",
            reviewer="maintainer",
            queue_dir=self.queue_dir,
        )
        self.assertEqual(reviewed["status"], "accepted")
        self.assertEqual(len(reviewed["review_history"]), 1)
        self.assertEqual(reviewed["promotion_status"], "not_promoted")
        self.assertIn("future_promotion", reviewed["next_action"])

    def test_record_writes_only_after_explicit_feedback(self):
        isolated_queue = self.queue_dir / "record-command"
        self.assertFalse(isolated_queue.exists())
        recorded = self.feedback.record_feedback(
            question="网前框架为什么容易僵硬？",
            video_specs=["V1=7661940775983482097"],
            feedback_text="V1 最有价值，已经解决了我的问题。",
            core_refs=["V1"],
            answer_mode="balanced",
            queue_dir=isolated_queue,
        )
        self.assertEqual(recorded["status"], "pending_review")
        self.assertEqual(recorded["signals"]["helpful_video_refs"], ["V1"])
        self.assertEqual(len(list((isolated_queue / "answers").glob("*.json"))), 1)
        self.assertEqual(len(list((isolated_queue / "queue").glob("*.json"))), 1)

    def test_github_issue_import_enters_same_review_queue(self):
        body = """### 用户问题
双打轮转时什么时候补位？

### 回答编号
A-public-example

### 最有价值的视频
https://www.douyin.com/video/7614167503938610417

### 明确不相关的视频
7659991105622862457

### 遗漏的视频
7658231159860261361

### 文字回答问题
文字内容有遗漏

### 补充说明
漏了被动回球后的处理边界。

### 版本信息
1.1.0-dev.2
"""
        imported = self.feedback.import_github_issue(
            body=body,
            source_url="https://github.com/example/repo/issues/1",
            queue_dir=self.queue_dir,
        )
        self.assertEqual(imported["status"], "pending_review")
        self.assertEqual(imported["source"]["type"], "github_issue")
        self.assertEqual(
            imported["signals"]["helpful_video_ids"],
            ["7614167503938610417"],
        )
        self.assertEqual(
            imported["signals"]["text_issue_types"], ["missing_content"]
        )

    def test_export_github_requires_accepted_local_feedback_and_public_consent(self):
        queued = self.feedback.record_feedback(
            question="我的私人问题：昨天在单位球馆被同事针对反手位怎么办？",
            video_specs=["V1=7614167503938610417", "V2=7659991105622862457"],
            feedback_text="这是私人反馈：V1 最有价值；V2 不相关；文字太笼统。",
            core_refs=["V1"],
            answer_mode="balanced",
            queue_dir=self.queue_dir,
        )
        with self.assertRaisesRegex(ValueError, "accepted"):
            self.feedback.export_github_feedback(
                feedback_id=queued["feedback_id"],
                public_question="双打中如何保护反手位？",
                confirm_public=True,
                queue_dir=self.queue_dir,
            )

        reviewed = self.feedback.review_feedback(
            feedback_id=queued["feedback_id"],
            decision="accepted",
            note="用户确认解析结果用于本地个性化",
            reviewer="local-user",
            queue_dir=self.queue_dir,
        )
        with self.assertRaisesRegex(ValueError, "confirm-public"):
            self.feedback.export_github_feedback(
                feedback_id=reviewed["feedback_id"],
                public_question="双打中如何保护反手位？",
                queue_dir=self.queue_dir,
            )

    def test_export_github_is_sanitized_and_round_trips_through_import(self):
        private_question = "我的私人问题：昨天在单位球馆被同事针对反手位怎么办？"
        private_feedback = "这是私人反馈：V1 最有价值；V2 不相关；文字太笼统。"
        queued = self.feedback.record_feedback(
            question=private_question,
            video_specs=["V1=7614167503938610417", "V2=7659991105622862457"],
            feedback_text=private_feedback,
            core_refs=["V1"],
            answer_mode="balanced",
            queue_dir=self.queue_dir,
        )
        reviewed = self.feedback.review_feedback(
            feedback_id=queued["feedback_id"],
            decision="accepted",
            note="用户确认解析结果用于本地个性化",
            reviewer="local-user",
            queue_dir=self.queue_dir,
        )
        public_question = "双打中如何保护反手位？"
        exported = self.feedback.export_github_feedback(
            feedback_id=reviewed["feedback_id"],
            public_question=public_question,
            confirm_public=True,
            queue_dir=self.queue_dir,
        )

        self.assertFalse(exported["uploaded"])
        self.assertEqual(exported["privacy"]["raw_feedback_included"], False)
        self.assertEqual(exported["privacy"]["original_question_included"], False)
        self.assertIn(public_question, exported["issue_body"])
        self.assertNotIn(private_question, exported["issue_body"])
        self.assertNotIn(private_feedback, exported["issue_body"])
        self.assertIn("7614167503938610417", exported["issue_body"])
        self.assertIn("7659991105622862457", exported["issue_body"])

        saved = self.feedback.show_feedback(reviewed["feedback_id"], self.queue_dir)
        self.assertTrue(saved["share_upstream"])
        self.assertFalse(saved["github_export"]["uploaded"])

        imported_queue = self.queue_dir / "imported"
        imported = self.feedback.import_github_issue(
            body=exported["issue_body"],
            source_url="https://github.com/example/repo/issues/2",
            queue_dir=imported_queue,
        )
        self.assertEqual(imported["status"], "pending_review")
        self.assertEqual(imported["question"], public_question)
        self.assertEqual(
            imported["signals"]["helpful_video_ids"], ["7614167503938610417"]
        )
        self.assertEqual(
            imported["signals"]["irrelevant_video_ids"], ["7659991105622862457"]
        )
        self.assertEqual(imported["signals"]["text_issue_types"], ["too_vague"])


if __name__ == "__main__":
    unittest.main()
