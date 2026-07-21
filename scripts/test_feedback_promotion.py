#!/usr/bin/env python3
import importlib.util
import json
import os
import subprocess
import sys
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

    def import_issue(
        self,
        source_url=(
            "https://github.com/MuyuanGuo/badminton-skills-coach/issues/17"
        ),
        verified=True,
    ):
        body = """### 用户问题
这里是不会进入公共信号的原始私人措辞

### 回答编号
A-public-example

### Skill 回答或出错片段
回答正文中的杀球力量建议过于笼统。

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
1.1.0-dev.3
"""
        verification = (
            {
                "method": "github_api",
                "repository": "MuyuanGuo/badminton-skills-coach",
                "issue_number": 17,
                "node_id": "I_test_feedback_source",
                "state": "open",
                "source_updated_at": "2026-07-14T00:00:00Z",
                "body_sha256": self.feedback.body_sha256(body),
                "verified_at": "2026-07-14T00:00:01Z",
            }
            if verified
            else None
        )
        return self.feedback.import_github_issue(
            body=body,
            source_url=source_url,
            queue_dir=self.queue_dir,
            source_verification=verification,
        )

    def promote(self, feedback_id, **kwargs):
        feedback = self.feedback.show_feedback(feedback_id, self.queue_dir)
        verification = feedback.get("source", {}).get("verification")
        if verification:
            feedback["source"]["promotion_verification"] = {
                **verification,
                "verified_at": self.feedback.utc_now(),
                "matches_imported_body": True,
            }
            self.feedback.atomic_write_json(
                self.queue_dir / "queue" / f"{feedback_id}.json", feedback
            )
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

    def test_promotion_requires_post_review_source_reverification(self):
        imported = self.import_issue()
        self.feedback.review_feedback(
            feedback_id=imported["feedback_id"],
            decision="accepted",
            note="已核对问题场景和全部公开视频",
            reviewer="test-maintainer",
            queue_dir=self.queue_dir,
        )
        with self.assertRaisesRegex(ValueError, "reverified"):
            self.promotion.promote_feedback(
                feedback_id=imported["feedback_id"],
                public_query="杀球不重没有威胁怎么办",
                evidence_note="已逐条回看三条公开视频并确认相关性边界",
                promoted_by="test-maintainer",
                queue_dir=self.queue_dir,
                signals_path=self.signals_path,
                skill_signals_path=self.skill_signals_path,
                evaluation_path=self.evaluation_path,
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
        self.assertEqual(
            result["signal"]["source_body_sha256"],
            imported["source"]["verification"]["body_sha256"],
        )

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

    def test_public_correction_reaches_query_replan_and_source_recheck(self):
        body = """### 用户问题
杀球不重没有威胁怎么办

### 用户真实意图
分别判断发力链和落点选择

### 回答编号
A-public-correction

### Skill 回答或出错片段
回答把用户问题错误地收窄成单一发力问题。

### 最有价值的视频
无

### 明确不相关的视频
无

### 遗漏的视频
无

### 需重新核对的视频
7659991105622862457

### 文字回答问题
- 问题理解错误
- 视频转写错误

### 补充说明
公开纠错测试。

### 版本信息
1.1.0-dev.3
"""
        issue_url = "https://github.com/MuyuanGuo/badminton-skills-coach/issues/18"
        imported = self.feedback.import_github_issue(
            body=body,
            source_url=issue_url,
            queue_dir=self.queue_dir,
            source_verification={
                "method": "github_api",
                "repository": "MuyuanGuo/badminton-skills-coach",
                "issue_number": 18,
                "node_id": "I_test_feedback_correction",
                "state": "open",
                "source_updated_at": "2026-07-14T00:00:00Z",
                "body_sha256": self.feedback.body_sha256(body),
                "verified_at": "2026-07-14T00:00:01Z",
            },
        )
        self.feedback.review_feedback(
            feedback_id=imported["feedback_id"],
            decision="accepted",
            note="已核对公开纠错字段和目标视频",
            reviewer="test-maintainer",
            queue_dir=self.queue_dir,
        )
        promoted = self.promote(imported["feedback_id"])
        self.assertEqual(promoted["signal"]["intended_query"], "分别判断发力链和落点选择")
        self.assertEqual(
            promoted["signal"]["source_issue_video_ids"],
            ["7659991105622862457"],
        )

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
        preferences = payload["feedback_guidance"]["answer_preferences"]
        self.assertTrue(preferences["needs_query_replan"])
        self.assertEqual(
            preferences["query_replan_hints"], ["分别判断发力链和落点选择"]
        )
        self.assertTrue(preferences["needs_source_recheck"])
        self.assertEqual(
            preferences["source_recheck_video_ids"], ["7659991105622862457"]
        )

    def test_unaccepted_or_local_feedback_cannot_enter_public_signals(self):
        imported = self.import_issue()
        with self.assertRaisesRegex(ValueError, "accepted"):
            self.promote(imported["feedback_id"])

        local = self.feedback.record_feedback(
            question="杀球不重怎么办",
            video_specs=["V1=7659991105622862457"],
            feedback_text="V1 最有价值。",
            answer_text="杀球力量回答正文。",
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

    def test_unverified_github_issue_cannot_enter_public_signals(self):
        imported = self.import_issue(verified=False)
        self.feedback.review_feedback(
            feedback_id=imported["feedback_id"],
            decision="accepted",
            note="内容已人工检查，但来源没有经过 GitHub API 校验",
            reviewer="test-maintainer",
            queue_dir=self.queue_dir,
        )
        with self.assertRaisesRegex(ValueError, "verified through the API"):
            self.promote(imported["feedback_id"])

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

    def test_changed_issue_revision_requires_explicit_single_signal_replacement(self):
        original = self.import_issue()
        self.feedback.review_feedback(
            feedback_id=original["feedback_id"],
            decision="accepted",
            note="已核对首个 Issue 修订",
            reviewer="test-maintainer",
            queue_dir=self.queue_dir,
        )
        first = self.promote(original["feedback_id"])

        changed_body = """### 用户问题
公开问题的新修订

### Skill 回答或出错片段
修改后的回答仍缺少可执行步骤。

### 最有价值的视频
7656560952972884730

### 明确不相关的视频
7659348110628345210

### 遗漏的视频
无

### 文字回答问题
难以执行

### 补充说明
公开内容已经修改。

### 版本信息
1.1.0-dev.3
"""
        verification = {
            "method": "github_api",
            "repository": "MuyuanGuo/badminton-skills-coach",
            "issue_number": 17,
            "node_id": "I_test_feedback_source",
            "state": "open",
            "source_updated_at": "2026-07-14T01:00:00Z",
            "body_sha256": self.feedback.body_sha256(changed_body),
            "verified_at": "2026-07-14T01:00:01Z",
        }
        replacement = self.feedback.import_github_issue(
            body=changed_body,
            source_url="https://github.com/MuyuanGuo/badminton-skills-coach/issues/17",
            queue_dir=self.queue_dir,
            source_verification=verification,
        )
        self.feedback.review_feedback(
            feedback_id=replacement["feedback_id"],
            decision="accepted",
            note="已核对修改后的 Issue 修订",
            reviewer="test-maintainer",
            queue_dir=self.queue_dir,
        )
        with self.assertRaisesRegex(ValueError, "older revision"):
            self.promote(replacement["feedback_id"])

        replaced = self.promote(
            replacement["feedback_id"], replace_existing=True
        )
        self.assertEqual(replaced["status"], "replaced")
        self.assertEqual(replaced["signal"]["signal_id"], first["signal"]["signal_id"])
        signals = json.loads(self.signals_path.read_text(encoding="utf-8"))["signals"]
        cases = json.loads(self.evaluation_path.read_text(encoding="utf-8"))["cases"]
        self.assertEqual(len(signals), 1)
        self.assertEqual(len(cases), 1)
        self.assertEqual(signals[0]["source_feedback_id"], replacement["feedback_id"])
        self.assertEqual(cases[0]["expected_answer_reminders"], ["hard_to_apply"])

    def test_atomic_bundle_restores_every_file_after_partial_failure(self):
        first = self.root / "first.json"
        second = self.root / "second.json"
        first.write_bytes(b"old-first\n")
        second.write_bytes(b"old-second\n")
        replace_count = 0

        def fail_second_replace(source, destination):
            nonlocal replace_count
            replace_count += 1
            if replace_count == 2:
                raise OSError("injected second-file failure")
            os.replace(source, destination)

        with self.assertRaisesRegex(OSError, "injected"):
            self.promotion.atomic_write_bundle(
                {first: b"new-first\n", second: b"new-second\n"},
                replace_func=fail_second_replace,
            )
        self.assertEqual(first.read_bytes(), b"old-first\n")
        self.assertEqual(second.read_bytes(), b"old-second\n")

    def test_concurrent_promotions_create_exactly_one_signal(self):
        imported = self.import_issue()
        self.feedback.review_feedback(
            feedback_id=imported["feedback_id"],
            decision="accepted",
            note="已核对问题场景和全部公开视频",
            reviewer="test-maintainer",
            queue_dir=self.queue_dir,
        )
        feedback = self.feedback.show_feedback(imported["feedback_id"], self.queue_dir)
        feedback["source"]["promotion_verification"] = {
            **feedback["source"]["verification"],
            "verified_at": self.feedback.utc_now(),
            "matches_imported_body": True,
        }
        self.feedback.atomic_write_json(
            self.queue_dir / "queue" / f"{imported['feedback_id']}.json", feedback
        )
        command = [
            sys.executable,
            str(PROMOTION_PATH),
            "--feedback-id",
            imported["feedback_id"],
            "--public-query",
            "杀球不重没有威胁怎么办",
            "--evidence-note",
            "已逐条回看三条公开视频并确认相关性边界",
            "--promoted-by",
            "concurrency-test",
            "--queue-dir",
            str(self.queue_dir),
            "--signals-path",
            str(self.signals_path),
            "--skill-signals-path",
            str(self.skill_signals_path),
            "--evaluation-path",
            str(self.evaluation_path),
        ]
        processes = [
            subprocess.Popen(
                command,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for _ in range(2)
        ]
        outputs = [process.communicate(timeout=20) for process in processes]
        for process, (stdout, stderr) in zip(processes, outputs):
            self.assertEqual(process.returncode, 0, msg=stdout + stderr)
        statuses = {json.loads(stdout)["status"] for stdout, _ in outputs}
        self.assertEqual(statuses, {"promoted", "already_promoted"})
        signals = json.loads(self.signals_path.read_text(encoding="utf-8"))["signals"]
        self.assertEqual(len(signals), 1)

    def test_readme_status_updates_current_template_without_rewriting_sections(self):
        template = """# Project
![Badminton Skills Coach：0 条教学视频、证据型检索与刘辉教学图谱](.github/assets/social-preview.png)
- 获取到的抖音公开视频：`0` 条
- 已排除非教学/广告器材内容：`0` 条
- 已加入 Skill 知识库的教学视频：`0` 条
- 可理解证据覆盖：`0/0`（`0` 条转写证据，`0` 条视觉复核摘要兜底）
- 等待人工复核：`0` 条
- 最新入库教学视频：旧内容
- 已晋升公共反馈信号：`0` 条（旧状态）
  evaluate_video_comprehension.py  审计0条可移植证据、本机转写和反向召回
- 视频理解审计：GitHub Actions 对 `0/0` 条 ready 视频检查仓库内可移植的转写证据或视觉复核摘要、运行时读取和自身证据候选召回，三项覆盖率都必须为 `100%`；当前构成为 `0 + 0`。原始转写文件不进入 Git，维护者在本机另用 `--require-raw-transcripts` 验证 0 条证据都能回溯到原始转写。
## 这个 Skill 能做什么
保留正文
"""
        video_index = json.loads(
            (ROOT / "data" / "douyin_video_index.json").read_text(encoding="utf-8")
        )
        teaching_filter = json.loads(
            (ROOT / "data" / "douyin_teaching_filtered.json").read_text(
                encoding="utf-8"
            )
        )
        knowledge = json.loads(
            (ROOT / "data" / "knowledge" / "douyin_knowledge_base.json").read_text(
                encoding="utf-8"
            )
        )
        updated = self.readme_status.update_readme_text(
            template,
            video_index,
            teaching_filter,
            knowledge,
            {"version": 1, "signals": [{"signal_id": "P-test"}]},
        )
        status = self.readme_status.derive_project_status(
            video_index, teaching_filter, knowledge
        )
        evidence = self.readme_status.evidence_counts(knowledge)
        self.assertIn("已晋升公共反馈信号：`1` 条", updated)
        self.assertIn(
            "已排除非教学/广告器材内容："
            f"`{status['excluded_non_teaching_ads_equipment']}` 条",
            updated,
        )
        self.assertIn(
            f"等待人工复核：`{status['pending_human_review_or_processing']}` 条",
            updated,
        )
        self.assertIn(
            f"可理解证据覆盖：`{evidence['ready']}/{evidence['ready']}`"
            f"（`{evidence['transcript']}` 条转写证据，"
            f"`{evidence['visual']}` 条视觉复核摘要兜底）",
            updated,
        )
        self.assertIn(
            f"当前构成为 `{evidence['transcript']} + {evidence['visual']}`",
            updated,
        )
        self.assertIn("## 这个 Skill 能做什么\n保留正文", updated)

    def test_skill_and_agent_status_counts_follow_knowledge(self):
        knowledge = {
            "videos": [
                {"processing_status": "ready", "confidence": "medium"},
                {"processing_status": "ready", "confidence": "visual_reviewed"},
                {"processing_status": "needs_visual_review", "confidence": "low"},
                {"processing_status": "not_teaching", "confidence": "low"},
            ]
        }
        skill = """---
description: Archive from the full 406-video processed knowledge base, including 350 ready teaching videos.
---
Base coaching claims on `references/knowledge-base.json`: 406 processed videos, including 350 `ready` teaching entries, 9 entries awaiting visual review.
Among the ready entries, 331 are transcript-backed and 19 use reviewed visual summaries.
- `knowledge-base.json`: full structured knowledge entries for 406 processed videos, including 350 ready teaching videos (331 transcript-backed and 19 visual-review fallbacks) and 9 entries awaiting visual review.
"""
        updated_skill = self.readme_status.update_skill_status_text(skill, knowledge)
        self.assertIn("full 4-video processed knowledge base", updated_skill)
        self.assertIn("including 2 ready teaching videos.", updated_skill)
        self.assertIn(
            "`references/knowledge-base.json`: 4 processed videos", updated_skill
        )
        self.assertIn(
            "including 2 `ready` teaching entries, 1 entries awaiting visual review",
            updated_skill,
        )
        self.assertIn(
            "Among the ready entries, 1 are transcript-backed and 1 use reviewed visual summaries",
            updated_skill,
        )
        self.assertIn(
            "full structured knowledge entries for 4 processed videos, including 2 ready teaching videos (1 transcript-backed and 1 visual-review fallbacks) and 1 entries awaiting visual review.",
            updated_skill,
        )

        metadata = (
            'interface:\n'
            '  short_description: "基于350条教学视频回答，并安全使用已审核的本地与公共反馈"\n'
        )
        updated_metadata = self.readme_status.update_agent_metadata_text(
            metadata, knowledge
        )
        self.assertIn("基于2条教学视频回答", updated_metadata)


if __name__ == "__main__":
    unittest.main()
