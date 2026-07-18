#!/usr/bin/env python3
import unittest

from apply_visual_review_notes import review_status
from build_douyin_knowledge import apply_review_annotation


def record():
    return {
        "title": "测试教学",
        "processing_status": "needs_visual_review",
        "confidence": "low",
        "teaching_note": {"topic": "测试"},
    }


def annotation(status, notes="复核说明"):
    return {
        "review_status": status,
        "review_notes": notes,
        "reviewed_at": "2026-01-01T00:00:00+00:00",
    }


class VisualReviewWorkflowTests(unittest.TestCase):
    def test_legacy_approve_transcript_wording_is_approved(self):
        self.assertEqual(
            review_status("有口播，按转写的结果加进skill"),
            "approved",
        )

    def test_explicit_correction_wording_stays_unpublished(self):
        self.assertEqual(review_status("术语需要修正"), "needs_correction")
        updated = apply_review_annotation(record(), annotation("needs_correction"))
        self.assertEqual(updated["processing_status"], "needs_correction")
        self.assertEqual(updated["confidence"], "review_needs_correction")

    def test_low_value_is_not_promoted(self):
        updated = apply_review_annotation(record(), annotation("low_value"))
        self.assertEqual(updated["processing_status"], "low_value")
        self.assertEqual(updated["confidence"], "reviewed_low_value")

    def test_only_approved_becomes_visual_reviewed_evidence(self):
        updated = apply_review_annotation(record(), annotation("approved"))
        self.assertEqual(updated["processing_status"], "ready")
        self.assertEqual(updated["confidence"], "visual_reviewed")
        self.assertIn("visual_review_evidence", updated["teaching_note"])

    def test_unknown_status_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "Unsupported visual review status"):
            apply_review_annotation(record(), annotation("mystery"))


if __name__ == "__main__":
    unittest.main()
