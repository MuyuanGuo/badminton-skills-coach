#!/usr/bin/env python3

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = ROOT / "scripts" / "build_runtime_store.py"
RUNTIME_PATH = (
    ROOT / "skills/liuhui-badminton-coach/scripts/runtime_store.py"
)
STORE_PATH = (
    ROOT / "skills/liuhui-badminton-coach/references/runtime-store.sqlite3"
)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RuntimeStoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.builder = load("runtime_store_builder_test", BUILDER_PATH)
        cls.runtime = load("runtime_store_reader_test", RUNTIME_PATH)

    def test_packaged_store_matches_canonical_inputs(self):
        result = self.builder.check_store(
            self.builder.KNOWLEDGE_PATH,
            self.builder.RETRIEVAL_INDEX_PATH,
            STORE_PATH,
        )
        self.assertEqual(result["status"], "ok")

    def test_build_is_logically_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            rebuilt = Path(directory) / "runtime-store.sqlite3"
            self.builder.build_store(
                self.builder.KNOWLEDGE_PATH,
                self.builder.RETRIEVAL_INDEX_PATH,
                rebuilt,
            )
            self.assertEqual(
                self.builder.logical_sha256(rebuilt),
                self.builder.logical_sha256(STORE_PATH),
            )

    def test_lazy_views_match_canonical_rows_without_full_materialization(self):
        store = self.runtime.RuntimeStore(STORE_PATH)
        try:
            knowledge = json.loads(
                self.builder.KNOWLEDGE_PATH.read_text(encoding="utf-8")
            )
            retrieval = json.loads(
                self.builder.RETRIEVAL_INDEX_PATH.read_text(encoding="utf-8")
            )
            self.assertEqual(len(store.knowledge_videos), len(knowledge["videos"]))
            self.assertEqual(len(store.retrieval_videos), len(retrieval["videos"]))
            self.assertEqual(store.knowledge_videos[0], knowledge["videos"][0])
            raw_payload = json.loads(
                store.connection.execute(
                    "SELECT payload FROM knowledge_videos WHERE position = 0"
                ).fetchone()[0]
            )
            self.assertNotIn("transcript_segments", raw_payload)
            self.assertNotIn("transcript_segments_json", raw_payload)
            self.assertEqual(store.retrieval_videos[-1], retrieval["videos"][-1])
            self.assertIsNone(store.knowledge_videos._decoded_rows)
            self.assertIsNone(store.transcript_payloads._decoded_rows)
            self.assertIsNone(store.retrieval_videos._decoded_rows)
        finally:
            store.close()
            store.close()


if __name__ == "__main__":
    unittest.main()
