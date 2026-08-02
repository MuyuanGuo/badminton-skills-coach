#!/usr/bin/env python3
import copy
import json
import unittest
from pathlib import Path

from migrate_bilibili_evidence_admission import migrate_knowledge


ROOT = Path(__file__).resolve().parents[1]
RULES = json.loads(
    (ROOT / "config" / "knowledge_quality_rules.json").read_text(
        encoding="utf-8"
    )
)


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


def recoverable_record():
    item = record("bilibili:BV1equipment")
    item["title"] = "球拍平衡点"
    item["quality"]["automatic_evidence"] = {
        "passed": False,
        "issues": [
            "missing_key_evidence",
            "too_few_teaching_term_matches",
        ],
    }
    item["teaching_note"] = {
        "key_evidence": [],
        "error_evidence": [
            {
                "timestamp": "00:01-00:04",
                "text": "买球拍首先要看平衡点和参数",
            },
            {
                "timestamp": "00:05-00:08",
                "text": "如果拍头太重就不适合刚入门的人",
            },
            {
                "timestamp": "00:09-00:12",
                "text": "今天直播间天气不错",
            },
        ],
        "action_cues": [],
    }
    return item


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

    def test_domain_supported_note_recovery_is_bounded_and_idempotent(self):
        payload = {"updated_at": "old", "videos": [recoverable_record()]}
        first = migrate_knowledge(payload, now="new")
        item = first["videos"][0]
        self.assertEqual(item["answer_eligibility"], "supplemental")
        self.assertEqual(
            item["automatic_admission"]["disposition"],
            "supplemental_bounded_note_recovery",
        )
        self.assertTrue(item["quality"]["bounded_note_recovery"]["passed"])
        self.assertEqual(
            [entry["timestamp"] for entry in item["teaching_note"]["error_evidence"]],
            ["00:01-00:04", "00:05-00:08"],
        )
        second = migrate_knowledge(copy.deepcopy(first), now="later")
        self.assertEqual(first, second)

    def test_stale_title_block_is_recomputed_as_advisory(self):
        item = record()
        item["automatic_admission"] = {
            "rules_version": 10,
            "disposition": "quarantined_transcript_or_title_quality",
            "blocking_issues": [
                "title_technical_concept_not_supported_by_transcript"
            ],
        }
        migrated = migrate_knowledge(
            {"updated_at": "old", "videos": [item]}, now="new"
        )["videos"][0]
        self.assertEqual(migrated["automatic_admission"]["blocking_issues"], [])
        self.assertEqual(
            migrated["automatic_admission"]["advisory_issues"],
            ["title_technical_concept_not_supported_by_transcript"],
        )

    def test_role_aware_note_recovers_equipment_as_supplemental(self):
        item = record()
        item["title"] = "球拍参数"
        item["category"] = "装备选择"
        item["quality"]["automatic_evidence"] = {
            "passed": False,
            "issues": [
                "missing_key_evidence",
                "too_few_teaching_term_matches",
            ],
        }
        item["quality"]["transcript"]["issues"] = []
        item["teaching_note"]["key_evidence"] = [
            {
                "timestamp": "00:01-00:08",
                "text": "这个球拍是5U，所以拍头重量需要一起看",
            },
            {
                "timestamp": "00:09-00:16",
                "text": "如果平衡点更高，就更适合借助拍头发力",
            },
        ]
        migrated = migrate_knowledge(
            {"updated_at": "old", "videos": [item]},
            rules=RULES,
            now="new",
        )
        recovered = migrated["videos"][0]
        self.assertEqual(recovered["answer_eligibility"], "supplemental")
        self.assertEqual(
            recovered["automatic_admission"]["disposition"],
            "supplemental_bounded_note_recovery",
        )
        self.assertIn("equipment", recovered["evidence_roles"])

    def test_role_aware_note_does_not_admit_one_weak_equipment_window(self):
        item = record()
        item["quality"]["automatic_evidence"] = {
            "passed": False,
            "issues": ["missing_key_evidence"],
        }
        item["quality"]["transcript"]["issues"] = []
        item["teaching_note"]["key_evidence"] = [
            {"timestamp": "00:01-00:08", "text": "这个球拍可以看一下"}
        ]
        migrated = migrate_knowledge(
            {"updated_at": "old", "videos": [item]},
            rules=RULES,
            now="new",
        )
        self.assertEqual(
            migrated["videos"][0]["answer_eligibility"], "none"
        )

    def test_migration_refreshes_stale_admission_rule_version(self):
        item = record()
        item["automatic_admission"] = {
            "disposition": "quarantined_transcript_or_title_quality",
            "rules_version": 10,
        }
        migrated = migrate_knowledge(
            {"updated_at": "old", "videos": [item]},
            rules=RULES,
            now="new",
        )
        admission = migrated["videos"][0]["automatic_admission"]
        self.assertEqual(admission["rules_version"], RULES["version"])
        self.assertEqual(admission["disposition"], "supplemental_title_alignment")

if __name__ == "__main__":
    unittest.main()
