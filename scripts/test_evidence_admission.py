#!/usr/bin/env python3
import json
import unittest
from pathlib import Path

from evidence_admission import (
    answer_admission,
    assess_bounded_note_recovery,
    validate_answer_evidence_fields,
)


ROOT = Path(__file__).resolve().parents[1]


class EvidenceAdmissionTests(unittest.TestCase):
    def test_title_alignment_issue_is_supplemental(self):
        result = answer_admission(
            origin_passed=True,
            transcript_issues=[
                "title_technical_concept_not_supported_by_transcript"
            ],
            source_content_safe=True,
            automatic_evidence_passed=True,
        )
        self.assertEqual(result["answer_eligibility"], "supplemental")
        self.assertEqual(result["metadata_title_trust"], "limited")
        self.assertTrue(result["answer_evidence_eligible"])

    def test_blocking_transcript_issue_remains_ineligible(self):
        result = answer_admission(
            origin_passed=True,
            transcript_issues=["repeated_segment_hallucination_risk"],
            source_content_safe=True,
            automatic_evidence_passed=True,
        )
        self.assertEqual(result["answer_eligibility"], "none")
        self.assertFalse(result["answer_evidence_eligible"])

    def test_duplicate_overrides_other_quality_signals(self):
        result = answer_admission(
            origin_passed=True,
            transcript_issues=[],
            source_content_safe=True,
            automatic_evidence_passed=True,
            duplicate=True,
        )
        self.assertEqual(result["disposition"], "duplicate")
        self.assertEqual(result["answer_eligibility"], "none")

    def test_non_ready_record_cannot_be_answer_eligible(self):
        with self.assertRaisesRegex(ValueError, "non-ready"):
            validate_answer_evidence_fields(
                {
                    "processing_status": "low_value",
                    "answer_eligibility": "supplemental",
                    "evidence_roles": ["correction"],
                }
            )

    def test_corpus_canary_recovers_only_domain_supported_windows(self):
        rules = json.loads(
            (ROOT / "config/knowledge_quality_rules.json").read_text(
                encoding="utf-8"
            )
        )
        knowledge = json.loads(
            (ROOT / "data/knowledge/bilibili_knowledge_base.json").read_text(
                encoding="utf-8"
            )
        )
        audited = {
            "bilibili:BV19nkvYeES8",
            "bilibili:BV1LCaAzYE3U",
            "bilibili:BV1MwbFeCE67",
            "bilibili:BV1er421W7WE",
            "bilibili:BV1gZ421a72b",
            "bilibili:BV1hByrBCEcE",
            "bilibili:BV1ju411b7kh",
            "bilibili:BV1p2gazqEhj",
            "bilibili:BV1pgv4BPEdm",
            "bilibili:BV1qe411B73P",
        }
        expected = {
            "bilibili:BV19nkvYeES8",
            "bilibili:BV1LCaAzYE3U",
            "bilibili:BV1MwbFeCE67",
            "bilibili:BV1er421W7WE",
            "bilibili:BV1ju411b7kh",
            "bilibili:BV1pgv4BPEdm",
            "bilibili:BV1qe411B73P",
        }
        actual = {
            item["video_id"]
            for item in knowledge["videos"]
            if item["video_id"] in audited
            and assess_bounded_note_recovery(item, rules)["passed"]
        }
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
