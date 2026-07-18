#!/usr/bin/env python3
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "liuhui-badminton-coach"


class SkillPortabilityTests(unittest.TestCase):
    def test_skill_documents_its_runtime_working_directory(self):
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("## Runtime Path Contract", skill_text)
        self.assertIn("directory that contains this `SKILL.md`", skill_text)
        self.assertIn("Do not resolve `scripts/...` against the user's current project", skill_text)

    def test_bundled_commands_run_outside_the_skill_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            installed_skill = temporary_root / "installed" / "liuhui-badminton-coach"
            external_workdir = temporary_root / "unrelated-project"
            shutil.copytree(SKILL_ROOT, installed_skill)
            external_workdir.mkdir()

            search = subprocess.run(
                [
                    sys.executable,
                    str(installed_skill / "scripts" / "search_knowledge.py"),
                    "正手握拍应该怎么握",
                    "--manifest-limit",
                    "1",
                    "--no-local-personalization",
                ],
                cwd=external_workdir,
                text=True,
                capture_output=True,
                check=True,
            )
            search_payload = json.loads(search.stdout)
            self.assertEqual(search_payload["query"], "正手握拍应该怎么握")
            self.assertEqual(len(search_payload["candidate_manifest"]), 1)

            navigation = subprocess.run(
                [
                    sys.executable,
                    str(installed_skill / "scripts" / "navigate_topics.py"),
                    "系统学习杀球",
                    "--limit",
                    "1",
                ],
                cwd=external_workdir,
                text=True,
                capture_output=True,
                check=True,
            )
            navigation_payload = json.loads(navigation.stdout)
            self.assertEqual(navigation_payload["intent"], "learning_path")
            self.assertEqual(len(navigation_payload["matches"]), 1)


if __name__ == "__main__":
    unittest.main()
