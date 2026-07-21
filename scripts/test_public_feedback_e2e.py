#!/usr/bin/env python3
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "liuhui-badminton-coach"
PROMOTION_PATH = ROOT / "scripts" / "promote_feedback.py"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PublicFeedbackEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.feedback = load_module(
            "public_e2e_feedback",
            SKILL_ROOT / "scripts" / "feedback.py",
        )
        cls.promotion = load_module("public_e2e_promotion", PROMOTION_PATH)

    def test_accepted_local_feedback_reaches_a_clean_install_only_after_promotion(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            local_queue = root / "local-user-feedback"
            maintainer_queue = root / "maintainer-feedback"
            clean_codex_home = root / "clean-codex-home"
            installed_skill = (
                clean_codex_home / "skills" / "liuhui-badminton-coach"
            )
            installed_skill.parent.mkdir(parents=True)
            shutil.copytree(SKILL_ROOT, installed_skill)

            private_question = "私人问题：我和固定球友训练时杀球总被嘲笑怎么办？"
            private_feedback = (
                "私人反馈：V1 最有价值；V2 不相关；"
                "还应该加入 https://www.douyin.com/video/7656560952972884730；"
                "回答太笼统，我仍然不知道怎么做。"
            )
            private_answer = "私人回答正文：包含固定球友场景，不得自动公开。"
            local = self.feedback.record_feedback(
                question=private_question,
                video_specs=[
                    "V1=7659991105622862457",
                    "V2=7659348110628345210",
                ],
                feedback_text=private_feedback,
                answer_text=private_answer,
                core_refs=["V1"],
                answer_mode="balanced",
                queue_dir=local_queue,
            )
            self.feedback.review_feedback(
                feedback_id=local["feedback_id"],
                decision="accepted",
                note="用户确认解析结果用于本地个性化",
                reviewer="local-user",
                queue_dir=local_queue,
            )

            public_question = "杀球不重没有威胁怎么办"
            exported = self.feedback.export_github_feedback(
                feedback_id=local["feedback_id"],
                public_question=public_question,
                public_answer_excerpt="回答第二点没有给出可执行的杀球力量调整方法。",
                confirm_public=True,
                queue_dir=local_queue,
            )
            self.assertNotIn(private_question, exported["issue_body"])
            self.assertNotIn(private_feedback, exported["issue_body"])
            self.assertNotIn(private_answer, exported["issue_body"])
            self.assertFalse(exported["uploaded"])

            issue_url = (
                "https://github.com/MuyuanGuo/"
                "badminton-skills-coach/issues/999999"
            )
            verification = {
                "method": "github_api",
                "repository": "MuyuanGuo/badminton-skills-coach",
                "issue_number": 999999,
                "node_id": "I_offline_e2e_fixture",
                "state": "open",
                "source_updated_at": "2026-07-14T00:00:00Z",
                "body_sha256": self.feedback.body_sha256(exported["issue_body"]),
                "verified_at": "2026-07-14T00:00:01Z",
            }
            imported = self.feedback.import_github_issue(
                body=exported["issue_body"],
                source_url=issue_url,
                queue_dir=maintainer_queue,
                source_verification=verification,
            )
            self.feedback.review_feedback(
                feedback_id=imported["feedback_id"],
                decision="accepted",
                note="已核对问题场景、来源和全部公开视频",
                reviewer="test-maintainer",
                queue_dir=maintainer_queue,
            )

            class FakeResponse:
                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc_value, traceback):
                    return False

                def read(self):
                    return json.dumps(
                        {
                            "html_url": issue_url,
                            "node_id": "I_offline_e2e_fixture",
                            "state": "open",
                            "updated_at": "2026-07-14T00:00:00Z",
                            "body": exported["issue_body"],
                        }
                    ).encode("utf-8")

            self.feedback.reverify_github_feedback(
                feedback_id=imported["feedback_id"],
                queue_dir=maintainer_queue,
                opener=lambda request, timeout: FakeResponse(),
            )

            signals_path = root / "release" / "feedback-signals.json"
            evaluation_path = root / "release" / "feedback-cases.json"
            signals_path.parent.mkdir(parents=True)
            signals_path.write_text(
                json.dumps({"version": 1, "updated_at": None, "signals": []}),
                encoding="utf-8",
            )
            evaluation_path.write_text(
                json.dumps({"version": 1, "cases": []}),
                encoding="utf-8",
            )
            installed_signals = installed_skill / "references" / "feedback-signals.json"
            production_signals_before = (
                ROOT / "config" / "feedback_signals.json"
            ).read_bytes()

            promoted = self.promotion.promote_feedback(
                feedback_id=imported["feedback_id"],
                public_query=public_question,
                evidence_note="已逐条回看三条公开视频并确认相关性边界",
                promoted_by="offline-e2e-test",
                queue_dir=maintainer_queue,
                signals_path=signals_path,
                skill_signals_path=installed_signals,
                evaluation_path=evaluation_path,
            )
            self.assertEqual(promoted["status"], "promoted")
            self.assertEqual(
                (ROOT / "config" / "feedback_signals.json").read_bytes(),
                production_signals_before,
            )

            installed_public_text = installed_signals.read_text(encoding="utf-8")
            self.assertNotIn(private_question, installed_public_text)
            self.assertNotIn(private_feedback, installed_public_text)
            installed_search = load_module(
                "clean_install_search",
                installed_skill / "scripts" / "search_knowledge.py",
            )
            search_result = installed_search.search(
                public_question,
                manifest_limit=None,
                local_personalization=False,
                feedback_dir=root / "unused-first-user-feedback",
            )
            manifest = {
                item["video_id"]: item
                for item in search_result["candidate_manifest"]
            }
            self.assertGreater(
                manifest["7659991105622862457"]["feedback_adjustment"][
                    "global_delta"
                ],
                0,
            )
            self.assertLess(
                manifest["7659348110628345210"]["feedback_adjustment"][
                    "global_delta"
                ],
                0,
            )
            self.assertGreater(
                manifest["7656560952972884730"]["feedback_adjustment"][
                    "global_delta"
                ],
                0,
            )
            self.assertEqual(
                search_result["feedback_guidance"]["global"][
                    "matched_signal_ids"
                ],
                [promoted["signal"]["signal_id"]],
            )
            self.assertFalse(search_result["feedback_guidance"]["local"]["enabled"])


if __name__ == "__main__":
    unittest.main()
