#!/usr/bin/env python3
import json
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from v3.canonical import atomic_write_json, sha256_text
from v3.ledger import ReviewLedger
from v3.review_server import ReviewApplication, create_server
from v3.seed import seed_vertical_slice
from v3.transcript import (
    build_candidate,
    candidate_event_payload,
    raw_registration_payload,
)


ROOT = Path(__file__).resolve().parents[1]
UI_ROOT = ROOT / "review-ui/v3"


def make_application(root, media_suffix=".mp4"):
    media = root / f"media/source{media_suffix}"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"synthetic-media-bytes")
    candidate = build_candidate(
        source_id="douyin:fixture-owner:123",
        platform="douyin",
        canonical_url="https://www.douyin.com/video/123",
        alternate_urls=[],
        title="Review workbench fixture",
        media_sha256=sha256_text("synthetic-media-bytes"),
        duration_ms=3000,
        raw_segments=[{"start_ms": 100, "end_ms": 2200, "text": "测试转写"}],
        asr_recipe={"engine": "fixture"},
        rule_version="fixture-v1",
    )
    candidate_path = root / "candidate.json"
    ledger_path = root / "review/ledger.sqlite3"
    atomic_write_json(candidate_path, candidate)
    with ReviewLedger(ledger_path) as ledger:
        first = ledger.append_event(
            entity_type="transcript",
            entity_id=candidate["candidate_id"],
            action="register_raw",
            reviewer_id="system:fixture",
            human_confirmation=False,
            payload=raw_registration_payload(candidate),
            expected_revision=0,
            expected_base_fingerprint="",
            occurred_at="2026-08-31T12:00:00Z",
        )
        ledger.append_event(
            entity_type="transcript",
            entity_id=candidate["candidate_id"],
            action="create_candidate",
            reviewer_id="system:fixture",
            human_confirmation=False,
            payload=candidate_event_payload(candidate),
            expected_revision=1,
            expected_base_fingerprint=first["content_fingerprint"],
            occurred_at="2026-08-31T12:00:01Z",
        )
    return ReviewApplication(
        candidate_path=candidate_path,
        ledger_path=ledger_path,
        media_path=media,
        media_root=media.parent,
    )


class ReviewApplicationTests(unittest.TestCase):
    def test_real_state_starts_candidate_only_and_draft_round_trips(self):
        with tempfile.TemporaryDirectory() as directory:
            application = make_application(Path(directory))
            summary = application.summary()
            self.assertEqual(summary["candidate"]["evidence_status"], "candidate_only")
            self.assertEqual(summary["media_review"]["kind"], "video")
            self.assertEqual(summary["heads"][0]["state"], "candidate")
            self.assertEqual(
                [event["to_state"] for event in summary["events"]],
                ["raw_available", "candidate"],
            )
            saved = application.save_draft(
                {
                    "entity_type": "transcript",
                    "entity_id": summary["transcript_entity_id"],
                    "base_revision": 2,
                    "draft": {"decisions": [], "playback_coverage": []},
                }
            )
            self.assertEqual(saved["base_revision"], 2)
            self.assertIsNotNone(application.summary()["transcript_draft"])

    def test_audio_only_media_defaults_visual_review_to_source_page(self):
        with tempfile.TemporaryDirectory() as directory:
            application = make_application(Path(directory), media_suffix=".m4a")
            media_review = application.summary()["media_review"]
            self.assertEqual(media_review["kind"], "audio_only")
            self.assertEqual(media_review["visual_basis_default"], "source_page")

    def test_automated_identity_cannot_begin_human_review(self):
        with tempfile.TemporaryDirectory() as directory:
            application = make_application(Path(directory))
            current = application.summary()["heads"][0]
            with self.assertRaisesRegex(ValueError, "automated reviewer"):
                application.begin_transcript_review(
                    {
                        "reviewer_id": "Codex model",
                        "human_confirmation": True,
                        "expected_revision": current["revision"],
                        "expected_base_fingerprint": current["content_fingerprint"],
                    }
                )

    def test_shared_ledger_does_not_leak_another_candidates_event_into_session(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_application = make_application(root)
            first_head = first_application.summary()["heads"][0]
            first_application.begin_transcript_review(
                {
                    "reviewer_id": "fixture-owner",
                    "human_confirmation": True,
                    "expected_revision": first_head["revision"],
                    "expected_base_fingerprint": first_head["content_fingerprint"],
                }
            )
            candidate = first_application.candidate
            segment = candidate["candidate"]["segments"][0]
            in_review = first_application.summary()["heads"][0]
            first_application.verify_transcript(
                {
                    "reviewer_id": "fixture-owner",
                    "human_confirmation": True,
                    "expected_revision": in_review["revision"],
                    "expected_base_fingerprint": in_review["content_fingerprint"],
                    "decisions": [
                        {
                            "segment_id": segment["segment_id"],
                            "decision": "keep_raw",
                            "start_ms": segment["start_ms"],
                            "end_ms": segment["end_ms"],
                        }
                    ],
                    "insertions": [],
                    "attestation": {
                        "review_basis": "local_media",
                        "full_media_reviewed": True,
                        "playback_coverage": [{"start_ms": 0, "end_ms": 3000}],
                        "segments_complete": True,
                        "missing_speech_resolved": True,
                        "false_positive_speech_resolved": True,
                        "timing_resolved": True,
                        "no_usable_speech_confirmed": False,
                    },
                }
            )
            formal = first_application.summary()["heads"][0]["payload"]["content"]
            first_event = first_application.transition_entity(
                {
                    "entity_type": "teaching_event",
                    "entity_id": "",
                    "action": "create_draft",
                    "content": {
                        "start_ms": 100,
                        "end_ms": 2200,
                        "modality": "language",
                        "segment_ids": [formal["segments"][0]["segment_id"]],
                        "evidence_boundary": "只支持第一条测试转写。",
                        "visual_observation": "",
                        "viewing_value": "用于测试候选隔离。",
                        "watch_focus": "只看第一条测试片段。",
                    },
                    "expected_revision": 0,
                    "expected_base_fingerprint": "",
                }
            )

            second_media = root / "media/second.mp4"
            second_media.write_bytes(b"second-synthetic-media")
            second_candidate = build_candidate(
                source_id="douyin:fixture-owner:456",
                platform="douyin",
                canonical_url="https://www.douyin.com/video/456",
                alternate_urls=[],
                title="Second review workbench fixture",
                media_sha256=sha256_text("second-synthetic-media"),
                duration_ms=4000,
                raw_segments=[
                    {"start_ms": 200, "end_ms": 2600, "text": "第二条测试转写"}
                ],
                asr_recipe={"engine": "fixture"},
                rule_version="fixture-v1",
            )
            second_candidate_path = root / "second-candidate.json"
            atomic_write_json(second_candidate_path, second_candidate)
            with ReviewLedger(first_application.ledger_path) as ledger:
                registered = ledger.append_event(
                    entity_type="transcript",
                    entity_id=second_candidate["candidate_id"],
                    action="register_raw",
                    reviewer_id="system:fixture",
                    human_confirmation=False,
                    payload=raw_registration_payload(second_candidate),
                    expected_revision=0,
                    expected_base_fingerprint="",
                    occurred_at="2026-08-31T12:01:00Z",
                )
                ledger.append_event(
                    entity_type="transcript",
                    entity_id=second_candidate["candidate_id"],
                    action="create_candidate",
                    reviewer_id="system:fixture",
                    human_confirmation=False,
                    payload=candidate_event_payload(second_candidate),
                    expected_revision=1,
                    expected_base_fingerprint=registered["content_fingerprint"],
                    occurred_at="2026-08-31T12:01:01Z",
                )
            second_application = ReviewApplication(
                candidate_path=second_candidate_path,
                ledger_path=first_application.ledger_path,
                media_path=second_media,
                media_root=second_media.parent,
            )
            second_summary = second_application.summary()
            self.assertEqual(
                [
                    (head["entity_type"], head["entity_id"])
                    for head in second_summary["heads"]
                ],
                [("transcript", second_candidate["candidate_id"])],
            )
            self.assertNotIn(
                first_event["head"]["entity_id"],
                {event["entity_id"] for event in second_summary["events"]},
            )


class VerticalSliceSeedTests(unittest.TestCase):
    def test_seed_is_idempotent_and_never_creates_formal_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            knowledge = root / "knowledge.json"
            source = root / "source.json"
            transcript = root / "transcript.json"
            media = root / "media.mp4"
            knowledge.write_text(
                json.dumps(
                    {
                        "videos": [
                            {
                                "video_id": "123",
                                "canonical_url": "https://www.douyin.com/video/123",
                                "title": "Fixture source",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            source.write_text(json.dumps({"profile_id": "fixture-owner"}), encoding="utf-8")
            transcript.write_text(
                json.dumps(
                    {
                        "video_id": "123",
                        "duration": 2.0,
                        "model": "fixture",
                        "language": "zh",
                        "segments": [{"start": 0.1, "end": 1.5, "text": "候选"}],
                    }
                ),
                encoding="utf-8",
            )
            media.write_bytes(b"fixture-media")
            first = seed_vertical_slice(
                video_id="123",
                knowledge_path=knowledge,
                source_config_path=source,
                transcript_path=transcript,
                media_path=media,
                private_root=root / ".local/v3",
            )
            second = seed_vertical_slice(
                video_id="123",
                knowledge_path=knowledge,
                source_config_path=source,
                transcript_path=transcript,
                media_path=media,
                private_root=root / ".local/v3",
            )
            self.assertEqual(first["candidate_id"], second["candidate_id"])
            self.assertEqual(second["formal_approvals_created"], 0)
            self.assertEqual(second["private_suggestions_loaded"], 0)
            with ReviewLedger(Path(second["ledger_path"])) as ledger:
                self.assertEqual(ledger.heads("transcript")[0]["state"], "candidate")
                self.assertEqual(len(ledger.events()), 2)

    def test_private_suggestions_are_optional_and_hash_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            knowledge = root / "knowledge.json"
            source = root / "source.json"
            transcript = root / "transcript.json"
            media = root / "media.mp4"
            suggestions = root / "suggestions.json"
            knowledge.write_text(
                json.dumps(
                    {
                        "videos": [
                            {
                                "video_id": "123",
                                "canonical_url": "https://www.douyin.com/video/123",
                                "title": "Fixture source",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            source.write_text(json.dumps({"profile_id": "fixture-owner"}), encoding="utf-8")
            transcript.write_text(
                json.dumps(
                    {
                        "video_id": "123",
                        "duration": 2.0,
                        "model": "fixture",
                        "language": "zh",
                        "segments": [{"start": 0.1, "end": 1.5, "text": "候选"}],
                    }
                ),
                encoding="utf-8",
            )
            media.write_bytes(b"fixture-media")
            payload: dict[str, Any] = {
                "schema_version": "3.0.0-m1",
                "kind": "private-candidate-suggestions",
                "video_id": "123",
                "suggestions": [
                    {
                        "segment_index": 0,
                        "raw_text_sha256": sha256_text("候选"),
                        "suggested_text": "人工候选",
                        "reason": "fixture only",
                        "risk_flags": ["meaning_sensitive"],
                    }
                ],
            }
            suggestions.write_text(json.dumps(payload), encoding="utf-8")
            result = seed_vertical_slice(
                video_id="123",
                knowledge_path=knowledge,
                source_config_path=source,
                transcript_path=transcript,
                media_path=media,
                private_root=root / ".local/v3",
                suggestions_path=suggestions,
            )
            self.assertEqual(result["private_suggestions_loaded"], 1)
            candidate = json.loads(Path(result["candidate_path"]).read_text(encoding="utf-8"))
            self.assertEqual(candidate["candidate"]["segments"][0]["suggested_text"], "人工候选")

            payload["suggestions"][0]["raw_text_sha256"] = sha256_text("other text")
            suggestions.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "different raw text"):
                seed_vertical_slice(
                    video_id="123",
                    knowledge_path=knowledge,
                    source_config_path=source,
                    transcript_path=transcript,
                    media_path=media,
                    private_root=root / ".local/v3-other",
                    suggestions_path=suggestions,
                )

    def test_bilibili_candidate_preserves_identity_and_alternate_url(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            knowledge = root / "knowledge.json"
            source = root / "source.json"
            transcript = root / "transcript.json"
            media = root / "media.m4a"
            knowledge.write_text(
                json.dumps(
                    {
                        "videos": [
                            {
                                "video_id": "bilibili:BVfixture",
                                "source_video_id": "BVfixture",
                                "source_type": "bilibili_video",
                                "uploader_profile_id": "fixture-uploader",
                                "canonical_url": "https://www.bilibili.com/video/BVfixture",
                                "title": "Fixture source",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            source.write_text(
                json.dumps({"profile_id": "fixture-owner"}), encoding="utf-8"
            )
            transcript.write_text(
                json.dumps(
                    {
                        "video_id": "BVfixture",
                        "duration": 2.0,
                        "model": "fixture",
                        "language": "zh",
                        "segments": [{"start": 0.1, "end": 1.5, "text": "候选"}],
                    }
                ),
                encoding="utf-8",
            )
            media.write_bytes(b"fixture-media")
            result = seed_vertical_slice(
                video_id="bilibili:BVfixture",
                knowledge_path=knowledge,
                source_config_path=source,
                transcript_path=transcript,
                media_path=media,
                private_root=root / ".local/v3",
                alternate_urls=["https://example.test/mirror/BVfixture"],
            )
            candidate = json.loads(
                Path(result["candidate_path"]).read_text(encoding="utf-8")
            )
            self.assertEqual(candidate["source"]["platform"], "bilibili")
            self.assertEqual(
                candidate["source"]["source_id"],
                "bilibili:fixture-uploader:BVfixture",
            )
            self.assertEqual(
                candidate["source"]["alternate_urls"],
                ["https://example.test/mirror/BVfixture"],
            )
            self.assertTrue(Path(result["candidate_session_path"]).is_file())


class ReviewHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.application = make_application(Path(self.temporary.name))
        self.server = create_server(self.application, "127.0.0.1", 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.temporary.cleanup()

    def request(self, path, *, token=True, body=None, origin=True, csrf=True, headers=None):
        values = dict(headers or {})
        if token:
            values["X-Review-Token"] = self.application.session_token
        if body is not None:
            values["Content-Type"] = "application/json"
            if origin:
                values["Origin"] = self.origin
            if csrf:
                values["X-CSRF-Token"] = self.application.csrf_token
        request = Request(
            self.origin + path,
            data=None if body is None else json.dumps(body).encode("utf-8"),
            headers=values,
            method="GET" if body is None else "POST",
        )
        return urlopen(request, timeout=3)

    def test_static_assets_have_security_headers_and_api_requires_token(self):
        with self.request("/", token=False) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
            self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        with self.assertRaises(HTTPError) as context:
            self.request("/api/session", token=False)
        self.assertEqual(context.exception.code, 403)
        with self.request("/api/session") as response:
            payload = json.load(response)
            self.assertEqual(payload["candidate"]["evidence_status"], "candidate_only")

    def test_post_requires_same_origin_and_csrf_then_recovers_draft(self):
        entity_id = self.application.transcript_id
        draft = {
            "entity_type": "transcript",
            "entity_id": entity_id,
            "base_revision": 2,
            "draft": {"decisions": [{"segment_id": "unfinished"}]},
        }
        with self.assertRaises(HTTPError) as context:
            self.request("/api/drafts", body=draft, origin=False)
        self.assertEqual(context.exception.code, 403)
        with self.assertRaises(HTTPError) as context:
            self.request("/api/drafts", body=draft, csrf=False)
        self.assertEqual(context.exception.code, 403)
        with self.request("/api/drafts", body=draft) as response:
            self.assertEqual(json.load(response)["base_revision"], 2)
        with self.request("/api/session") as response:
            self.assertEqual(
                json.load(response)["transcript_draft"]["draft"]["decisions"][0][
                    "segment_id"
                ],
                "unfinished",
            )

    def test_media_supports_authenticated_byte_ranges(self):
        path = f"/api/media?token={self.application.session_token}"
        with self.request(path, token=False, headers={"Range": "bytes=0-8"}) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.read(), b"synthetic")
            self.assertEqual(response.headers["Accept-Ranges"], "bytes")


class ReviewUIContractTests(unittest.TestCase):
    html: str
    css: str
    javascript: str

    @classmethod
    def setUpClass(cls):
        cls.html = (UI_ROOT / "index.html").read_text(encoding="utf-8")
        cls.css = (UI_ROOT / "styles.css").read_text(encoding="utf-8")
        cls.javascript = (UI_ROOT / "app.js").read_text(encoding="utf-8")

    def test_ui_exposes_the_evidence_spine_and_separate_human_gates(self):
        for label in (
            "逐段已校正",
            "完整播放确认",
            "来源事实已确认",
            "领域主张已批准",
            "可进入 shadow",
        ):
            self.assertIn(label, self.html)
        self.assertIn("机器栏只是一种建议", self.html)
        self.assertIn("这只批准来源文字事实", self.javascript)
        self.assertIn("这不会批准羽毛球归纳本身", self.javascript)
        self.assertIn("自动系统不能替你执行", self.javascript)

    def test_ui_is_local_self_contained_accessible_and_recovers_drafts(self):
        self.assertNotIn("https://", self.html)
        self.assertNotIn("http://", self.html)
        self.assertIn(":focus-visible", self.css)
        self.assertIn("prefers-reduced-motion", self.css)
        self.assertIn('aria-live="polite"', self.html)
        self.assertIn("/api/drafts", self.javascript)
        self.assertIn("transcript_draft", self.javascript)
        self.assertIn("X-CSRF-Token", self.javascript)
        self.assertIn("history.replaceState", self.javascript)
        self.assertIn("sessionStorage", self.javascript)

    def test_ui_scopes_events_and_claims_to_the_active_transcript(self):
        self.assertIn("function eventHeads()", self.javascript)
        self.assertIn('dependencyKeys(item, "transcript")', self.javascript)
        self.assertIn("function claimHeads()", self.javascript)
        self.assertNotIn(
            'return head("teaching_event", selected) || head("teaching_event")',
            self.javascript,
        )

    def test_ui_records_visual_review_basis_and_timestamps(self):
        for identifier in (
            "event-visual-basis",
            "event-visual-timestamps",
            "event-visual-basis-note",
        ):
            self.assertIn(identifier, self.html)
        self.assertIn("visual_review_basis", self.javascript)
        self.assertIn("visual_timestamps_ms", self.javascript)
        self.assertIn("collectVisualTimestamps", self.javascript)

    def test_new_teaching_event_defaults_to_the_complete_formal_transcript(self):
        self.assertIn("本事件引用的正式转写（默认全选）", self.html)
        self.assertIn("event-segment-note", self.html)
        self.assertIn("function selectAllEventSegments()", self.javascript)
        self.assertIn("else {\n    selectAllEventSegments();", self.javascript)


if __name__ == "__main__":
    unittest.main()
