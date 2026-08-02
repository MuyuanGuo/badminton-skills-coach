#!/usr/bin/env python3
import copy
import hashlib
import importlib.util
import json
import math
import os
import struct
import subprocess
import sys
import tempfile
import textwrap
import threading
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
    def test_force_reacquires_transcribed_item_for_quality_recovery(self):
        processor = load("process_bilibili_candidates")
        bvid = "BV16G411y7Rs"
        verification = {
            "status": "verified_collection_policy",
            "source_metadata": {
                "title": "反手发力",
                "description": "",
                "tags": [],
                "duration_seconds": 10.0,
            },
        }
        record = {
            "bvid": bvid,
            "video_id": f"bilibili:{bvid}",
            "url": f"https://www.bilibili.com/video/{bvid}/",
            "title": "反手发力",
            "decision": "required_transcription_policy",
            "collection_policy": {"basis": "collection"},
            "classification_rules_version": 3,
            "classification_rules_hash": "a" * 64,
            "knowledge_admission_eligible": True,
            "origin_verification": verification,
        }
        existing = {
            "video_id": bvid,
            "status": "transcribed",
            "transcript_model": "small",
            "attempts": 0,
            "media_sha256": "old",
        }
        validation = {
            "media_bytes": 8192,
            "media_sha256": "b" * 64,
            "media_validation_version": 2,
            "media_decoded_frame_count": 10,
            "media_decoded_samples": 1024,
            "media_duration_seconds": 10.0,
        }
        with (
            mock.patch.object(
                processor, "may_enter_knowledge_base", return_value=True
            ),
            mock.patch.object(
                processor,
                "completed_media",
                return_value=(
                    Path("/tmp")
                    / f"{processor.media_storage_key(bvid)}.m4a",
                    validation,
                ),
            ),
        ):
            outcome = processor.process_candidate(
                record,
                existing,
                metadata_only=False,
                cooldown_minutes=30,
                force_reacquire=True,
            )

        item = outcome["queue_item"]
        self.assertEqual(outcome["result"]["status"], "downloaded")
        self.assertTrue(outcome["result"]["media_reused"])
        self.assertEqual(
            item["media_recovery_audit"][-1]["reason"],
            "forced_transcript_quality_recovery",
        )
        self.assertEqual(item["transcription_force_recoveries"], 1)

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


class BilibiliParallelAcquisitionTests(unittest.TestCase):
    @staticmethod
    def record(bvid):
        return {
            "bvid": bvid,
            "video_id": f"bilibili:{bvid}",
            "url": f"https://www.bilibili.com/video/{bvid}/",
            "title": f"教学 {bvid}",
            "decision": "required_transcription_policy",
            "collection_policy": {"basis": "collection"},
            "classification_rules_version": 3,
            "classification_rules_hash": "a" * 64,
            "knowledge_admission_eligible": True,
            "origin_verification": {
                "status": "verified_collection_policy",
                "source_metadata": {
                    "title": f"教学 {bvid}",
                    "description": "",
                    "tags": [],
                    "duration_seconds": 10.0,
                },
            },
            "processing_state": {
                "stage": "metadata_ready",
                "terminal": False,
            },
        }

    def test_workers_acquire_in_parallel_but_main_thread_alone_persists(self):
        processor = load("process_bilibili_candidates")
        bvids = ["BV16G411y7Rs", "BV1aw411179M"]
        ledger = {
            "version": 1,
            "platform": "bilibili",
            "counts": {"required_transcription_policy": 2},
            "videos": [self.record(bvid) for bvid in bvids],
        }
        queue = {
            "version": 1,
            "platform": "bilibili",
            "counts": {},
            "items": [],
        }
        barrier = threading.Barrier(2)
        download_threads = set()
        persist_threads = []
        snapshots = []
        main_thread = threading.get_ident()

        def fake_download(_url, bvid, _duration, metadata_info=None):
            self.assertIsNone(metadata_info)
            download_threads.add(threading.get_ident())
            barrier.wait(timeout=2)
            return (
                processor.RAW_ROOT / f"{bvid}.m4a",
                {
                    "media_bytes": 8192,
                    "media_sha256": bvid.lower().ljust(64, "0")[:64],
                },
            )

        def fake_load(path):
            if path == processor.LEDGER_PATH:
                return ledger
            if path == processor.QUEUE_PATH:
                return queue
            raise AssertionError(path)

        def fake_persist(saved_ledger, saved_queue):
            persist_threads.append(threading.get_ident())
            snapshots.append(
                (
                    copy.deepcopy(saved_ledger),
                    copy.deepcopy(saved_queue),
                )
            )

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
            mock.patch.object(processor, "download_audio", side_effect=fake_download),
            mock.patch.object(processor, "persist", side_effect=fake_persist),
            mock.patch.object(
                sys,
                "argv",
                [
                    "process_bilibili_candidates.py",
                    "--max-items",
                    "2",
                    "--checkpoint-every",
                    "1",
                    "--download-workers",
                    "2",
                ],
            ),
        ):
            exit_code = processor.main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(download_threads), 2)
        self.assertNotIn(main_thread, download_threads)
        self.assertTrue(persist_threads)
        self.assertEqual(set(persist_threads), {main_thread})
        self.assertEqual(
            {item["video_id"] for item in snapshots[-1][1]["items"]},
            set(bvids),
        )

    def test_current_downloaded_queue_item_is_never_downloaded_again(self):
        processor = load("process_bilibili_candidates")
        record = self.record("BV16G411y7Rs")
        existing = {
            "video_id": record["bvid"],
            "status": "downloaded",
            "media_path": f"data/raw_videos/bilibili/{record['bvid']}.m4a",
        }
        with (
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
            mock.patch.object(
                processor,
                "download_audio",
                side_effect=AssertionError("duplicate download"),
            ),
        ):
            outcome = processor.process_candidate(
                copy.deepcopy(record),
                copy.deepcopy(existing),
                metadata_only=False,
                cooldown_minutes=30,
            )
        self.assertEqual(outcome["result"]["status"], "already_downloaded")
        self.assertEqual(outcome["queue_item"]["status"], "downloaded")


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

    def test_download_worker_limit_is_forwarded_to_acquisition(self):
        exit_code, commands = self.run_main(
            [
                "--skip-ingest",
                "--skip-transcription",
                "--skip-release",
                "--allow-partial",
                "--download-workers",
                "4",
            ]
        )
        acquisition = next(
            command
            for command in commands
            if "scripts/process_bilibili_candidates.py" in command
        )
        self.assertEqual(
            acquisition[acquisition.index("--download-workers") + 1],
            "4",
        )
        self.assertEqual(exit_code, 0)

    def test_external_media_cache_is_forwarded_to_acquisition_and_transcription(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_root = Path(directory) / "bilibili-cache"
            transcript_root = Path(directory) / "transcript-cache"
            exit_code, commands = self.run_main(
                [
                    "--skip-ingest",
                    "--skip-release",
                    "--allow-partial",
                    "--media-cache-dir",
                    str(cache_root),
                    "--transcript-cache-dir",
                    str(transcript_root),
                ]
            )

        acquisition = next(
            command
            for command in commands
            if "scripts/process_bilibili_candidates.py" in command
            and "--existing-queue-only" not in command
        )
        transcription = next(
            command
            for command in commands
            if "scripts/batch_transcribe_directory.py" in command
        )
        self.assertEqual(
            acquisition[acquisition.index("--media-cache-dir") + 1],
            str(cache_root),
        )
        self.assertEqual(transcription[2], str(cache_root))
        self.assertEqual(
            transcription[
                transcription.index("--output-dir") + 1
            ],
            str(transcript_root),
        )
        self.assertEqual(
            transcription[
                transcription.index("--fallback-output-dir") + 1
            ],
            str(
                self.orchestrator.ROOT
                / "data"
                / "transcripts"
                / "bilibili"
            ),
        )
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


class BilibiliCollisionSafeStorageTests(unittest.TestCase):
    def test_force_reuses_completed_media_for_a_transcribed_item(self):
        candidates = load("process_bilibili_candidates")
        video_id = "BV1DSNFz2Ets"
        record = BilibiliParallelAcquisitionTests.record(video_id)
        existing = {
            "video_id": video_id,
            "status": "transcribed",
            "media_path": None,
            "attempts": 2,
            "transcription_attempts": 1,
        }
        media = Path(f"/tmp/{video_id}.m4a")
        validation = {"media_bytes": 9000, "media_sha256": "b" * 64}
        with (
            mock.patch.object(
                candidates, "may_enter_knowledge_base", return_value=True
            ),
            mock.patch.object(
                candidates, "completed_media", return_value=(media, validation)
            ),
            mock.patch.object(candidates, "download_audio") as download,
        ):
            outcome = candidates.process_candidate(
                copy.deepcopy(record),
                copy.deepcopy(existing),
                metadata_only=False,
                cooldown_minutes=30,
                force_reacquire=True,
            )

        download.assert_not_called()
        self.assertEqual(outcome["result"]["status"], "downloaded")
        self.assertTrue(outcome["result"]["media_reused"])
        self.assertEqual(outcome["queue_item"]["status"], "downloaded")
        self.assertEqual(
            outcome["queue_item"]["media_recovery_audit"][-1]["reason"],
            "forced_transcript_quality_recovery",
        )

    def test_explicit_force_relocates_failed_media_and_preserves_asr_audit(self):
        candidates = load("process_bilibili_candidates")
        storage = load("bilibili_storage")
        video_id = "BV1DSNFz2Ets"
        record = BilibiliParallelAcquisitionTests.record(video_id)
        validation = {
            "media_bytes": 9000,
            "media_sha256": "b" * 64,
        }
        with tempfile.TemporaryDirectory() as directory:
            project_root = Path(directory) / "project"
            old_cache = project_root / "legacy-cache"
            external_cache = Path(directory) / "media-cache"
            old_cache.mkdir(parents=True)
            filename = f"{storage.media_storage_key(video_id)}.m4a"
            old_media = old_cache / filename
            old_media.write_bytes(b"legacy")
            existing = {
                "video_id": video_id,
                "status": "transcription_failed",
                "media_path": f"legacy-cache/{filename}",
                "media_cache_key": filename,
                "media_sha256": "a" * 64,
                "media_bytes": 8192,
                "attempts": 4,
                "transcription_attempts": 2,
                "transcription_retry_attempts": 2,
                "media_recoveries": 1,
            }
            replacement = (
                external_cache
                / filename
            )
            with (
                mock.patch.object(candidates, "ROOT", project_root),
                mock.patch.object(candidates, "RAW_ROOT", external_cache),
                mock.patch.object(
                    candidates,
                    "may_enter_knowledge_base",
                    return_value=True,
                ),
                mock.patch.object(
                    candidates,
                    "media_validation_is_current",
                    return_value=True,
                ),
                mock.patch.object(
                    candidates,
                    "download_audio",
                    return_value=(replacement, validation),
                ) as download,
            ):
                outcome = candidates.process_candidate(
                    copy.deepcopy(record),
                    copy.deepcopy(existing),
                    metadata_only=False,
                    cooldown_minutes=30,
                    force_reacquire=True,
                )

        download.assert_called_once()
        item = outcome["queue_item"]
        self.assertEqual(outcome["result"]["status"], "downloaded")
        self.assertEqual(item["status"], "downloaded")
        self.assertEqual(item["attempts"], 4)
        self.assertEqual(item["transcription_attempts"], 2)
        self.assertEqual(item["transcription_retry_attempts"], 0)
        self.assertEqual(item["media_recoveries"], 2)
        self.assertEqual(item["transcription_force_recoveries"], 1)
        self.assertEqual(
            item["media_recovery_audit"][-1]["reason"],
            "external_cache_relocation",
        )
        self.assertEqual(
            item["media_recovery_audit"][-1][
                "transcription_retry_attempts"
            ],
            2,
        )

    def test_explicit_force_reacquires_hash_mismatch_inside_active_cache(self):
        candidates = load("process_bilibili_candidates")
        storage = load("bilibili_storage")
        video_id = "BV1DSNFz2Ets"
        record = BilibiliParallelAcquisitionTests.record(video_id)
        validation = {
            "media_bytes": 9000,
            "media_sha256": "b" * 64,
        }
        with tempfile.TemporaryDirectory() as directory:
            project_root = Path(directory) / "project"
            cache_root = Path(directory) / "media-cache"
            cache_root.mkdir()
            filename = f"{storage.media_storage_key(video_id)}.m4a"
            media = cache_root / filename
            media.write_bytes(b"stale")
            existing = {
                "video_id": video_id,
                "status": "transcription_failed",
                "media_path": str(media),
                "media_cache_key": filename,
                "media_sha256": "a" * 64,
                "media_bytes": 8192,
                "attempts": 2,
                "transcription_attempts": 1,
                "transcription_retry_attempts": 1,
            }
            with (
                mock.patch.object(candidates, "ROOT", project_root),
                mock.patch.object(candidates, "RAW_ROOT", cache_root),
                mock.patch.object(
                    candidates,
                    "may_enter_knowledge_base",
                    return_value=True,
                ),
                mock.patch.object(
                    candidates,
                    "media_validation_is_current",
                    return_value=False,
                ),
                mock.patch.object(
                    candidates,
                    "validate_media",
                ) as validate,
                mock.patch.object(
                    candidates,
                    "download_audio",
                    return_value=(media, validation),
                ) as download,
            ):
                outcome = candidates.process_candidate(
                    copy.deepcopy(record),
                    copy.deepcopy(existing),
                    metadata_only=False,
                    cooldown_minutes=30,
                    force_reacquire=True,
                )

        validate.assert_not_called()
        download.assert_called_once()
        self.assertEqual(outcome["result"]["status"], "downloaded")
        self.assertEqual(
            outcome["queue_item"]["media_recovery_audit"][-1]["reason"],
            "forced_media_integrity_reacquisition",
        )
        self.assertEqual(
            outcome["queue_item"]["transcription_attempts"],
            1,
        )

    def test_external_media_queue_item_keeps_portable_cache_key(self):
        candidates = load("process_bilibili_candidates")
        storage = load("bilibili_storage")
        video_id = "BV1DSNFz2Ets"
        record = BilibiliParallelAcquisitionTests.record(video_id)
        verification = record["origin_verification"]
        with tempfile.TemporaryDirectory() as directory:
            cache_root = Path(directory) / "cache"
            cache_root.mkdir()
            media = cache_root / f"{storage.media_storage_key(video_id)}.m4a"
            media.write_bytes(b"audio")
            item = candidates.queue_item(
                record,
                verification,
                media,
                {
                    "media_bytes": 5,
                    "media_sha256": hashlib.sha256(b"audio").hexdigest(),
                },
            )
            with mock.patch.object(candidates, "RAW_ROOT", cache_root):
                resolved = candidates.queued_media_path(item, video_id)

        self.assertTrue(Path(item["media_path"]).is_absolute())
        self.assertEqual(item["media_cache_key"], media.name)
        self.assertEqual(resolved, media)

    def test_case_colliding_ids_download_to_distinct_paths_and_deduplicate(self):
        candidates = load("process_bilibili_candidates")
        storage = load("bilibili_storage")
        video_ids = ["BV1DSNFz2ETs", "BV1DSNFz2Ets"]
        self.assertNotEqual(
            storage.media_storage_key(video_ids[0]).casefold(),
            storage.media_storage_key(video_ids[1]).casefold(),
        )

        with tempfile.TemporaryDirectory() as directory:
            raw_root = Path(directory)
            downloads = []

            class FakeYoutubeDL:
                def __init__(self, options):
                    self.options = options

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

                def download(self, _urls):
                    target = Path(
                        self.options["outtmpl"].replace("%(ext)s", "m4a")
                    )
                    downloads.append(target)
                    target.write_bytes(target.stem.encode("utf-8"))

            def fake_validate(path, _expected_duration=None):
                return {
                    "media_bytes": path.stat().st_size,
                    "media_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }

            with (
                mock.patch.object(candidates, "RAW_ROOT", raw_root),
                mock.patch.object(
                    candidates,
                    "validate_media",
                    side_effect=fake_validate,
                ),
                mock.patch.dict(
                    sys.modules,
                    {"yt_dlp": types.SimpleNamespace(YoutubeDL=FakeYoutubeDL)},
                ),
            ):
                first, _ = candidates.download_audio(
                    f"https://www.bilibili.com/video/{video_ids[0]}/",
                    video_ids[0],
                )
                second, _ = candidates.download_audio(
                    f"https://www.bilibili.com/video/{video_ids[1]}/",
                    video_ids[1],
                )
                first_again, _ = candidates.download_audio(
                    f"https://www.bilibili.com/video/{video_ids[0]}/",
                    video_ids[0],
                )

            self.assertEqual(first_again, first)
            self.assertNotEqual(first.name.casefold(), second.name.casefold())
            self.assertEqual(
                {path.stem for path in downloads},
                {
                    storage.media_storage_key(video_id)
                    for video_id in video_ids
                },
            )
            self.assertEqual(len(downloads), 2)

    def test_completed_media_accepts_only_exact_case_legacy_bvid(self):
        candidates = load("process_bilibili_candidates")
        requested = "BV1DSNFz2Ets"
        other = "BV1DSNFz2ETs"
        with tempfile.TemporaryDirectory() as directory:
            raw_root = Path(directory)
            other_path = raw_root / f"{other}.m4a"
            other_path.write_bytes(b"other")
            with (
                mock.patch.object(candidates, "RAW_ROOT", raw_root),
                mock.patch.object(
                    candidates,
                    "validate_media",
                    return_value={"media_bytes": 5, "media_sha256": "a" * 64},
                ),
            ):
                media, validation = candidates.completed_media(requested)

            self.assertIsNone(media)
            self.assertIsNone(validation)
            self.assertTrue(other_path.exists())

    def test_wrong_case_colliding_queue_path_is_redownloaded(self):
        candidates = load("process_bilibili_candidates")
        storage = load("bilibili_storage")
        requested = "BV1DSNFz2Ets"
        other = "BV1DSNFz2ETs"
        record = BilibiliParallelAcquisitionTests.record(requested)
        existing = {
            "video_id": requested,
            "status": "downloaded",
            "media_path": f"data/raw_videos/bilibili/{other}.m4a",
            "media_validation_version": candidates.MEDIA_VALIDATION_VERSION,
            "media_decoded_frame_count": 1,
            "media_decoded_samples": 1,
            "media_bytes": 8192,
            "media_sha256": "a" * 64,
        }
        replacement = (
            candidates.RAW_ROOT
            / f"{storage.media_storage_key(requested)}.m4a"
        )
        validation = {
            "media_bytes": 9000,
            "media_sha256": "b" * 64,
        }
        with (
            mock.patch.object(
                candidates,
                "may_enter_knowledge_base",
                return_value=True,
            ),
            mock.patch.object(
                candidates,
                "media_fingerprint",
                return_value={
                    "media_bytes": 8192,
                    "media_sha256": "a" * 64,
                },
            ),
            mock.patch.object(
                candidates,
                "download_audio",
                return_value=(replacement, validation),
            ) as download,
        ):
            outcome = candidates.process_candidate(
                copy.deepcopy(record),
                copy.deepcopy(existing),
                metadata_only=False,
                cooldown_minutes=30,
            )

        download.assert_called_once()
        self.assertEqual(outcome["result"]["status"], "downloaded")
        self.assertEqual(
            Path(outcome["queue_item"]["media_path"]).name,
            replacement.name,
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
