#!/usr/bin/env python3
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import backfill_bilibili_transcription_recipe as backfill
import build_bilibili_transcription_plan as planner
import finalize_bilibili_transcripts as finalizer
from bilibili_storage import media_storage_key


def transcript_payload(video_id):
    return {
        "video_id": video_id,
        "source_file": "bilibili-media-cache/source.m4a",
        "source_bytes": 8192,
        "source_sha256": "a" * 64,
        "model": "small",
        "language": "zh",
        "language_probability": 0.99,
        "duration": 2.0,
        "segments": [{"start": 0.0, "end": 2.0, "text": "击球"}],
        "full_text": "击球",
    }


class BilibiliTranscriptCacheTests(unittest.TestCase):
    def test_finalizer_falls_back_after_unreadable_external_json(self):
        video_id = "BV16G411y7Rs"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media_root = root / "media"
            external = root / "external"
            legacy = root / "legacy"
            media_root.mkdir()
            external.mkdir()
            legacy.mkdir()
            media = media_root / f"{media_storage_key(video_id)}.m4a"
            media.write_bytes(b"audio")
            payload = transcript_payload(video_id)
            payload["source_bytes"] = media.stat().st_size
            import hashlib
            payload["source_sha256"] = hashlib.sha256(
                media.read_bytes()
            ).hexdigest()
            preferred = external / f"{video_id}.json"
            preferred.write_text("placeholder", encoding="utf-8")
            fallback = legacy / f"{video_id}.json"
            fallback.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
            queue_path = root / "queue.json"
            queue_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "video_id": video_id,
                                "status": "downloaded",
                                "media_path": str(media),
                                "attempts": 0,
                                "error": None,
                            }
                        ],
                        "counts": {"downloaded": 1},
                    }
                ),
                encoding="utf-8",
            )
            original_load = finalizer.load_valid_transcript

            def load_with_eviction(path, *args, **kwargs):
                if path == preferred:
                    raise OSError(60, "Operation timed out")
                return original_load(path, *args, **kwargs)

            with (
                mock.patch.object(finalizer, "QUEUE_PATH", queue_path),
                mock.patch.object(finalizer, "MEDIA_ROOT", media_root),
                mock.patch.object(
                    finalizer,
                    "bilibili_transcript_roots",
                    return_value=[external, legacy],
                ),
                mock.patch.object(
                    finalizer,
                    "acquire_bilibili_pipeline_lock",
                    return_value=object(),
                ),
                mock.patch.object(
                    finalizer,
                    "load_valid_transcript",
                    side_effect=load_with_eviction,
                ),
                mock.patch.object(
                    sys,
                    "argv",
                    ["finalize_bilibili_transcripts.py"],
                ),
            ):
                finalizer.main()

            updated = json.loads(queue_path.read_text(encoding="utf-8"))

        self.assertEqual(updated["items"][0]["status"], "transcribed")

    def test_finalizer_skips_completed_items_without_reading_media(self):
        video_id = "BV16G411y7Rs"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media_root = root / "media"
            transcript_root = root / "transcripts"
            media_root.mkdir()
            transcript_root.mkdir()
            media = media_root / f"{media_storage_key(video_id)}.m4a"
            media.write_bytes(b"audio")
            queue_path = root / "queue.json"
            queue_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "video_id": video_id,
                                "status": "transcribed",
                                "attempts": 1,
                                "error": None,
                            }
                        ],
                        "counts": {"transcribed": 1},
                    }
                ),
                encoding="utf-8",
            )
            with (
                mock.patch.object(finalizer, "QUEUE_PATH", queue_path),
                mock.patch.object(
                    finalizer,
                    "acquire_bilibili_pipeline_lock",
                    return_value=object(),
                ),
                mock.patch.object(
                    finalizer,
                    "load_valid_transcript",
                ) as load_valid_transcript,
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "finalize_bilibili_transcripts.py",
                        "--media-cache-dir",
                        str(media_root),
                        "--transcript-cache-dir",
                        str(transcript_root),
                    ],
                ),
            ):
                finalizer.main()
        load_valid_transcript.assert_not_called()

    def test_plan_accepts_readable_repository_fallback(self):
        video_id = "BV16G411y7Rs"
        archive = {"items": [{"bvid": video_id}]}
        ledger = {
            "videos": [
                {
                    "bvid": video_id,
                    "decision": "required_transcription_policy",
                    "collection_policy": {"basis": "collection"},
                }
            ]
        }
        queue = {
            "updated_at": "2026-07-29T00:00:00+00:00",
            "items": [{"video_id": video_id, "status": "transcribed"}],
        }
        rules = {
            "_identity": {
                "version": 3,
                "sha256": "b" * 64,
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            external = root / "external"
            legacy = root / "legacy"
            legacy.mkdir()
            (legacy / f"{video_id}.json").write_text("{}", encoding="utf-8")

            plan = planner.build_plan(
                archive,
                ledger,
                queue,
                archive_sha256="c" * 64,
                rules=rules,
                transcript_roots=[external, legacy],
            )

        self.assertEqual(plan["counts"]["baseline_completed"], 1)
        self.assertEqual(plan["counts"]["pending"], 0)

    def test_backfill_migrates_legacy_json_to_external_cache(self):
        video_id = "BV16G411y7Rs"
        payload = transcript_payload(video_id)
        queue = {
            "items": [
                {
                    "video_id": video_id,
                    "transcript_source_sha256": payload["source_sha256"],
                    "transcript_source_bytes": payload["source_bytes"],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            external = root / "external"
            legacy = root / "legacy"
            legacy.mkdir()
            legacy_path = legacy / f"{video_id}.json"
            legacy_path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
            original_legacy = legacy_path.read_bytes()
            queue_path = root / "queue.json"
            queue_path.write_text(json.dumps(queue), encoding="utf-8")

            with (
                mock.patch.object(backfill, "QUEUE_PATH", queue_path),
                mock.patch.object(
                    backfill,
                    "bilibili_transcript_roots",
                    return_value=[external, legacy],
                ),
                mock.patch.object(
                    backfill,
                    "eligible_for_backfill",
                    return_value=True,
                ),
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "backfill_bilibili_transcription_recipe.py",
                        "--transcript-cache-dir",
                        str(external),
                    ],
                ),
            ):
                self.assertEqual(backfill.main(), 0)

            migrated = next(external.rglob(f"{video_id}.json"))
            migrated_payload = json.loads(migrated.read_text(encoding="utf-8"))
            legacy_after = legacy_path.read_bytes()

        self.assertIn("transcription_recipe", migrated_payload)
        self.assertEqual(legacy_after, original_legacy)


if __name__ == "__main__":
    unittest.main()
