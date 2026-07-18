#!/usr/bin/env python3
import hashlib
import json
import unittest

from build_manifest import (
    OUTPUT_PATH,
    SKILL_OUTPUT_PATH,
    build_manifest_payload,
    canonical_json_bytes,
    manifest_bytes,
)
from build_retrieval_index import (
    KNOWLEDGE_PATH,
    OUTPUT_PATH as RETRIEVAL_OUTPUT_PATH,
    RULES_PATH,
    TOPIC_INDEX_PATH,
    build_index,
)
from check_video_links import INDEX_PATH, deterministic_sample, syntax_check


class BuildReproducibilityTests(unittest.TestCase):
    def test_committed_manifest_rebuilds_byte_for_byte(self):
        expected = manifest_bytes()
        self.assertEqual(OUTPUT_PATH.read_bytes(), expected)
        self.assertEqual(SKILL_OUTPUT_PATH.read_bytes(), expected)

        payload = build_manifest_payload()
        build_id = payload.pop("build_id")
        self.assertEqual(
            build_id,
            hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
        )

    def test_manifest_hashes_every_declared_skill_artifact(self):
        payload = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(payload["skill_artifacts"]), 20)
        self.assertEqual(
            payload["link_integrity"]["canonical_syntax_invalid_video_ids"],
            [],
        )

    def test_committed_inputs_rebuild_retrieval_index_byte_for_byte(self):
        knowledge = json.loads(KNOWLEDGE_PATH.read_text(encoding="utf-8"))
        topic_index = json.loads(TOPIC_INDEX_PATH.read_text(encoding="utf-8"))
        rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
        rebuilt = build_index(knowledge, topic_index, rules)
        rebuilt_bytes = (
            json.dumps(rebuilt, ensure_ascii=False, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        self.assertEqual(RETRIEVAL_OUTPUT_PATH.read_bytes(), rebuilt_bytes)

    def test_link_sampling_is_deterministic_and_syntax_is_canonical(self):
        videos = json.loads(INDEX_PATH.read_text(encoding="utf-8"))["videos"]
        first = deterministic_sample(videos, 5)
        second = deterministic_sample(videos, 5)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 5)
        self.assertEqual(syntax_check(videos), [])


if __name__ == "__main__":
    unittest.main()
