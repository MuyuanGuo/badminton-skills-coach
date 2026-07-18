#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from douyin_pipeline import (
    compute_status_counts,
    normalize_transcribed_media_state,
    validate_queue_statuses,
    now_iso,
    write_json,
)
from media_assets import (
    MediaAssetError,
    downloaded_media_error,
    load_media_policy,
    read_download_config,
    redact_urls,
    validate_batch_name,
)
from run_full_update_pipeline import rebuild_and_validate


ROOT = Path(__file__).resolve().parents[1]
QUEUE_PATH = ROOT / "data" / "processing" / "douyin_queue.json"
RAW_ROOT = ROOT / "data" / "raw_videos" / "douyin"
TRANSCRIPT_ROOT = ROOT / "data" / "transcripts" / "douyin"
TMP_ROOT = ROOT / "data" / "tmp"
ALLOWED_INITIAL_DIRTY_PATHS = {
    "data/douyin_classification_ledger.json",
    "data/douyin_teaching_filtered.json",
    "data/douyin_video_index.json",
    "data/processing/douyin_discovery_state.json",
    "data/processing/douyin_queue.json",
    "output/classification-drift-report.json",
}


def run(command, *, check=True):
    normalized = [str(part) for part in command]
    print(f"$ {' '.join(normalized)}", flush=True)
    return subprocess.run(normalized, cwd=ROOT, check=check)


def resolve_transcription_python(override=None, root=ROOT):
    if override:
        candidate = Path(override).expanduser()
        return candidate.absolute() if candidate.is_file() else None
    if os.environ.get("LIUHUI_TRANSCRIPTION_PYTHON"):
        candidate = Path(os.environ["LIUHUI_TRANSCRIPTION_PYTHON"]).expanduser()
        return candidate.absolute() if candidate.is_file() else None
    candidates = [
        root / ".venv" / "bin" / "python",
        root / ".venv" / "Scripts" / "python.exe",
    ]
    candidates.append(Path(sys.executable))
    # Preserve a virtualenv launcher path; resolving its symlink bypasses venv site-packages.
    return next((path.absolute() for path in candidates if path.is_file()), None)


def git_changed_paths(root=ROOT):
    paths = set()
    for command in (
        ["git", "diff", "--name-only"],
        ["git", "diff", "--cached", "--name-only"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ):
        output = subprocess.check_output(command, cwd=root, text=True)
        paths.update(line.strip() for line in output.splitlines() if line.strip())
    return sorted(paths)


def unexpected_dirty_paths(paths):
    return sorted(set(paths) - ALLOWED_INITIAL_DIRTY_PATHS)


def run_transcription_preflight(transcription_python):
    return run(
        [
            sys.executable,
            "scripts/doctor.py",
            "--profile",
            "transcription",
            "--transcription-python",
            transcription_python,
            "--no-smoke",
        ],
        check=False,
    )


def run_browser_download(
    transcription_python,
    batch,
    *,
    video_ids=None,
    chrome=None,
    node=None,
    preflight_only=False,
):
    command = [
        transcription_python,
        "scripts/download_douyin_browser_batch.py",
        batch,
    ]
    if preflight_only:
        command.append("--preflight-only")
    for video_id in video_ids or []:
        command.extend(["--video-id", video_id])
    if chrome:
        command.extend(["--chrome", chrome])
    if node:
        command.extend(["--node", node])
    return run(command, check=False)


def browser_download_candidate_ids(requested_video_ids=None):
    allowed = {
        "classified_teaching",
        "pending",
        "download_failed",
        "extraction_failed",
    }
    queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    requested = set(requested_video_ids or [])
    return [
        str(item["video_id"])
        for item in queue["items"]
        if item.get("status") in allowed
        and item.get("classification_decision") == "保留：教学"
        and (not requested or str(item["video_id"]) in requested)
    ]


def queue_counts():
    queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    return compute_counts(queue)


def compute_counts(queue):
    validate_queue_statuses(queue["items"])
    return compute_status_counts(queue["items"])


def write_queue(queue):
    queue["counts"] = compute_counts(queue)
    queue["updated_at"] = now_iso()
    write_json(QUEUE_PATH, queue)


def batch_items(batch):
    prefix = f"data/raw_videos/douyin/{batch}/"
    queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    return [
        item for item in queue["items"]
        if item.get("status") in {"media_ready", "downloaded", "transcription_failed"}
        and item.get("media_path", "").startswith(prefix)
    ]


def download_ready_items(batch, items):
    media_policy = load_media_policy()
    queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    queue_by_id = {item["video_id"]: item for item in queue["items"]}
    downloaded = []
    failed = []
    for item in items:
        video_id = item["video_id"]
        config = TMP_ROOT / batch / f"{video_id}.curl"
        queue_item = queue_by_id[video_id]
        media_path = ROOT / queue_item["media_path"]
        media_path.unlink(missing_ok=True)
        if not config.exists():
            queue_item["status"] = "download_failed"
            queue_item["attempts"] = int(queue_item.get("attempts") or 0) + 1
            queue_item["download_attempts"] = int(queue_item.get("download_attempts") or 0) + 1
            queue_item["error"] = f"Missing curl config: {config.relative_to(ROOT)}"
            queue_item["error_stage"] = "download"
            queue_item["last_attempt_at"] = now_iso()
            failed.append(video_id)
            write_queue(queue)
            continue
        try:
            asset_url = read_download_config(
                config, queue_item["media_path"], media_policy
            )
        except (OSError, MediaAssetError) as error:
            media_path.unlink(missing_ok=True)
            queue_item["status"] = "download_failed"
            queue_item["attempts"] = int(queue_item.get("attempts") or 0) + 1
            queue_item["download_attempts"] = int(queue_item.get("download_attempts") or 0) + 1
            queue_item["error"] = f"Unsafe or invalid download config: {error}"
            queue_item["error_stage"] = "download"
            queue_item["last_attempt_at"] = now_iso()
            failed.append(video_id)
            write_queue(queue)
            continue
        completed = subprocess.run(
            [
                "curl",
                "--location",
                "--fail",
                "--retry",
                "2",
                "--connect-timeout",
                "20",
                "--max-time",
                "300",
                "--user-agent",
                "Mozilla/5.0",
                "--proto",
                "=https",
                "--proto-redir",
                "=https",
                "--silent",
                "--show-error",
                "--output",
                str(media_path.relative_to(ROOT)),
                asset_url,
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        media_error = (
            downloaded_media_error(
                media_path, media_policy["minimum_download_bytes"]
            )
            if not completed.returncode
            else None
        )
        if completed.returncode or media_error:
            media_path.unlink(missing_ok=True)
            queue_item["status"] = "download_failed"
            queue_item["attempts"] = int(queue_item.get("attempts") or 0) + 1
            queue_item["download_attempts"] = int(queue_item.get("download_attempts") or 0) + 1
            queue_item["error"] = (
                media_error
                or redact_urls(completed.stderr or completed.stdout or "download failed")
            ).strip()[-1200:]
            queue_item["error_stage"] = "download"
            queue_item["last_attempt_at"] = now_iso()
            failed.append(video_id)
        else:
            queue_item["status"] = "downloaded"
            queue_item["error"] = None
            queue_item["error_stage"] = None
            queue_item["last_attempt_at"] = now_iso()
            downloaded.append(video_id)
        write_queue(queue)
    return downloaded, failed


def cleanup_transcribed_media(batch, video_ids, *, root=ROOT, queue_path=QUEUE_PATH):
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    queue_by_id = {item["video_id"]: item for item in queue["items"]}
    removed = []
    skipped = []
    for video_id in video_ids:
        item = queue_by_id.get(video_id)
        if not item or item.get("status") != "transcribed":
            skipped.append(video_id)
            continue
        media_path = item.get("media_path")
        if media_path:
            path = root / media_path
            path.unlink(missing_ok=True)
        (root / "data" / "tmp" / batch / f"{video_id}.curl").unlink(missing_ok=True)
        normalize_transcribed_media_state(item)
        removed.append(video_id)
    queue["counts"] = compute_counts(queue)
    queue["updated_at"] = now_iso()
    write_json(queue_path, queue)
    return {"removed": removed, "skipped": skipped}


def finalize_transcribed_batch(batch, video_ids):
    cleanup = cleanup_transcribed_media(batch, video_ids)
    print(json.dumps({"media_cleanup": cleanup}, ensure_ascii=False), flush=True)
    rebuild_and_validate()
    return cleanup


def commit_if_changed(message, push):
    status = subprocess.check_output(
        ["git", "status", "--short"],
        cwd=ROOT,
        text=True,
    ).strip()
    if not status:
        print("No tracked changes to commit.", flush=True)
        return
    run(["git", "add", "."])
    run(["git", "diff", "--cached", "--stat"])
    run(["git", "commit", "-m", message])
    if push:
        run(["git", "push"])


def main():
    parser = argparse.ArgumentParser(
        description="Download, transcribe, validate, clean, and commit one Douyin media_ready batch."
    )
    parser.add_argument("batch", help="Batch name, for example batch-009")
    parser.add_argument("--no-push", action="store_true", help="Commit locally but skip git push")
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Validate the worktree, disk, curl, Whisper package, and cached model without downloading",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow unrelated pre-existing worktree changes; unsafe for unattended commits",
    )
    parser.add_argument(
        "--min-free-gb",
        type=float,
        default=8.0,
        help="Stop before download if available disk space is below this threshold",
    )
    parser.add_argument(
        "--transcription-python",
        type=Path,
        help="Python with faster-whisper installed; overrides automatic .venv detection",
    )
    parser.add_argument("--model", default="small", help="faster-whisper model name")
    parser.add_argument(
        "--auto-download",
        action="store_true",
        help=(
            "Download classified or failed items through isolated anonymous Chrome; "
            "also retry expired direct curl downloads through that path"
        ),
    )
    parser.add_argument(
        "--video-id",
        action="append",
        default=[],
        help="Limit --auto-download to one queued video ID; repeatable",
    )
    parser.add_argument(
        "--chrome",
        type=Path,
        help="Chrome/Edge executable passed to the anonymous browser downloader",
    )
    parser.add_argument(
        "--node",
        type=Path,
        help="Node.js executable passed to the anonymous browser downloader",
    )
    args = parser.parse_args()
    if args.video_id and not args.auto_download:
        parser.error("--video-id requires --auto-download")
    try:
        args.batch = validate_batch_name(args.batch)
    except MediaAssetError as error:
        raise SystemExit(str(error)) from error

    dirty_paths = git_changed_paths()
    unexpected_paths = unexpected_dirty_paths(dirty_paths)
    if unexpected_paths and not args.allow_dirty:
        print(
            json.dumps(
                {
                    "error": "unexpected_dirty_worktree",
                    "paths": unexpected_paths,
                    "remediation": (
                        "Commit, stash, or remove unrelated changes before processing; "
                        "use --allow-dirty only for an attended recovery"
                    ),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    if unexpected_paths:
        print(
            json.dumps(
                {"warning": "allowing_unrelated_dirty_paths", "paths": unexpected_paths},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )

    usage = shutil.disk_usage(ROOT)
    free_gb = usage.free / (1024 ** 3)
    if free_gb < args.min_free_gb:
        print(
            json.dumps({"error": "low_disk_space", "free_gb": round(free_gb, 2)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2

    if not shutil.which("curl"):
        print(
            json.dumps(
                {"error": "missing_dependency", "dependency": "curl"},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    transcription_python = resolve_transcription_python(args.transcription_python)
    if transcription_python is None:
        print(
            json.dumps(
                {
                    "error": "missing_transcription_python",
                    "requested": str(args.transcription_python or os.environ.get("LIUHUI_TRANSCRIPTION_PYTHON") or "automatic"),
                    "remediation": (
                        "Create .venv and install requirements-transcription.txt, "
                        "or set LIUHUI_TRANSCRIPTION_PYTHON"
                    ),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    if run_transcription_preflight(transcription_python).returncode:
        print(
            json.dumps(
                {
                    "error": "transcription_preflight_failed",
                    "remediation": "Run python3 scripts/doctor.py --profile transcription",
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2

    browser_candidates = (
        browser_download_candidate_ids(args.video_id) if args.auto_download else []
    )
    if args.auto_download:
        browser_preflight = run_browser_download(
            transcription_python,
            args.batch,
            chrome=args.chrome,
            node=args.node,
            preflight_only=True,
        )
        if browser_preflight.returncode:
            print(
                json.dumps(
                    {
                        "error": "browser_download_preflight_failed",
                        "remediation": (
                            "Install requirements-transcription.txt and Node.js 22+, "
                            "and make Chrome/Edge available or pass --chrome"
                        ),
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
            return 2

    items = batch_items(args.batch)
    preflight = {
        "batch": args.batch,
        "actionable": len(items),
        "statuses": compute_status_counts(items),
        "free_gb": round(free_gb, 2),
        "transcription_python": str(transcription_python),
        "model": args.model,
        "browser_download_candidates": browser_candidates,
        "preexisting_dirty_paths": dirty_paths,
    }
    if args.preflight_only:
        print(json.dumps({**preflight, "preflight": "passed"}, ensure_ascii=False))
        return 0
    if args.auto_download and browser_candidates:
        browser_completed = run_browser_download(
            transcription_python,
            args.batch,
            video_ids=browser_candidates,
            chrome=args.chrome,
            node=args.node,
        )
        if browser_completed.returncode:
            print(
                json.dumps(
                    {
                        "batch": args.batch,
                        "error": "browser_download_failed",
                        "queue": queue_counts(),
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
            return browser_completed.returncode
        items = batch_items(args.batch)
    if not items:
        print(json.dumps(preflight, ensure_ascii=False))
        return 0

    media_dir = RAW_ROOT / args.batch
    transcript_dir = TRANSCRIPT_ROOT / args.batch
    media_dir.mkdir(parents=True, exist_ok=True)
    transcript_dir.mkdir(parents=True, exist_ok=True)

    print(json.dumps({
        "batch": args.batch,
        "actionable": len(items),
        "before": queue_counts(),
        "free_gb": round(free_gb, 2),
    }, ensure_ascii=False), flush=True)

    media_ready = [item for item in items if item.get("status") == "media_ready"]
    downloaded, failed = download_ready_items(args.batch, media_ready)
    if failed and args.auto_download:
        fallback_completed = run_browser_download(
            transcription_python,
            args.batch,
            video_ids=failed,
            chrome=args.chrome,
            node=args.node,
        )
        if fallback_completed.returncode == 0:
            queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
            recovered = {
                str(item["video_id"])
                for item in queue["items"]
                if item.get("status") == "downloaded"
            }
            downloaded.extend(video_id for video_id in failed if video_id in recovered)
            failed = [video_id for video_id in failed if video_id not in recovered]
    print(json.dumps({
        "downloaded": len(downloaded),
        "download_failed": len(failed),
        "failed_video_ids": failed,
    }, ensure_ascii=False), flush=True)
    transcribe_candidates = [
        item
        for item in batch_items(args.batch)
        if item.get("status") in {"downloaded", "transcription_failed"}
        and item.get("media_path")
        and (ROOT / item["media_path"]).exists()
    ]
    if transcribe_candidates:
        completed = run([
            transcription_python,
            "scripts/batch_transcribe_directory.py",
            str(media_dir.relative_to(ROOT)),
            "--output-dir",
            str(transcript_dir.relative_to(ROOT)),
            "--queue",
            str(QUEUE_PATH.relative_to(ROOT)),
            "--model",
            args.model,
        ], check=False)
        if completed.returncode:
            print(
                json.dumps(
                    {
                        "batch": args.batch,
                        "error": "transcription_failed",
                        "queue": queue_counts(),
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
            return completed.returncode
    unresolved = [
        item
        for item in batch_items(args.batch)
        if item.get("status") != "transcribed"
    ]
    if failed or unresolved:
        print(
            json.dumps(
                {
                    "batch": args.batch,
                    "error": "batch_has_unresolved_items",
                    "video_ids": [item["video_id"] for item in unresolved],
                    "queue": queue_counts(),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    finalize_transcribed_batch(
        args.batch,
        [item["video_id"] for item in items],
    )

    commit_if_changed(
        f"Process Douyin teaching {args.batch}",
        push=not args.no_push,
    )

    print(json.dumps({
        "batch": args.batch,
        "after": queue_counts(),
        "validated": True,
        "pushed": not args.no_push,
    }, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
