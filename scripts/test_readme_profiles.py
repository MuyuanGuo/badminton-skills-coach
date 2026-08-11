#!/usr/bin/env python3
import json
import tempfile
import unittest
from pathlib import Path

from readme_profiles import (
    profile_for_channel,
    render_public_fact_files,
    render_readme,
)


ROOT = Path(__file__).resolve().parents[1]


class ReadmeProfileTests(unittest.TestCase):
    def test_active_profile_matches_release_channel(self):
        metadata = json.loads(
            (ROOT / "config" / "feedback_rules.json").read_text(
                encoding="utf-8"
            )
        )
        profile = profile_for_channel(metadata["channel"])
        rendered = render_readme(profile)
        self.assertEqual(
            rendered,
            (ROOT / "README.md").read_text(encoding="utf-8"),
        )
        self.assertIn(f"<!-- README_PROFILE: {profile} -->", rendered)
        self.assertNotIn("README.en.md", rendered)
        self.assertNotIn("{{", rendered)

    def test_main_profile_is_directly_bilingual(self):
        rendered = render_readme("main")
        self.assertIn("把你的羽毛球问题说清楚一点", rendered)
        self.assertIn("Describe your badminton situation", rendered)
        self.assertIn("<!-- README_PROFILE: main -->", rendered)
        self.assertNotIn("README.en.md", rendered)
        self.assertNotIn("{{", rendered)

    def test_develop_profile_explains_engineering_and_answer_flow(self):
        rendered = render_readme(
            "develop",
            stable_version="2.1.2",
            development_version="2.1.3-dev.1",
        )
        self.assertIn("工程概览 / Engineering overview", rendered)
        self.assertIn(
            "从用户提问到最终回答 / From user question to final answer",
            rendered,
        )
        self.assertIn("完整上下文 auditor 通过？", rendered)
        self.assertIn("向用户发送回答 / Send the answer to the user", rendered)
        self.assertIn("选择最多 5 条核心视频（证据不足不补齐）", rendered)
        self.assertIn("only claim-authorized synthesis evidence", rendered)
        self.assertNotIn("选择 3–5 条核心视频", rendered)
        self.assertNotIn("3–5 `core_videos`", rendered)
        self.assertIn("当前开发版本是 **2.1.3-dev.1**", rendered)
        self.assertIn(
            "current development version is **2.1.3-dev.1**",
            rendered,
        )
        self.assertIn("<!-- README_PROFILE: develop -->", rendered)
        self.assertNotIn("招聘", rendered)
        self.assertNotIn("recruiter", rendered.lower())
        self.assertNotIn("README.en.md", rendered)
        self.assertNotIn("{{", rendered)

    def test_unknown_template_token_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = root / ".github" / "readme-profiles" / "main.md.tmpl"
            profile.parent.mkdir(parents=True)
            profile.write_text(
                "<!-- README_PROFILE: main -->\n{{UNKNOWN_VALUE}}\n",
                encoding="utf-8",
            )
            metadata = root / "config" / "feedback_rules.json"
            metadata.parent.mkdir(parents=True)
            metadata.write_text(
                '{"skill_version":"1.0.0","stable_version":"1.0.0"}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "Unknown README tokens"):
                render_readme("main", root=root)

    def test_public_fact_files_match_current_corpus(self):
        rendered = render_public_fact_files(ROOT)
        for relative, expected in rendered.items():
            self.assertEqual(
                expected,
                (ROOT / relative).read_text(encoding="utf-8"),
                str(relative),
            )

    def test_public_fact_render_updates_all_public_surfaces(self):
        facts = {
            "READY_VIDEO_COUNT": "12",
            "PRIMARY_VIDEO_COUNT": "8",
            "SUPPLEMENTAL_VIDEO_COUNT": "4",
            "TRANSCRIPT_VIDEO_COUNT": "9",
            "TRANSCRIPT_ITEM_COUNT": "1,234",
            "BOUNDED_VIDEO_COUNT": "2",
            "VISUAL_VIDEO_COUNT": "1",
            "PROCESSED_PUBLIC_VIDEO_COUNT": "20",
            "BILIBILI_CATALOG_COUNT": "7",
            "BILIBILI_READY_COUNT": "5",
            "BILIBILI_ISOLATED_COUNT": "2",
            "BILIBILI_PENDING_COUNT": "0",
            "ANSWER_QUALITY_CASE_COUNT": "6",
            "QUERY_UNDERSTANDING_CASE_COUNT": "11",
            "METAMORPHIC_VARIANT_COUNT": "3",
            "HARD_NEGATIVE_COUNT": "4",
            "LIVE_GENERATION_CASE_COUNT": "5",
            "PUBLIC_FEEDBACK_SIGNAL_COUNT": "0",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs" / "en").mkdir(parents=True)
            (root / "README.en.md").write_text(
                """- 1 primary sources lead. 1 bounded supplemental sources remain.
| Processed public videos | 1 |
| Bilibili full source catalog | 1: 1 answer-ready, 0 policy-excluded or quality-isolated, 0 pending |
| Ready teaching videos | 1 |
| Primary / bounded supplemental evidence | 1 / 1 |
| Transcript-backed evidence | 1 |
| Bounded timestamp-window evidence | 1 |
| Reviewed visual-summary fallbacks | 1 |
| Maintainer-reviewed answer cases | 1/1 |
| Query-understanding cases | 1/1 |
| Metamorphic language variants | 1/1 |
| Hard-negative selections | 0 of 1 |
| Current-runtime reproducible release answers | 1/1 |
| Promoted public feedback signals | 1 |
All 1 transcript evidence items have timestamps.
""",
                encoding="utf-8",
            )
            (root / "docs" / "index.html").write_text(
                """它从 1 条教学视频中寻找答案
<strong>1</strong><span>条可用教学视频</span>
<strong>1</strong><span>条转写证据</span>
<strong>1 / 1</strong><span>维护者审核回答</span>
""",
                encoding="utf-8",
            )
            (root / "docs" / "en" / "index.html").write_text(
                """searches 1 Chinese badminton teaching videos
<strong>1</strong><span>ready teaching videos</span>
<strong>1</strong><span>transcript-backed sources</span>
<strong>1 / 1</strong><span>maintainer-reviewed answers</span>
""",
                encoding="utf-8",
            )
            rendered = render_public_fact_files(root, facts=facts)
            self.assertIn("8 primary", rendered[Path("README.en.md")])
            self.assertIn("11/11", rendered[Path("README.en.md")])
            self.assertIn("5/5", rendered[Path("README.en.md")])
            self.assertIn(
                "<strong>12</strong><span>条可用教学视频</span>",
                rendered[Path("docs/index.html")],
            )
            self.assertIn(
                "<strong>9</strong><span>transcript-backed sources</span>",
                rendered[Path("docs/en/index.html")],
            )


if __name__ == "__main__":
    unittest.main()
