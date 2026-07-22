#!/usr/bin/env python3
import importlib.util
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "check_douyin_updates.py"


def load_module():
    spec = importlib.util.spec_from_file_location("douyin_snapshot_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DouyinSnapshotValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()
        cls.now = datetime(2026, 7, 17, 12, tzinfo=timezone.utc)
        cls.config = {
            "profile_id": "creator-id",
            "snapshot": {
                "max_age_hours": 24,
                "min_observed_links": 4,
                "min_known_coverage_ratio": 0.1,
            },
        }

    def payload(self, count=5):
        videos = [
            {
                "video_id": f"{100000000000000000 + index}",
                "url": f"https://www.douyin.com/video/{100000000000000000 + index}",
                "title": f"video-{index}",
            }
            for index in range(count)
        ]
        return {
            "profile_url": "https://www.douyin.com/user/creator-id?from_tab_name=main",
            "collected_at": (self.now - timedelta(hours=1)).isoformat(),
            "collected_unique_links": len(videos),
            "videos": videos,
        }

    def test_accepts_fresh_creator_snapshot_with_sufficient_coverage(self):
        result = self.module.validate_snapshot_payload(
            self.payload(), known_count=40, source_config=self.config, current_time=self.now
        )
        self.assertEqual(result["profile_id"], "creator-id")
        self.assertEqual(result["minimum_required"], 4)
        self.assertEqual(result["observed"], 5)

    def test_rejects_wrong_creator_stale_or_partial_snapshots(self):
        wrong_creator = self.payload()
        wrong_creator["profile_url"] = "https://www.douyin.com/user/someone-else"
        with self.assertRaisesRegex(ValueError, "configured creator"):
            self.module.validate_snapshot_payload(
                wrong_creator, 40, self.config, self.now
            )

        stale = self.payload()
        stale["collected_at"] = (self.now - timedelta(hours=25)).isoformat()
        with self.assertRaisesRegex(ValueError, "stale"):
            self.module.validate_snapshot_payload(stale, 40, self.config, self.now)

        partial = self.payload(count=3)
        with self.assertRaisesRegex(ValueError, "coverage is too low"):
            self.module.validate_snapshot_payload(partial, 40, self.config, self.now)

        mismatched_count = deepcopy(self.payload())
        mismatched_count["collected_unique_links"] = 99
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.module.validate_snapshot_payload(
                mismatched_count, 40, self.config, self.now
            )

    def test_v3_snapshot_declares_incremental_scope_and_scroll_completion(self):
        payload = self.payload()
        payload.update(
            {
                "collector_version": 3,
                "snapshot_scope": "incremental_recent_profile_observation",
                "full_profile_archive": False,
                "scroll_stabilized": True,
            }
        )
        result = self.module.validate_snapshot_payload(
            payload, 40, self.config, self.now
        )
        self.assertEqual(result["observed"], 5)

        payload["scroll_stabilized"] = False
        with self.assertRaisesRegex(ValueError, "did not stabilize"):
            self.module.validate_snapshot_payload(
                payload, 40, self.config, self.now
            )


if __name__ == "__main__":
    unittest.main()
