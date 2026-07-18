#!/usr/bin/env python3
import json
import unittest
from pathlib import Path

from douyin_pipeline import classify_video, load_classification_rules
from reclassify_douyin_catalog import effective_decision


class ClassificationMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = load_classification_rules()

    def test_classification_records_rule_version_and_hash(self):
        result = classify_video(
            {"video_id": "1", "title": "正手握拍教学", "raw_text": ""},
            self.rules,
        )
        self.assertEqual(result["classification_rules_version"], 2)
        self.assertEqual(len(result["classification_rules_hash"]), 64)

    def test_transcript_evidence_prevents_title_only_false_exclusion(self):
        automatic = {
            "decision": "排除：非教学",
            "decision_reason": "标题无教学信号",
        }
        knowledge = {
            "quality": {"automatic_evidence": {"passed": True}},
            "confidence": "medium",
        }
        decision, _, action = effective_decision(
            automatic, True, knowledge_record=knowledge
        )
        self.assertEqual(decision, "保留：教学")
        self.assertEqual(action, "preserve_transcript_backed_teaching")

    def test_evidence_backed_promotion_is_routed_to_review(self):
        automatic = {
            "decision": "排除：广告/器材推广",
            "decision_reason": "器材推广",
        }
        knowledge = {
            "quality": {"automatic_evidence": {"passed": True}},
            "confidence": "medium",
        }
        decision, _, action = effective_decision(
            automatic, True, knowledge_record=knowledge
        )
        self.assertEqual(decision, "待复核：教学夹带推广")
        self.assertIn("promotion_to_review", action)

    def test_brand_hashtag_alone_does_not_override_transcript_evidence(self):
        automatic = {
            "decision": "待复核：教学夹带推广",
            "decision_reason": "品牌标签",
            "classification_signals": {"ad_strong_hashtag_only": True},
        }
        knowledge = {
            "quality": {"automatic_evidence": {"passed": True}},
            "confidence": "medium",
        }
        decision, _, action = effective_decision(
            automatic, True, knowledge_record=knowledge
        )
        self.assertEqual(decision, "保留：教学")
        self.assertEqual(action, "preserve_hashtag_only_transcript_teaching")

    def test_existing_review_decision_has_precedence(self):
        automatic = {
            "decision": "保留：教学",
            "decision_reason": "标题教学信号",
        }
        decision, _, action = effective_decision(
            automatic,
            True,
            review={"review_status": "not_teaching"},
        )
        self.assertEqual(decision, "排除：非教学")
        self.assertEqual(action, "preserve_reviewed_exclusion")

    def test_full_catalog_ledger_and_queue_share_one_rule_identity(self):
        root = Path(__file__).resolve().parents[1]
        ledger = json.loads(
            (root / "data" / "douyin_classification_ledger.json").read_text(
                encoding="utf-8"
            )
        )
        queue = json.loads(
            (root / "data" / "processing" / "douyin_queue.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(len(ledger["videos"]), 472)
        identity = ledger["classification_rules"]
        self.assertEqual(
            {item["classification_rules_hash"] for item in ledger["videos"]},
            {identity["sha256"]},
        )
        self.assertTrue(
            all(
                item["classification_rules_hash"] == identity["sha256"]
                and item["classification_rules_version"] == identity["version"]
                for item in queue["items"]
            )
        )
        product = next(
            item
            for item in ledger["videos"]
            if item["video_id"] == "7056596925721726220"
        )
        self.assertEqual(
            product["automatic_decision"], "待复核：教学夹带推广"
        )
        self.assertEqual(product["decision"], "保留：教学")
        self.assertEqual(product["migration_action"], "preserve_reviewed_keep")


if __name__ == "__main__":
    unittest.main()
