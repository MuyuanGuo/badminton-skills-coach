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
        self.assertIn("## Runtime Path", skill_text)
        self.assertIn("directory containing this `SKILL.md`", skill_text)
        self.assertIn("Never assume a fixed home-directory installation path", skill_text)

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

            context = subprocess.run(
                [
                    sys.executable,
                    str(
                        installed_skill
                        / "scripts"
                        / "prepare_answer_context.py"
                    ),
                    "网前框架怎么做才不会身体僵硬",
                    "--max-videos",
                    "2",
                    "--no-local-personalization",
                ],
                cwd=external_workdir,
                text=True,
                capture_output=True,
                check=True,
            )
            context_payload = json.loads(context.stdout)
            self.assertTrue(context_payload["selected_videos"])
            self.assertEqual(context_payload["selected_videos"][0]["label"], "V1")

            clarification_context = subprocess.run(
                [
                    sys.executable,
                    str(
                        installed_skill
                        / "scripts"
                        / "prepare_answer_context.py"
                    ),
                    "双打接杀挡网总冒高，是拍面还是击球点问题？",
                    "--max-videos",
                    "2",
                    "--no-local-personalization",
                ],
                cwd=external_workdir,
                text=True,
                capture_output=True,
                check=True,
            )
            clarification_context_path = external_workdir / "context.json"
            clarification_context_path.write_text(
                clarification_context.stdout, encoding="utf-8"
            )
            continued = subprocess.run(
                [
                    sys.executable,
                    str(
                        installed_skill
                        / "scripts"
                        / "prepare_answer_context.py"
                    ),
                    "球的最高点在对方场区",
                    "--continue-from",
                    str(clarification_context_path),
                    "--max-videos",
                    "2",
                    "--no-local-personalization",
                ],
                cwd=external_workdir,
                text=True,
                capture_output=True,
                check=True,
            )
            continued_payload = json.loads(continued.stdout)
            self.assertEqual(
                continued_payload["clarification_state"]["original_query"],
                "双打接杀挡网总冒高，是拍面还是击球点问题？",
            )
            self.assertEqual(
                continued_payload["clarification_state"][
                    "pending_question_ids"
                ],
                [],
            )

            audit_context_path = external_workdir / "audit-context.json"
            audit_answer_path = external_workdir / "audit-answer.md"
            audit_context_path.write_text(
                json.dumps(
                    {
                        "query": "测试问题",
                        "boundary": {"type": "none", "required_statement": None},
                        "diagnostic_model": {"do_not_claim_unique_cause": False},
                        "clarification_decision": {"action": "answer_now", "questions": []},
                        "claim_evidence_map": [],
                        "completeness_contract": {"items": []},
                        "selected_videos": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            audit_answer_path.write_text("这是一个无需引用的边界回答。", encoding="utf-8")
            audit = subprocess.run(
                [
                    sys.executable,
                    str(installed_skill / "scripts" / "audit_answer.py"),
                    "测试问题",
                    "--context",
                    str(audit_context_path),
                    "--answer",
                    str(audit_answer_path),
                ],
                cwd=external_workdir,
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertTrue(json.loads(audit.stdout)["passed"])

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
