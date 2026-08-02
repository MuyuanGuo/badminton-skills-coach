#!/usr/bin/env python3
import importlib.util
import json
import tempfile
import unittest
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load(name):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BilibiliPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pipeline = load("bilibili_pipeline")
        cls.updates = load("check_bilibili_updates")
        cls.rules = cls.pipeline.load_rules()

    def classify(self, title, **extra):
        bvid = extra.pop("bvid", "BV16G411y7Rs")
        item = self.pipeline.normalize_video({
            "bvid": bvid,
            "title": title,
            **extra,
        })
        return self.pipeline.classify_video(item, self.rules)

    def membership(self, name, list_id):
        return {
            "name": name,
            "url": (
                "https://space.bilibili.com/1423436652/"
                f"lists/{list_id}?type=season"
            ),
        }

    def test_explicit_liuhui_teaching_is_candidate_but_not_admitted(self):
        item = self.classify("刘辉教练教你反手万能握拍")
        self.assertEqual(item["decision"], "candidate_liuhui_teaching")
        self.assertEqual(item["origin_status"], "origin_verification_pending")
        self.assertFalse(item["knowledge_admission_eligible"])
        self.assertFalse(self.pipeline.may_enter_knowledge_base(item))

    def test_uncollected_teaching_without_origin_signal_needs_confirmation(self):
        item = self.classify("反手高远球提高稳定性的技巧")
        self.assertEqual(item["decision"], "review_pending")
        self.assertEqual(
            item["collection_policy"]["action"],
            "needs_confirmation",
        )
        self.assertFalse(item["processing_state"]["terminal"])

    def test_seo_description_cannot_contaminate_origin_decision(self):
        item = self.classify(
            "反手高远球提高稳定性的技巧",
            description="直播教学切片已获刘辉教练授权；相关视频：刘辉教练教你",
        )
        self.assertEqual(item["decision"], "review_pending")

    def test_uncollected_non_teaching_and_medical_remain_pending(self):
        self.assertEqual(
            self.classify("直播花絮 第45集")["decision"],
            "review_pending",
        )
        self.assertEqual(
            self.classify("为什么打完羽毛球后膝盖疼？刘辉教练告诉你")["decision"],
            "review_pending",
        )

    def test_required_collection_overrides_missing_origin_and_title_signals(self):
        item = self.classify(
            "反手高远球提高稳定性的技巧",
            collection_memberships=[
                self.membership("合集·反手发力", "1815203"),
            ],
        )
        self.assertEqual(item["decision"], "required_transcription_policy")
        self.assertEqual(item["collection_policy"]["basis"], "collection")
        self.assertTrue(item["transcription_required"])
        self.assertEqual(item["processing_state"]["stage"], "metadata_pending")
        self.assertFalse(item["processing_state"]["terminal"])

    def test_excluded_collection_overrides_liuhui_teaching_title(self):
        item = self.classify(
            "刘辉教练教你反手万能握拍",
            collection_memberships=[
                self.membership("合集·刘辉教练直播花絮", "5307613"),
            ],
        )
        self.assertEqual(item["decision"], "excluded_transcription_policy")
        self.assertFalse(item["transcription_required"])
        self.assertTrue(item["processing_state"]["terminal"])

    def test_manual_video_policy_applies_after_user_confirmation(self):
        included = self.classify(
            "羽毛球专项力量怎么练？",
            bvid="BV1Gx4y1Q7Xb",
        )
        excluded = self.classify(
            "李宁雷霆100深度评测",
            bvid="BV1DM4y177i5",
        )
        self.assertEqual(
            included["decision"],
            "required_transcription_policy",
        )
        self.assertEqual(
            included["collection_policy"]["basis"],
            "video_override",
        )
        self.assertTrue(included["transcription_required"])
        self.assertEqual(
            excluded["decision"],
            "excluded_transcription_policy",
        )
        self.assertEqual(
            excluded["collection_policy"]["basis"],
            "video_override",
        )
        self.assertTrue(excluded["processing_state"]["terminal"])

    def test_collection_policy_admission_keeps_origin_status_distinct(self):
        item = self.classify(
            "反手高远球提高稳定性的技巧",
            collection_memberships=[
                self.membership("合集·反手发力", "1815203"),
            ],
        )
        item["origin_verification"] = {
            "status": "verified_collection_policy",
            "methods": [
                "verified_uploader_profile",
                "user_confirmed_collection_policy",
            ],
            "verified_at": "2026-07-28T00:00:00+00:00",
            "signals": {
                "video_id_matches": True,
                "uploader_profile_matches": True,
                "canonical_url_matches": True,
                "duration_valid": True,
            },
        }
        self.assertTrue(self.pipeline.may_enter_knowledge_base(item))
        self.assertNotEqual(
            item["origin_verification"]["status"],
            "verified_liuhui_clip",
        )

    def test_verified_origin_requires_method_and_timestamp(self):
        item = self.classify("刘辉教练教你反手万能握拍")
        item["origin_verification"] = {
            "status": "verified_liuhui_clip",
            "methods": ["publisher_origin_annotation"],
            "verified_at": "2026-07-26T00:00:00+00:00",
            "signals": {
                "uploader_profile_matches": True,
                "publisher_text_names_liuhui": True,
                "dedicated_origin_tag": True,
            },
        }
        self.assertTrue(self.pipeline.may_enter_knowledge_base(item))

    def test_snapshot_validation_checks_profile_freshness_and_coverage(self):
        now = datetime(2026, 7, 26, tzinfo=timezone.utc)
        source = {
            "profile_id": "1423436652",
            "snapshot": {"max_age_hours": 24, "min_observed_links": 2},
        }
        payload = {
            "profile_id": "1423436652",
            "profile_url": "https://space.bilibili.com/1423436652",
            "collected_at": (now - timedelta(hours=1)).isoformat(),
            "collected_unique_links": 2,
            "videos": [
                {"bvid": "BV16G411y7Rs"},
                {"bvid": "BV1aw411179M"},
            ],
        }
        result = self.updates.validate_snapshot(payload, source, now)
        self.assertEqual(result["observed"], 2)
        payload["profile_id"] = "other"
        with self.assertRaisesRegex(ValueError, "configured"):
            self.updates.validate_snapshot(payload, source, now)

    def test_full_snapshot_requires_contiguous_hashed_pages_and_exact_total(self):
        now = datetime(2026, 7, 26, tzinfo=timezone.utc)
        source = {
            "profile_id": "1423436652",
            "snapshot": {"max_age_hours": 24, "min_observed_links": 2},
        }
        payload = {
            "profile_id": "1423436652",
            "profile_url": "https://space.bilibili.com/1423436652",
            "collected_at": (now - timedelta(hours=1)).isoformat(),
            "collected_unique_links": 2,
            "full_profile_archive": True,
            "profile_reported_video_count": 2,
            "profile_pages_complete": True,
            "profile_pages": [
                {
                    "page": 1,
                    "count": 2,
                    "first_bvid": "BV16G411y7Rs",
                    "last_bvid": "BV1aw411179M",
                    "bvid_sha256": "a" * 64,
                    "sorted_bvid_sha256": self.updates.page_bvid_content_sha256(
                        ["BV16G411y7Rs", "BV1aw411179M"]
                    ),
                }
            ],
            "coverage": {
                "profile_pages": 1,
                "profile_reported_video_count": 2,
                "profile_collected_count": 2,
                "profile_unique_videos": 2,
            },
            "videos": [
                {"bvid": "BV16G411y7Rs", "profile_page": 1},
                {"bvid": "BV1aw411179M", "profile_page": 1},
            ],
        }
        result = self.updates.validate_snapshot(payload, source, now)
        self.assertTrue(result["full_profile_archive"])
        payload["profile_pages"][0]["sorted_bvid_sha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "content hash"):
            self.updates.validate_snapshot(payload, source, now)
        payload["profile_pages"][0][
            "sorted_bvid_sha256"
        ] = self.updates.page_bvid_content_sha256(
            ["BV16G411y7Rs", "BV1aw411179M"]
        )
        payload["profile_reported_video_count"] = 3
        with self.assertRaisesRegex(ValueError, "profile video count"):
            self.updates.validate_snapshot(payload, source, now)

    def test_cross_platform_dedupe_uses_inverted_index(self):
        postings, titles = self.updates.build_douyin_term_index([
            {"video_id": "1", "title": "刘辉教练 反手 万能握拍 技巧"},
            {"video_id": "2", "title": "双打 接发球 站位"},
        ])
        matches = self.updates.possible_douyin_duplicates(
            "刘辉教练反手万能握拍技巧", postings, titles, threshold=0.3
        )
        self.assertEqual(matches[0]["video_id"], "1")

    def test_identical_snapshot_replay_preserves_updated_at(self):
        old = {
            "version": 1,
            "updated_at": "2026-07-28T10:00:00+00:00",
            "videos": [{"video_id": "bilibili:BV16G411y7Rs"}],
        }
        replay = {
            **old,
            "updated_at": "2026-07-28T11:00:00+00:00",
        }
        result = self.updates.stabilize_updated_at(
            old,
            replay,
            "2026-07-28T12:00:00+00:00",
        )
        self.assertEqual(result, old)

    def test_changed_snapshot_uses_deterministic_observation_time(self):
        old = {
            "version": 1,
            "updated_at": "2026-07-28T10:00:00+00:00",
            "videos": [{"video_id": "bilibili:BV16G411y7Rs"}],
        }
        changed = {
            **old,
            "videos": [
                *old["videos"],
                {"video_id": "bilibili:BV1aw411179M"},
            ],
        }
        observed_at = "2026-07-28T12:00:00+00:00"
        result = self.updates.stabilize_updated_at(
            old,
            changed,
            observed_at,
        )
        self.assertEqual(result["updated_at"], observed_at)
        self.assertEqual(result["videos"], changed["videos"])

    def test_processing_persist_does_not_touch_unchanged_queue_timestamps(self):
        processor = load("process_bilibili_candidates")
        old_at = "2026-07-28T10:00:00+00:00"
        changed_at = "2026-07-28T12:00:00+00:00"
        ledger = {
            "version": 1,
            "platform": "bilibili",
            "updated_at": old_at,
            "counts": {"candidate_liuhui_teaching": 1},
            "videos": [
                {
                    "video_id": "bilibili:BV16G411y7Rs",
                    "decision": "candidate_liuhui_teaching",
                    "knowledge_admission_eligible": True,
                    "processing_state": {"stage": "downloaded"},
                }
            ],
        }
        queue = {
            "version": 1,
            "platform": "bilibili",
            "updated_at": old_at,
            "counts": {"transcribed": 1},
            "items": [
                {
                    "video_id": "BV16G411y7Rs",
                    "status": "transcribed",
                }
            ],
        }
        review = {
            "version": 1,
            "platform": "bilibili",
            "updated_at": old_at,
            "counts": {},
            "items": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {
                "LEDGER_PATH": root / "ledger.json",
                "QUEUE_PATH": root / "queue.json",
                "REVIEW_PATH": root / "review.json",
                "TRANSACTION_PATH": root / "transaction.json",
            }
            for name, payload in [
                ("LEDGER_PATH", ledger),
                ("QUEUE_PATH", queue),
                ("REVIEW_PATH", review),
            ]:
                paths[name].write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            changed_ledger = json.loads(json.dumps(ledger))
            changed_ledger["videos"][0]["processing_state"]["stage"] = "transcribed"
            with (
                mock.patch.multiple(processor, **paths),
                mock.patch.object(processor, "now_iso", return_value=changed_at),
            ):
                processor.persist(changed_ledger, queue)
            persisted_ledger = json.loads(
                paths["LEDGER_PATH"].read_text(encoding="utf-8")
            )
            persisted_queue = json.loads(
                paths["QUEUE_PATH"].read_text(encoding="utf-8")
            )
            persisted_review = json.loads(
                paths["REVIEW_PATH"].read_text(encoding="utf-8")
            )
        self.assertEqual(persisted_ledger["updated_at"], changed_at)
        self.assertEqual(persisted_queue["updated_at"], old_at)
        self.assertEqual(persisted_review["updated_at"], old_at)

    def test_download_metadata_requires_uploader_text_tag_and_duration(self):
        processor = load("process_bilibili_candidates")
        valid = {
            "id": "BV16G411y7Rs",
            "uploader": "大G羽毛球",
            "uploader_id": "1423436652",
            "title": "刘辉教练教你反手发力",
            "description": "直播教学切片",
            "tags": ["刘辉", "刘辉羽毛球", "羽毛球教学"],
            "duration": 300.0,
            "webpage_url": "https://www.bilibili.com/video/BV16G411y7Rs/",
        }
        result = processor.verify_metadata(valid, "BV16G411y7Rs")
        self.assertEqual(result["status"], "verified_liuhui_clip")
        for field in ["uploader_profile_matches", "publisher_text_names_liuhui",
                      "dedicated_origin_tag", "duration_valid"]:
            self.assertTrue(result["signals"][field])

        for key, bad_value in [
            ("uploader_id", "other"),
            ("title", "反手发力教学"),
            ("tags", ["羽毛球教学"]),
            ("duration", 0),
        ]:
            invalid = {**valid, key: bad_value}
            if key == "title":
                invalid["description"] = "直播教学切片"
            self.assertEqual(
                processor.verify_metadata(invalid, "BV16G411y7Rs")["status"],
                "verification_failed",
            )
        previous = {**result, "verified_at": "2026-07-26T00:00:00+00:00"}
        refreshed = {**result, "verified_at": "2026-07-27T00:00:00+00:00"}
        self.assertEqual(
            processor.preserve_verification_timestamp(previous, refreshed)[
                "verified_at"
            ],
            previous["verified_at"],
        )
        self.assertNotIn("worstaudio", processor.ydl_options()["format"])
        self.assertEqual(
            processor.classify_error(
                "Unable to download webpage: nodename nor servname provided"
            ),
            ("temporary_network", True),
        )

    def test_required_collection_metadata_does_not_claim_liuhui_origin(self):
        processor = load("process_bilibili_candidates")
        metadata = {
            "id": "BV16G411y7Rs",
            "uploader": "大G羽毛球",
            "uploader_id": "1423436652",
            "title": "反手发力教学",
            "description": "",
            "tags": ["羽毛球教学"],
            "duration": 300.0,
            "webpage_url": "https://www.bilibili.com/video/BV16G411y7Rs/",
        }
        result = processor.verify_metadata(
            metadata,
            "BV16G411y7Rs",
            "required_transcription_policy",
            "collection",
        )
        self.assertEqual(result["status"], "verified_collection_policy")
        self.assertEqual(
            result["verification_tier"],
            "user_confirmed_collection_policy",
        )
        self.assertFalse(result["signals"]["publisher_text_names_liuhui"])
        self.assertFalse(result["signals"]["dedicated_origin_tag"])

    def test_required_video_metadata_uses_distinct_policy_status(self):
        processor = load("process_bilibili_candidates")
        metadata = {
            "id": "BV1Gx4y1Q7Xb",
            "uploader": "大G羽毛球",
            "uploader_id": "1423436652",
            "title": "羽毛球专项力量怎么练？",
            "description": "",
            "tags": [],
            "duration": 89.0,
            "webpage_url": "https://www.bilibili.com/video/BV1Gx4y1Q7Xb/",
        }
        result = processor.verify_metadata(
            metadata,
            "BV1Gx4y1Q7Xb",
            "required_transcription_policy",
            "video_override",
        )
        self.assertEqual(result["status"], "verified_video_policy")
        self.assertEqual(
            result["verification_tier"],
            "user_confirmed_video_policy",
        )
        self.assertIn("user_confirmed_video_policy", result["methods"])

    def test_existing_metadata_can_be_promoted_without_refetch(self):
        processor = load("process_bilibili_candidates")
        record = {
            "decision": "required_transcription_policy",
            "collection_policy": {"basis": "collection"},
            "origin_verification": {
                "status": "verification_failed",
                "signals": {
                    "video_id_matches": True,
                    "uploader_profile_matches": True,
                    "canonical_url_matches": True,
                    "duration_valid": True,
                    "publisher_text_names_liuhui": True,
                    "dedicated_origin_tag": False,
                },
                "source_metadata": {
                    "duration_seconds": 300.0,
                },
            },
        }
        with mock.patch.object(
            processor,
            "now_iso",
            return_value="2026-07-28T00:00:00+00:00",
        ):
            promoted = processor.promote_existing_collection_verification(record)
        self.assertEqual(promoted["status"], "verified_collection_policy")
        self.assertEqual(
            promoted["methods"],
            [
                "verified_uploader_profile",
                "user_confirmed_collection_policy",
            ],
        )

    def test_rules_upgrade_reopens_obsolete_classification_terminal(self):
        classified = self.classify(
            "反手发力教学",
            collection_memberships=[
                self.membership("合集·反手发力", "1815203"),
            ],
        )
        existing = {
            "classification_rules_hash": "old",
            "processing_state": {
                "stage": "quarantined_origin_unknown",
                "terminal": True,
            },
        }
        state = self.updates.reconcile_processing_state(existing, classified)
        self.assertEqual(state["stage"], "metadata_pending")
        self.assertFalse(state["terminal"])

    def test_rules_upgrade_preserves_completed_transcription(self):
        classified = self.classify(
            "反手发力教学",
            collection_memberships=[
                self.membership("合集·反手发力", "1815203"),
            ],
        )
        existing = {
            "classification_rules_hash": "old",
            "processing_state": {
                "stage": "transcribed",
                "terminal": False,
            },
        }
        self.assertEqual(
            self.updates.reconcile_processing_state(existing, classified),
            existing["processing_state"],
        )

    def test_committed_archive_has_exact_collection_policy_partition(self):
        archive = json.loads(
            (
                ROOT
                / "data"
                / "snapshots"
                / "bilibili_profile_full_archive.json"
            ).read_text(encoding="utf-8")
        )
        normalized, _ = self.updates.normalize_snapshot_shape(archive)
        classified = [
            self.pipeline.classify_video(
                self.pipeline.normalize_video(item),
                self.rules,
            )
            for item in normalized["videos"]
        ]
        self.assertEqual(
            Counter(
                item["collection_policy"]["action"]
                for item in classified
            ),
            {
                "required_transcription": 602,
                "excluded": 165,
            },
        )

    def test_media_completion_ignores_part_and_quarantines_broken_final(self):
        processor = load("process_bilibili_candidates")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            broken = root / "BV16G411y7Rs.m4a"
            broken.write_bytes(b"x" * 8192)
            partial = root / "BV16G411y7Rs.m4a.part"
            partial.write_bytes(b"x" * 8192)
            with (
                mock.patch.object(processor, "RAW_ROOT", root),
                mock.patch.object(
                    processor,
                    "validate_media",
                    side_effect=RuntimeError("broken"),
                ),
                mock.patch.object(
                    processor,
                    "inspect_media_content",
                    side_effect=RuntimeError("still broken"),
                ),
            ):
                media, validation = processor.completed_media(
                    "BV16G411y7Rs"
                )
            self.assertIsNone(media)
            self.assertIsNone(validation)
            self.assertFalse(broken.exists())
            self.assertTrue(partial.exists())
            self.assertTrue(any((root / "quarantine").iterdir()))

    def test_webm_is_transcribable(self):
        transcriber = load("batch_transcribe_directory")
        self.assertIn(".webm", transcriber.MEDIA_SUFFIXES)

    def test_transcript_duplicate_gate_requires_high_similarity_and_duration(self):
        builder = load("build_bilibili_knowledge")
        source = "反手发力动作要领需要放松握拍击球前加速" * 12
        douyin = {
            "videos": [{
                "video_id": "100000000000000001",
                "source_type": "douyin_video",
                "processing_status": "ready",
                "duration_seconds": 100,
                "transcript_segments": [{"text": source}],
            }]
        }
        index = builder.build_douyin_shingle_index(douyin)
        duplicate = builder.duplicate_candidates(
            [{"text": source}], 102, index
        )
        self.assertEqual(duplicate[0]["evidence_id"], "100000000000000001")
        distinct = builder.duplicate_candidates(
            [{"text": "双打接发站位与封网轮转完全不同的教学内容" * 12}],
            102,
            index,
        )
        self.assertEqual(distinct, [])
        builder.add_to_shingle_index(
            index,
            "bilibili:BV1aw411179M",
            [{"text": "单打接发站位与封网轮转完全不同的教学内容" * 12}],
            102,
        )
        same_bilibili = builder.duplicate_candidates(
            [{"text": "单打接发站位与封网轮转完全不同的教学内容" * 12}],
            101,
            index,
        )
        self.assertEqual(
            same_bilibili[0]["evidence_id"],
            "bilibili:BV1aw411179M",
        )


if __name__ == "__main__":
    unittest.main()
