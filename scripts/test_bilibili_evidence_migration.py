#!/usr/bin/env python3
import copy
import unittest

from migrate_bilibili_evidence_admission import migrate_knowledge


def record(video_id="bilibili:BV16G411y7Rs"):
    return {
        "video_id": video_id,
        "evidence_id": video_id,
        "title": "反手发力",
        "category": "后场技术",
        "processing_status": "low_value",
        "confidence": "low",
        "quality": {
            "origin_verification": {"passed": True},
            "source_content_safety": {"passed": True},
            "automatic_evidence": {"passed": True},
            "transcript": {
                "issues": [
                    "title_technical_concept_not_supported_by_transcript"
                ]
            },
        },
        "possible_duplicate_evidence": [],
        "teaching_note": {
            "key_evidence": [
                {"timestamp": "00:01-00:03", "text": "手指放松后快速握紧"}
            ]
        },
        "transcript_segments": [],
    }


class BilibiliEvidenceMigrationTests(unittest.TestCase):
    def test_title_only_quarantine_becomes_bounded_supplemental(self):
        payload = {"updated_at": "old", "videos": [record()]}
        migrated = migrate_knowledge(payload, now="new")
        item = migrated["videos"][0]
        self.assertEqual(item["processing_status"], "ready")
        self.assertEqual(item["answer_eligibility"], "supplemental")
        self.assertEqual(item["runtime_evidence_mode"], "bounded_note_windows")
        self.assertEqual(migrated["knowledge_counts"]["bounded_note_ready"], 1)

    def test_blocking_issue_stays_quarantined(self):
        item = record()
        item["quality"]["transcript"]["issues"] = [
            "repeated_segment_hallucination_risk"
        ]
        migrated = migrate_knowledge(
            {"updated_at": "old", "videos": [item]}, now="new"
        )
        self.assertEqual(migrated["videos"][0]["processing_status"], "low_value")
        self.assertEqual(migrated["videos"][0]["answer_eligibility"], "none")

    def test_migration_is_idempotent(self):
        payload = {"updated_at": "old", "videos": [record()]}
        first = migrate_knowledge(copy.deepcopy(payload), now="new")
        second = migrate_knowledge(copy.deepcopy(first), now="later")
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
