#!/usr/bin/env python3
import tempfile
import unittest
from pathlib import Path

from readme_profiles import render_readme


ROOT = Path(__file__).resolve().parents[1]


class ReadmeProfileTests(unittest.TestCase):
    def test_main_profile_is_directly_bilingual_and_current(self):
        rendered = render_readme("main")
        self.assertEqual(
            rendered,
            (ROOT / "README.md").read_text(encoding="utf-8"),
        )
        self.assertIn("把你的羽毛球问题说清楚一点", rendered)
        self.assertIn("Describe your badminton situation", rendered)
        self.assertNotIn("README.en.md", rendered)
        self.assertNotIn("{{", rendered)

    def test_develop_profile_targets_engineers_and_recruiters(self):
        rendered = render_readme(
            "develop",
            stable_version="2.1.2",
            development_version="2.1.3-dev.1",
        )
        self.assertIn("招聘方快速阅读 / Recruiter snapshot", rendered)
        self.assertIn("系统怎样工作 / How the system works", rendered)
        self.assertIn("当前开发版本是 **2.1.3-dev.1**", rendered)
        self.assertIn(
            "current development version is **2.1.3-dev.1**",
            rendered,
        )
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
