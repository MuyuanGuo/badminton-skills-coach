#!/usr/bin/env python3
import importlib.util
import tempfile
import unittest
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
        item = self.pipeline.normalize_video({
            "bvid": "BV16G411y7Rs",
            "title": title,
            **extra,
        })
        return self.pipeline.classify_video(item, self.rules)

    def test_explicit_liuhui_teaching_is_candidate_but_not_admitted(self):
        item = self.classify("刘辉教练教你反手万能握拍")
        self.assertEqual(item["decision"], "candidate_liuhui_teaching")
        self.assertEqual(item["origin_status"], "origin_verification_pending")
        self.assertFalse(item["knowledge_admission_eligible"])
        self.assertFalse(self.pipeline.may_enter_knowledge_base(item))

    def test_creator_teaching_without_origin_signal_is_isolated(self):
        item = self.classify("反手高远球提高稳定性的技巧")
        self.assertEqual(item["decision"], "excluded_creator_original_or_unknown")

    def test_seo_description_cannot_contaminate_origin_decision(self):
        item = self.classify(
            "反手高远球提高稳定性的技巧",
            description="直播教学切片已获刘辉教练授权；相关视频：刘辉教练教你",
        )
        self.assertEqual(item["decision"], "excluded_creator_original_or_unknown")

    def test_non_teaching_and_medical_are_not_candidates(self):
        self.assertEqual(
            self.classify("直播花絮 第45集")["decision"],
            "excluded_non_teaching",
        )
        self.assertEqual(
            self.classify("为什么打完羽毛球后膝盖疼？刘辉教练告诉你")["decision"],
            "excluded_non_teaching",
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

    def test_media_completion_ignores_part_and_quarantines_broken_final(self):
        processor = load("process_bilibili_candidates")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            broken = root / "BV16G411y7Rs.m4a"
            broken.write_bytes(b"x" * 8192)
            (root / "BV16G411y7Rs.m4a.part").write_bytes(b"x" * 8192)
            with (
                mock.patch.object(processor, "RAW_ROOT", root),
                mock.patch.object(
                    processor,
                    "validate_media",
                    side_effect=RuntimeError("broken"),
                ),
            ):
                media, validation = processor.completed_media(
                    "BV16G411y7Rs"
                )
            self.assertIsNone(media)
            self.assertIsNone(validation)
            self.assertFalse(broken.exists())
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
