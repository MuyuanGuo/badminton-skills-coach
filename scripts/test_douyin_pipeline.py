#!/usr/bin/env python3
import unittest

from douyin_pipeline import classify_video, load_classification_rules


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


if __name__ == "__main__":
    unittest.main()
