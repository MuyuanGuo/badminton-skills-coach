#!/usr/bin/env python3
import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "check_maintenance_health.py"


def load_module():
    spec = importlib.util.spec_from_file_location("maintenance_health_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MaintenanceHealthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def payloads(self):
        return {
            "index": {"collected_at": "2026-07-20T00:00:00+00:00"},
            "knowledge": {"updated_at": "2026-07-21T00:00:00+00:00"},
            "queue": {"items": [], "counts": {}},
            "discovery": {"counts": {}},
            "forward_tests": {
                "results": [{"tested_at": "2026-07-19"}],
                "unseen_rounds": [{"tested_at": "2026-07-21"}],
            },
        }

    def report(self, **changes):
        payloads = self.payloads()
        payloads.update(changes)
        return self.module.build_report(
            **payloads,
            now=datetime(2026, 7, 22, tzinfo=timezone.utc),
        )

    def test_fresh_idle_pipeline_is_healthy(self):
        report = self.report()
        self.assertEqual(report["status"], "healthy")
        self.assertEqual(report["next_action"], "No maintenance action is currently required.")

    def test_stale_profile_is_overdue_and_highest_priority(self):
        report = self.report(index={"collected_at": "2026-07-01T00:00:00+00:00"})
        self.assertEqual(report["status"], "overdue")
        self.assertIn("fresh Douyin profile snapshot", report["next_action"])

    def test_failed_and_pending_queue_items_need_attention(self):
        report = self.report(
            queue={
                "counts": {"download_failed": 1, "classified_teaching": 1},
                "items": [
                    {"video_id": "1", "status": "download_failed"},
                    {"video_id": "2", "status": "classified_teaching"},
                ],
            }
        )
        self.assertEqual(report["status"], "attention")
        queue_check = next(item for item in report["checks"] if item["id"] == "processing_queue")
        self.assertEqual(queue_check["failed_video_ids"], ["1"])
        self.assertEqual(queue_check["pending_video_ids"], ["2"])
        self.assertIn("failed queue items", report["next_action"])

    def test_missing_forward_tests_are_overdue(self):
        report = self.report(forward_tests={"results": [], "unseen_rounds": []})
        self.assertEqual(report["status"], "overdue")
        forward = next(item for item in report["checks"] if item["id"] == "forward_tests")
        self.assertIsNone(forward["age_days"])

    def test_markdown_summary_includes_all_checks(self):
        summary = self.module.markdown_summary(self.report())
        self.assertIn("Knowledge maintenance health", summary)
        self.assertIn("`profile_observation`", summary)
        self.assertIn("`classification_review`", summary)


if __name__ == "__main__":
    unittest.main()
