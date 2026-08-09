#!/usr/bin/env python3
import json
import tempfile
import unittest
from pathlib import Path

from prepare_develop_sync import (
    development_readme_en,
    development_readme_zh,
    next_patch_development_version,
    prepare_develop_sync,
)


class PrepareDevelopSyncTests(unittest.TestCase):
    def write_develop_profile(self, root):
        path = root / ".github" / "readme-profiles" / "develop.md.tmpl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            """<!-- README_PROFILE: develop -->
当前开发版本是 **{{DEVELOPMENT_VERSION}}**
current development version is **{{DEVELOPMENT_VERSION}}**
稳定版：`main` / `v{{STABLE_VERSION}}`
""",
            encoding="utf-8",
        )

    def test_next_patch_version_is_derived_from_stable(self):
        self.assertEqual(
            next_patch_development_version("2.1.9"),
            "2.1.10-dev.1",
        )
        with self.assertRaisesRegex(ValueError, "MAJOR.MINOR.PATCH"):
            next_patch_development_version("2.1.0-dev.1")

    def test_chinese_readme_becomes_unreleased_develop_state(self):
        source = """# Project
**2.1.0 稳定版**通过 GitHub `main` 分支和 release 提供；后续开发继续在 `develop`。
## 2.1.0 带来了什么
- capability
## 分支与发布

- 稳定版：`main` / `v2.1.0`
"""
        updated = development_readme_zh(source, "2.1.0", "2.1.1-dev.1")
        self.assertIn("你正在查看 `develop` 分支", updated)
        self.assertIn("当前开发版本是 **2.1.1-dev.1**", updated)
        self.assertIn("- 稳定版：`main` / `v2.1.0`", updated)
        self.assertNotIn("**2.1.0 稳定版**通过", updated)

    def test_english_readme_becomes_unreleased_develop_state(self):
        source = """# Project
**Version 2.1.0 is the stable release** on `main`.
## What changed in 2.1.0
- capability
- Stable release: `main` / `v2.1.0`
"""
        updated = development_readme_en(source, "2.1.0", "2.1.1-dev.1")
        self.assertIn("You are viewing the `develop` branch", updated)
        self.assertIn("current development version is **2.1.1-dev.1**", updated)
        self.assertIn("- Stable release: `main` / `v2.1.0`", updated)
        self.assertNotIn("**Version 2.1.0 is the stable release**", updated)

    def test_full_sync_preserves_unrelated_json_formatting(self):
        metadata_text = """{
  "skill_version": "2.1.0",
  "channel": "stable",
  "stable_version": "2.1.0",
  "scenario_conflicts": [["网前", "后场"]]
}
"""
        readme_zh = """# Project
**2.1.0 稳定版**通过 GitHub `main` 分支和 release 提供。
## 2.1.0 带来了什么
- capability
## 分支与发布

- 稳定版：`main` / `v2.1.0`
"""
        readme_en = """# Project
**Version 2.1.0 is the stable release** on `main`.
## What changed in 2.1.0
- capability
- Stable release: `main` / `v2.1.0`
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata_paths = (
                root / "config" / "feedback_rules.json",
                root
                / "skills"
                / "liuhui-badminton-coach"
                / "references"
                / "feedback-rules.json",
            )
            for path in metadata_paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(metadata_text, encoding="utf-8")
            (root / "README.md").write_text(readme_zh, encoding="utf-8")
            (root / "README.en.md").write_text(readme_en, encoding="utf-8")
            self.write_develop_profile(root)
            for relative in (
                ".github/ISSUE_TEMPLATE/bug-report.yml",
                ".github/ISSUE_TEMPLATE/question.yml",
                ".github/ISSUE_TEMPLATE/skill-feedback.yml",
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("version: 2.1.0\n", encoding="utf-8")

            result = prepare_develop_sync(root)

            updated_text = metadata_paths[0].read_text(encoding="utf-8")
            updated = json.loads(updated_text)
            self.assertEqual(result["skill_version"], "2.1.1-dev.1")
            self.assertEqual(updated["channel"], "development")
            self.assertIn('[["网前", "后场"]]', updated_text)

    def test_existing_expected_development_state_is_idempotent(self):
        metadata_text = """{
  "skill_version": "2.1.1-dev.1",
  "channel": "development",
  "stable_version": "2.1.0"
}
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata_paths = (
                root / "config" / "feedback_rules.json",
                root
                / "skills"
                / "liuhui-badminton-coach"
                / "references"
                / "feedback-rules.json",
            )
            for path in metadata_paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(metadata_text, encoding="utf-8")
            (root / "README.md").write_text(
                "当前开发版本是 **2.1.1-dev.1**\n稳定版：`main` / `v2.1.0`\n",
                encoding="utf-8",
            )
            (root / "README.en.md").write_text(
                "current development version is **2.1.1-dev.1**\n"
                "Stable release: `main` / `v2.1.0`\n",
                encoding="utf-8",
            )
            self.write_develop_profile(root)
            for relative in (
                ".github/ISSUE_TEMPLATE/bug-report.yml",
                ".github/ISSUE_TEMPLATE/question.yml",
                ".github/ISSUE_TEMPLATE/skill-feedback.yml",
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("version: 2.1.1-dev.1\n", encoding="utf-8")

            before = {
                path: path.read_text(encoding="utf-8") for path in metadata_paths
            }
            result = prepare_develop_sync(root)

            self.assertEqual(result["skill_version"], "2.1.1-dev.1")
            self.assertEqual(
                before,
                {path: path.read_text(encoding="utf-8") for path in metadata_paths},
            )

    def test_existing_development_state_fails_closed_when_stale(self):
        metadata_text = """{
  "skill_version": "2.1.9-dev.1",
  "channel": "development",
  "stable_version": "2.1.0"
}
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "config" / "feedback_rules.json"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(metadata_text, encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "next stable patch"):
                prepare_develop_sync(root)


if __name__ == "__main__":
    unittest.main()
