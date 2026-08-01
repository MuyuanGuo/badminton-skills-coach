#!/usr/bin/env python3
import unittest

from build_evidence_graph import build_graph


class EvidenceGraphTests(unittest.TestCase):
    def test_primary_and_supplemental_postings_stay_separate(self):
        knowledge = {
            "updated_at": "2026-08-01T00:00:00+00:00",
            "videos": [
                {
                    "video_id": "primary",
                    "teaching_note": {"key_evidence": [{"text": "反手动作"}]},
                },
                {
                    "video_id": "supplemental",
                    "teaching_note": {"key_evidence": [{"text": "反手纠错"}]},
                },
            ],
        }
        retrieval = {
            "videos": [
                {
                    "video_id": "primary",
                    "source_type": "douyin_video",
                    "answer_eligibility": "primary",
                    "runtime_evidence_mode": "full_transcript",
                    "metadata_title_trust": "reviewed",
                    "lexicon_terms": ["反手"],
                    "topic_ids": ["后场/反手"],
                    "evidence_roles": ["action"],
                },
                {
                    "video_id": "supplemental",
                    "source_type": "bilibili_video",
                    "answer_eligibility": "supplemental",
                    "runtime_evidence_mode": "bounded_note_windows",
                    "metadata_title_trust": "limited",
                    "lexicon_terms": ["反手"],
                    "topic_ids": ["后场/反手"],
                    "evidence_roles": ["correction"],
                },
            ]
        }
        graph = build_graph(knowledge, retrieval, {})
        self.assertEqual(graph["concept_support"]["反手"]["primary"], ["primary"])
        self.assertEqual(
            graph["concept_support"]["反手"]["supplemental"],
            ["supplemental"],
        )
        self.assertEqual(graph["counts"]["total_edges"], 6)


if __name__ == "__main__":
    unittest.main()
