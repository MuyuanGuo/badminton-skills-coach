#!/usr/bin/env python3
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from v3.canonical import atomic_write_json, canonical_json, sha256_text
from v3.ledger import ReviewLedger, dependency_for
from v3.state import is_automated_reviewer, resolve_transition
from v3.transcript import (
    build_candidate,
    candidate_event_payload,
    compile_formal_transcript,
    evidence_window,
    raw_registration_payload,
    verification_payload,
)


FIXED_TIME = "2026-08-31T12:00:00Z"


def append_current(
    ledger,
    entity_type,
    entity_id,
    action,
    payload,
    reviewer_id="fixture-reviewer",
    human_confirmation=True,
):
    head = ledger.head(entity_type, entity_id)
    return ledger.append_event(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        reviewer_id=reviewer_id,
        human_confirmation=human_confirmation,
        payload=payload,
        expected_revision=head["revision"] if head else 0,
        expected_base_fingerprint=head["content_fingerprint"] if head else "",
        occurred_at=FIXED_TIME,
    )


def fixture_candidate():
    return build_candidate(
        source_id="douyin:fixture-owner:1234567890123456789",
        platform="douyin",
        canonical_url="https://www.douyin.com/video/1234567890123456789",
        alternate_urls=["https://example.test/mirror/1234567890123456789"],
        title="合成纵切测试，不是正式教学证据",
        media_sha256=sha256_text("synthetic-media-bytes"),
        duration_ms=5000,
        raw_segments=[
            {"start_ms": 500, "end_ms": 1800, "text": "原始错词"},
            {"start_ms": 2300, "end_ms": 3900, "text": "第二句话"},
        ],
        asr_recipe={"engine": "fixture", "version": "1"},
        rule_version="fixture-rules-v1",
        suggestions={
            0: {
                "text": "候选纠正",
                "reason": "合成测试建议",
                "risk_flags": ["meaning_sensitive"],
            }
        },
    )


def verified_transcript(ledger):
    candidate = fixture_candidate()
    transcript_id = candidate["candidate_id"]
    append_current(
        ledger,
        "transcript",
        transcript_id,
        "register_raw",
        raw_registration_payload(candidate),
        "system:fixture-ingest",
        False,
    )
    append_current(
        ledger,
        "transcript",
        transcript_id,
        "create_candidate",
        candidate_event_payload(candidate),
        "system:fixture-candidate",
        False,
    )
    append_current(
        ledger,
        "transcript",
        transcript_id,
        "begin_review",
        candidate_event_payload(candidate),
    )
    segments = candidate["candidate"]["segments"]
    compiled = compile_formal_transcript(
        candidate,
        [
            {
                "segment_id": segments[0]["segment_id"],
                "decision": "human_corrected",
                "text": "人工核对后的第一句话",
            },
            {
                "segment_id": segments[1]["segment_id"],
                "decision": "keep_raw",
            },
        ],
        [
            {
                "start_ms": 4000,
                "end_ms": 4700,
                "text": "人工补录漏句",
                "reason": "完整播放时发现漏句",
            }
        ],
    )
    payload = verification_payload(
        compiled,
        {
            "review_basis": "local_media",
            "full_media_reviewed": True,
            "playback_coverage": [{"start_ms": 0, "end_ms": 5000}],
            "segments_complete": True,
            "missing_speech_resolved": True,
            "false_positive_speech_resolved": True,
            "timing_resolved": True,
            "no_usable_speech_confirmed": False,
        },
    )
    append_current(
        ledger,
        "transcript",
        transcript_id,
        "source_verify",
        payload,
    )
    return candidate, compiled, ledger.head("transcript", transcript_id)


def verified_event(ledger, candidate, compiled, transcript_head):
    formal = compiled["formal_projection"]
    selected_ids = [formal["segments"][0]["segment_id"]]
    event_content = {
        "source_id": candidate["source"]["source_id"],
        "source": candidate["source"],
        "start_ms": formal["segments"][0]["start_ms"],
        "end_ms": formal["segments"][0]["end_ms"],
        "modality": "language",
        "evidence_boundary": "仅验证合成测试中的第一句话",
        "formal_projection_sha256": formal["formal_projection_sha256"],
        "evidence_window": evidence_window(formal, selected_ids),
        "viewing_value": "验证证据窗口与正式转写绑定",
        "watch_focus": "观察测试文字是否一致",
    }
    payload = {
        "content": event_content,
        "dependencies": [dependency_for(transcript_head)],
    }
    append_current(
        ledger,
        "teaching_event",
        "event_fixture_1",
        "create_draft",
        payload,
        "system:fixture-candidate",
        False,
    )
    append_current(
        ledger,
        "teaching_event",
        "event_fixture_1",
        "source_verify",
        payload,
    )
    return ledger.head("teaching_event", "event_fixture_1")


def published_claim(ledger, event_head):
    content = {
        "topic": "synthetic_fixture",
        "symptoms": ["合成症状"],
        "applicability": ["仅用于自动化测试"],
        "mechanism": "合成机制，不是羽毛球教学判断",
        "correction_direction": "合成纠正方向",
        "exclusions": ["不得用于回答真实用户问题"],
        "confidence": "low",
        "training_method": "无",
        "support_event_ids": ["event_fixture_1"],
        "aliases": ["fixture-only"],
    }
    payload = {
        "content": content,
        "dependencies": [dependency_for(event_head)],
    }
    append_current(
        ledger,
        "semantic_claim",
        "claim_fixture_1",
        "create_draft",
        payload,
        "system:fixture-candidate",
        False,
    )
    for action in ("source_verify", "domain_approve", "publish"):
        append_current(
            ledger,
            "semantic_claim",
            "claim_fixture_1",
            action,
            payload,
        )
    return ledger.head("semantic_claim", "claim_fixture_1")


class CanonicalTests(unittest.TestCase):
    def test_canonical_json_and_atomic_write_are_deterministic(self):
        value = {"中文": [2, 1], "a": {"z": True}}
        self.assertEqual(canonical_json(value), canonical_json(json.loads(canonical_json(value))))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "value.json"
            atomic_write_json(path, value)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), value)
            self.assertTrue(path.read_text(encoding="utf-8").endswith("\n"))


class StateMachineTests(unittest.TestCase):
    def test_automated_reviewer_cannot_make_formal_decisions(self):
        self.assertTrue(is_automated_reviewer("system:codex"))
        with self.assertRaisesRegex(ValueError, "automated reviewer"):
            resolve_transition(
                "semantic_claim",
                "source_verified",
                "domain_approve",
                "Codex model",
                True,
            )

    def test_state_machine_rejects_skipped_approval(self):
        with self.assertRaisesRegex(ValueError, "invalid semantic_claim transition"):
            resolve_transition(
                "semantic_claim", "draft", "publish", "owner", True
            )


class TranscriptTests(unittest.TestCase):
    def test_all_raw_segments_and_complete_playback_are_independent_gates(self):
        candidate = fixture_candidate()
        with self.assertRaisesRegex(ValueError, "every raw ASR segment"):
            compile_formal_transcript(
                candidate,
                [
                    {
                        "segment_id": candidate["candidate"]["segments"][0][
                            "segment_id"
                        ],
                        "decision": "keep_raw",
                    }
                ],
            )
        with tempfile.TemporaryDirectory() as directory:
            with ReviewLedger(Path(directory) / "ledger.sqlite3") as ledger:
                candidate, compiled, _ = verified_transcript(ledger)
                transcript_head = ledger.head("transcript", candidate["candidate_id"])
                self.assertIsNotNone(transcript_head)
                assert transcript_head is not None
                self.assertEqual(
                    transcript_head["state"],
                    "source_verified",
                )
                content = compiled["formal_projection"]
                self.assertEqual(len(content["segments"]), 3)

    def test_incomplete_playback_cannot_source_verify_transcript(self):
        candidate = fixture_candidate()
        with tempfile.TemporaryDirectory() as directory:
            with ReviewLedger(Path(directory) / "ledger.sqlite3") as ledger:
                transcript_id = candidate["candidate_id"]
                append_current(
                    ledger,
                    "transcript",
                    transcript_id,
                    "register_raw",
                    raw_registration_payload(candidate),
                    "system:fixture",
                    False,
                )
                append_current(
                    ledger,
                    "transcript",
                    transcript_id,
                    "create_candidate",
                    candidate_event_payload(candidate),
                    "system:fixture",
                    False,
                )
                append_current(
                    ledger,
                    "transcript",
                    transcript_id,
                    "begin_review",
                    candidate_event_payload(candidate),
                )
                compiled = compile_formal_transcript(
                    candidate,
                    [
                        {"segment_id": segment["segment_id"], "decision": "keep_raw"}
                        for segment in candidate["candidate"]["segments"]
                    ],
                )
                payload = verification_payload(
                    compiled,
                    {
                        "review_basis": "local_media",
                        "full_media_reviewed": True,
                        "playback_coverage": [{"start_ms": 500, "end_ms": 5000}],
                        "segments_complete": True,
                        "missing_speech_resolved": True,
                        "false_positive_speech_resolved": True,
                        "timing_resolved": True,
                    },
                )
                with self.assertRaisesRegex(ValueError, "complete media"):
                    append_current(
                        ledger,
                        "transcript",
                        transcript_id,
                        "source_verify",
                        payload,
                    )


class LedgerTests(unittest.TestCase):
    def test_multimodal_event_records_visual_review_basis_and_timestamps(self):
        with tempfile.TemporaryDirectory() as directory:
            with ReviewLedger(Path(directory) / "ledger.sqlite3") as ledger:
                candidate, compiled, transcript_head = verified_transcript(ledger)
                formal = compiled["formal_projection"]
                selected_ids = [formal["segments"][0]["segment_id"]]
                window = evidence_window(formal, selected_ids)
                window["visual_observation"] = "合成画面观察"
                content = {
                    "source_id": candidate["source"]["source_id"],
                    "source": candidate["source"],
                    "start_ms": formal["segments"][0]["start_ms"],
                    "end_ms": formal["segments"][0]["end_ms"],
                    "modality": "multimodal",
                    "evidence_boundary": "仅验证视觉审核元数据",
                    "formal_projection_sha256": formal["formal_projection_sha256"],
                    "evidence_window": window,
                    "viewing_value": "验证来源页面视觉核对",
                    "watch_focus": "观察合成时间点",
                }
                payload = {
                    "content": content,
                    "dependencies": [dependency_for(transcript_head)],
                }
                append_current(
                    ledger,
                    "teaching_event",
                    "event_visual_fixture",
                    "create_draft",
                    payload,
                    "system:fixture-candidate",
                    False,
                )
                with self.assertRaisesRegex(ValueError, "visual review metadata"):
                    append_current(
                        ledger,
                        "teaching_event",
                        "event_visual_fixture",
                        "source_verify",
                        payload,
                    )
                content["evidence_window"]["visual_review"] = {
                    "review_basis": "source_page",
                    "timestamps_ms": [formal["segments"][0]["start_ms"]],
                    "source_url": "https://www.douyin.com/video/wrong-source",
                    "media_sha256": "",
                }
                with self.assertRaisesRegex(ValueError, "differs from the event source"):
                    append_current(
                        ledger,
                        "teaching_event",
                        "event_visual_fixture",
                        "source_verify",
                        payload,
                    )
                content["evidence_window"]["visual_review"]["source_url"] = candidate[
                    "source"
                ]["canonical_url"]
                append_current(
                    ledger,
                    "teaching_event",
                    "event_visual_fixture",
                    "source_verify",
                    payload,
                )
                self.assertEqual(
                    ledger.head("teaching_event", "event_visual_fixture")["state"],
                    "source_verified",
                )

    def test_vertical_chain_is_rebuildable_and_source_change_propagates_stale(self):
        with tempfile.TemporaryDirectory() as directory:
            with ReviewLedger(Path(directory) / "ledger.sqlite3") as ledger:
                candidate, compiled, transcript_head = verified_transcript(ledger)
                event_head = verified_event(
                    ledger, candidate, compiled, transcript_head
                )
                published_claim(ledger, event_head)
                report = ledger.verify_integrity()
                self.assertEqual(report["entities"], 3)
                claim_head = ledger.head("semantic_claim", "claim_fixture_1")
                self.assertIsNotNone(claim_head)
                assert claim_head is not None
                self.assertEqual(
                    claim_head["state"],
                    "published",
                )
                transcript_id = candidate["candidate_id"]
                append_current(
                    ledger,
                    "transcript",
                    transcript_id,
                    "invalidate",
                    {
                        "content": {
                            "reason": "synthetic source bytes changed",
                            "replacement_media_sha256": sha256_text("changed-media"),
                        },
                        "dependencies": [],
                    },
                    "system:source-watcher",
                    False,
                )
                invalidated = ledger.propagate_stale("upstream transcript changed")
                self.assertEqual(len(invalidated), 2)
                event_after = ledger.head("teaching_event", "event_fixture_1")
                claim_after = ledger.head("semantic_claim", "claim_fixture_1")
                self.assertIsNotNone(event_after)
                self.assertIsNotNone(claim_after)
                assert event_after is not None
                assert claim_after is not None
                self.assertEqual(
                    event_after["state"],
                    "stale",
                )
                self.assertEqual(
                    claim_after["state"],
                    "stale",
                )
                ledger.verify_integrity()

    def test_formal_events_are_append_only_and_drafts_are_recoverable(self):
        with tempfile.TemporaryDirectory() as directory:
            with ReviewLedger(Path(directory) / "ledger.sqlite3") as ledger:
                saved = ledger.save_draft(
                    "semantic_claim",
                    "claim_draft",
                    0,
                    {"mechanism": "unfinished"},
                    FIXED_TIME,
                )
                loaded = ledger.load_draft("semantic_claim", "claim_draft")
                self.assertIsNotNone(loaded)
                assert loaded is not None
                self.assertEqual(loaded["draft_fingerprint"], saved["draft_fingerprint"])
                append_current(
                    ledger,
                    "semantic_claim",
                    "claim_draft",
                    "create_draft",
                    {"content": {"topic": "draft"}, "dependencies": []},
                    "system:fixture",
                    False,
                )
                with self.assertRaises(sqlite3.IntegrityError):
                    ledger.connection.execute(
                        "UPDATE review_events SET note='tampered'"
                    )

    def test_optimistic_revision_rejects_stale_browser_submission(self):
        with tempfile.TemporaryDirectory() as directory:
            with ReviewLedger(Path(directory) / "ledger.sqlite3") as ledger:
                append_current(
                    ledger,
                    "semantic_claim",
                    "claim_concurrency",
                    "create_draft",
                    {"content": {"topic": "draft"}, "dependencies": []},
                    "system:fixture",
                    False,
                )
                with self.assertRaisesRegex(ValueError, "stale revision"):
                    ledger.append_event(
                        entity_type="semantic_claim",
                        entity_id="claim_concurrency",
                        action="source_verify",
                        reviewer_id="owner",
                        human_confirmation=True,
                        payload={"content": {}, "dependencies": []},
                        expected_revision=0,
                        expected_base_fingerprint="",
                        occurred_at=FIXED_TIME,
                    )


if __name__ == "__main__":
    unittest.main()
