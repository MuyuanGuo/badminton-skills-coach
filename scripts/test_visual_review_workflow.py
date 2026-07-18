#!/usr/bin/env python3
import unittest

from apply_visual_review_notes import review_evidence_source, review_status
from build_douyin_knowledge import (
    apply_review_annotation,
    filter_segments_by_time_ranges,
)


def record():
    return {
        "title": "测试教学",
        "processing_status": "needs_visual_review",
        "confidence": "low",
        "teaching_note": {
            "topic": "测试",
            "key_evidence": [{"timestamp": "00:00", "text": "错误歌词"}],
            "action_cues": [{"timestamp": "00:00", "text": "无关自动证据"}],
        },
        "quality": {"automatic_evidence": {"passed": False}},
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
        self.assertNotIn("key_evidence", updated["teaching_note"])
        self.assertNotIn("action_cues", updated["teaching_note"])
        self.assertFalse(updated["quality"]["automatic_evidence"]["searchable"])

    def test_reviewed_transcript_replaces_automatic_windows_but_keeps_source_kind(self):
        notes = "有口播，按转写的结果加进skill"
        reviewed = annotation("approved", notes)
        reviewed["evidence_source"] = review_evidence_source(notes)
        updated = apply_review_annotation(record(), reviewed)
        self.assertEqual(updated["confidence"], "reviewed_transcript")
        self.assertEqual(updated["review_evidence_source"], "reviewed_transcript")
        self.assertNotIn("key_evidence", updated["teaching_note"])
        self.assertNotIn("visual_review_evidence", updated["teaching_note"])

    def test_reviewed_transcript_can_limit_searchable_evidence_to_teaching_range(self):
        reviewed = annotation("approved", "按转写结果加进skill，只保留教学片段")
        reviewed.update(
            {
                "evidence_source": "reviewed_transcript",
                "retrieval_title": "正手抽球旋转发力",
                "category_override": "中前场与抽挡",
                "tags_override": ["中前场与抽挡", "发力与身体运用"],
                "allowed_time_ranges": [
                    {"start": 2.3, "end": 4.3},
                    {"start": 6.3, "end": 21.3},
                ],
                "excluded_content_note": "范围外是产品评价",
            }
        )
        updated = apply_review_annotation(record(), reviewed)
        self.assertEqual(updated["retrieval_title"], "正手抽球旋转发力")
        self.assertEqual(updated["category"], "中前场与抽挡")
        self.assertEqual(updated["tags"], ["中前场与抽挡", "发力与身体运用"])
        self.assertEqual(
            updated["transcript_scope"]["allowed_time_ranges"],
            [{"start": 2.3, "end": 4.3}, {"start": 6.3, "end": 21.3}],
        )
        segments = [
            {"start": 2.3, "end": 4.3, "text": "教学开场"},
            {"start": 4.3, "end": 6.3, "text": "产品介绍"},
            {"start": 6.3, "end": 10.0, "text": "教学动作"},
            {"start": 21.3, "end": 30.0, "text": "产品评价"},
        ]
        self.assertEqual(
            [item["text"] for item in filter_segments_by_time_ranges(
                segments, updated["transcript_scope"]["allowed_time_ranges"]
            )],
            ["教学开场", "教学动作"],
        )

    def test_unknown_status_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "Unsupported visual review status"):
            apply_review_annotation(record(), annotation("mystery"))


if __name__ == "__main__":
    unittest.main()
