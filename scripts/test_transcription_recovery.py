#!/usr/bin/env python3
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import report_pipeline_status
import batch_transcribe_directory as transcriber
from bilibili_storage import (
    BILIBILI_MEDIA_CACHE_ENV,
    BILIBILI_TRANSCRIPT_CACHE_ENV,
    bilibili_media_cache_root,
    bilibili_transcript_roots,
    first_readable_transcript,
    index_exact_transcript_candidates,
    media_storage_key,
    portable_transcript_reference,
    queue_media_locator,
    resolve_queue_media_path,
)
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


class MutatingModel(FakeModel):
    def transcribe(self, media, **kwargs):
        Path(media).write_bytes(b"changed while decoding")
        return super().transcribe(media, **kwargs)


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
    def test_force_reruns_valid_transcript_with_requested_recovery_model(self):
        video_id = "BV16G411y7Rs"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media_dir = root / "media"
            output_dir = root / "output"
            media_dir.mkdir()
            media = media_dir / f"{video_id}.m4a"
            media.write_bytes(b"audio")
            old_payload = {
                "video_id": video_id,
                "source_file": str(media),
                **media_fingerprint(media),
                "model": "small",
                "language": "zh",
                "language_probability": 1.0,
                "duration": 2.0,
                "segments": [
                    {"start": 0.0, "end": 2.0, "text": "旧转写"}
                ],
                "full_text": "旧转写",
            }
            write_transcript_outputs(output_dir, old_payload)
            queue_path = root / "queue.json"
            queue_path.write_text(
                json.dumps(
                    queue_payload(video_id, str(media), status="transcribed")
                ),
                encoding="utf-8",
            )

            result = transcribe_directory(
                media_dir,
                output_dir,
                queue_path=queue_path,
                model_name="medium",
                model_factory=lambda _name: FakeModel(),
                video_ids=[video_id],
                force=True,
            )

            self.assertEqual(result["attempted"], 1)
            self.assertEqual(result["transcribed"], 1)
            recovered = json.loads(
                (output_dir / f"{video_id}.json").read_text(encoding="utf-8")
            )
            self.assertEqual(recovered["model"], "medium")
            item = json.loads(queue_path.read_text(encoding="utf-8"))["items"][0]
            self.assertEqual(item["transcript_model"], "medium")
            self.assertNotIn("transcription_recovery_required_model", item)

    def test_external_transcript_root_is_preferred_with_repository_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            project_root = Path(directory) / "project"
            external = Path(directory) / "transcripts"
            roots = bilibili_transcript_roots(
                project_root,
                environ={BILIBILI_TRANSCRIPT_CACHE_ENV: str(external)},
            )

            self.assertEqual(
                roots,
                [
                    external,
                    project_root / "data" / "transcripts" / "bilibili",
                ],
            )

    def test_exact_transcript_index_preserves_root_priority_and_case(self):
        video_ids = ["BV1DSNFz2ETs", "BV1DSNFz2Ets"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            external = root / "external"
            legacy = root / "legacy"
            external.mkdir()
            legacy.mkdir()
            legacy_paths = {}
            for position, video_id in enumerate(video_ids):
                parent = (
                    legacy
                    if position == 0
                    else legacy / media_storage_key(video_id)
                )
                parent.mkdir(parents=True, exist_ok=True)
                legacy_paths[video_id] = parent / f"{video_id}.json"
                legacy_paths[video_id].write_text("{}", encoding="utf-8")
            preferred = external / f"{video_ids[0]}.json"
            preferred.write_text("{}", encoding="utf-8")

            indexed = index_exact_transcript_candidates([external, legacy])

            self.assertEqual(
                indexed[video_ids[0]],
                [preferred, legacy_paths[video_ids[0]]],
            )
            self.assertEqual(
                indexed[video_ids[1]],
                [legacy_paths[video_ids[1]]],
            )

    def test_first_readable_transcript_falls_back_after_evicted_candidate(self):
        candidates = [Path("/external/video.json"), Path("/legacy/video.json")]
        original_open = Path.open

        def fake_open(path, *args, **kwargs):
            if path == candidates[0]:
                raise OSError(60, "Operation timed out")
            if path == candidates[1]:
                return mock.mock_open(read_data=b"{}")()
            return original_open(path, *args, **kwargs)

        with mock.patch.object(Path, "open", fake_open):
            selected = first_readable_transcript(candidates)

        self.assertEqual(selected, candidates[1])

    def test_portable_external_transcript_reference_uses_repository_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            cache = root / "cache"
            path = cache / "collision" / "BV1test.json"
            self.assertEqual(
                portable_transcript_reference(
                    path,
                    project_root=project,
                    cache_root=cache,
                ),
                "data/transcripts/bilibili/collision/BV1test.json",
            )

    def test_external_cache_locator_is_portable_across_cache_roots(self):
        video_id = "BV1DSNFz2Ets"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_root = root / "project"
            first_cache = root / "first-cache"
            relocated_cache = root / "relocated-cache"
            first_cache.mkdir()
            relocated_cache.mkdir()
            filename = f"{media_storage_key(video_id)}.m4a"
            original = first_cache / filename
            relocated = relocated_cache / filename
            original.write_bytes(b"original")
            relocated.write_bytes(b"relocated")

            locator = queue_media_locator(
                original,
                video_id,
                project_root=project_root,
            )
            original.unlink()
            resolved = resolve_queue_media_path(
                locator,
                video_id,
                project_root=project_root,
                cache_root=relocated_cache,
            )

            self.assertEqual(locator["media_cache_key"], filename)
            self.assertTrue(Path(locator["media_path"]).is_absolute())
            self.assertEqual(resolved, relocated)

    def test_cache_root_configuration_defaults_and_external_override(self):
        with tempfile.TemporaryDirectory() as directory:
            project_root = Path(directory) / "project"
            external = Path(directory) / "external"
            self.assertEqual(
                bilibili_media_cache_root(project_root, environ={}),
                project_root / "data" / "raw_videos" / "bilibili",
            )
            self.assertEqual(
                bilibili_media_cache_root(
                    project_root,
                    environ={BILIBILI_MEDIA_CACHE_ENV: str(external)},
                ),
                external,
            )

    def test_transcription_recovers_relocated_cache_from_portable_key(self):
        video_id = "BV1DSNFz2Ets"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media_dir = root / "relocated-cache"
            output_dir = root / "output"
            media_dir.mkdir()
            media = media_dir / f"{media_storage_key(video_id)}.m4a"
            media.write_bytes(b"relocated audio")
            queue = queue_payload(
                video_id,
                str(root / "evicted-cache" / media.name),
            )
            queue["items"][0]["media_cache_key"] = media.name
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
            )

            self.assertEqual(result["transcribed"], 1)
            payload = json.loads(
                (output_dir / f"{video_id}.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                payload["source_sha256"],
                media_fingerprint(media)["source_sha256"],
            )
            self.assertEqual(
                payload["source_file"],
                f"bilibili-media-cache/{media.name}",
            )
            updated = json.loads(queue_path.read_text(encoding="utf-8"))["items"][0]
            self.assertIsNone(updated["media_path"])
            self.assertNotIn("media_cache_key", updated)

    def test_external_transcript_cache_migrates_readable_legacy_completion(self):
        video_id = "BV16G411y7Rs"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media_dir = root / "media"
            external_output = root / "external-transcripts"
            legacy_output = root / "legacy-transcripts"
            media_dir.mkdir()
            legacy_output.mkdir()
            media = media_dir / f"{media_storage_key(video_id)}.m4a"
            media.write_bytes(b"audio")
            payload = {
                "video_id": video_id,
                "source_file": "data/raw_videos/bilibili/legacy.m4a",
                **media_fingerprint(media),
                "model": "small",
                "language": "zh",
                "language_probability": 1.0,
                "duration": 2.0,
                "segments": [{"start": 0.0, "end": 2.0, "text": "击球"}],
                "full_text": "击球",
            }
            write_transcript_outputs(legacy_output, payload)
            queue_path = root / "queue.json"
            queue_path.write_text(
                json.dumps(
                    queue_payload(video_id, str(media)),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = transcribe_directory(
                media_dir,
                external_output,
                queue_path=queue_path,
                fallback_output_dirs=[legacy_output],
                model_factory=lambda _name: (_ for _ in ()).throw(
                    AssertionError("readable legacy JSON must avoid ASR")
                ),
            )

            self.assertEqual(result["already_done"], 1)
            migrated = json.loads(
                next(external_output.rglob(f"{video_id}.json")).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(migrated["source_sha256"], payload["source_sha256"])

    def test_evicted_external_transcript_falls_back_to_legacy_completion(self):
        video_id = "BV16G411y7Rs"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media_dir = root / "media"
            external_output = root / "external-transcripts"
            legacy_output = root / "legacy-transcripts"
            media_dir.mkdir()
            external_output.mkdir()
            legacy_output.mkdir()
            media = media_dir / f"{media_storage_key(video_id)}.m4a"
            media.write_bytes(b"audio")
            payload = {
                "video_id": video_id,
                "source_file": "data/raw_videos/bilibili/legacy.m4a",
                **media_fingerprint(media),
                "model": "small",
                "language": "zh",
                "language_probability": 1.0,
                "duration": 2.0,
                "segments": [{"start": 0.0, "end": 2.0, "text": "击球"}],
                "full_text": "击球",
            }
            write_transcript_outputs(legacy_output, payload)
            evicted = external_output / f"{video_id}.json"
            evicted.write_text("placeholder", encoding="utf-8")
            queue_path = root / "queue.json"
            queue_path.write_text(
                json.dumps(queue_payload(video_id, str(media))),
                encoding="utf-8",
            )
            original_load = transcriber.load_valid_transcript

            def load_with_eviction(path, *args, **kwargs):
                if (
                    path.name == evicted.name
                    and "external-transcripts" in path.parts
                ):
                    raise OSError(60, "Operation timed out")
                return original_load(path, *args, **kwargs)

            with mock.patch.object(
                transcriber,
                "load_valid_transcript",
                side_effect=load_with_eviction,
            ):
                result = transcribe_directory(
                    media_dir,
                    external_output,
                    queue_path=queue_path,
                    fallback_output_dirs=[legacy_output],
                    model_factory=lambda _name: (_ for _ in ()).throw(
                        AssertionError("legacy fallback must avoid ASR")
                    ),
                )

            self.assertEqual(result["already_done"], 1)
            recovered = json.loads(evicted.read_text(encoding="utf-8"))
            self.assertEqual(recovered["full_text"], "击球")

    def test_portable_key_rejects_wrong_case_colliding_bvid(self):
        requested = "BV1DSNFz2Ets"
        other = "BV1DSNFz2ETs"
        item = {
            "media_cache_key": f"{media_storage_key(other)}.m4a",
        }
        with self.assertRaisesRegex(ValueError, "exact BVID"):
            resolve_queue_media_path(
                item,
                requested,
                project_root=Path("/project"),
                cache_root=Path("/cache"),
            )

    def test_queue_media_path_takes_identity_precedence_over_media_stem(self):
        video_id = "BV16G411y7Rs"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media_dir = root / "media"
            output_dir = root / "output"
            media_dir.mkdir()
            media = media_dir / "opaque-storage-key.m4a"
            media.write_bytes(b"audio")
            queue_path = root / "queue.json"
            queue_path.write_text(
                json.dumps(
                    queue_payload(video_id, str(media)),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = transcribe_directory(
                media_dir,
                output_dir,
                queue_path=queue_path,
                model_factory=lambda _name: FakeModel(),
            )

            self.assertEqual(result["transcribed"], 1)
            self.assertTrue((output_dir / f"{video_id}.json").exists())
            self.assertFalse((output_dir / "opaque-storage-key.json").exists())

    def test_case_colliding_bvids_use_exact_queue_media_mapping(self):
        video_ids = ["BV1DSNFz2ETs", "BV1DSNFz2Ets"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media_dir = root / "media"
            output_dir = root / "output"
            media_dir.mkdir()
            items = []
            for position, video_id in enumerate(video_ids, start=1):
                media = media_dir / f"{media_storage_key(video_id)}.m4a"
                media.write_bytes(f"audio-{position}".encode())
                items.append({
                    "video_id": video_id,
                    "status": "downloaded",
                    "media_path": str(media),
                    "attempts": 0,
                    "error": None,
                })
            queue_path = root / "queue.json"
            queue_path.write_text(
                json.dumps(
                    {
                        "items": items,
                        "counts": {"downloaded": 2},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = transcribe_directory(
                media_dir,
                output_dir,
                queue_path=queue_path,
                model_factory=lambda _name: FakeModel(),
            )

            self.assertEqual(set(result["failed_video_ids"]), set())
            self.assertEqual(result["transcribed"], 2)
            completion_markers = {
                path.name: json.loads(path.read_text(encoding="utf-8"))
                for path in output_dir.rglob("*.json")
            }
            self.assertEqual(
                set(completion_markers),
                {f"{video_id}.json" for video_id in video_ids},
            )
            for video_id in video_ids:
                self.assertEqual(
                    completion_markers[f"{video_id}.json"]["video_id"],
                    video_id,
                )
            self.assertEqual(
                len({path.parent for path in output_dir.rglob("*.json")}),
                2,
            )

    def test_legacy_exact_bvid_basename_still_maps_to_queue_video_id(self):
        video_id = "BV16G411y7Rs"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media_dir = root / "media"
            output_dir = root / "output"
            media_dir.mkdir()
            media = media_dir / f"{video_id}.m4a"
            media.write_bytes(b"legacy audio")
            queue_path = root / "queue.json"
            queue_path.write_text(
                json.dumps(
                    queue_payload(video_id, str(media)),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = transcribe_directory(
                media_dir,
                output_dir,
                queue_path=queue_path,
                model_factory=lambda _name: FakeModel(),
            )

            self.assertEqual(result["transcribed"], 1)
            payload = json.loads(
                (output_dir / f"{video_id}.json").read_text(encoding="utf-8")
            )
            self.assertEqual(payload["video_id"], video_id)

    def test_parallel_schedule_starts_longest_known_media_first(self):
        pending = [
            Path("short.m4a"),
            Path("unknown.m4a"),
            Path("long-b.m4a"),
            Path("long-a.m4a"),
        ]
        queue_items = {
            "short": {"media_duration_seconds": 30},
            "long-a": {"media_duration_seconds": 120},
            "long-b": {"media_duration_seconds": 120},
        }

        scheduled = transcriber.schedule_pending_media(pending, queue_items)

        self.assertEqual(
            [media.stem for media in scheduled],
            ["long-a", "long-b", "short", "unknown"],
        )

    def test_new_transcription_hashes_media_only_before_and_after_decode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media_dir = root / "media"
            output_dir = root / "output"
            media_dir.mkdir()
            (media_dir / "stable.m4a").write_bytes(b"audio")
            original_fingerprint = transcriber.media_fingerprint

            with mock.patch.object(
                transcriber,
                "media_fingerprint",
                wraps=original_fingerprint,
            ) as fingerprint:
                result = transcribe_directory(
                    media_dir,
                    output_dir,
                    model_factory=lambda _name: FakeModel(),
                )

            self.assertEqual(result["transcribed"], 1)
            self.assertEqual(fingerprint.call_count, 2)

    def test_media_changed_during_decode_is_rejected_without_a_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media_dir = root / "media"
            output_dir = root / "output"
            media_dir.mkdir()
            (media_dir / "mutable.m4a").write_bytes(b"original audio")

            result = transcribe_directory(
                media_dir,
                output_dir,
                model_factory=lambda _name: MutatingModel(),
            )

            self.assertEqual(result["transcribed"], 0)
            self.assertEqual(result["failed_video_ids"], ["mutable"])
            self.assertFalse((output_dir / "mutable.json").exists())

    def test_completed_worker_output_survives_queue_checkpoint_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media_dir = root / "media"
            output_dir = root / "output"
            media_dir.mkdir()
            media = media_dir / "recover-after-crash.m4a"
            media.write_bytes(b"audio")
            queue_path = root / "queue.json"
            queue_path.write_text(
                json.dumps(
                    queue_payload("recover-after-crash", str(media)),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with (
                mock.patch.object(
                    transcriber,
                    "save_queue",
                    side_effect=OSError("checkpoint unavailable"),
                ),
                self.assertRaisesRegex(OSError, "checkpoint unavailable"),
            ):
                transcribe_directory(
                    media_dir,
                    output_dir,
                    queue_path=queue_path,
                    model_factory=lambda _name: FakeModel(),
                )

            self.assertTrue((output_dir / "recover-after-crash.json").exists())

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

    def test_force_explicitly_retranscribes_a_completed_item_with_new_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media_dir = root / "media"
            output_dir = root / "output"
            media_dir.mkdir()
            media = media_dir / "completed.m4a"
            media.write_bytes(b"audio")
            queue = queue_payload(
                "completed",
                str(media),
                status="transcribed",
            )
            queue["items"][0].update(
                {
                    "media_sha256": media_fingerprint(media)["source_sha256"],
                    "media_bytes": media.stat().st_size,
                    "transcript_model": "small",
                }
            )
            queue_path = root / "queue.json"
            queue_path.write_text(json.dumps(queue), encoding="utf-8")
            old_payload = transcriber.payload_from_model(
                media,
                "small",
                FakeModel(),
                source_fingerprint=media_fingerprint(media),
                video_id="completed",
            )
            write_transcript_outputs(output_dir, old_payload)

            result = transcribe_directory(
                media_dir,
                output_dir,
                queue_path=queue_path,
                model_name="medium",
                model_factory=lambda _name: FakeModel(),
                video_ids=["completed"],
                force=True,
            )
            item = json.loads(queue_path.read_text(encoding="utf-8"))["items"][0]
            transcript = json.loads(
                (output_dir / "completed.json").read_text(encoding="utf-8")
            )

            self.assertEqual(result["transcribed"], 1)
            self.assertEqual(transcript["model"], "medium")
            self.assertEqual(item["transcript_model"], "medium")
            self.assertEqual(item["transcription_force_recoveries"], 1)
            self.assertNotIn("transcription_recovery_required_model", item)

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
