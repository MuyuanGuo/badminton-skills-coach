#!/usr/bin/env python3

import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "paired_blind_evaluation.py"


def load_module():
    spec = importlib.util.spec_from_file_location("paired_blind_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PairedBlindEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()
        cls.holdout = {
            "schema_version": 1,
            "holdout_id": "test-holdout",
            "development_use_forbidden": True,
            "cases": [
                {"case_id": "C1", "query": "问题一"},
                {"case_id": "C2", "query": "问题二"},
            ],
        }
        digest = cls.module.canonical_digest(cls.holdout)
        metadata = {
            "schema_version": 1,
            "holdout_digest": digest,
            "model": "fixed-model",
            "generation_settings": {"temperature": 0},
            "generated_at": "2026-07-23T00:00:00Z",
        }
        cls.main_run = {
            **metadata,
            "branch_role": "main",
            "commit_sha": "a" * 40,
            "answers": [
                {"case_id": "C1", "answer": "main one"},
                {"case_id": "C2", "answer": "main two"},
            ],
        }
        cls.develop_run = {
            **metadata,
            "branch_role": "develop",
            "commit_sha": "b" * 40,
            "answers": [
                {"case_id": "C1", "answer": "develop one"},
                {"case_id": "C2", "answer": "develop two"},
            ],
        }

    def test_blinded_artifact_hides_branch_mapping(self):
        blinded, key = self.module.build_blinded_pairs(
            self.holdout, self.main_run, self.develop_run, "secret-seed"
        )
        self.assertEqual(len(blinded["pairs"]), 2)
        self.assertNotIn("commit_sha", json.dumps(blinded))
        self.assertNotIn("branch_role", json.dumps(blinded))
        self.assertEqual(len(key["mappings"]), 2)
        self.assertEqual(
            key["blinded_pairs_digest"], self.module.canonical_digest(blinded)
        )

    def test_branch_runs_must_use_identical_generation_settings(self):
        changed = copy.deepcopy(self.develop_run)
        changed["generation_settings"]["temperature"] = 1
        with self.assertRaisesRegex(self.module.BlindEvaluationError, "settings"):
            self.module.build_blinded_pairs(
                self.holdout, self.main_run, changed, "secret-seed"
            )

    def test_independent_human_review_is_required_before_unblinding(self):
        blinded, key = self.module.build_blinded_pairs(
            self.holdout, self.main_run, self.develop_run, "secret-seed"
        )
        reviews = self.module.review_template(blinded)
        reviews["reviewer"].update(
            {"reviewer_id": "reviewer-1", "reviewed_at": "2026-07-23T01:00:00Z"}
        )
        for review in reviews["reviews"]:
            review["preference"] = "A"
            review["notes"] = "Compared correctness, evidence, omissions, and clarity."
            for label in ("A", "B"):
                review["scores"][label] = {
                    dimension: 4 for dimension in self.module.RUBRIC
                }
        result = self.module.score_reviews(blinded, key, reviews)
        self.assertEqual(result["pair_count"], 2)
        self.assertEqual(sum(result["wins"].values()), 2)
        reviews["reviewer"]["branch_identity_known_during_review"] = True
        with self.assertRaisesRegex(
            self.module.BlindEvaluationError, "blinded human review"
        ):
            self.module.score_reviews(blinded, key, reviews)


if __name__ == "__main__":
    unittest.main()
