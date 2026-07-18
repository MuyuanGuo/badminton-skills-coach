#!/usr/bin/env python3
"""Validation helpers for short-lived Douyin media assets."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
SOURCE_CONFIG_PATH = ROOT / "config" / "douyin_source.json"
VIDEO_ID_PATTERN = re.compile(r"\d{18,20}")
BATCH_PATTERN = re.compile(r"batch-[A-Za-z0-9][A-Za-z0-9._-]{0,47}")
URL_PATTERN = re.compile(r'^url\s*=\s*(?P<value>"(?:[^"\\]|\\.)*")$')
OUTPUT_PATTERN = re.compile(r'^output\s*=\s*(?P<value>"(?:[^"\\]|\\.)*")$')


class MediaAssetError(ValueError):
    pass


def load_media_policy(path=SOURCE_CONFIG_PATH):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    policy = payload.get("media", {})
    suffixes = policy.get("allowed_https_host_suffixes")
    if not isinstance(suffixes, list) or not suffixes or not all(
        isinstance(item, str) and item and "." in item for item in suffixes
    ):
        raise MediaAssetError("Douyin media host policy is missing or invalid")
    if not isinstance(policy.get("maximum_asset_url_length"), int):
        raise MediaAssetError("Douyin media URL length policy is invalid")
    if not isinstance(policy.get("minimum_download_bytes"), int):
        raise MediaAssetError("Douyin minimum media size policy is invalid")
    if not isinstance(policy.get("snapshot_max_age_minutes"), int):
        raise MediaAssetError("Douyin media snapshot age policy is invalid")
    return policy


def validate_video_id(video_id):
    normalized = str(video_id or "")
    if not VIDEO_ID_PATTERN.fullmatch(normalized):
        raise MediaAssetError(f"Invalid Douyin video ID: {normalized!r}")
    return normalized


def validate_batch_name(batch):
    normalized = str(batch or "")
    if not BATCH_PATTERN.fullmatch(normalized):
        raise MediaAssetError(
            "Batch must start with 'batch-' and contain only letters, numbers, '.', '_' or '-'"
        )
    return normalized


def validate_page_url(url, video_id):
    video_id = validate_video_id(video_id)
    try:
        parts = urlsplit(str(url or ""))
        port = parts.port
    except ValueError as error:
        raise MediaAssetError("Snapshot page URL is malformed") from error
    if (
        parts.scheme != "https"
        or parts.hostname != "www.douyin.com"
        or parts.username
        or parts.password
        or port not in {None, 443}
        or parts.path.rstrip("/") != f"/video/{video_id}"
    ):
        raise MediaAssetError("Snapshot page URL does not match its Douyin video ID")
    return str(url)


def validate_media_snapshot(snapshot, video_id, policy, current_time=None):
    if not isinstance(snapshot, dict):
        raise MediaAssetError("Media snapshot must be a JSON object")
    validate_page_url(snapshot.get("page_url"), video_id)
    value = snapshot.get("collected_at")
    if not isinstance(value, str) or not value.strip():
        raise MediaAssetError("Media snapshot is missing collected_at")
    try:
        collected_at = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise MediaAssetError("Media snapshot collected_at is invalid") from error
    if collected_at.tzinfo is None:
        raise MediaAssetError("Media snapshot collected_at must include a timezone")
    now = current_time or datetime.now(timezone.utc)
    age_minutes = (
        now.astimezone(timezone.utc) - collected_at.astimezone(timezone.utc)
    ).total_seconds() / 60
    if age_minutes < -1:
        raise MediaAssetError("Media snapshot collected_at is unexpectedly in the future")
    if age_minutes > policy["snapshot_max_age_minutes"]:
        raise MediaAssetError(
            "Media snapshot is stale: "
            f"{age_minutes:.1f} minutes old; maximum is "
            f"{policy['snapshot_max_age_minutes']}"
        )
    assets = snapshot.get("assets")
    if not isinstance(assets, list) or not assets:
        if snapshot.get("collection_status") == "no_downloadable_media":
            diagnostics = snapshot.get("diagnostics") or {}
            if diagnostics.get("blob_stream_count"):
                raise MediaAssetError(
                    "The Douyin player only exposed a blob/MediaSource stream; "
                    "run the media collector in the browser DevTools console after playback starts"
                )
        raise MediaAssetError("Media snapshot does not contain any assets")
    return round(age_minutes, 2)


def _host_allowed(hostname, suffixes):
    host = (hostname or "").lower().rstrip(".")
    return any(
        host == suffix.lower().lstrip(".")
        or host.endswith("." + suffix.lower().lstrip("."))
        for suffix in suffixes
    )


def validate_asset_url(url, policy):
    normalized = str(url or "")
    if not normalized or len(normalized) > policy["maximum_asset_url_length"]:
        raise MediaAssetError("Media asset URL is empty or too long")
    if any(ord(character) < 32 for character in normalized):
        raise MediaAssetError("Media asset URL contains control characters")
    try:
        parts = urlsplit(normalized)
        port = parts.port
    except ValueError as error:
        raise MediaAssetError("Media asset URL has an invalid port") from error
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
        or port not in {None, 443}
        or not _host_allowed(
            parts.hostname, policy["allowed_https_host_suffixes"]
        )
    ):
        raise MediaAssetError("Media asset URL is not an approved HTTPS CDN URL")
    return normalized


def render_download_config(url, output_path, policy):
    url = validate_asset_url(url, policy)
    output = Path(output_path)
    if output.is_absolute() or ".." in output.parts:
        raise MediaAssetError("Media output path must stay inside the repository")
    return "\n".join(
        [
            f"url = {json.dumps(url)}",
            f"output = {json.dumps(output.as_posix())}",
            "location",
            "fail",
            "retry = 2",
            "connect-timeout = 20",
            "max-time = 300",
            'user-agent = "Mozilla/5.0"',
            'proto = "=https"',
            'proto-redir = "=https"',
            "",
        ]
    )


def read_download_config(path, expected_output, policy):
    text = Path(path).read_text(encoding="utf-8")
    url_matches = [URL_PATTERN.fullmatch(line.strip()) for line in text.splitlines()]
    url_matches = [match for match in url_matches if match]
    output_matches = [
        OUTPUT_PATTERN.fullmatch(line.strip()) for line in text.splitlines()
    ]
    output_matches = [match for match in output_matches if match]
    if len(url_matches) != 1 or len(output_matches) != 1:
        raise MediaAssetError("Download config needs exactly one URL and output")
    try:
        url = json.loads(url_matches[0].group("value"))
        output = json.loads(output_matches[0].group("value"))
    except json.JSONDecodeError as error:
        raise MediaAssetError("Download config contains invalid quoting") from error
    expected = Path(expected_output).as_posix()
    if output != expected:
        raise MediaAssetError("Download config output does not match the queued path")
    return validate_asset_url(url, policy)


def downloaded_media_error(path, minimum_bytes):
    path = Path(path)
    if not path.is_file():
        return "curl completed without creating the media file"
    size = path.stat().st_size
    if size < minimum_bytes:
        return f"downloaded media is too small ({size} bytes)"
    with path.open("rb") as file:
        head = file.read(4096)
    normalized_head = head.lstrip().lower()
    if (
        normalized_head.startswith(b"<!doctype html")
        or normalized_head.startswith(b"<html")
        or normalized_head.startswith(b"<?xml")
        or b"<html" in normalized_head
        or b"accessdenied" in normalized_head
    ):
        return "downloaded content is an HTML/XML error response, not media"
    mp4_box = len(head) >= 12 and head[4:8] in {
        b"ftyp",
        b"styp",
        b"moov",
        b"moof",
        b"mdat",
    }
    known_signature = (
        mp4_box
        or b"ftyp" in head[:128]
        or (head.startswith(b"RIFF") and head[8:12] == b"WAVE")
        or head.startswith(b"ID3")
        or (len(head) >= 2 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0)
        or head.startswith(b"OggS")
        or head.startswith(b"\x1aE\xdf\xa3")
    )
    if not known_signature:
        return "downloaded file does not have a recognized media signature"
    return None


def redact_urls(message):
    return re.sub(r"https?://\S+", "[redacted-media-url]", str(message or ""))
