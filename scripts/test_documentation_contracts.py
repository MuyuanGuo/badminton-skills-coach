#!/usr/bin/env python3
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README_ZH = ROOT / "README.md"
README_EN = ROOT / "README.en.md"
LANDING_PAGE = ROOT / "docs" / "index.html"
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
        cls.landing_page = LANDING_PAGE.read_text(encoding="utf-8")
        cls.skill = SKILL.read_text(encoding="utf-8")
        cls.answer_workflow = ANSWER_WORKFLOW.read_text(encoding="utf-8")
        cls.release_channel = json.loads(
            (ROOT / "config" / "feedback_rules.json").read_text(
                encoding="utf-8"
            )
        )["channel"]

    def test_readme_audience_matches_release_channel(self):
        if self.release_channel == "development":
            self.assertIn("`develop` 是集成分支", self.readme_zh)
            self.assertIn("`develop` is the integration branch", self.readme_en)
        else:
            self.assertIn("`main` 是稳定发布来源", self.readme_zh)
            self.assertIn("`main` is the stable release source", self.readme_en)

    def test_bilibili_causal_chain_is_serial_and_bilingual(self):
        for marker in (
            'C --> D["确定性ASR"]',
            'D --> P["转写配方、ASR质量、来源安全与重复硬门禁"]',
            'P --> E["结构化知识库（含隔离审计记录）"]',
            'E --> A["回答资格分层',
            'A --> S["只读 SQLite 运行时证据存储',
            'S --> F["45秒 chunk-first + 受限窗口检索',
        ):
            self.assertIn(marker, self.readme_zh)
        for marker in (
            'C --> D["Deterministic ASR"]',
            'D --> P["Recipe, ASR quality, source-safety, and duplicate hard gates"]',
            'P --> E["Structured knowledge, including quarantine audit records"]',
            'E --> A["Answer admission layers',
            'A --> S["Read-only SQLite runtime evidence store',
            'S --> F["45-second chunk-first plus bounded-window retrieval',
        ):
            self.assertIn(marker, self.readme_en)
        self.assertNotIn('B --> D["确定性ASR', self.readme_zh)
        self.assertNotIn('B --> D["Deterministic ASR', self.readme_en)

    def test_new_text_memory_boundary_is_explicit_and_bilingual(self):
        for marker in (
            "新增转写不会写入模型权重或成为 Codex 的会话记忆",
            "原始 `.json`、`.srt` 或 `.txt` 文件单独存在不会改变回答",
            "完整通过的记录成为 `primary`",
            "成为 `supplemental`",
        ):
            self.assertIn(marker, self.readme_zh)
        for marker in (
            "A new transcript does not update model weights or become Codex "
            "conversational memory",
            "A raw `.json`, `.srt`, or `.txt` file alone changes no answer",
            "A fully aligned record becomes `primary`",
            "becomes `supplemental`",
        ):
            self.assertIn(marker, self.readme_en)

    def test_automatic_isolation_and_rollback_are_distinct(self):
        for marker in (
            "保留审计状态并保持 `answer_eligibility: none`",
            "受限补充证据",
            "才回滚本轮生成产物",
        ):
            self.assertIn(marker, self.readme_zh)
        for marker in (
            "audit state is retained with `answer_eligibility: none`",
            "bounded supplemental evidence",
            "still roll back the generated artifacts for that run",
        ):
            self.assertIn(marker, self.readme_en)

    def test_recovery_has_one_documented_entry_point(self):
        self.assertEqual(self.readme_zh.count(RECOVERY_COMMAND), 1)
        self.assertEqual(self.readme_en.count(RECOVERY_COMMAND), 1)
        self.assertNotIn(RECOVERY_COMMAND, self.skill)
        self.assertNotIn(RECOVERY_COMMAND, self.answer_workflow)

    def test_install_snippets_download_and_verify_the_sbom_fail_closed(self):
        for document in (self.readme_zh, self.readme_en, self.landing_page):
            self.assertIn("SBOM.cdx.json", document)
            self.assertIn("--fail", document)
            self.assertIn("--show-error", document)
            self.assertIn("--location", document)
            self.assertIn("--retry 3", document)
            self.assertNotIn("curl -L ", document)

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

    def test_site_has_accessibility_and_discovery_basics(self):
        for relative in ("404.html", "favicon.svg", "robots.txt", "sitemap.xml"):
            self.assertTrue((ROOT / "docs" / relative).is_file(), relative)
        for relative in ("index.html", "en/index.html", "evaluation/index.html"):
            page = (ROOT / "docs" / relative).read_text(encoding="utf-8")
            self.assertIn('rel="icon"', page)
            self.assertIn('href="#main"', page)
        evaluation = (
            ROOT / "docs" / "evaluation" / "index.html"
        ).read_text(encoding="utf-8")
        self.assertIn("blob/main/data/evaluation/evaluation_report.json", evaluation)
        self.assertNotIn("blob/develop/", evaluation)

    def test_governance_and_data_terms_are_bilingual_and_linked(self):
        for relative in (
            "CONTRIBUTING.md",
            "CONTRIBUTING.en.md",
            "SECURITY.md",
            "SECURITY.en.md",
            "LICENSE-DATA",
            ".github/REPOSITORY_SETTINGS.md",
            ".github/labels.yml",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)
        for document in (self.readme_zh, self.readme_en):
            self.assertIn("LICENSE-DATA", document)


if __name__ == "__main__":
    unittest.main()
