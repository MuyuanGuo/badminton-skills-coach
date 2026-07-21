#!/usr/bin/env python3
import importlib.util
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "check_douyin_updates.py"


def load_module():
    spec = importlib.util.spec_from_file_location("douyin_update_state_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DouyinUpdateStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def paths(self, root):
        return {
            "INDEX_PATH": root / "index.json",
            "TEACHING_PATH": root / "teaching.json",
            "LEDGER_PATH": root / "ledger.json",
            "QUEUE_PATH": root / "queue.json",
            "DISCOVERY_STATE_PATH": root / "discovery.json",
            "TRANSACTION_PATH": root / ".transaction.json",
        }

    def write_baseline(self, paths):
        self.module.write_json(
            paths["INDEX_PATH"],
            {"videos": [], "collected_unique_links": 0},
        )
        self.module.write_json(
            paths["TEACHING_PATH"],
            {
                "videos": [],
                "counts": {
                    "total": 0,
                    "kept_teaching": 0,
                    "review": 0,
                    "excluded_ads": 0,
                    "excluded_non_teaching": 0,
                },
            },
        )
        self.module.write_json(
            paths["LEDGER_PATH"],
            {"videos": [], "counts": {}, "classification_rules": {}},
        )
        self.module.write_json(
            paths["QUEUE_PATH"],
            {"items": [], "counts": {}},
        )
        self.module.write_json(
            paths["DISCOVERY_STATE_PATH"],
            {
                "version": 1,
                "created_at": "test",
                "updated_at": None,
                "baseline_index_count": 0,
                "counts": {},
                "items": [],
            },
        )

    def classified(self, video_id, decision):
        return {
            "video_id": video_id,
            "url": f"https://www.douyin.com/video/{video_id}",
            "title": f"video-{video_id}",
            "raw_text": f"video-{video_id}",
            "decision": decision,
            "decision_reason": "test",
            "primary_category": "后场技术" if decision == "保留：教学" else "",
            "tags": "后场技术" if decision == "保留：教学" else "",
        }

    def test_apply_records_every_decision_and_review_can_be_resolved(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = self.paths(Path(temporary))
            self.write_baseline(paths)
            with ExitStack() as stack:
                for name, value in paths.items():
                    stack.enter_context(mock.patch.object(self.module, name, value))
                classified = [
                    self.classified("100000000000000001", "保留：教学"),
                    self.classified("100000000000000002", "待复核：教学夹带推广"),
                    self.classified("100000000000000003", "排除：非教学"),
                ]
                new_videos = [
                    {
                        key: item[key]
                        for key in ["video_id", "url", "title", "raw_text"]
                    }
                    for item in classified
                ]
                applied = self.module.apply_updates(new_videos, classified)
                self.assertEqual(applied["index_added"], 3)
                self.assertEqual(applied["ledger_added"], 3)
                self.assertEqual(applied["queue_added"], 1)
                self.assertEqual(applied["review_pending"], 1)

                discovery = self.module.load_json(paths["DISCOVERY_STATE_PATH"])
                self.assertEqual(
                    discovery["counts"],
                    {
                        "classified_teaching": 1,
                        "review_pending": 1,
                        "excluded_non_teaching": 1,
                    },
                )
                result = self.module.resolve_review(
                    "100000000000000002", "keep", "画面包含明确教学步骤"
                )
                self.assertEqual(result["status"], "classified_teaching")
                teaching = self.module.load_json(paths["TEACHING_PATH"])
                ledger = self.module.load_json(paths["LEDGER_PATH"])
                queue = self.module.load_json(paths["QUEUE_PATH"])
                discovery = self.module.load_json(paths["DISCOVERY_STATE_PATH"])
                self.assertEqual(teaching["counts"]["review"], 0)
                self.assertEqual(teaching["counts"]["kept_teaching"], 2)
                self.assertEqual(
                    ledger["counts"],
                    {"保留：教学": 2, "排除：非教学": 1},
                )
                reviewed = next(
                    item
                    for item in ledger["videos"]
                    if item["video_id"] == "100000000000000002"
                )
                self.assertEqual(reviewed["automatic_decision"], "待复核：教学夹带推广")
                self.assertEqual(reviewed["decision"], "保留：教学")
                self.assertEqual(reviewed["migration_action"], "manual_review_keep")
                self.assertEqual(queue["counts"], {"classified_teaching": 2})
                rules_identity = self.module.load_classification_rules()[
                    "_rules_identity"
                ]
                for queue_item in queue["items"]:
                    self.assertEqual(
                        queue_item["classification_rules_version"],
                        rules_identity["version"],
                    )
                    self.assertEqual(
                        queue_item["classification_rules_hash"],
                        rules_identity["sha256"],
                    )
                self.assertEqual(discovery["counts"]["classified_teaching"], 2)
                self.assertNotIn("review_pending", discovery["counts"])
                with self.assertRaises(ValueError):
                    self.module.resolve_review(
                        "100000000000000002", "keep", "duplicate"
                    )


if __name__ == "__main__":
    unittest.main()
