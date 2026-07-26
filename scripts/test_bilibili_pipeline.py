#!/usr/bin/env python3
import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(name):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BilibiliPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pipeline = load("bilibili_pipeline")
        cls.updates = load("check_bilibili_updates")
        cls.rules = cls.pipeline.load_rules()

    def classify(self, title, **extra):
        item = self.pipeline.normalize_video({
            "bvid": "BV16G411y7Rs",
            "title": title,
            **extra,
        })
        return self.pipeline.classify_video(item, self.rules)

    def test_explicit_liuhui_teaching_is_candidate_but_not_admitted(self):
        item = self.classify("刘辉教练教你反手万能握拍")
        self.assertEqual(item["decision"], "candidate_liuhui_teaching")
        self.assertEqual(item["origin_status"], "origin_verification_pending")
        self.assertFalse(item["knowledge_admission_eligible"])
        self.assertFalse(self.pipeline.may_enter_knowledge_base(item))

    def test_creator_teaching_without_origin_signal_is_isolated(self):
        item = self.classify("反手高远球提高稳定性的技巧")
        self.assertEqual(item["decision"], "excluded_creator_original_or_unknown")

    def test_seo_description_cannot_contaminate_origin_decision(self):
        item = self.classify(
            "反手高远球提高稳定性的技巧",
            description="直播教学切片已获刘辉教练授权；相关视频：刘辉教练教你",
        )
        self.assertEqual(item["decision"], "excluded_creator_original_or_unknown")

    def test_non_teaching_and_medical_are_not_candidates(self):
        self.assertEqual(
            self.classify("直播花絮 第45集")["decision"],
            "excluded_non_teaching",
        )
        self.assertEqual(
            self.classify("为什么打完羽毛球后膝盖疼？刘辉教练告诉你")["decision"],
            "excluded_non_teaching",
        )

    def test_verified_origin_requires_method_and_timestamp(self):
        item = self.classify("刘辉教练教你反手万能握拍")
        item["origin_verification"] = {
            "status": "verified_liuhui_clip",
            "methods": ["verified_collection_membership"],
            "verified_at": "2026-07-26T00:00:00+00:00",
        }
        self.assertTrue(self.pipeline.may_enter_knowledge_base(item))

    def test_snapshot_validation_checks_profile_freshness_and_coverage(self):
        now = datetime(2026, 7, 26, tzinfo=timezone.utc)
        source = {
            "profile_id": "1423436652",
            "snapshot": {"max_age_hours": 24, "min_observed_links": 2},
        }
        payload = {
            "profile_id": "1423436652",
            "profile_url": "https://space.bilibili.com/1423436652",
            "collected_at": (now - timedelta(hours=1)).isoformat(),
            "collected_unique_links": 2,
            "videos": [{}, {}],
        }
        result = self.updates.validate_snapshot(payload, source, now)
        self.assertEqual(result["observed"], 2)
        payload["profile_id"] = "other"
        with self.assertRaisesRegex(ValueError, "configured"):
            self.updates.validate_snapshot(payload, source, now)

    def test_cross_platform_dedupe_uses_inverted_index(self):
        postings, titles = self.updates.build_douyin_term_index([
            {"video_id": "1", "title": "刘辉教练 反手 万能握拍 技巧"},
            {"video_id": "2", "title": "双打 接发球 站位"},
        ])
        matches = self.updates.possible_douyin_duplicates(
            "刘辉教练反手万能握拍技巧", postings, titles, threshold=0.3
        )
        self.assertEqual(matches[0]["video_id"], "1")


if __name__ == "__main__":
    unittest.main()
