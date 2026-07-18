#!/usr/bin/env python3
import unittest

from douyin_pipeline import (
    classify_video,
    load_classification_rules,
    normalize_transcribed_media_state,
)


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
            "duration_seconds": 12.3,
        }
        self.assertTrue(normalize_transcribed_media_state(item))
        self.assertIsNone(item["media_path"])
        self.assertNotIn("media_asset_kind", item)
        self.assertNotIn("media_asset_source", item)
        self.assertEqual(item["duration_seconds"], 12.3)


if __name__ == "__main__":
    unittest.main()
