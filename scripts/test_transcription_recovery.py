#!/usr/bin/env python3
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import report_pipeline_status
import batch_transcribe_directory as transcriber
from batch_transcribe_directory import (
    media_fingerprint,
    transcribe_directory,
    validate_transcript_payload,
    write_transcript_outputs,
)
from process_douyin_ready_batch import cleanup_transcribed_media


class FakeModel:
    def transcribe(self, _media, **_kwargs):
        segments = [SimpleNamespace(start=0.0, end=2.0, text=" 挥拍击球 ")]
        info = SimpleNamespace(
            language="zh",
            language_probability=0.99,
            duration=2.0,
        )
        return iter(segments), info


class FailingModel:
    def transcribe(self, _media, **_kwargs):
        raise RuntimeError("decoder exploded")


def queue_payload(video_id, media_path, status="downloaded"):
    return {
        "items": [
            {
                "video_id": video_id,
                "status": status,
                "media_path": media_path,
                "attempts": 0,
                "error": None,
            }
        ],
        "counts": {status: 1},
    }


class TranscriptionRecoveryTests(unittest.TestCase):
    def test_video_id_filter_limits_the_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media_dir = root / "media"
            output_dir = root / "output"
            media_dir.mkdir()
            (media_dir / "selected.m4a").write_bytes(b"selected audio")
            (media_dir / "ignored.m4a").write_bytes(b"ignored audio")

            result = transcribe_directory(
                media_dir,
                output_dir,
                model_factory=lambda _name: FakeModel(),
                video_ids=["selected"],
            )

            self.assertEqual(result["media_files"], 1)
            self.assertEqual(result["transcribed"], 1)
            self.assertTrue((output_dir / "selected.json").exists())
            self.assertFalse((output_dir / "ignored.json").exists())

    def test_valid_json_repairs_sidecars_without_loading_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media_dir = root / "media"
            output_dir = root / "output"
            media_dir.mkdir()
            media = media_dir / "123.m4a"
            media.write_bytes(b"audio")
            payload = {
                "video_id": "123",
                "source_file": str(media),
                **media_fingerprint(media),
                "model": "small",
                "language": "zh",
                "language_probability": 1.0,
                "duration": 2.0,
                "segments": [{"start": 0.0, "end": 2.0, "text": "击球"}],
                "full_text": "击球",
            }
            write_transcript_outputs(output_dir, payload)
            (output_dir / "123.txt").unlink()
            queue_path = root / "queue.json"
            queue_path.write_text(
                json.dumps(queue_payload("123", str(media)), ensure_ascii=False),
                encoding="utf-8",
            )

            def should_not_load(_name):
                raise AssertionError("model should not load for valid JSON")

            result = transcribe_directory(
                media_dir,
                output_dir,
                queue_path=queue_path,
                model_factory=should_not_load,
            )
            updated = json.loads(queue_path.read_text(encoding="utf-8"))
            self.assertEqual(result["already_done"], 1)
            self.assertTrue((output_dir / "123.txt").exists())
            self.assertEqual(updated["items"][0]["status"], "transcribed")
            self.assertEqual(
                updated["items"][0]["transcript_source_sha256"],
                payload["source_sha256"],
            )

    def test_corrupt_completion_marker_is_removed_and_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media_dir = root / "media"
            output_dir = root / "output"
            media_dir.mkdir()
            output_dir.mkdir()
            (media_dir / "456.m4a").write_bytes(b"audio")
            (output_dir / "456.json").write_text("{broken", encoding="utf-8")
            queue_path = root / "queue.json"
            queue_path.write_text(
                json.dumps(queue_payload("456", "media/456.m4a"), ensure_ascii=False),
                encoding="utf-8",
            )
            result = transcribe_directory(
                media_dir,
                output_dir,
                queue_path=queue_path,
                model_factory=lambda _name: FakeModel(),
            )
            payload = json.loads((output_dir / "456.json").read_text(encoding="utf-8"))
            self.assertEqual(result["transcribed"], 1)
            self.assertEqual(payload["full_text"], "挥拍击球")

    def test_model_failure_is_persisted_and_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media_dir = root / "media"
            output_dir = root / "output"
            media_dir.mkdir()
            (media_dir / "789.m4a").write_bytes(b"audio")
            queue_path = root / "queue.json"
            queue_path.write_text(
                json.dumps(queue_payload("789", "media/789.m4a"), ensure_ascii=False),
                encoding="utf-8",
            )

            def fail_model(_name):
                raise RuntimeError("model unavailable")

            result = transcribe_directory(
                media_dir,
                output_dir,
                queue_path=queue_path,
                model_factory=fail_model,
            )
            item = json.loads(queue_path.read_text(encoding="utf-8"))["items"][0]
            self.assertEqual(result["failed_video_ids"], ["789"])
            self.assertEqual(item["status"], "downloaded")
            self.assertEqual(item["attempts"], 0)
            self.assertIsNone(item["error"])
            self.assertEqual(result["batch_error"], "model unavailable")
            self.assertFalse((output_dir / "789.json").exists())

    def test_item_failure_has_finite_retries_then_is_quarantined(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media_dir = root / "media"
            output_dir = root / "output"
            media_dir.mkdir()
            (media_dir / "bounded.m4a").write_bytes(b"broken audio")
            queue_path = root / "queue.json"
            queue_path.write_text(
                json.dumps(
                    queue_payload("bounded", "media/bounded.m4a"),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            results = []
            for _ in range(3):
                results.append(
                    transcribe_directory(
                        media_dir,
                        output_dir,
                        queue_path=queue_path,
                        model_factory=lambda _name: FailingModel(),
                    )
                )
            item = json.loads(queue_path.read_text(encoding="utf-8"))["items"][0]

            self.assertEqual(results[0]["retryable_failed_video_ids"], ["bounded"])
            self.assertEqual(results[1]["retryable_failed_video_ids"], ["bounded"])
            self.assertEqual(results[2]["quarantined_video_ids"], ["bounded"])
            self.assertEqual(results[2]["retryable_failed_video_ids"], [])
            self.assertEqual(item["status"], "transcription_quarantined")
            self.assertEqual(item["transcription_retry_attempts"], 3)
            self.assertEqual(item["transcription_attempts"], 3)
            self.assertFalse(item["transcription_retryable"])
            self.assertIsNotNone(item["transcription_isolated_at"])

            skipped = transcribe_directory(
                media_dir,
                output_dir,
                queue_path=queue_path,
                model_factory=lambda _name: (_ for _ in ()).throw(
                    AssertionError("isolated media must not load the model")
                ),
            )
            self.assertEqual(skipped["attempted"], 0)
            self.assertEqual(skipped["quarantined_video_ids"], ["bounded"])

    def test_force_explicitly_recovers_a_quarantined_item(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media_dir = root / "media"
            output_dir = root / "output"
            media_dir.mkdir()
            media = media_dir / "recoverable.m4a"
            media.write_bytes(b"audio")
            queue = queue_payload(
                "recoverable",
                "media/recoverable.m4a",
                status="transcription_quarantined",
            )
            queue["items"][0].update(
                {
                    "transcription_attempts": 3,
                    "transcription_retry_attempts": 3,
                    "transcription_retryable": False,
                    "transcription_isolated_at": "2026-07-28T00:00:00+00:00",
                }
            )
            queue_path = root / "queue.json"
            queue_path.write_text(
                json.dumps(queue, ensure_ascii=False),
                encoding="utf-8",
            )

            result = transcribe_directory(
                media_dir,
                output_dir,
                queue_path=queue_path,
                model_factory=lambda _name: FakeModel(),
                video_ids=["recoverable"],
                force=True,
            )
            item = json.loads(queue_path.read_text(encoding="utf-8"))["items"][0]

            self.assertEqual(result["transcribed"], 1)
            self.assertEqual(item["status"], "transcribed")
            self.assertEqual(item["transcription_retry_attempts"], 0)
            self.assertEqual(item["transcription_force_recoveries"], 1)
            self.assertEqual(item["transcription_attempts"], 3)

    def test_legacy_failure_at_limit_is_quarantined_without_an_extra_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media_dir = root / "media"
            output_dir = root / "output"
            media_dir.mkdir()
            (media_dir / "legacy.m4a").write_bytes(b"broken audio")
            queue = queue_payload(
                "legacy",
                "media/legacy.m4a",
                status="transcription_failed",
            )
            queue["items"][0]["transcription_attempts"] = 3
            queue_path = root / "queue.json"
            queue_path.write_text(json.dumps(queue), encoding="utf-8")

            result = transcribe_directory(
                media_dir,
                output_dir,
                queue_path=queue_path,
                model_factory=lambda _name: (_ for _ in ()).throw(
                    AssertionError("exhausted legacy failure must not load the model")
                ),
            )
            item = json.loads(queue_path.read_text(encoding="utf-8"))["items"][0]

            self.assertEqual(result["attempted"], 0)
            self.assertEqual(result["quarantined_video_ids"], ["legacy"])
            self.assertEqual(item["status"], "transcription_quarantined")
            self.assertEqual(item["transcription_retry_attempts"], 3)
            self.assertEqual(item["transcription_attempts"], 3)

    def test_cli_treats_terminal_quarantine_as_handled(self):
        result = {
            "failed_video_ids": ["isolated"],
            "retryable_failed_video_ids": [],
            "quarantined_video_ids": ["isolated"],
        }
        with (
            mock.patch.object(transcriber, "transcribe_directory", return_value=result),
            mock.patch(
                "sys.argv",
                [
                    "batch_transcribe_directory.py",
                    "/tmp/media",
                    "--output-dir",
                    "/tmp/output",
                ],
            ),
        ):
            exit_code = transcriber.main()
        self.assertEqual(exit_code, 0)

    def test_bilibili_status_counts_transcription_quarantine_as_terminal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "archive.json"
            ledger_path = root / "ledger.json"
            queue_path = root / "queue.json"
            knowledge_path = root / "knowledge.json"
            archive_path.write_text(
                json.dumps(
                    {
                        "coverage": {
                            "full_profile_archive": True,
                            "profile_unique_videos": 1,
                        },
                        "videos": [{"bvid": "BV16G411y7Rs"}],
                    }
                ),
                encoding="utf-8",
            )
            ledger_path.write_text(
                json.dumps(
                    {
                        "counts": {"candidate_liuhui_teaching": 1},
                        "videos": [
                            {
                                "bvid": "BV16G411y7Rs",
                                "decision": "candidate_liuhui_teaching",
                                "processing_state": {
                                    "stage": "downloaded",
                                    "terminal": False,
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            queue_path.write_text(
                json.dumps(
                    {
                        "counts": {"transcription_quarantined": 1},
                        "items": [
                            {
                                "video_id": "BV16G411y7Rs",
                                "status": "transcription_quarantined",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            knowledge_path.write_text(
                json.dumps(
                    {
                        "knowledge_counts": {"videos": 1, "low_value": 1},
                        "videos": [
                            {
                                "source_video_id": "BV16G411y7Rs",
                                "processing_status": "low_value",
                                "automatic_admission": {
                                    "disposition": (
                                        "quarantined_transcription_retry_exhausted"
                                    )
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with (
                mock.patch.object(
                    report_pipeline_status,
                    "BILIBILI_ARCHIVE_PATH",
                    archive_path,
                ),
                mock.patch.object(
                    report_pipeline_status,
                    "BILIBILI_LEDGER_PATH",
                    ledger_path,
                ),
                mock.patch.object(
                    report_pipeline_status,
                    "BILIBILI_QUEUE_PATH",
                    queue_path,
                ),
                mock.patch.object(
                    report_pipeline_status,
                    "BILIBILI_KNOWLEDGE_PATH",
                    knowledge_path,
                ),
                mock.patch.object(
                    report_pipeline_status,
                    "BUILD_MANIFEST_PATH",
                    root / "missing-build.json",
                ),
                mock.patch.object(
                    report_pipeline_status,
                    "INSTALLED_MANIFEST_PATH",
                    root / "missing-installed.json",
                ),
            ):
                status = report_pipeline_status.bilibili_status()

            self.assertTrue(status["all_videos_terminal"])
            self.assertEqual(status["terminal_videos"], 1)
            self.assertEqual(status["pending_videos"], 0)
            self.assertEqual(
                status["stage_counts"],
                {"transcription_quarantined": 1},
            )

    def test_changed_media_invalidates_a_completed_transcript(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media_dir = root / "media"
            output_dir = root / "output"
            media_dir.mkdir()
            media = media_dir / "321.m4a"
            media.write_bytes(b"first media")
            payload = {
                "video_id": "321",
                "source_file": str(media),
                **media_fingerprint(media),
                "model": "small",
                "language": "zh",
                "language_probability": 1.0,
                "duration": 2.0,
                "segments": [{"start": 0.0, "end": 2.0, "text": "旧内容"}],
                "full_text": "旧内容",
            }
            write_transcript_outputs(output_dir, payload)
            media.write_bytes(b"replacement media")
            queue_path = root / "queue.json"
            queue_path.write_text(
                json.dumps(queue_payload("321", str(media)), ensure_ascii=False),
                encoding="utf-8",
            )
            result = transcribe_directory(
                media_dir,
                output_dir,
                queue_path=queue_path,
                model_factory=lambda _name: FakeModel(),
            )
            updated = json.loads((output_dir / "321.json").read_text(encoding="utf-8"))
            self.assertEqual(result["invalid_outputs_removed"], ["321"])
            self.assertEqual(result["transcribed"], 1)
            self.assertEqual(updated["full_text"], "挥拍击球")
            self.assertEqual(updated["source_sha256"], media_fingerprint(media)["source_sha256"])

    def test_transcript_structure_rejects_invalid_duration_and_probability(self):
        payload = {
            "video_id": "654",
            "source_file": "654.m4a",
            "model": "small",
            "language": "zh",
            "language_probability": 1.5,
            "duration": 0,
            "segments": [],
            "full_text": "",
        }
        with self.assertRaises(ValueError):
            validate_transcript_payload(payload, "654")

    def test_cleanup_removes_only_successful_media(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch = "batch-test"
            media_dir = root / "data" / "raw_videos" / "douyin" / batch
            media_dir.mkdir(parents=True)
            successful = media_dir / "success.m4a"
            failed = media_dir / "failed.m4a"
            unrelated = media_dir / "notes.txt"
            for path in [successful, failed, unrelated]:
                path.write_bytes(b"x")
            queue = {
                "items": [
                    {
                        "video_id": "success",
                        "status": "transcribed",
                        "media_path": str(successful.relative_to(root)),
                    },
                    {
                        "video_id": "failed",
                        "status": "transcription_failed",
                        "media_path": str(failed.relative_to(root)),
                    },
                ]
            }
            queue_path = root / "queue.json"
            queue_path.write_text(json.dumps(queue), encoding="utf-8")
            result = cleanup_transcribed_media(
                batch,
                ["success", "failed"],
                root=root,
                queue_path=queue_path,
            )
            self.assertEqual(result, {"removed": ["success"], "skipped": ["failed"]})
            self.assertFalse(successful.exists())
            self.assertTrue(failed.exists())
            self.assertTrue(unrelated.exists())
            saved_items = {
                item["video_id"]: item
                for item in json.loads(queue_path.read_text(encoding="utf-8"))["items"]
            }
            self.assertIsNone(saved_items["success"]["media_path"])
            self.assertEqual(saved_items["failed"]["media_path"], str(failed.relative_to(root)))


if __name__ == "__main__":
    unittest.main()
