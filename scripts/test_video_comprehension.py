#!/usr/bin/env python3
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "evaluate_video_comprehension.py"


def load_module():
    spec = importlib.util.spec_from_file_location("video_comprehension_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VideoComprehensionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def transcript_video(self, transcript_file):
        return {
            "video_id": "7000000000000000001",
            "processing_status": "ready",
            "confidence": "medium",
            "transcript_file": transcript_file,
            "quality": {
                "transcript": {"passed": True},
                "automatic_evidence": {"passed": True},
            },
            "teaching_note": {
                "topic": "接发准备",
                "key_evidence": [
                    {"timestamp": "00:01-00:03", "text": "先准备最快的回球线路"}
                ],
                "error_evidence": [],
                "action_cues": [],
            },
        }

    def test_transcript_evidence_must_roundtrip_to_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transcript_path = root / "transcript.json"
            transcript_path.write_text(
                json.dumps(
                    {
                        "full_text": "接发时先准备最快的回球线路，再处理慢线路。",
                        "segments": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            audit = self.module.audit_video_content(
                self.transcript_video("transcript.json"),
                root=root,
                indexed_video_ids={"7000000000000000001"},
            )
        self.assertEqual(audit["source_kind"], "transcript")
        self.assertEqual(audit["raw_transcript_status"], "verified")
        self.assertEqual(audit["failures"], [])

    def test_missing_raw_transcript_is_optional_only_for_portable_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            portable = self.module.audit_video_content(
                self.transcript_video("transcript.json"),
                root=root,
                indexed_video_ids={"7000000000000000001"},
            )
            strict = self.module.audit_video_content(
                self.transcript_video("transcript.json"),
                root=root,
                indexed_video_ids={"7000000000000000001"},
                require_raw_transcript=True,
            )
        self.assertEqual(portable["raw_transcript_status"], "unavailable")
        self.assertEqual(portable["failures"], [])
        self.assertIn("missing_transcript_file", strict["failures"])
        self.assertNotIn("empty_transcript", strict["failures"])

    def test_transcript_mismatch_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "transcript.json").write_text(
                json.dumps({"full_text": "这段转写讲的是其他内容。"}, ensure_ascii=False),
                encoding="utf-8",
            )
            audit = self.module.audit_video_content(
                self.transcript_video("transcript.json"),
                root=root,
                indexed_video_ids={"7000000000000000001"},
            )
        self.assertTrue(
            any(item.startswith("evidence_not_in_transcript") for item in audit["failures"])
        )

    def test_visual_demo_requires_review_summary_and_evidence(self):
        video = {
            "video_id": "7000000000000000002",
            "processing_status": "ready",
            "confidence": "visual_reviewed",
            "teaching_note": {
                "topic": "正手握拍",
                "review_summary": "纯动作示范，展示正手握拍手型。",
                "visual_review_evidence": [
                    {
                        "timestamp": "visual_review_no_timestamp",
                        "text": "纯动作示范，展示正手握拍手型。",
                    }
                ],
            },
        }
        audit = self.module.audit_video_content(
            video, indexed_video_ids={"7000000000000000002"}
        )
        self.assertEqual(audit["source_kind"], "visual_review")
        self.assertEqual(audit["failures"], [])
        video["teaching_note"]["visual_review_evidence"] = []
        audit = self.module.audit_video_content(
            video, indexed_video_ids={"7000000000000000002"}
        )
        self.assertIn("missing_visual_review_evidence", audit["failures"])


if __name__ == "__main__":
    unittest.main()
