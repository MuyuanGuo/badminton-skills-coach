#!/usr/bin/env python3
import unittest
from unittest.mock import patch

import process_douyin_ready_batch as batch_processor

from douyin_pipeline import (
    classify_video,
    load_classification_rules,
    normalize_transcribed_media_state,
)
from process_douyin_ready_batch import unexpected_dirty_paths
from report_pipeline_status import next_action
from run_full_update_pipeline import validation_commands


class DouyinClassificationRulesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = load_classification_rules()

    def classify_title(self, title, video_id="test-video"):
        return classify_video(
            {
                "video_id": video_id,
                "url": f"https://www.douyin.com/video/{video_id}",
                "title": title,
                "raw_text": title,
                "teaching_candidate": "unknown",
            },
            self.rules,
        )

    def test_keeps_clear_teaching_video(self):
        item = self.classify_title("网前框架 #羽毛球 #刘辉羽毛球 #羽毛球教学 #羽毛球训练")
        self.assertEqual(item["decision"], "保留：教学")
        self.assertEqual(item["primary_category"], "网前技术")

    def test_excludes_pure_equipment_or_ad_video(self):
        item = self.classify_title("紫电青霜正式首发 直播间购买福利 #华羽")
        self.assertEqual(item["decision"], "排除：广告/器材推广")

    def test_routes_mixed_teaching_and_promotion_to_review(self):
        item = self.classify_title("双打抓回头 #羽毛球教学 紫电青霜直播间福利")
        self.assertEqual(item["decision"], "待复核：教学夹带推广")

    def test_manual_exclusion_overrides_signals(self):
        item = self.classify_title(
            "杀球教学 #羽毛球教学",
            video_id="7239168493294226740",
        )
        self.assertEqual(item["decision"], "排除：广告/器材推广")
        self.assertEqual(item["decision_reason"], "用户指定去除")

    def test_non_teaching_content_is_not_rescued_by_teaching_hashtags(self):
        item = self.classify_title("春节放假通知 #羽毛球教学 #羽毛球训练")
        self.assertEqual(item["decision"], "排除：非教学")
        self.assertEqual(item["tags"], "")

    def test_equipment_commerce_is_not_rescued_by_teaching_hashtag(self):
        item = self.classify_title("新球拍推荐入手，今晚带走 #羽毛球教学")
        self.assertEqual(item["decision"], "排除：广告/器材推广")

    def test_hashtag_only_content_requires_review(self):
        item = self.classify_title("今天和大家聊一聊 #羽毛球教学")
        self.assertEqual(item["decision"], "待复核：仅通用教学标签")
        self.assertEqual(item["primary_category"], "")

    def test_transcribed_state_drops_only_temporary_media_fields(self):
        item = {
            "video_id": "123456789012345678",
            "status": "transcribed",
            "media_path": "data/raw_videos/douyin/batch-001/video.m4a",
            "media_asset_kind": "audio",
            "media_asset_source": "data/tmp/snapshot.json",
            "media_download_method": "anonymous_chrome_cdp_yt_dlp",
            "duration_seconds": 12.3,
            "transcript_source_sha256": "a" * 64,
        }
        self.assertTrue(normalize_transcribed_media_state(item))
        self.assertIsNone(item["media_path"])
        self.assertNotIn("media_asset_kind", item)
        self.assertNotIn("media_asset_source", item)
        self.assertNotIn("media_download_method", item)
        self.assertEqual(item["duration_seconds"], 12.3)
        self.assertEqual(item["transcript_source_sha256"], "a" * 64)

    def test_batch_rejects_unrelated_preexisting_changes(self):
        self.assertEqual(
            unexpected_dirty_paths(
                [
                    "data/processing/douyin_queue.json",
                    "README.md",
                    "notes/private.txt",
                ]
            ),
            ["README.md", "notes/private.txt"],
        )

    def test_successful_batch_cleans_temporary_state_before_full_validation(self):
        events = []
        with patch.object(
            batch_processor,
            "cleanup_transcribed_media",
            side_effect=lambda *_args: events.append("cleanup") or {"removed": ["123"], "skipped": []},
        ), patch.object(
            batch_processor,
            "rebuild_and_validate",
            side_effect=lambda: events.append("validate"),
        ):
            batch_processor.finalize_transcribed_batch("batch-049", ["123"])
        self.assertEqual(events, ["cleanup", "validate"])

    def test_full_maintenance_gate_covers_answer_and_video_quality(self):
        commands = [" ".join(map(str, command)) for command in validation_commands()]
        for required in [
            "evaluate_answer_context.py",
            "evaluate_answer_quality.py",
            "evaluate_query_understanding.py",
            "evaluate_retrieval.py",
            "evaluate_video_comprehension.py --require-raw-transcripts",
            "build_manifest.py --check",
            "validate_project.py",
            "test_export_douyin_cookies_cdp.mjs",
        ]:
            self.assertTrue(
                any(required in command for command in commands),
                required,
            )

    def test_applied_update_report_advances_to_media_extraction(self):
        action = next_action(
            {"counts": {"classified_teaching": 1, "transcribed": 406}},
            {"new": 1, "teaching": 1, "applied": {"queue_added": 1}},
        )
        self.assertIn("--auto-download", action)


if __name__ == "__main__":
    unittest.main()
