#!/usr/bin/env python3
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TopicNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.builder = load_module(
            "topic_builder_test", ROOT / "scripts" / "build_topic_index.py"
        )
        cls.navigator = load_module(
            "topic_navigator_test",
            ROOT
            / "skills"
            / "liuhui-badminton-coach"
            / "scripts"
            / "navigate_topics.py",
        )
        cls.practice_rules = json.loads(
            (
                ROOT
                / "skills"
                / "liuhui-badminton-coach"
                / "references"
                / "practice-plan-rules.json"
            ).read_text(encoding="utf-8")
        )

    def test_curated_video_without_topic_match_gets_no_free_score(self):
        data = {
            "scope": "test",
            "updated_at": "2026-07-17T00:00:00Z",
            "videos": [
                {
                    "video_id": "100000000000000001",
                    "title": "后场框架",
                    "url": "https://www.douyin.com/video/100000000000000001",
                    "category": "后场技术",
                    "processing_status": "ready",
                    "confidence": "curated",
                    "teaching_note": {"topic": "后场框架"},
                },
                {
                    "video_id": "100000000000000002",
                    "title": "接发准备",
                    "url": "https://www.douyin.com/video/100000000000000002",
                    "category": "发球与接发",
                    "processing_status": "ready",
                    "confidence": "medium",
                    "teaching_note": {"topic": "双打接发准备"},
                },
            ],
        }
        index = self.builder.build_index(data)
        reception = next(
            subtopic
            for category in index["categories"]
            if category["name"] == "发球与接发"
            for subtopic in category["subtopics"]
            if subtopic["name"] == "接发"
        )
        self.assertEqual(reception["video_ids"], ["100000000000000002"])
        self.assertEqual(
            reception["representative_videos"][0]["video_id"],
            "100000000000000002",
        )

    def test_context_is_inferred_and_changes_learning_path(self):
        query = "零基础双打接发系统学习，每次30分钟，有搭档"
        context = self.navigator.build_user_context(query, self.practice_rules)
        self.assertEqual(context["level"], "beginner")
        self.assertEqual(context["discipline"], "doubles")
        self.assertEqual(context["practice_setup"], "partner")
        self.assertEqual(context["session_minutes"], 30)
        self.assertEqual(self.navigator.clarification_questions(context), [])
        graph = json.loads(
            (
                ROOT
                / "skills"
                / "liuhui-badminton-coach"
                / "references"
                / "topic-map.json"
            ).read_text(encoding="utf-8")
        )
        matches = self.navigator.match_topics(graph, query, 3)
        path = self.navigator.learning_path(
            matches, context, self.practice_rules
        )
        goals = " ".join(stage["goal"] for stage in path)
        self.assertIn("30 分钟", goals)
        self.assertIn("搭档", goals)
        self.assertIn("下一拍衔接", goals)

    def test_minute_allocation_is_exact_and_keeps_every_segment(self):
        for total in [5, 15, 30, 120]:
            with self.subTest(total=total):
                allocation = self.navigator.allocate_minutes(total)
                self.assertEqual(sum(allocation.values()), total)
                self.assertTrue(all(value >= 1 for value in allocation.values()))

    def test_pain_signal_precedes_training_personalization(self):
        context = self.navigator.build_user_context(
            "杀球时肩膀疼，想每天练30分钟", self.practice_rules
        )
        adaptation = self.navigator.practice_adaptation(
            context, self.practice_rules
        )
        self.assertTrue(context["pain_or_injury"])
        self.assertIn("停止相关动作", adaptation["pain_boundary"])
        self.assertIn("医疗专业人士", self.navigator.clarification_questions(context)[0])

    def test_solo_practice_does_not_imply_singles(self):
        context = self.navigator.build_user_context(
            "我想单人练双打接发", self.practice_rules
        )
        self.assertEqual(context["discipline"], "doubles")
        self.assertEqual(context["practice_setup"], "solo")


if __name__ == "__main__":
    unittest.main()
