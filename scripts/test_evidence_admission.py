#!/usr/bin/env python3
import unittest

from evidence_admission import answer_admission, validate_answer_evidence_fields


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


if __name__ == "__main__":
    unittest.main()
