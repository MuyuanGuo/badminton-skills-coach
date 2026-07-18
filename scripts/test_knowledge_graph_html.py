#!/usr/bin/env python3
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "generate_knowledge_graph.py"


def load_module():
    spec = importlib.util.spec_from_file_location("knowledge_graph_html_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class KnowledgeGraphHtmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def malicious_graph(self):
        return {
            "version": "test",
            "source": "test",
            "scope": "test",
            "source_updated_at": "2026-07-17T00:00:00+00:00",
            "video_count": 1,
            "indexable_video_count": 1,
            "assigned_video_count": 1,
            "multi_topic_video_count": 0,
            "categories": [
                {
                    "name": "</option><img src=x onerror=alert(1)>",
                    "description": "<svg onload=alert(2)>",
                    "video_count": 1,
                    "subtopics": [
                        {
                            "name": "</summary><script>alert(3)</script>",
                            "keywords": ["<b>unsafe</b>"],
                            "video_count": 1,
                            "ready_count": 1,
                            "representative_videos": [
                                {
                                    "video_id": "123456789012345678",
                                    "title": "</script><script>alert(4)</script>",
                                    "url": "javascript:alert(5)",
                                    "confidence": "<img onerror=alert(6)>",
                                    "category": "test",
                                    "duration_seconds": 1,
                                    "score": 1,
                                }
                            ],
                        }
                    ],
                }
            ],
        }

    def test_untrusted_graph_values_cannot_create_markup_or_end_script(self):
        rendered = self.module.render_html(self.malicious_graph())
        self.assertNotIn("</script><script>alert(4)", rendered)
        self.assertNotIn("<img src=x onerror", rendered)
        self.assertIn("\\u003c/script\\u003e", rendered)
        self.assertNotIn("innerHTML", rendered)
        self.assertIn("textContent", rendered)
        self.assertIn("Content-Security-Policy", rendered)
        self.assertIn("safeVideoUrl", rendered)

    def test_only_canonical_matching_douyin_urls_are_accepted(self):
        good = "https://www.douyin.com/video/123456789012345678"
        self.assertEqual(
            self.module.validate_video_url(good, "123456789012345678"), good
        )
        for unsafe in [
            "javascript:alert(1)",
            "https://evil.example/video/123456789012345678",
            "https://www.douyin.com/video/123456789012345678?redirect=evil",
        ]:
            with self.subTest(url=unsafe):
                with self.assertRaises(ValueError):
                    self.module.validate_video_url(unsafe)
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.module.validate_video_url(good, "999999999999999999")

    def test_generated_graph_has_no_external_runtime_assets(self):
        rendered = self.module.render_html(self.malicious_graph())
        self.assertNotRegex(rendered, r"<script[^>]+src=")
        self.assertNotRegex(rendered, r"<link[^>]+href=")
        self.assertNotIn("fetch(", rendered)


if __name__ == "__main__":
    unittest.main()
