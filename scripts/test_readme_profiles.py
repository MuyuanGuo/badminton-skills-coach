#!/usr/bin/env python3
import json
import tempfile
import unittest
from pathlib import Path

from readme_profiles import profile_for_channel, render_readme


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


if __name__ == "__main__":
    unittest.main()
