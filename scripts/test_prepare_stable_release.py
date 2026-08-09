#!/usr/bin/env python3
import json
import tempfile
import unittest
from pathlib import Path

from prepare_stable_release import (
    prepare_stable_release,
    release_version_from_development,
)


class PrepareStableReleaseTests(unittest.TestCase):
    def write_main_profile(self, root):
        path = root / ".github" / "readme-profiles" / "main.md.tmpl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            """<!-- README_PROFILE: main -->
**{{STABLE_VERSION}} 稳定版**
**Version {{STABLE_VERSION}} is the stable release**
""",
            encoding="utf-8",
        )

    def test_release_version_is_derived_from_development(self):
        self.assertEqual(
            release_version_from_development("2.1.10-dev.2"),
            "2.1.10",
        )
        with self.assertRaisesRegex(ValueError, "MAJOR.MINOR.PATCH-dev.N"):
            release_version_from_development("2.1.10")

    def test_full_release_syncs_metadata_docs_and_quality_floor(self):
        metadata = {
            "skill_version": "2.1.1-dev.1",
            "channel": "development",
            "stable_version": "2.1.0",
            "scenario_conflicts": [["网前", "后场"]],
        }
        readme_zh = """# Project
[安装 2.1.0](#安装稳定版)
你正在查看 `develop` 分支；当前开发版本是 **2.1.1-dev.1**，发布状态为 **unreleased**。稳定安装仍来自 `main` 与 v2.1.0。
## 当前开发版（2.1.1-dev.1）

本分支在稳定版 2.1.0 基础上汇总尚未发布的数据、运行时与工程改动；以下内容描述当前开发树，不表示已经存在对应的稳定安装包。
- capability
## 分支与发布

- 当前分支：`develop`
"""
        readme_en = """# Project
[Install 2.1.0](#install)
You are viewing the `develop` branch; the current development version is **2.1.1-dev.1** and its release status is **unreleased**. Stable installs remain on `main` and v2.1.0.
## Current development build (2.1.1-dev.1)

This branch collects unreleased data, runtime, and engineering changes on top of stable 2.1.0. It describes the development tree, not an already available stable package.
- capability
- Current branch: `develop`
"""
        baseline = {
            "schema_version": 1,
            "baselines": {
                "v2.1.0": {
                    "description": "Stable release v2.1.0 quality floor",
                    "invalidated_metrics": {},
                    "metrics": {
                        "quality.score": {
                            "value": 0.9,
                            "direction": "at_least",
                        },
                        "quality.dynamic_limit": {
                            "value_source": "quality.limits.maximum",
                            "direction": "at_most",
                        },
                    },
                }
            },
        }
        report = {
            "development_version": "2.1.1-dev.1",
            "baseline_version": "v2.1.0",
            "summary": {"status": "pass"},
            "baseline_comparison": [
                {"metric": "quality.score", "current": 0.95},
                {"metric": "quality.dynamic_limit", "current": 0.2},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in (
                "config/feedback_rules.json",
                "skills/liuhui-badminton-coach/references/feedback-rules.json",
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            (root / "README.md").write_text(readme_zh, encoding="utf-8")
            (root / "README.en.md").write_text(readme_en, encoding="utf-8")
            self.write_main_profile(root)
            for relative in ("docs/index.html", "docs/en/index.html"):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("Install v2.1.0 archive 2.1.0\n", encoding="utf-8")
            for relative in (
                ".github/ISSUE_TEMPLATE/bug-report.yml",
                ".github/ISSUE_TEMPLATE/question.yml",
                ".github/ISSUE_TEMPLATE/skill-feedback.yml",
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("version: 2.1.1-dev.1\n", encoding="utf-8")
            baseline_path = root / "data/evaluation/evaluation_baselines.json"
            report_path = root / "data/evaluation/evaluation_report.json"
            baseline_path.parent.mkdir(parents=True, exist_ok=True)
            baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
            report_path.write_text(json.dumps(report), encoding="utf-8")

            result = prepare_stable_release(root)

            self.assertEqual(result["skill_version"], "2.1.1")
            updated = json.loads(
                (root / "config/feedback_rules.json").read_text(encoding="utf-8")
            )
            self.assertEqual(updated["channel"], "stable")
            self.assertEqual(updated["stable_version"], "2.1.1")
            self.assertIn("**2.1.1 稳定版**", (root / "README.md").read_text())
            self.assertIn(
                "**Version 2.1.1 is the stable release**",
                (root / "README.md").read_text(),
            )
            self.assertIn(
                "**Version 2.1.1 is the stable release**",
                (root / "README.en.md").read_text(),
            )
            self.assertNotIn("2.1.1-dev.1", (root / "README.md").read_text())
            promoted = json.loads(baseline_path.read_text(encoding="utf-8"))[
                "baselines"
            ]["v2.1.1"]
            self.assertEqual(promoted["metrics"]["quality.score"]["value"], 0.95)
            self.assertIn(
                "value_source",
                promoted["metrics"]["quality.dynamic_limit"],
            )

    def test_release_rejects_a_stale_or_failing_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = {
                "skill_version": "2.1.1-dev.1",
                "channel": "development",
                "stable_version": "2.1.0",
            }
            for relative in (
                "config/feedback_rules.json",
                "skills/liuhui-badminton-coach/references/feedback-rules.json",
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(metadata), encoding="utf-8")
            baseline_path = root / "data/evaluation/evaluation_baselines.json"
            report_path = root / "data/evaluation/evaluation_report.json"
            baseline_path.parent.mkdir(parents=True, exist_ok=True)
            baseline_path.write_text(
                json.dumps({"baselines": {"v2.1.0": {"metrics": {}}}}),
                encoding="utf-8",
            )
            report_path.write_text(
                json.dumps(
                    {
                        "development_version": "2.1.1-dev.1",
                        "baseline_version": "v2.1.0",
                        "summary": {"status": "fail"},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "passing evaluation report"):
                prepare_stable_release(root)


if __name__ == "__main__":
    unittest.main()
