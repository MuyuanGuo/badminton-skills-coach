#!/usr/bin/env python3
"""Download queued Douyin teaching videos through an isolated anonymous browser."""

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from douyin_pipeline import compute_status_counts, now_iso, write_json
from media_assets import (
    MediaAssetError,
    downloaded_media_error,
    load_media_policy,
    redact_urls,
    validate_batch_name,
    validate_page_url,
    validate_video_id,
)


ROOT = Path(__file__).resolve().parents[1]
QUEUE_PATH = ROOT / "data" / "processing" / "douyin_queue.json"
RAW_ROOT = ROOT / "data" / "raw_videos" / "douyin"
SOURCE_CONFIG_PATH = ROOT / "config" / "douyin_source.json"
COOKIE_EXPORTER = ROOT / "scripts" / "export_douyin_cookies_cdp.mjs"
DOWNLOADABLE_STATUSES = {
    "classified_teaching",
    "pending",
    "download_failed",
    "extraction_failed",
}
MEDIA_SUFFIXES = {".mp4", ".m4a", ".webm", ".mp3"}


class BrowserDownloadError(RuntimeError):
    pass


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def find_chrome_executable(override=None):
    candidates = []
    if override:
        candidates.append(str(Path(override).expanduser()))
    if os.environ.get("LIUHUI_CHROME"):
        candidates.append(os.environ["LIUHUI_CHROME"])
    if sys.platform == "darwin":
        candidates.extend(
            [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                "/Applications/Chromium.app/Contents/MacOS/Chromium",
            ]
        )
    elif os.name == "nt":
        for root in [
            os.environ.get("PROGRAMFILES"),
            os.environ.get("PROGRAMFILES(X86)"),
            os.environ.get("LOCALAPPDATA"),
        ]:
            if not root:
                continue
            candidates.extend(
                [
                    str(Path(root) / "Google/Chrome/Application/chrome.exe"),
                    str(Path(root) / "Microsoft/Edge/Application/msedge.exe"),
                ]
            )
    candidates.extend(
        [
            "google-chrome",
            "google-chrome-stable",
            "chromium",
            "chromium-browser",
            "microsoft-edge",
            "msedge",
        ]
    )
    for candidate in candidates:
        expanded = Path(candidate).expanduser()
        if expanded.is_file():
            return expanded.absolute()
        resolved = shutil.which(candidate)
        if resolved:
            return Path(resolved).absolute()
    return None


def node_supports_websocket(node):
    completed = subprocess.run(
        [str(node), "-e", "process.exit(typeof WebSocket === 'function' ? 0 : 1)"],
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.returncode == 0


def preflight(chrome_override=None, node_override=None):
    chrome = find_chrome_executable(chrome_override)
    node = Path(node_override).expanduser() if node_override else None
    if node and not node.is_file():
        node = None
    if node is None:
        node_path = shutil.which("node")
        node = Path(node_path).absolute() if node_path else None
    checks = {
        "chrome": str(chrome) if chrome else None,
        "node": str(node) if node else None,
        "node_websocket": bool(node and node_supports_websocket(node)),
        "yt_dlp": bool(importlib.util.find_spec("yt_dlp")),
        "cookie_exporter": COOKIE_EXPORTER.is_file(),
    }
    checks["ok"] = all(
        [
            checks["chrome"],
            checks["node"],
            checks["node_websocket"],
            checks["yt_dlp"],
            checks["cookie_exporter"],
        ]
    )
    return checks


def wait_for_devtools_endpoint(profile_dir, process, timeout_seconds):
    port_file = Path(profile_dir) / "DevToolsActivePort"
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise BrowserDownloadError("Anonymous Chrome exited before DevTools became ready")
        if port_file.is_file():
            lines = port_file.read_text(encoding="utf-8").splitlines()
            if len(lines) >= 2:
                try:
                    port = int(lines[0])
                except ValueError as error:
                    raise BrowserDownloadError("Chrome wrote an invalid DevTools port") from error
                websocket_path = lines[1]
                if not 1 <= port <= 65535 or not websocket_path.startswith("/devtools/browser/"):
                    raise BrowserDownloadError("Chrome wrote an invalid DevTools endpoint")
                return f"ws://127.0.0.1:{port}{websocket_path}"
        time.sleep(0.1)
    raise BrowserDownloadError("Timed out waiting for the anonymous Chrome DevTools endpoint")


@contextmanager
def anonymous_chrome_session(chrome, page_url, profile_dir, timeout_seconds=20):
    command = [
        str(chrome),
        "--headless=new",
        "--remote-debugging-port=0",
        "--remote-allow-origins=*",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--disable-default-apps",
        "--disable-sync",
        "--mute-audio",
        "--autoplay-policy=no-user-gesture-required",
        page_url,
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        yield wait_for_devtools_endpoint(profile_dir, process, timeout_seconds), process
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def export_anonymous_cookies(node, endpoint, page_url, cookie_path, timeout_seconds=30):
    completed = subprocess.run(
        [
            str(node),
            str(COOKIE_EXPORTER),
            "--endpoint",
            endpoint,
            "--url",
            page_url,
            "--output",
            str(cookie_path),
            "--timeout-seconds",
            str(timeout_seconds),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout_seconds + 10,
    )
    if completed.returncode:
        message = redact_urls(completed.stderr or completed.stdout or "cookie export failed")
        raise BrowserDownloadError(message.strip()[-1200:])
    if not Path(cookie_path).is_file() or Path(cookie_path).stat().st_size <= 0:
        raise BrowserDownloadError("Chrome cookie export completed without a cookie file")
    if os.name != "nt" and Path(cookie_path).stat().st_mode & 0o077:
        raise BrowserDownloadError("Temporary cookie file permissions are too broad")
    return json.loads(completed.stdout)


def parse_metadata_line(line, expected_video_id, expected_profile_id):
    fields = line.rstrip("\n").split("\t")
    if len(fields) != 7:
        raise BrowserDownloadError("yt-dlp returned malformed metadata")
    video_id, duration, uploader_id, channel_id, extension, format_id, webpage_url = fields
    if video_id != expected_video_id:
        raise BrowserDownloadError(
            f"yt-dlp returned video {video_id or 'missing'}, expected {expected_video_id}"
        )
    if channel_id != expected_profile_id:
        raise BrowserDownloadError("Downloaded video does not belong to the configured creator profile")
    try:
        duration_seconds = float(duration)
    except ValueError as error:
        raise BrowserDownloadError("yt-dlp returned an invalid duration") from error
    if not 0 < duration_seconds <= 7200:
        raise BrowserDownloadError("yt-dlp returned an implausible duration")
    if f"/video/{expected_video_id}" not in webpage_url:
        raise BrowserDownloadError("yt-dlp returned a mismatched canonical video URL")
    return {
        "video_id": video_id,
        "duration_seconds": duration_seconds,
        "uploader_id": uploader_id,
        "channel_id": channel_id,
        "extension": extension.lower(),
        "format_id": format_id,
    }


def validate_metadata_info(info, expected_video_id, expected_profile_id):
    fields = [
        str(info.get("id") or ""),
        str(info.get("duration") or ""),
        str(info.get("uploader_id") or ""),
        str(info.get("channel_id") or ""),
        str(info.get("ext") or ""),
        str(info.get("format_id") or ""),
        str(info.get("webpage_url") or ""),
    ]
    return parse_metadata_line("\t".join(fields), expected_video_id, expected_profile_id)


class RedactingYtDlpLogger:
    def __init__(self):
        self.errors = []

    def debug(self, _message):
        return None

    def info(self, _message):
        return None

    def warning(self, _message):
        return None

    def error(self, message):
        self.errors.append(redact_urls(message).strip()[-1200:])


def download_verified_video(
    cookie_path,
    page_url,
    video_id,
    profile_id,
    output_dir,
    policy,
    force=False,
):
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{video_id}-", dir=output_dir) as staging_name:
        staging = Path(staging_name)
        output_template = staging / f"{video_id}.%(ext)s"
        metadata = {}
        verification_error = []
        logger = RedactingYtDlpLogger()

        def verify_entry(info, *, incomplete):
            if incomplete:
                return None
            try:
                metadata.update(validate_metadata_info(info, video_id, profile_id))
            except BrowserDownloadError as error:
                verification_error.append(str(error))
                return str(error)
            return None

        options = {
            "cookiefile": str(cookie_path),
            "socket_timeout": 20,
            "retries": 2,
            "fragment_retries": 2,
            "extractor_retries": 2,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "format": "best[ext=mp4]/best",
            "outtmpl": str(output_template),
            "match_filter": verify_entry,
            "logger": logger,
        }
        try:
            with YoutubeDL(options) as downloader:
                result = downloader.extract_info(page_url, download=True)
        except DownloadError as error:
            message = logger.errors[-1] if logger.errors else redact_urls(str(error))
            raise BrowserDownloadError(message) from error
        if verification_error:
            raise BrowserDownloadError(verification_error[-1])
        if not result or not metadata:
            raise BrowserDownloadError("yt-dlp did not verify and download the requested video")
        files = [
            path for path in staging.iterdir()
            if path.is_file() and path.suffix.lower() in MEDIA_SUFFIXES
        ]
        if len(files) != 1:
            raise BrowserDownloadError("yt-dlp did not create exactly one recognized media file")
        source = files[0]
        media_error = downloaded_media_error(source, policy["minimum_download_bytes"])
        if media_error:
            raise BrowserDownloadError(media_error)
        destination = output_dir / f"{video_id}{source.suffix.lower()}"
        if destination.exists() and not force:
            raise BrowserDownloadError(f"Media destination already exists: {destination.relative_to(ROOT)}")
        destination.unlink(missing_ok=True)
        os.replace(source, destination)
        return destination, metadata


def select_candidates(queue, requested_video_ids=None):
    by_id = {str(item["video_id"]): item for item in queue["items"]}
    requested = [validate_video_id(video_id) for video_id in (requested_video_ids or [])]
    if requested:
        missing = [video_id for video_id in requested if video_id not in by_id]
        if missing:
            raise BrowserDownloadError("Videos are not present in the queue: " + ", ".join(missing))
        candidates = [by_id[video_id] for video_id in requested]
    else:
        candidates = [
            item for item in queue["items"]
            if item.get("status") in DOWNLOADABLE_STATUSES
        ]
    invalid = [
        str(item["video_id"]) for item in candidates
        if item.get("status") not in DOWNLOADABLE_STATUSES
        or item.get("classification_decision") != "保留：教学"
    ]
    if invalid:
        raise BrowserDownloadError(
            "Refusing browser download for non-teaching or non-downloadable queue items: "
            + ", ".join(invalid)
        )
    return candidates


def update_queue_item(queue, video_id, **changes):
    item = next(row for row in queue["items"] if str(row["video_id"]) == str(video_id))
    item.update(changes)
    queue["counts"] = compute_status_counts(queue["items"])
    queue["updated_at"] = now_iso()
    write_json(QUEUE_PATH, queue)
    return item


def record_failure(queue, item, status, stage, error):
    return update_queue_item(
        queue,
        item["video_id"],
        status=status,
        attempts=int(item.get("attempts") or 0) + 1,
        download_attempts=int(item.get("download_attempts") or 0) + 1,
        error=redact_urls(error).strip()[-1200:],
        error_stage=stage,
        last_attempt_at=now_iso(),
    )


def process_batch(batch, requested_video_ids=None, chrome_override=None, node_override=None, force=False):
    batch = validate_batch_name(batch)
    checks = preflight(chrome_override, node_override)
    if not checks["ok"]:
        raise BrowserDownloadError("Browser download preflight failed: " + json.dumps(checks))
    queue = load_json(QUEUE_PATH)
    candidates = select_candidates(queue, requested_video_ids)
    if not candidates:
        return {"batch": batch, "downloaded": [], "failed": [], "preflight": checks}

    source_config = load_json(SOURCE_CONFIG_PATH)
    profile_id = source_config["profile_id"]
    policy = load_media_policy()
    output_dir = RAW_ROOT / batch
    downloaded = []
    failed = []
    with tempfile.TemporaryDirectory(prefix="liuhui-douyin-browser-") as temporary_name:
        temporary = Path(temporary_name)
        cookie_path = temporary / "cookies.txt"
        try:
            first_item = candidates[0]
            first_url = validate_page_url(first_item["url"], first_item["video_id"])
            with anonymous_chrome_session(checks["chrome"], first_url, temporary / "chrome") as (endpoint, _process):
                export_anonymous_cookies(checks["node"], endpoint, first_url, cookie_path)
        except (BrowserDownloadError, MediaAssetError, OSError, subprocess.SubprocessError) as error:
            for item in candidates:
                record_failure(queue, item, "extraction_failed", "anonymous_browser", str(error))
                failed.append(str(item["video_id"]))
            return {"batch": batch, "downloaded": downloaded, "failed": failed, "preflight": checks}

        for item in candidates:
            video_id = str(item["video_id"])
            try:
                page_url = validate_page_url(item["url"], video_id)
                media_path, metadata = download_verified_video(
                    cookie_path,
                    page_url,
                    video_id,
                    profile_id,
                    output_dir,
                    policy,
                    force=force,
                )
                relative_media = str(media_path.relative_to(ROOT))
                kind = "audio" if media_path.suffix.lower() in {".m4a", ".mp3"} else "video"
                update_queue_item(
                    queue,
                    video_id,
                    status="downloaded",
                    media_path=relative_media,
                    media_asset_kind=kind,
                    media_asset_source="anonymous_chrome_cdp_yt_dlp",
                    media_download_method="anonymous_chrome_cdp_yt_dlp",
                    duration_seconds=metadata["duration_seconds"],
                    attempts=int(item.get("attempts") or 0) + 1,
                    download_attempts=int(item.get("download_attempts") or 0) + 1,
                    error=None,
                    error_stage=None,
                    last_attempt_at=now_iso(),
                )
                downloaded.append(video_id)
            except (
                BrowserDownloadError,
                MediaAssetError,
                OSError,
                subprocess.SubprocessError,
            ) as error:
                record_failure(queue, item, "download_failed", "browser_download", str(error))
                failed.append(video_id)
    return {"batch": batch, "downloaded": downloaded, "failed": failed, "preflight": checks}


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Download classified Douyin teaching videos with isolated anonymous Chrome cookies, "
            "yt-dlp metadata verification, and queue checkpoints."
        )
    )
    parser.add_argument("batch", help="Batch name, for example batch-049")
    parser.add_argument("--video-id", action="append", default=[], help="Limit the batch to one queued video ID; repeatable")
    parser.add_argument("--chrome", type=Path, help="Chrome/Edge executable; defaults to LIUHUI_CHROME or auto-detection")
    parser.add_argument("--node", type=Path, help="Node.js executable with built-in WebSocket support")
    parser.add_argument("--force", action="store_true", help="Replace an existing destination media file")
    parser.add_argument("--preflight-only", action="store_true", help="Check Chrome, Node.js, yt-dlp, and helper availability without network access")
    args = parser.parse_args()

    try:
        batch = validate_batch_name(args.batch)
        checks = preflight(args.chrome, args.node)
        if args.preflight_only:
            print(json.dumps({"batch": batch, "preflight": checks}, ensure_ascii=False))
            return 0 if checks["ok"] else 2
        result = process_batch(
            batch,
            requested_video_ids=args.video_id,
            chrome_override=args.chrome,
            node_override=args.node,
            force=args.force,
        )
    except (BrowserDownloadError, MediaAssetError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
