#!/usr/bin/env python3
import importlib.util
import json
import math
import os
import struct
import subprocess
import sys
import tempfile
import textwrap
import types
import unittest
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def load(name):
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(
        f"bilibili_recovery_contracts_{name}",
        path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BilibiliWriterLockTests(unittest.TestCase):
    def test_cross_process_writer_lock_rejects_a_second_owner(self):
        pipeline = load("bilibili_pipeline")
        holder_source = textwrap.dedent(
            """
            import sys
            from pathlib import Path
            import bilibili_pipeline

            bilibili_pipeline.PIPELINE_LOCK_PATH = Path(sys.argv[1])
            bilibili_pipeline.ROOT = bilibili_pipeline.PIPELINE_LOCK_PATH.parent
            handle = bilibili_pipeline.acquire_bilibili_pipeline_lock()
            print("locked", flush=True)
            sys.stdin.readline()
            """
        )
        contender_source = textwrap.dedent(
            """
            import sys
            from pathlib import Path
            import bilibili_pipeline

            bilibili_pipeline.PIPELINE_LOCK_PATH = Path(sys.argv[1])
            bilibili_pipeline.ROOT = bilibili_pipeline.PIPELINE_LOCK_PATH.parent
            try:
                handle = bilibili_pipeline.acquire_bilibili_pipeline_lock()
            except RuntimeError as error:
                print(str(error), file=sys.stderr)
                raise SystemExit(7)
            print("acquired")
            """
        )
        environment = dict(os.environ)
        environment.pop(pipeline.PIPELINE_LOCK_OWNER_ENV, None)
        environment["PYTHONPATH"] = os.pathsep.join(
            value
            for value in [str(SCRIPTS), environment.get("PYTHONPATH")]
            if value
        )
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "pipeline.lock"
            holder = subprocess.Popen(
                [sys.executable, "-c", holder_source, str(lock_path)],
                cwd=ROOT,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                self.assertEqual(holder.stdout.readline().strip(), "locked")
                blocked = subprocess.run(
                    [sys.executable, "-c", contender_source, str(lock_path)],
                    cwd=ROOT,
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                self.assertEqual(blocked.returncode, 7)
                self.assertIn("Another Bilibili pipeline writer", blocked.stderr)
            finally:
                if holder.stdin:
                    holder.stdin.close()
                holder.wait(timeout=5)
                holder_error = holder.stderr.read()
                holder.stdout.close()
                holder.stderr.close()
                if holder.returncode:
                    self.fail(holder_error)

            acquired = subprocess.run(
                [sys.executable, "-c", contender_source, str(lock_path)],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertEqual(acquired.returncode, 0, acquired.stderr)
            self.assertEqual(acquired.stdout.strip(), "acquired")


class BilibiliRetryStateTests(unittest.TestCase):
    def test_blocked_auth_is_nonterminal_and_force_can_resume_it(self):
        pipeline = load("bilibili_pipeline")
        processor = load("process_bilibili_candidates")
        bvid = "BV16G411y7Rs"
        record = pipeline.classify_video(
            pipeline.normalize_video(
                {
                    "bvid": bvid,
                    "title": "刘辉教练教你反手发力",
                }
            ),
            pipeline.load_rules(),
        )
        valid_metadata = {
            "id": bvid,
            "uploader": "大G羽毛球",
            "uploader_id": "1423436652",
            "title": "刘辉教练教你反手发力",
            "description": "刘辉教学直播切片",
            "tags": ["刘辉", "羽毛球教学"],
            "duration": 300.0,
            "webpage_url": f"https://www.bilibili.com/video/{bvid}/",
        }

        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            ledger_path = temporary / "ledger.json"
            queue_path = temporary / "queue.json"
            review_path = temporary / "review.json"
            transaction_path = temporary / ".transaction.json"
            ledger_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "platform": "bilibili",
                        "counts": {"candidate_liuhui_teaching": 1},
                        "videos": [record],
                    }
                ),
                encoding="utf-8",
            )
            queue_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "platform": "bilibili",
                        "counts": {},
                        "items": [],
                    }
                ),
                encoding="utf-8",
            )

            with (
                mock.patch.object(processor, "LEDGER_PATH", ledger_path),
                mock.patch.object(processor, "QUEUE_PATH", queue_path),
                mock.patch.object(processor, "REVIEW_PATH", review_path),
                mock.patch.object(
                    processor,
                    "TRANSACTION_PATH",
                    transaction_path,
                ),
                mock.patch.object(
                    processor,
                    "acquire_bilibili_pipeline_lock",
                    return_value=object(),
                ),
                mock.patch.object(
                    processor,
                    "extract_metadata",
                    side_effect=RuntimeError("HTTP Error 403: login required"),
                ),
                mock.patch.object(
                    sys,
                    "argv",
                    ["process_bilibili_candidates.py", "--bvid", bvid],
                ),
            ):
                self.assertEqual(processor.main(), 1)

            blocked = json.loads(ledger_path.read_text(encoding="utf-8"))[
                "videos"
            ][0]
            self.assertEqual(
                blocked["processing_state"]["stage"],
                "blocked_auth",
            )
            self.assertFalse(blocked["processing_state"]["terminal"])
            self.assertEqual(
                blocked["processing_state"]["attempts_by_stage"]["acquisition"],
                1,
            )
            self.assertIsNotNone(blocked["processing_state"]["next_retry_at"])

            with (
                mock.patch.object(processor, "LEDGER_PATH", ledger_path),
                mock.patch.object(processor, "QUEUE_PATH", queue_path),
                mock.patch.object(processor, "REVIEW_PATH", review_path),
                mock.patch.object(
                    processor,
                    "TRANSACTION_PATH",
                    transaction_path,
                ),
                mock.patch.object(
                    processor,
                    "acquire_bilibili_pipeline_lock",
                    return_value=object(),
                ),
                mock.patch.object(
                    processor,
                    "extract_metadata",
                    return_value=valid_metadata,
                ),
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "process_bilibili_candidates.py",
                        "--bvid",
                        bvid,
                        "--force",
                        "--metadata-only",
                    ],
                ),
            ):
                self.assertEqual(processor.main(), 0)

            resumed = json.loads(ledger_path.read_text(encoding="utf-8"))[
                "videos"
            ][0]
            self.assertEqual(
                resumed["processing_state"]["stage"],
                "metadata_ready",
            )
            self.assertFalse(resumed["processing_state"]["terminal"])
            self.assertIsNone(resumed["processing_state"]["next_retry_at"])
            self.assertTrue(resumed["knowledge_admission_eligible"])

    def test_acquisition_preserves_transcription_retry_and_quarantine_states(self):
        processor = load("process_bilibili_candidates")
        bvid = "BV16G411y7Rs"
        for status in ["transcription_failed", "transcription_quarantined"]:
            with self.subTest(status=status):
                ledger = {
                    "videos": [
                        {
                            "bvid": bvid,
                            "video_id": f"bilibili:{bvid}",
                            "url": f"https://www.bilibili.com/video/{bvid}/",
                            "decision": "candidate_liuhui_teaching",
                            "knowledge_admission_eligible": True,
                            "origin_verification": {
                                "status": "verified_liuhui_clip",
                                "source_metadata": {"duration_seconds": 10.0},
                            },
                            "processing_state": {
                                "stage": status,
                                "terminal": False,
                            },
                        }
                    ]
                }
                queue = {
                    "items": [
                        {
                            "video_id": bvid,
                            "status": status,
                            "media_path": f"data/raw_videos/bilibili/{bvid}.m4a",
                            "transcription_attempts": 2,
                            "transcription_retry_attempts": 2,
                            "attempts": 2,
                        }
                    ]
                }
                persisted = {}

                def fake_load(path):
                    return ledger if path == processor.LEDGER_PATH else queue

                def fake_persist(saved_ledger, saved_queue):
                    persisted["ledger"] = saved_ledger
                    persisted["queue"] = saved_queue

                with (
                    mock.patch.object(
                        processor,
                        "acquire_bilibili_pipeline_lock",
                        return_value=object(),
                    ),
                    mock.patch.object(processor, "load_json", side_effect=fake_load),
                    mock.patch.object(
                        processor,
                        "may_enter_knowledge_base",
                        return_value=True,
                    ),
                    mock.patch.object(
                        processor,
                        "media_validation_is_current",
                        return_value=True,
                    ),
                    mock.patch.object(processor, "persist", side_effect=fake_persist),
                    mock.patch.object(
                        sys,
                        "argv",
                        ["process_bilibili_candidates.py", "--bvid", bvid],
                    ),
                ):
                    exit_code = processor.main()

                saved_item = persisted["queue"]["items"][0]
                self.assertEqual(exit_code, 0)
                self.assertEqual(saved_item["status"], status)
                self.assertEqual(saved_item["transcription_attempts"], 2)
                self.assertEqual(saved_item["transcription_retry_attempts"], 2)


class BilibiliOrchestratorContractTests(unittest.TestCase):
    def setUp(self):
        self.orchestrator = load("run_bilibili_update_pipeline")
        self.incomplete_status = {
            "bilibili": {
                "all_videos_terminal": False,
                "pending_videos": 1,
                "installed_matches_repo": False,
            }
        }

    def run_main(self, arguments, *, status=None):
        commands = []

        def fake_run(command, **_kwargs):
            normalized = [str(part) for part in command]
            commands.append(normalized)
            if "--validation-receipt" in normalized:
                receipt = Path(
                    normalized[normalized.index("--validation-receipt") + 1]
                )
                receipt.write_text(
                    json.dumps({"schema_version": 1, "build_id": "a" * 64}),
                    encoding="utf-8",
                )
            return 0

        with (
            mock.patch.object(
                self.orchestrator,
                "acquire_bilibili_pipeline_lock",
                return_value=object(),
            ),
            mock.patch.object(self.orchestrator, "run", side_effect=fake_run),
            mock.patch.object(
                self.orchestrator,
                "load_status",
                return_value=status or self.incomplete_status,
            ),
            mock.patch.object(
                sys,
                "argv",
                ["run_bilibili_update_pipeline.py", *arguments],
            ),
            mock.patch.dict(os.environ, {}, clear=False),
        ):
            return self.orchestrator.main(), commands

    def test_incomplete_is_nonzero_by_default_but_allow_partial_is_zero(self):
        common = [
            "--skip-ingest",
            "--skip-acquisition",
            "--skip-transcription",
            "--skip-release",
        ]
        exit_code, _ = self.run_main(common)
        self.assertEqual(exit_code, 2)
        exit_code, _ = self.run_main([*common, "--allow-partial"])
        self.assertEqual(exit_code, 0)

    def test_skip_release_cannot_be_combined_with_install(self):
        with (
            mock.patch.object(
                sys,
                "argv",
                [
                    "run_bilibili_update_pipeline.py",
                    "--install",
                    "--skip-release",
                ],
            ),
            self.assertRaises(SystemExit) as raised,
        ):
            self.orchestrator.main()
        self.assertEqual(raised.exception.code, 2)

    def test_partial_status_refuses_install_before_install_command(self):
        commands = []

        def fake_run(command, **_kwargs):
            normalized = [str(part) for part in command]
            commands.append(normalized)
            if "--validation-receipt" in normalized:
                receipt = Path(
                    normalized[normalized.index("--validation-receipt") + 1]
                )
                receipt.write_text(
                    json.dumps({"schema_version": 1, "build_id": "a" * 64}),
                    encoding="utf-8",
                )
            return 0

        with (
            mock.patch.object(
                self.orchestrator,
                "acquire_bilibili_pipeline_lock",
                return_value=object(),
            ),
            mock.patch.object(self.orchestrator, "run", side_effect=fake_run),
            mock.patch.object(
                self.orchestrator,
                "load_status",
                return_value=self.incomplete_status,
            ),
            mock.patch.object(
                sys,
                "argv",
                [
                    "run_bilibili_update_pipeline.py",
                    "--skip-ingest",
                    "--skip-acquisition",
                    "--allow-partial",
                    "--install",
                ],
            ),
            mock.patch.dict(os.environ, {}, clear=False),
            self.assertRaisesRegex(RuntimeError, "Refusing to install"),
        ):
            self.orchestrator.main()
        self.assertFalse(
            any("scripts/install_skill.py" in command for command in commands)
        )

    def test_install_is_bound_to_the_build_validated_in_this_run(self):
        build_id = "a" * 64
        statuses = [
            {
                "bilibili": {
                    "all_videos_terminal": True,
                    "repo_build_id": build_id,
                    "installed_matches_repo": False,
                }
            },
            {
                "bilibili": {
                    "all_videos_terminal": True,
                    "repo_build_id": build_id,
                    "installed_matches_repo": True,
                }
            },
        ]
        commands = []

        def fake_run(command, **_kwargs):
            normalized = [str(part) for part in command]
            commands.append(normalized)
            if "--validation-receipt" in normalized:
                receipt = Path(
                    normalized[normalized.index("--validation-receipt") + 1]
                )
                receipt.write_text(
                    json.dumps({"schema_version": 1, "build_id": "a" * 64}),
                    encoding="utf-8",
                )
            return 0

        with (
            mock.patch.object(
                self.orchestrator,
                "acquire_bilibili_pipeline_lock",
                return_value=object(),
            ),
            mock.patch.object(self.orchestrator, "run", side_effect=fake_run),
            mock.patch.object(
                self.orchestrator,
                "load_status",
                side_effect=statuses,
            ),
            mock.patch.object(
                sys,
                "argv",
                [
                    "run_bilibili_update_pipeline.py",
                    "--skip-ingest",
                    "--skip-acquisition",
                    "--install",
                ],
            ),
            mock.patch.dict(os.environ, {}, clear=False),
        ):
            exit_code = self.orchestrator.main()

        self.assertEqual(exit_code, 0)
        release_index = next(
            index
            for index, command in enumerate(commands)
            if "scripts/run_full_update_pipeline.py" in command
        )
        install_index = next(
            index
            for index, command in enumerate(commands)
            if "scripts/install_skill.py" in command
        )
        self.assertLess(release_index, install_index)
        self.assertEqual(
            commands[install_index],
            [
                sys.executable,
                "scripts/install_skill.py",
                "--destination",
                str(self.orchestrator.default_install_destination()),
                "--expected-build-id",
                build_id,
            ],
        )
        doctor_command = next(
            command
            for command in commands
            if "skills/liuhui-badminton-coach/scripts/doctor.py" in command
        )
        self.assertEqual(
            doctor_command[-2:],
            [
                "--skill-root",
                str(self.orchestrator.default_install_destination()),
            ],
        )

    def test_terminal_status_without_valid_build_id_refuses_install(self):
        status = {
            "bilibili": {
                "all_videos_terminal": True,
                "repo_build_id": "not-a-build-id",
                "installed_matches_repo": False,
            }
        }
        with self.assertRaisesRegex(RuntimeError, "valid build_id"):
            self.run_main(
                [
                    "--skip-ingest",
                    "--skip-acquisition",
                    "--install",
                ],
                status=status,
            )

    def test_repository_build_change_after_validation_refuses_install(self):
        status = {
            "bilibili": {
                "all_videos_terminal": True,
                "repo_build_id": "b" * 64,
                "installed_matches_repo": False,
            }
        }
        with self.assertRaisesRegex(RuntimeError, "Refusing to install"):
            self.run_main(
                [
                    "--skip-ingest",
                    "--skip-acquisition",
                    "--install",
                ],
                status=status,
            )

    def test_failed_release_validation_never_runs_install(self):
        commands = []

        def fake_run(command, **_kwargs):
            normalized = [str(part) for part in command]
            commands.append(normalized)
            if "scripts/run_full_update_pipeline.py" in normalized:
                raise subprocess.CalledProcessError(1, normalized)
            return 0

        with (
            mock.patch.object(
                self.orchestrator,
                "acquire_bilibili_pipeline_lock",
                return_value=object(),
            ),
            mock.patch.object(self.orchestrator, "run", side_effect=fake_run),
            mock.patch.object(
                sys,
                "argv",
                [
                    "run_bilibili_update_pipeline.py",
                    "--skip-ingest",
                    "--skip-acquisition",
                    "--install",
                ],
            ),
            mock.patch.dict(os.environ, {}, clear=False),
            self.assertRaises(subprocess.CalledProcessError),
        ):
            self.orchestrator.main()
        self.assertFalse(
            any("scripts/install_skill.py" in command for command in commands)
        )

    def test_success_exit_without_validation_receipt_never_runs_install(self):
        commands = []

        def fake_run(command, **_kwargs):
            commands.append([str(part) for part in command])
            return 0

        with (
            mock.patch.object(
                self.orchestrator,
                "acquire_bilibili_pipeline_lock",
                return_value=object(),
            ),
            mock.patch.object(self.orchestrator, "run", side_effect=fake_run),
            mock.patch.object(
                sys,
                "argv",
                [
                    "run_bilibili_update_pipeline.py",
                    "--skip-ingest",
                    "--skip-acquisition",
                    "--install",
                ],
            ),
            mock.patch.dict(os.environ, {}, clear=False),
            self.assertRaisesRegex(RuntimeError, "no readable build receipt"),
        ):
            self.orchestrator.main()
        self.assertFalse(
            any("scripts/install_skill.py" in command for command in commands)
        )


@unittest.skipUnless(
    importlib.util.find_spec("av"),
    "PyAV maintainer dependency is not installed",
)
class BilibiliPyAVMediaTests(unittest.TestCase):
    @staticmethod
    def write_audio(path):
        import av

        with av.open(str(path), "w") as output:
            stream = output.add_stream("aac", rate=16_000)
            stream.layout = "mono"
            pts = 0
            for _ in range(64):
                frame = av.AudioFrame(format="fltp", layout="mono", samples=1_024)
                frame.sample_rate = 16_000
                frame.time_base = Fraction(1, 16_000)
                frame.pts = pts
                samples = [
                    0.3
                    * math.sin(
                        2
                        * math.pi
                        * (440 + 37 * math.sin((pts + index) / 777))
                        * ((pts + index) / 16_000)
                    )
                    for index in range(1_024)
                ]
                frame.planes[0].update(struct.pack("<1024f", *samples))
                pts += 1_024
                for packet in stream.encode(frame):
                    output.mux(packet)
            for packet in stream.encode(None):
                output.mux(packet)

    @staticmethod
    def write_video_only(path):
        import av

        with av.open(str(path), "w") as output:
            stream = output.add_stream("mpeg4", rate=10)
            stream.width = 64
            stream.height = 64
            stream.pix_fmt = "yuv420p"
            for index in range(20):
                frame = av.VideoFrame(64, 64, "yuv420p")
                frame.pts = index
                frame.time_base = Fraction(1, 10)
                for plane in frame.planes:
                    plane.update(os.urandom(plane.buffer_size))
                for packet in stream.encode(frame):
                    output.mux(packet)
            for packet in stream.encode(None):
                output.mux(packet)

    def test_valid_audio_is_fully_decoded(self):
        candidates = load("process_bilibili_candidates")
        with tempfile.TemporaryDirectory() as directory:
            media_path = Path(directory) / "valid.m4a"
            self.write_audio(media_path)

            result = candidates.validate_media(media_path, expected_duration=4.096)

            self.assertEqual(result["media_validation_version"], 2)
            self.assertEqual(result["media_codec"], "aac")
            self.assertEqual(result["media_sample_rate"], 16_000)
            self.assertGreater(result["media_packet_count"], 0)
            self.assertGreater(result["media_decoded_frame_count"], 0)
            self.assertGreater(result["media_decoded_samples"], 0)
            self.assertAlmostEqual(
                result["media_duration_seconds"],
                4.096,
                delta=0.2,
            )

    def test_truncated_audio_fails_stream_decode(self):
        candidates = load("process_bilibili_candidates")
        with tempfile.TemporaryDirectory() as directory:
            valid_path = Path(directory) / "valid.m4a"
            truncated_path = Path(directory) / "truncated.m4a"
            self.write_audio(valid_path)
            valid_bytes = valid_path.read_bytes()
            truncated_path.write_bytes(valid_bytes[: len(valid_bytes) // 2])

            with self.assertRaisesRegex(
                RuntimeError,
                "audio decode failed|decoded audio",
            ):
                candidates.validate_media(truncated_path)

    def test_video_without_audio_is_rejected(self):
        candidates = load("process_bilibili_candidates")
        with tempfile.TemporaryDirectory() as directory:
            media_path = Path(directory) / "video_only.mp4"
            self.write_video_only(media_path)

            with self.assertRaisesRegex(RuntimeError, "no readable audio stream"):
                candidates.validate_media(media_path)

    def test_completed_media_quarantines_then_redownloads_corruption(self):
        candidates = load("process_bilibili_candidates")
        bvid = "BV16G411y7Rs"
        with tempfile.TemporaryDirectory() as directory:
            raw_root = Path(directory)
            media_path = raw_root / f"{bvid}.m4a"
            self.write_audio(media_path)
            valid_bytes = media_path.read_bytes()
            media_path.write_bytes(valid_bytes[: len(valid_bytes) // 2])

            class FakeYoutubeDL:
                def __init__(self, _options):
                    pass

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

                def download(self, _urls):
                    BilibiliPyAVMediaTests.write_audio(media_path)

            with (
                mock.patch.object(candidates, "RAW_ROOT", raw_root),
                mock.patch.dict(
                    sys.modules,
                    {"yt_dlp": types.SimpleNamespace(YoutubeDL=FakeYoutubeDL)},
                ),
            ):
                recovered_path, result = candidates.download_audio(
                    "https://www.bilibili.com/video/BV16G411y7Rs/",
                    bvid,
                    expected_duration=4.096,
                )

            self.assertEqual(recovered_path, media_path)
            self.assertEqual(result["media_validation_version"], 2)
            self.assertGreater(result["media_decoded_frame_count"], 0)
            quarantined = list((raw_root / "quarantine").glob(f"{bvid}.*.invalid"))
            self.assertEqual(len(quarantined), 1)
            self.assertEqual(
                quarantined[0].read_bytes(),
                valid_bytes[: len(valid_bytes) // 2],
            )


class BilibiliArchiveEvidenceTests(unittest.TestCase):
    def test_full_page_content_hash_is_bound_to_page_membership(self):
        updates = load("check_bilibili_updates")
        now = datetime(2026, 7, 28, tzinfo=timezone.utc)
        bvids = [
            "BV16G411y7Rs",
            "BV1aw411179M",
            "BV1TT411r7Ft",
        ]
        payload = {
            "profile_id": "1423436652",
            "profile_url": "https://space.bilibili.com/1423436652",
            "collected_at": (now - timedelta(hours=1)).isoformat(),
            "collected_unique_links": 3,
            "full_profile_archive": True,
            "profile_reported_video_count": 3,
            "profile_pages_complete": True,
            "profile_pages": [
                {
                    "page": 1,
                    "count": 3,
                    "first_bvid": bvids[0],
                    "last_bvid": bvids[-1],
                    "bvid_sha256": "a" * 64,
                    "sorted_bvid_sha256":
                        updates.page_bvid_content_sha256(bvids),
                }
            ],
            "coverage": {
                "profile_pages": 1,
                "profile_reported_video_count": 3,
                "profile_collected_count": 3,
                "profile_unique_videos": 3,
            },
            "videos": [
                {"bvid": bvid, "profile_page": 1}
                for bvid in bvids
            ],
        }
        source = {
            "profile_id": "1423436652",
            "snapshot": {"max_age_hours": 24, "min_observed_links": 3},
        }
        updates.validate_snapshot(payload, source, now)

        payload["videos"][1]["bvid"] = "BV11F411D7s4"
        with self.assertRaisesRegex(ValueError, "content hash"):
            updates.validate_snapshot(payload, source, now)


if __name__ == "__main__":
    unittest.main()
