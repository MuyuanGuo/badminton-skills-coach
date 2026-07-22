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
        taxonomy = self.builder.load_taxonomy()
        taxonomy["reviewed_video_topic_overrides"] = {}
        taxonomy["reviewed_video_topic_replacements"] = {}
        index = self.builder.build_index(data, taxonomy=taxonomy)
        reception = next(
            subtopic
            for category in index["categories"]
            if category["name"] == "发球与接发"
            for subtopic in category["subtopics"]
            if subtopic["name"] == "接发与抢发"
        )
        self.assertEqual(reception["video_ids"], ["100000000000000002"])
        self.assertEqual(
            reception["representative_videos"][0]["video_id"],
            "100000000000000002",
        )

    def test_serve_variation_topic_requires_serve_context(self):
        data = {
            "scope": "test",
            "updated_at": "2026-07-21T00:00:00Z",
            "videos": [
                {
                    "video_id": "100000000000000003",
                    "title": "后场架拍怎样提高隐蔽性",
                    "url": "https://www.douyin.com/video/100000000000000003",
                    "category": "后场技术",
                    "processing_status": "ready",
                    "confidence": "medium",
                    "teaching_note": {"topic": "后场架拍和挥拍空间"},
                }
            ],
        }
        taxonomy = self.builder.load_taxonomy()
        taxonomy["reviewed_video_topic_overrides"] = {}
        taxonomy["reviewed_video_topic_replacements"] = {}
        index = self.builder.build_index(data, taxonomy=taxonomy)
        serve_variation = next(
            subtopic
            for category in index["categories"]
            if category["name"] == "发球与接发"
            for subtopic in category["subtopics"]
            if subtopic["name"] == "发后场与发球变化"
        )
        self.assertNotIn("100000000000000003", serve_variation["video_ids"])

    def test_reviewed_topic_replacement_is_exclusive(self):
        video_id = "100000000000000004"
        data = {
            "scope": "test",
            "updated_at": "2026-07-21T00:00:00Z",
            "videos": [
                {
                    "video_id": video_id,
                    "title": "后场架拍与发球隐蔽变化",
                    "url": f"https://www.douyin.com/video/{video_id}",
                    "category": "后场技术",
                    "processing_status": "ready",
                    "confidence": "reviewed_transcript",
                    "teaching_note": {"topic": "后场架拍与发球隐蔽变化"},
                }
            ],
        }
        taxonomy = self.builder.load_taxonomy()
        taxonomy["reviewed_video_topic_overrides"] = {}
        taxonomy["reviewed_video_topic_replacements"] = {
            video_id: ["后场技术/架拍与后场框架"]
        }
        index = self.builder.build_index(data, taxonomy=taxonomy)
        assigned_topics = {
            f"{category['name']}/{subtopic['name']}"
            for category in index["categories"]
            for subtopic in category["subtopics"]
            if video_id in subtopic["video_ids"]
        }
        self.assertEqual(assigned_topics, {"后场技术/架拍与后场框架"})

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

    def test_practice_context_handles_natural_solo_and_chinese_duration(self):
        context = self.navigator.build_user_context(
            "新手一个人每天练十五分钟杀球", self.practice_rules
        )
        self.assertEqual(context["level"], "beginner")
        self.assertEqual(context["practice_setup"], "solo")
        self.assertEqual(context["session_minutes"], 15)
        self.assertEqual(context["sources"]["practice_setup"], "query")
        self.assertEqual(context["sources"]["session_minutes"], "query")

        partner = self.navigator.build_user_context(
            "有一个人给我喂球，每次二十分钟", self.practice_rules
        )
        self.assertEqual(partner["practice_setup"], "partner")
        self.assertEqual(partner["session_minutes"], 20)

        no_partner = self.navigator.build_user_context(
            "没有陪练，只能自己练二十分钟", self.practice_rules
        )
        self.assertEqual(no_partner["practice_setup"], "solo")

        partner_without_coach = self.navigator.build_user_context(
            "没有教练，但有搭档喂球", self.practice_rules
        )
        self.assertEqual(partner_without_coach["practice_setup"], "partner")

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

    def test_full_topic_index_assigns_every_ready_video(self):
        index = json.loads(
            (ROOT / "data" / "knowledge" / "topic_index.json").read_text(
                encoding="utf-8"
            )
        )
        knowledge = json.loads(
            (ROOT / "data" / "knowledge" / "douyin_knowledge_base.json").read_text(
                encoding="utf-8"
            )
        )
        ready_count = sum(
            video["processing_status"] == "ready" for video in knowledge["videos"]
        )
        self.assertEqual(index["assigned_video_count"], ready_count)
        self.assertEqual(index["unassigned_video_ids"], [])
        self.assertEqual(index["taxonomy_version"], "topic-taxonomy-v11")
        self.assertTrue(
            any(category["name"] == "单打战术" for category in index["categories"])
        )

    def test_latest_reviewed_video_only_uses_rear_court_framework_topic(self):
        video_id = "7664908274752137146"
        index = json.loads(
            (ROOT / "data" / "knowledge" / "topic_index.json").read_text(
                encoding="utf-8"
            )
        )
        assigned_topics = {
            f"{category['name']}/{subtopic['name']}"
            for category in index["categories"]
            for subtopic in category["subtopics"]
            if video_id in subtopic["video_ids"]
        }
        self.assertEqual(assigned_topics, {"后场技术/架拍与后场框架"})

    def test_reviewed_point_smash_sources_are_in_the_smash_topic(self):
        index = json.loads(
            (ROOT / "data" / "knowledge" / "topic_index.json").read_text(
                encoding="utf-8"
            )
        )
        smash = next(
            subtopic
            for category in index["categories"]
            if category["name"] == "后场技术"
            for subtopic in category["subtopics"]
            if subtopic["name"] == "杀球与突击"
        )
        self.assertTrue(
            {
                "7272944156618542336",
                "7125615679402724623",
            }.issubset(smash["video_ids"])
        )

    def test_reviewed_jump_smash_sources_are_in_the_smash_topic(self):
        index = json.loads(
            (ROOT / "data" / "knowledge" / "topic_index.json").read_text(
                encoding="utf-8"
            )
        )
        smash = next(
            subtopic
            for category in index["categories"]
            if category["name"] == "后场技术"
            for subtopic in category["subtopics"]
            if subtopic["name"] == "杀球与突击"
        )
        self.assertTrue(
            {
                "7161980324409363712",
                "7055491154288102667",
                "7138604160051612969",
                "7634016952800880570",
                "7606560547489149691",
                "7561558424342056250",
                "7506362888166083897",
            }.issubset(smash["video_ids"])
        )

    def test_singles_systematic_navigation_never_returns_doubles_branch(self):
        graph = json.loads(
            (
                ROOT
                / "skills"
                / "liuhui-badminton-coach"
                / "references"
                / "topic-map.json"
            ).read_text(encoding="utf-8")
        )
        matches = self.navigator.match_topics(
            graph, "我想从零开始系统学习单打战术", 5
        )
        self.assertTrue(matches)
        self.assertEqual(matches[0]["category"], "单打战术")
        self.assertTrue(all(match["category"] != "双打战术" for match in matches))

    def test_doubles_rotation_navigation_has_relevant_representatives(self):
        graph = json.loads(
            (
                ROOT
                / "skills"
                / "liuhui-badminton-coach"
                / "references"
                / "topic-map.json"
            ).read_text(encoding="utf-8")
        )
        matches = self.navigator.match_topics(graph, "系统学习双打轮转", 5)
        self.assertEqual(matches[0]["category"], "双打战术")
        self.assertEqual(matches[0]["subtopic"], "轮转与补位")
        titles = [
            video["title"] for video in matches[0]["representative_videos"]
        ]
        self.assertTrue(all("正手区前后步法" not in title for title in titles))


if __name__ == "__main__":
    unittest.main()
