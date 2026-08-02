#!/usr/bin/env python3
import unittest
from pathlib import Path
from unittest import mock

import refresh_bilibili_recovery_records as refresh


class BilibiliRecoveryRefreshTests(unittest.TestCase):
    def test_only_changed_approved_recovery_transcript_replaces_record(self):
        old = {
            "video_id": "bilibili:BV16G411y7Rs",
            "evidence_id": "bilibili:BV16G411y7Rs",
            "source_video_id": "BV16G411y7Rs",
            "processing_status": "low_value",
            "quality": {
                "transcript": {
                    "integrity": {"transcript_sha256": "old"}
                }
            },
        }
        queue = {
            "items": [
                {
                    "video_id": "BV16G411y7Rs",
                    "evidence_id": "bilibili:BV16G411y7Rs",
                    "status": "transcribed",
                    "transcript_model": "medium",
                },
                {
                    "video_id": "BV1aw411179M",
                    "evidence_id": "bilibili:BV1aw411179M",
                    "status": "transcribed",
                    "transcript_model": "small",
                },
            ]
        }
        replacement = {**old, "processing_status": "ready"}
        rules = {
            "version": 12,
            "bilibili_unattended": {"quality_recovery_models": ["medium"]},
        }

        def fake_shingle_index(videos):
            self.assertNotIn(
                "bilibili:BV16G411y7Rs",
                {item.get("evidence_id") for item in videos},
            )
            return {}, {}, {}

        with (
            mock.patch.object(
                refresh, "load_valid_queue_transcript", return_value={}
            ),
            mock.patch.object(
                refresh,
                "transcript_integrity",
                return_value={"transcript_sha256": "new"},
            ),
            mock.patch.object(
                refresh, "build_shingle_index", side_effect=fake_shingle_index
            ),
            mock.patch.object(refresh, "build_record", return_value=replacement),
            mock.patch.object(refresh, "add_to_shingle_index"),
        ):
            output, changed = refresh.refreshed_knowledge(
                {"updated_at": "old", "videos": [old]},
                queue,
                {"BV16G411y7Rs": [Path("recovered.json")]},
                rules,
                {"videos": [old]},
                now="new",
            )

        self.assertEqual(changed, ["bilibili:BV16G411y7Rs"])
        self.assertEqual(output["videos"][0]["processing_status"], "ready")
        self.assertEqual(
            output["videos"][0]["quality_recovery"]["model"], "medium"
        )


if __name__ == "__main__":
    unittest.main()
