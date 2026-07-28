#!/usr/bin/env python3
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README_ZH = ROOT / "README.md"
README_EN = ROOT / "README.en.md"
SKILL = ROOT / "skills" / "liuhui-badminton-coach" / "SKILL.md"
ANSWER_WORKFLOW = (
    ROOT
    / "skills"
    / "liuhui-badminton-coach"
    / "references"
    / "answer-workflow.md"
)
RECOVERY_COMMAND = (
    "python3 scripts/run_bilibili_update_pipeline.py --install"
)


class DocumentationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readme_zh = README_ZH.read_text(encoding="utf-8")
        cls.readme_en = README_EN.read_text(encoding="utf-8")
        cls.skill = SKILL.read_text(encoding="utf-8")
        cls.answer_workflow = ANSWER_WORKFLOW.read_text(encoding="utf-8")

    def test_develop_readmes_keep_recruiter_audience_contract(self):
        self.assertIn(
            "`develop` README 面向招聘官、技术面试官和贡献者",
            self.readme_zh,
        )
        self.assertIn(
            "The `develop` README targets recruiters, technical interviewers, "
            "and contributors",
            self.readme_en,
        )

    def test_bilibili_causal_chain_is_serial_and_bilingual(self):
        for marker in (
            'C --> D["确定性ASR"]',
            'D --> P["转写配方、ASR质量、标题正文与重复门禁"]',
            'P --> E["结构化知识库（含隔离审计记录）"]',
            'E --> R["仅ready进入运行时证据池"]',
            'R --> F["45秒 chunk-first 检索',
        ):
            self.assertIn(marker, self.readme_zh)
        for marker in (
            'C --> D["Deterministic ASR"]',
            'D --> P["Recipe, ASR quality, title-text, and duplicate gates"]',
            'P --> E["Structured knowledge, including quarantine audit records"]',
            'E --> R["Only ready records enter runtime evidence"]',
            'R --> F["45-second chunk-first retrieval',
        ):
            self.assertIn(marker, self.readme_en)
        self.assertNotIn('B --> D["确定性ASR', self.readme_zh)
        self.assertNotIn('B --> D["Deterministic ASR', self.readme_en)

    def test_new_text_memory_boundary_is_explicit_and_bilingual(self):
        for marker in (
            "新增转写不会写入模型权重或成为 Codex 的会话记忆",
            "原始 `.json`、`.srt` 或 `.txt` 文件单独存在不会改变回答",
            "成为 `processing_status: ready` 的知识记录",
        ):
            self.assertIn(marker, self.readme_zh)
        for marker in (
            "A new transcript does not update model weights or become Codex "
            "conversational memory",
            "A raw `.json`, `.srt`, or `.txt` file alone changes no answer",
            "becoming a `processing_status: ready` knowledge record",
        ):
            self.assertIn(marker, self.readme_en)

    def test_automatic_isolation_and_rollback_are_distinct(self):
        for marker in (
            "保留审计状态但保持非 `ready`",
            "不向运行时打包转写段",
            "才回滚本轮生成产物",
        ):
            self.assertIn(marker, self.readme_zh)
        for marker in (
            "audit state is retained but it remains non-`ready`",
            "no transcript segments are packaged for runtime use",
            "instead rolls back the generated artifacts for that run",
        ):
            self.assertIn(marker, self.readme_en)

    def test_recovery_has_one_documented_entry_point(self):
        self.assertEqual(self.readme_zh.count(RECOVERY_COMMAND), 1)
        self.assertEqual(self.readme_en.count(RECOVERY_COMMAND), 1)
        self.assertNotIn(RECOVERY_COMMAND, self.skill)
        self.assertNotIn(RECOVERY_COMMAND, self.answer_workflow)

    def test_runtime_docs_forbid_raw_transcript_shortcuts(self):
        self.assertIn(
            "New transcript files do not update model weights or memory",
            self.skill,
        )
        self.assertIn(
            "never read raw transcript files to fill an evidence gap",
            self.skill,
        )
        self.assertIn(
            "A transcript file on disk is not answer evidence",
            self.answer_workflow,
        )
        self.assertIn(
            "never inspect raw transcripts to repair a missing claim",
            self.answer_workflow,
        )
        self.assertLessEqual(len(self.skill.encode("utf-8")), 12_000)


if __name__ == "__main__":
    unittest.main()
