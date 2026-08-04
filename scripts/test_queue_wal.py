#!/usr/bin/env python3

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "scripts" / "queue_wal.py"


def load_module():
    spec = importlib.util.spec_from_file_location("queue_wal_test", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class QueueWALTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_replays_latest_durable_item_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            queue_path = Path(directory) / "queue.json"
            wal = self.module.QueueWAL(queue_path, checkpoint_interval=2)
            wal.record({"video_id": "V1", "status": "downloaded"})
            wal.record({"video_id": "V1", "status": "transcribed"})
            queue = {"items": [{"video_id": "V1", "status": "pending"}]}
            self.assertTrue(wal.replay(queue))
            self.assertEqual(queue["items"][0]["status"], "transcribed")
            self.assertTrue(wal.should_checkpoint())
            wal.clear()
            self.assertFalse(wal.path.exists())

    def test_unknown_video_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            wal = self.module.QueueWAL(Path(directory) / "queue.json")
            wal.record({"video_id": "unknown", "status": "transcribed"})
            with self.assertRaisesRegex(ValueError, "unknown video"):
                wal.replay({"items": []})


if __name__ == "__main__":
    unittest.main()
