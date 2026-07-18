#!/usr/bin/env python3
import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_SCRIPTS = ROOT / "skills" / "liuhui-badminton-coach" / "scripts"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FeedbackPersonalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.feedback = load_module("feedback_personalization_feedback", SKILL_SCRIPTS / "feedback.py")
        cls.search = load_module("feedback_personalization_search", SKILL_SCRIPTS / "search_knowledge.py")

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.feedback_dir = Path(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def record_and_accept(self, **kwargs):
        record = self.feedback.record_feedback(
            queue_dir=self.feedback_dir,
            **kwargs,
        )
        self.feedback.review_feedback(
            feedback_id=record["feedback_id"],
            decision="accepted",
            note="已回看来源并确认这是用户个人相关性或表达偏好",
            reviewer="test-maintainer",
            queue_dir=self.feedback_dir,
        )
        return record

    def search_query(self, query, enabled=True):
        return self.search.search(
            query,
            manifest_limit=None,
            local_personalization=enabled,
            feedback_dir=self.feedback_dir,
        )

    def test_accepted_feedback_reranks_exact_query_and_adds_reminders(self):
        query = "杀球不重没有威胁怎么办"
        record = self.record_and_accept(
            question=query,
            video_specs=[
                "V1=7659991105622862457",
                "V2=7659348110628345210",
            ],
            feedback_text="V1 最有价值；V2 不相关；回答太笼统，我不知道怎么做。",
            core_refs=["V1"],
            answer_mode="balanced",
        )
        payload = self.search_query(query)
        manifest = {item["video_id"]: item for item in payload["candidate_manifest"]}
        helpful = manifest["7659991105622862457"]["feedback_adjustment"]
        irrelevant = manifest["7659348110628345210"]["feedback_adjustment"]

        self.assertGreater(helpful["local_delta"], 0)
        self.assertEqual(helpful["adjusted_tier"], "direct")
        self.assertLess(irrelevant["local_delta"], 0)
        self.assertEqual(irrelevant["adjusted_tier"], "semantic_lead")
        self.assertEqual(
            payload["feedback_guidance"]["local"]["matched_feedback_ids"],
            [record["feedback_id"]],
        )
        self.assertEqual(
            payload["feedback_guidance"]["answer_preferences"]["query_reminders"],
            ["hard_to_apply", "too_vague"],
        )

    def test_accepted_missing_video_becomes_a_feedback_candidate(self):
        query = "双打防守被动时怎么处理"
        missing_id = "7607852875611759802"
        self.record_and_accept(
            question=query,
            video_specs=[],
            feedback_text=(
                "漏了 https://www.douyin.com/video/" + missing_id
            ),
            answer_mode="text_primary",
        )
        payload = self.search_query(query)
        manifest = {item["video_id"]: item for item in payload["candidate_manifest"]}
        self.assertIn(missing_id, manifest)
        self.assertIn(
            "local_missing",
            manifest[missing_id]["feedback_adjustment"]["reasons"],
        )
        self.assertIn(
            "local_accepted_feedback",
            manifest[missing_id]["feedback_adjustment"]["sources"],
        )

    def test_pending_feedback_is_ignored_and_personalization_can_be_disabled(self):
        query = "网前框架怎么做才不会身体僵硬"
        self.feedback.record_feedback(
            question=query,
            video_specs=["V1=7661940775983482097"],
            feedback_text="V1 最有价值。",
            queue_dir=self.feedback_dir,
        )
        pending_payload = self.search_query(query)
        self.assertEqual(
            pending_payload["feedback_guidance"]["local"]["accepted_record_count"],
            0,
        )
        self.assertEqual(
            pending_payload["feedback_guidance"]["local"]["matched_feedback_count"],
            0,
        )

        self.record_and_accept(
            question=query,
            video_specs=["V1=7661940775983482097"],
            feedback_text="V1 最有价值。",
        )
        disabled_payload = self.search_query(query, enabled=False)
        self.assertFalse(disabled_payload["feedback_guidance"]["local"]["enabled"])
        self.assertFalse(
            any(
                item.get("feedback_adjustment", {}).get("local_delta")
                for item in disabled_payload["candidate_manifest"]
            )
        )

    def test_repeated_accepted_style_feedback_builds_local_preference(self):
        for question, video_id in [
            ("杀球应该怎么发力", "7656560952972884730"),
            ("双打轮转怎么补位", "7614167503938610417"),
        ]:
            self.record_and_accept(
                question=question,
                video_specs=[f"V1={video_id}"],
                feedback_text="V1 有帮助，但是回答太长。",
            )
        payload = self.search_query("网前搓球怎么控制拍面")
        preferences = payload["feedback_guidance"]["answer_preferences"]
        self.assertEqual(preferences["preferred_verbosity"], "concise")
        self.assertEqual(preferences["preference_evidence_counts"]["too_verbose"], 2)

    def test_question_correction_triggers_query_replan_for_similar_question(self):
        query = "双打接发应该怎么调整"
        self.record_and_accept(
            question=query,
            video_specs=[],
            feedback_text=(
                "你理解错了我的问题，我问的是双打接发战术和接发握拍两个独立问题。"
            ),
            answer_mode="balanced",
        )
        preferences = self.search_query(query)["feedback_guidance"][
            "answer_preferences"
        ]
        self.assertTrue(preferences["needs_query_replan"])
        self.assertEqual(
            preferences["query_replan_hints"],
            ["双打接发战术和接发握拍两个独立问题"],
        )
        self.assertIn("question_misunderstood", preferences["query_reminders"])

    def test_source_error_triggers_targeted_evidence_recheck(self):
        query = "重杀框架怎么做"
        video_id = "7659991105622862457"
        self.record_and_accept(
            question=query,
            video_specs=[f"V1={video_id}"],
            feedback_text="V1 转写错了，原视频说的是拍头不是拍低。",
            answer_mode="balanced",
        )
        preferences = self.search_query(query)["feedback_guidance"][
            "answer_preferences"
        ]
        self.assertTrue(preferences["needs_source_recheck"])
        self.assertEqual(preferences["source_recheck_video_ids"], [video_id])
        self.assertIn("transcript_error", preferences["query_reminders"])


if __name__ == "__main__":
    unittest.main()
