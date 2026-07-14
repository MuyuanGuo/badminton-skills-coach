#!/usr/bin/env python3
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_SCRIPTS = ROOT / "skills" / "liuhui-badminton-coach" / "scripts"
PROMOTION_PATH = ROOT / "scripts" / "promote_feedback.py"
README_STATUS_PATH = ROOT / "scripts" / "update_readme_status.py"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FeedbackPromotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.feedback = load_module("promotion_feedback", SKILL_SCRIPTS / "feedback.py")
        cls.promotion = load_module("promotion_pipeline", PROMOTION_PATH)
        cls.search = load_module("promotion_search", SKILL_SCRIPTS / "search_knowledge.py")
        cls.readme_status = load_module("promotion_readme_status", README_STATUS_PATH)

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.queue_dir = self.root / "feedback"
        self.signals_path = self.root / "feedback-signals.json"
        self.skill_signals_path = self.root / "skill-feedback-signals.json"
        self.evaluation_path = self.root / "feedback-relevance-cases.json"
        self.signals_path.write_text(
            json.dumps({"version": 1, "updated_at": None, "signals": []}),
            encoding="utf-8",
        )
        self.evaluation_path.write_text(
            json.dumps({"version": 1, "cases": []}),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def import_issue(self, source_url="https://github.com/example/repo/issues/17"):
        body = """### 用户问题
这里是不会进入公共信号的原始私人措辞

### 回答编号
A-public-example

### 最有价值的视频
https://www.douyin.com/video/7659991105622862457

### 明确不相关的视频
7659348110628345210

### 遗漏的视频
7656560952972884730

### 文字回答问题
过于笼统

### 补充说明
这里是不会进入公共信号的原始补充内容。

### 版本信息
1.1.0-dev.2
"""
        return self.feedback.import_github_issue(
            body=body,
            source_url=source_url,
            queue_dir=self.queue_dir,
        )

    def promote(self, feedback_id, **kwargs):
        return self.promotion.promote_feedback(
            feedback_id=feedback_id,
            public_query="杀球不重没有威胁怎么办",
            evidence_note="已逐条回看三条公开视频并确认相关性边界",
            promoted_by="test-maintainer",
            queue_dir=self.queue_dir,
            signals_path=self.signals_path,
            skill_signals_path=self.skill_signals_path,
            evaluation_path=self.evaluation_path,
            **kwargs,
        )

    def test_accepted_github_feedback_promotes_sanitized_signal_and_evaluation(self):
        imported = self.import_issue()
        self.feedback.review_feedback(
            feedback_id=imported["feedback_id"],
            decision="accepted",
            note="已核对问题场景和全部公开视频",
            reviewer="test-maintainer",
            queue_dir=self.queue_dir,
        )
        result = self.promote(imported["feedback_id"])
        self.assertEqual(result["status"], "promoted")
        self.assertFalse(result["privacy"]["raw_feedback_included"])
        self.assertFalse(result["privacy"]["original_question_included"])

        public_text = self.signals_path.read_text(encoding="utf-8")
        self.assertNotIn("原始私人措辞", public_text)
        self.assertNotIn("原始补充内容", public_text)
        self.assertEqual(
            json.loads(public_text),
            json.loads(self.skill_signals_path.read_text(encoding="utf-8")),
        )
        cases = json.loads(self.evaluation_path.read_text(encoding="utf-8"))["cases"]
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["expected_answer_reminders"], ["too_vague"])

        promoted_feedback = self.feedback.show_feedback(
            imported["feedback_id"], queue_dir=self.queue_dir
        )
        self.assertEqual(promoted_feedback["promotion_status"], "promoted")
        self.assertEqual(
            promoted_feedback["promotion"]["signal_id"],
            result["signal"]["signal_id"],
        )

    def test_promoted_signal_improves_first_user_search_without_local_queue(self):
        imported = self.import_issue()
        self.feedback.review_feedback(
            feedback_id=imported["feedback_id"],
            decision="accepted",
            note="已核对问题场景和全部公开视频",
            reviewer="test-maintainer",
            queue_dir=self.queue_dir,
        )
        promoted = self.promote(imported["feedback_id"])
        original_signals_path = self.search.FEEDBACK_SIGNALS_PATH
        self.search.FEEDBACK_SIGNALS_PATH = self.signals_path
        try:
            payload = self.search.search(
                "杀球不重没有威胁怎么办",
                manifest_limit=None,
                local_personalization=False,
                feedback_dir=self.root / "unused-local-queue",
            )
        finally:
            self.search.FEEDBACK_SIGNALS_PATH = original_signals_path

        manifest = {item["video_id"]: item for item in payload["candidate_manifest"]}
        helpful = manifest["7659991105622862457"]["feedback_adjustment"]
        irrelevant = manifest["7659348110628345210"]["feedback_adjustment"]
        missing = manifest["7656560952972884730"]["feedback_adjustment"]
        self.assertGreater(helpful["global_delta"], 0)
        self.assertLess(irrelevant["global_delta"], 0)
        self.assertEqual(irrelevant["adjusted_tier"], "semantic_lead")
        self.assertIn("global_missing", missing["reasons"])
        self.assertFalse(payload["feedback_guidance"]["local"]["enabled"])
        self.assertEqual(
            payload["feedback_guidance"]["global"]["matched_signal_ids"],
            [promoted["signal"]["signal_id"]],
        )
        self.assertIn(
            "too_vague",
            payload["feedback_guidance"]["answer_preferences"]["query_reminders"],
        )

    def test_unaccepted_or_local_feedback_cannot_enter_public_signals(self):
        imported = self.import_issue()
        with self.assertRaisesRegex(ValueError, "accepted"):
            self.promote(imported["feedback_id"])

        local = self.feedback.record_feedback(
            question="杀球不重怎么办",
            video_specs=["V1=7659991105622862457"],
            feedback_text="V1 最有价值。",
            share_upstream=True,
            queue_dir=self.queue_dir,
        )
        self.feedback.review_feedback(
            feedback_id=local["feedback_id"],
            decision="accepted",
            note="本地反馈即使同意分享也必须先形成公开 GitHub Issue",
            reviewer="test-maintainer",
            queue_dir=self.queue_dir,
        )
        with self.assertRaisesRegex(ValueError, "public GitHub issue"):
            self.promote(local["feedback_id"])

    def test_promotion_is_idempotent(self):
        imported = self.import_issue()
        self.feedback.review_feedback(
            feedback_id=imported["feedback_id"],
            decision="accepted",
            note="已核对问题场景和全部公开视频",
            reviewer="test-maintainer",
            queue_dir=self.queue_dir,
        )
        first = self.promote(imported["feedback_id"])
        second = self.promote(imported["feedback_id"])
        self.assertEqual(second["status"], "already_promoted")
        self.assertEqual(first["signal"]["signal_id"], second["signal"]["signal_id"])
        self.assertEqual(
            len(json.loads(self.signals_path.read_text(encoding="utf-8"))["signals"]),
            1,
        )

    def test_readme_status_updates_current_template_without_rewriting_sections(self):
        template = """# Project
- 获取到的抖音公开视频：`0` 条
- 已排除非教学/广告器材内容：`0` 条
- 已加入 Skill 知识库的教学视频：`0` 条
- 最新入库教学视频：旧内容
- 已晋升公共反馈信号：`0` 条（旧状态）
## 这个 Skill 能做什么
保留正文
"""
        updated = self.readme_status.update_readme_text(
            template,
            json.loads((ROOT / "data" / "douyin_video_index.json").read_text(encoding="utf-8")),
            json.loads(
                (ROOT / "data" / "knowledge" / "douyin_knowledge_base.json").read_text(
                    encoding="utf-8"
                )
            ),
            {"version": 1, "signals": [{"signal_id": "P-test"}]},
        )
        self.assertIn("已晋升公共反馈信号：`1` 条", updated)
        self.assertIn("## 这个 Skill 能做什么\n保留正文", updated)


if __name__ == "__main__":
    unittest.main()
