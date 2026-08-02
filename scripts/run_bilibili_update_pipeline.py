#!/usr/bin/env python3
"""Resume the Bilibili corpus from a verified archive through Skill release."""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from bilibili_pipeline import (
    PIPELINE_LOCK_OWNER_ENV,
    acquire_bilibili_pipeline_lock,
)
from bilibili_storage import (
    BILIBILI_MEDIA_CACHE_ENV,
    BILIBILI_TRANSCRIPT_CACHE_ENV,
    bilibili_media_cache_root,
    bilibili_transcript_cache_root,
    bilibili_transcript_roots,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE = (
    ROOT / "data" / "snapshots" / "bilibili_profile_full_archive.json"
)
MEDIA_ROOT = bilibili_media_cache_root(ROOT)
TRANSCRIPT_ROOT = bilibili_transcript_cache_root(ROOT)
QUEUE_PATH = ROOT / "data" / "processing" / "bilibili_queue.json"


def default_install_destination():
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    return codex_home.expanduser() / "skills" / "liuhui-badminton-coach"


def run(command, *, allow_incomplete=False):
    normalized = [str(part) for part in command]
    print(f"$ {' '.join(normalized)}", flush=True)
    completed = subprocess.run(
        normalized,
        cwd=ROOT,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join(
                value
                for value in [
                    str(ROOT / "scripts"),
                    os.environ.get("PYTHONPATH"),
                ]
                if value
            ),
        },
    )
    if completed.returncode and not allow_incomplete:
        raise subprocess.CalledProcessError(completed.returncode, normalized)
    return completed.returncode


def load_status():
    completed = subprocess.run(
        [sys.executable, "scripts/report_pipeline_status.py", "--json"],
        cwd=ROOT,
        env={
            **os.environ,
            "PYTHONPATH": str(ROOT / "scripts"),
        },
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=DEFAULT_ARCHIVE,
        help="Validated full-profile archive to ingest before resuming",
    )
    parser.add_argument(
        "--skip-ingest",
        action="store_true",
        help="Keep the current ledger instead of applying --snapshot",
    )
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="Verify provenance without downloading media",
    )
    parser.add_argument("--max-items", type=int)
    parser.add_argument(
        "--download-workers",
        type=int,
        choices=range(1, 5),
        default=int(os.environ.get("BSC_BILIBILI_DOWNLOAD_WORKERS", "2")),
        metavar="{1,2,3,4}",
        help="Bounded concurrent Bilibili acquisition workers (default: 2)",
    )
    parser.add_argument("--model", default="small")
    parser.add_argument(
        "--media-cache-dir",
        type=Path,
        help=(
            "Local Bilibili media cache outside synchronized Documents storage "
            f"(default: {BILIBILI_MEDIA_CACHE_ENV} or data/raw_videos/bilibili)"
        ),
    )
    parser.add_argument(
        "--transcript-cache-dir",
        type=Path,
        help=(
            "Preferred Bilibili transcript cache outside synchronized "
            f"Documents storage (default: {BILIBILI_TRANSCRIPT_CACHE_ENV} "
            "or data/transcripts/bilibili)"
        ),
    )
    parser.add_argument(
        "--skip-acquisition",
        action="store_true",
        help="Skip metadata verification and media download",
    )
    parser.add_argument(
        "--skip-transcription",
        action="store_true",
        help="Skip Whisper and transcript reconciliation",
    )
    parser.add_argument(
        "--skip-release",
        action="store_true",
        help="Skip knowledge rebuild and regression validation",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="Atomically install the validated repository Skill",
    )
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="Deprecated compatibility flag; completeness is required by default",
    )
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Allow an intentionally partial run to exit zero",
    )
    args = parser.parse_args()
    media_root = bilibili_media_cache_root(
        ROOT,
        override=args.media_cache_dir,
    )
    transcript_root = bilibili_transcript_cache_root(
        ROOT,
        override=args.transcript_cache_dir,
    )
    if args.media_cache_dir is not None:
        os.environ[BILIBILI_MEDIA_CACHE_ENV] = str(media_root)
    if args.transcript_cache_dir is not None:
        os.environ[BILIBILI_TRANSCRIPT_CACHE_ENV] = str(transcript_root)
    if args.require_complete and args.allow_partial:
        parser.error("--require-complete and --allow-partial are mutually exclusive")
    if args.install and (
        args.metadata_only
        or args.skip_transcription
        or args.skip_release
        or args.max_items is not None
    ):
        parser.error(
            "--install requires a complete transcription and validated release run"
        )
    pipeline_lock = acquire_bilibili_pipeline_lock()
    os.environ[PIPELINE_LOCK_OWNER_ENV] = "1"

    if not args.skip_ingest:
        if not args.snapshot.exists():
            parser.error(f"snapshot does not exist: {args.snapshot}")
        run(
            [
                sys.executable,
                "scripts/check_bilibili_updates.py",
                args.snapshot,
                "--apply",
            ]
        )

    acquisition_incomplete = False
    if not args.skip_acquisition and not args.skip_ingest:
        run(
            [
                sys.executable,
                "scripts/process_bilibili_candidates.py",
                "--existing-queue-only",
            ]
        )
    if not args.skip_acquisition:
        command = [
            sys.executable,
            "scripts/process_bilibili_candidates.py",
            "--media-cache-dir",
            media_root,
        ]
        if args.metadata_only:
            command.append("--metadata-only")
        if args.max_items:
            command.extend(["--max-items", str(args.max_items)])
        command.extend(["--download-workers", str(args.download_workers)])
        acquisition_incomplete = bool(run(command, allow_incomplete=True))

    if (
        not args.metadata_only
        and not args.skip_transcription
    ):
        run(
            [
                sys.executable,
                "scripts/batch_transcribe_directory.py",
                media_root,
                "--output-dir",
                transcript_root,
                "--queue",
                QUEUE_PATH,
                "--model",
                args.model,
            ]
            + [
                part
                for fallback_root in bilibili_transcript_roots(
                    ROOT,
                    override=transcript_root,
                )[1:]
                for part in ["--fallback-output-dir", fallback_root]
            ]
        )
        run(
            [
                sys.executable,
                "scripts/finalize_bilibili_transcripts.py",
                "--media-cache-dir",
                media_root,
                "--transcript-cache-dir",
                transcript_root,
            ]
        )

    release_validated = False
    release_build_id = None
    if (
        not args.metadata_only
        and not args.skip_release
        and not acquisition_incomplete
    ):
        with tempfile.TemporaryDirectory(
            prefix="bilibili-validation-"
        ) as directory:
            receipt_path = Path(directory) / "validated-build.json"
            run(
                [
                    sys.executable,
                    "scripts/run_full_update_pipeline.py",
                    "--validation-receipt",
                    receipt_path,
                ]
            )
            try:
                receipt = json.loads(
                    receipt_path.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError) as error:
                raise RuntimeError(
                    "Full update pipeline returned no readable build receipt"
                ) from error
            release_build_id = str(receipt.get("build_id") or "")
            if not re.fullmatch(r"[0-9a-f]{64}", release_build_id):
                raise RuntimeError(
                    "Full update pipeline returned no valid build receipt"
                )
            run([sys.executable, "scripts/evaluate_bilibili_canaries.py"])
        release_validated = True

    status = load_status()
    bilibili = status["bilibili"]
    if args.install:
        current_build_id = str(bilibili.get("repo_build_id") or "")
        install_destination = default_install_destination()
        if (
            acquisition_incomplete
            or not release_validated
            or not bilibili.get("all_videos_terminal")
            or not re.fullmatch(r"[0-9a-f]{64}", release_build_id or "")
            or current_build_id != release_build_id
        ):
            raise RuntimeError(
                "Refusing to install before the full archive is terminal and "
                "this run has rebuilt and validated a release with a valid "
                "build_id"
            )
        run(
            [
                sys.executable,
                "scripts/install_skill.py",
                "--destination",
                install_destination,
                "--expected-build-id",
                release_build_id,
            ]
        )
        run(
            [
                sys.executable,
                "skills/liuhui-badminton-coach/scripts/doctor.py",
                "--skill-root",
                install_destination,
            ]
        )
        status = load_status()
        bilibili = status["bilibili"]
        if not bilibili.get("installed_matches_repo"):
            raise RuntimeError("Installed Skill build ID does not match the repository")

    result = {
        "status": (
            "complete"
            if bilibili.get("all_videos_terminal")
            else "incomplete"
        ),
        "acquisition_incomplete": acquisition_incomplete,
        "release_validated": release_validated,
        "bilibili": bilibili,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not bilibili.get("all_videos_terminal") and not args.allow_partial:
        return 2
    return 0 if args.allow_partial else (1 if acquisition_incomplete else 0)


if __name__ == "__main__":
    raise SystemExit(main())
