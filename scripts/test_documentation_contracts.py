#!/usr/bin/env python3
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README_ZH = ROOT / "README.md"
README_EN = README_ZH
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
        cls.version_metadata = json.loads(
            (ROOT / "config" / "feedback_rules.json").read_text(
                encoding="utf-8"
            )
        )
        cls.release_channel = cls.version_metadata["channel"]

    def test_readme_audience_matches_release_channel(self):
        self.assertNotIn("README.en.md", self.readme_zh)
        self.assertRegex(self.readme_zh, r"[\u4e00-\u9fff]")
        self.assertIn("This ", self.readme_zh)
        if self.release_channel == "development":
            self.assertIn("`develop` 是集成分支", self.readme_zh)
            self.assertIn("`develop` is the integration branch", self.readme_en)
            self.assertNotIn("招聘", self.readme_zh)
            self.assertNotIn("recruiter", self.readme_en.lower())
        else:
            self.assertIn("`main` 是稳定发布来源", self.readme_zh)
            self.assertIn("`main` is the stable release source", self.readme_en)

    def test_develop_documents_the_complete_answer_runtime_flow(self):
        if self.release_channel != "development":
            self.assertNotIn("从用户提问到最终回答", self.readme_zh)
            return
        for marker in (
            "用户提交完整问题 / User submits the full question",
            "新问题还是澄清回复？ / New question or clarification reply?",
            "规范术语；解析意图、主体、事件链、条件、子问题与交付要求",
            "只读 SQLite 混合高召回检索",
            "逐子问题语义准入",
            "保留可回答全集；再做去重与合成层限流",
            "构建诊断、澄清、完整性、交付与安全边界契约",
            "SHA-256 绑定的紧凑 answer packet",
            "仅按 claim allowlist 与 synthesis evidence 组织技术内容",
            "选择最多 5 条核心视频（证据不足不补齐）",
            "确定性 renderer 输出结论",
            "完整上下文 auditor 通过？",
            "向用户发送回答 / Send the answer to the user",
        ):
            self.assertIn(marker, self.readme_zh)
        self.assertIn("用户补充澄清 / User clarifies", self.readme_zh)
        self.assertIn("只有 `passed: true` 才发送", self.readme_zh)
        self.assertNotIn("选择 3–5 条核心视频", self.readme_zh)

    def test_versions_and_install_links_match_branch_metadata(self):
        skill_version = self.version_metadata["skill_version"]
        stable_version = self.version_metadata["stable_version"]
        skill_rules = json.loads(
            (
                ROOT
                / "skills"
                / "liuhui-badminton-coach"
                / "references"
                / "feedback-rules.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(skill_rules, self.version_metadata)

        if self.release_channel == "development":
            self.assertIn(
                f"当前开发版本是 **{skill_version}**", self.readme_zh
            )
            self.assertIn(
                f"current development version is **{skill_version}**",
                self.readme_en,
            )
            self.assertIn("发布状态为 **unreleased**", self.readme_zh)
            self.assertIn("release status is **unreleased**", self.readme_en)
            development_core = tuple(
                int(part) for part in skill_version.split("-", 1)[0].split(".")
            )
            stable_core = tuple(int(part) for part in stable_version.split("."))
            self.assertGreater(development_core, stable_core)
        else:
            self.assertEqual(skill_version, stable_version)
            self.assertIn(f"**{stable_version} 稳定版**", self.readme_zh)
            self.assertIn(
                f"**Version {stable_version} is the stable release**",
                self.readme_en,
            )

        for document in (
            self.readme_zh,
            self.readme_en,
            self.landing_page,
            (ROOT / "docs" / "en" / "index.html").read_text(encoding="utf-8"),
        ):
            download_versions = set(
                re.findall(r"releases/download/v(\d+\.\d+\.\d+)", document)
            )
            archive_versions = set(
                re.findall(
                    r"liuhui-badminton-coach-(\d+\.\d+\.\d+)\.zip",
                    document,
                )
            )
            self.assertEqual(download_versions, {stable_version})
            self.assertEqual(archive_versions, {stable_version})

    def test_bilibili_causal_chain_is_serial_and_bilingual(self):
        if self.release_channel != "development":
            self.assertNotIn('C --> D["确定性ASR"]', self.readme_zh)
            return
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
        if self.release_channel != "development":
            self.assertNotIn("新增转写不会写入模型权重", self.readme_zh)
            return
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
        if self.release_channel != "development":
            self.assertNotIn("answer_eligibility: none", self.readme_zh)
            return
        for marker in (
            "保留审计状态并保持 `answer_eligibility: none`",
            "受限补充证据",
            "才回滚本轮生成产物",
        ):
            self.assertIn(marker, self.readme_zh)
        for marker in (
            "audit state is retained with `answer_eligibility: none`",
            "bounded supplemental evidence",
            "only generation-level consistency failures roll back",
        ):
            self.assertIn(marker, self.readme_en)

    def test_recovery_has_one_documented_entry_point(self):
        expected = 1 if self.release_channel == "development" else 0
        self.assertEqual(self.readme_zh.count(RECOVERY_COMMAND), expected)
        self.assertEqual(self.readme_en.count(RECOVERY_COMMAND), expected)
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
