#!/usr/bin/env python3
import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from test_v3_evidence_core import (
    append_current,
    published_claim,
    verified_event,
    verified_transcript,
)
from v3.canonical import sha256_text
from v3.audit import audit_public_v3_tree, audit_shadow_artifacts
from v3.build import build_shadow_artifacts
from v3.canonical import read_json
from v3.ledger import ReviewLedger
from v3.publication import (
    assert_no_private_leaks,
    empty_publication,
    export_publication,
    validate_publication,
    write_publication,
)
from v3.runtime import build_runtime, runtime_metadata, shadow_answer_packet


ROOT = Path(__file__).resolve().parents[1]


class PublicationContractTests(unittest.TestCase):
    def test_empty_publication_builds_an_empty_readonly_shadow_runtime(self):
        publication = empty_publication()
        self.assertEqual(
            validate_publication(publication),
            {"sources": 0, "events": 0, "claims": 0},
        )
        with tempfile.TemporaryDirectory() as directory:
            store = Path(directory) / "shadow.sqlite3"
            manifest = build_runtime(publication, store)
            self.assertEqual(manifest["row_counts"]["claims"], 0)
            packet = shadow_answer_packet(store, "正手后场")
            self.assertEqual(packet["claims"], [])
            self.assertTrue(packet["evidence_gap"])
            readonly = sqlite3.connect(f"file:{store}?mode=ro", uri=True)
            try:
                with self.assertRaises(sqlite3.OperationalError):
                    readonly.execute("DELETE FROM metadata")
            finally:
                readonly.close()

    def test_checked_in_artifacts_match_the_deterministic_builder(self):
        checked_in = read_json(ROOT / "data/v3/publication.json")
        report = validate_publication(checked_in)
        self.assertGreaterEqual(report["claims"], 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = build_shadow_artifacts(
                ROOT / "data/v3/publication.json",
                root / "shadow.sqlite3",
                root / "manifest.json",
            )
            self.assertEqual(manifest, read_json(ROOT / "data/v3/build-manifest.json"))
            audit = audit_shadow_artifacts(
                ROOT / "data/v3/publication.json",
                root / "manifest.json",
                root / "shadow.sqlite3",
            )
            self.assertEqual(audit["runtime"], "valid")
        self.assertEqual(audit_public_v3_tree(ROOT)["private_leaks"], 0)

    def test_first_approved_claim_handles_a_paraphrased_user_query(self):
        publication = read_json(ROOT / "data/v3/publication.json")
        with tempfile.TemporaryDirectory() as directory:
            store = Path(directory) / "shadow.sqlite3"
            build_runtime(publication, store)
            packet = shadow_answer_packet(
                store,
                "正手后场被动球时，为什么球拍追着球走，来不及架拍和发力？",
            )
        self.assertEqual(
            packet["claims"][0]["claim_id"],
            "claim_86db9db46f65ac031864654d",
        )
        self.assertEqual(packet["claims"][0]["evidence_labels"], ["V1"])
        self.assertEqual(packet["evidence"][0]["label"], "V1")
        self.assertEqual(packet["evidence_gap"], "")


class SanitizedPublicationTests(unittest.TestCase):
    def build_fixture_publication(self, ledger):
        candidate, compiled, transcript_head = verified_transcript(ledger)
        event_head = verified_event(ledger, candidate, compiled, transcript_head)
        published_claim(ledger, event_head)
        return export_publication(ledger)

    def test_export_is_deterministic_minimal_and_queryable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with ReviewLedger(root / "ledger.sqlite3") as ledger:
                publication = self.build_fixture_publication(ledger)
                self.assertEqual(publication, export_publication(ledger))
            report = validate_publication(publication)
            self.assertEqual(report, {"sources": 1, "events": 1, "claims": 1})
            serialized = json.dumps(publication, ensure_ascii=False)
            self.assertNotIn("人工核对后的第一句话 第二句话", serialized)
            self.assertNotIn("fixture-reviewer", serialized)
            self.assertNotIn("raw_asr_sha256", serialized)
            first_store = root / "shadow-a.sqlite3"
            second_store = root / "shadow-b.sqlite3"
            first = build_runtime(publication, first_store)
            second = build_runtime(publication, second_store)
            self.assertEqual(first["runtime_fingerprint"], second["runtime_fingerprint"])
            self.assertEqual(
                runtime_metadata(first_store)["runtime_fingerprint"],
                first["runtime_fingerprint"],
            )
            packet = shadow_answer_packet(first_store, "fixture-only")
            self.assertEqual(packet["runtime_version"], "v3-shadow")
            self.assertEqual(packet["claims"][0]["claim_id"], "claim_fixture_1")
            self.assertEqual(packet["claims"][0]["evidence_labels"], ["V1"])
            self.assertEqual(packet["evidence"][0]["label"], "V1")

            paraphrase = shadow_answer_packet(
                first_store,
                "我遇到合成症状但不知道怎么办",
            )
            self.assertEqual(paraphrase["claims"][0]["claim_id"], "claim_fixture_1")

            unrelated = shadow_answer_packet(first_store, "双打发球站位怎么选")
            self.assertEqual(unrelated["claims"], [])
            self.assertTrue(unrelated["evidence_gap"])

    def test_approved_projection_is_validated_and_written_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "publication.json"
            with ReviewLedger(root / "ledger.sqlite3") as ledger:
                expected = self.build_fixture_publication(ledger)
                report = write_publication(ledger, output)
            self.assertEqual(read_json(output), expected)
            self.assertEqual(report["claims"], 1)
            self.assertEqual(report["events"], 1)
            self.assertEqual(report["sources"], 1)
            self.assertEqual(
                report["publication_fingerprint"],
                expected["publication_fingerprint"],
            )

    def test_tampered_or_private_publication_fails_closed(self):
        publication = empty_publication()
        tampered = copy.deepcopy(publication)
        tampered["scope"]["topics"] = ["changed-after-fingerprint"]
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            validate_publication(tampered)
        with self.assertRaisesRegex(ValueError, "private data leak"):
            assert_no_private_leaks({"media_path": "/Users/example/private.mp4"})

    def test_source_change_removes_stale_claim_from_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            with ReviewLedger(Path(directory) / "ledger.sqlite3") as ledger:
                publication = self.build_fixture_publication(ledger)
                self.assertEqual(len(publication["semantic_claims"]), 1)
                transcript_head = ledger.heads("transcript")[0]
                append_current(
                    ledger,
                    "transcript",
                    transcript_head["entity_id"],
                    "invalidate",
                    {
                        "content": {
                            "reason": "source bytes changed",
                            "replacement_media_sha256": sha256_text("replacement"),
                        },
                        "dependencies": [],
                    },
                    "system:source-watcher",
                    False,
                )
                ledger.propagate_stale("upstream transcript changed")
                after = export_publication(ledger)
                self.assertEqual(after["semantic_claims"], [])
                self.assertEqual(after["teaching_events"], [])
                self.assertEqual(after["sources"], [])


if __name__ == "__main__":
    unittest.main()
