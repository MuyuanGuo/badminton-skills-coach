#!/usr/bin/env python3
import unittest
from pathlib import Path
from typing import Any

from v3.canonical import read_json, sha256_json
from v3.inventory import validate_inventory_source_coverage, validate_source_inventory


ROOT = Path(__file__).resolve().parents[1]


class V3SourceInventoryTests(unittest.TestCase):
    inventory: dict[str, Any]

    @classmethod
    def setUpClass(cls):
        cls.inventory = read_json(ROOT / "data/v3/source-inventory.json")

    def test_all_current_answer_eligible_sources_are_explicitly_unreviewed(self):
        self.assertEqual(self.inventory["summary"]["answer_eligible_sources"], 959)
        self.assertEqual(self.inventory["summary"]["v3_formal_sources"], 0)
        self.assertEqual(len(self.inventory["sources"]), 959)
        self.assertEqual(
            {source["v3_formal_status"] for source in self.inventory["sources"]},
            {"missing"},
        )

    def test_inventory_is_sanitized_deterministic_and_checked_in(self):
        self.assertEqual(
            validate_source_inventory(self.inventory),
            {"sources": 959, "formal_sources": 0},
        )
        validate_inventory_source_coverage(
            self.inventory,
            ROOT / "data/knowledge/douyin_knowledge_base.json",
            ROOT / "config/douyin_source.json",
        )
        body = {
            key: value
            for key, value in self.inventory.items()
            if key != "inventory_fingerprint"
        }
        self.assertEqual(self.inventory["inventory_fingerprint"], sha256_json(body))
        self.assertEqual(
            read_json(ROOT / "data/v3/source-inventory.json"), self.inventory
        )
        serialized = str(self.inventory)
        self.assertNotIn("data/transcripts", serialized)
        self.assertNotIn("data/raw_videos", serialized)
        self.assertNotIn("transcript_segments", serialized)


if __name__ == "__main__":
    unittest.main()
