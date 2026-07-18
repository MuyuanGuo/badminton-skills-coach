#!/usr/bin/env python3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from media_assets import (
    MediaAssetError,
    downloaded_media_error,
    read_download_config,
    redact_urls,
    render_download_config,
    validate_asset_url,
    validate_batch_name,
    validate_media_snapshot,
    validate_page_url,
)


POLICY = {
    "allowed_https_host_suffixes": ["zjcdn.com", "douyinvod.com"],
    "snapshot_max_age_minutes": 20,
    "maximum_asset_url_length": 8192,
    "minimum_download_bytes": 8,
}
VIDEO_ID = "123456789012345678"
ASSET_HOST = "v3-dy-o." + "zjcdn.com"
ASSET_URL = f"https://{ASSET_HOST}/media/audio.mp4?token=secret"


class MediaAssetTests(unittest.TestCase):
    def test_safe_download_config_round_trip(self):
        output = Path("data/raw_videos/douyin/batch-001") / f"{VIDEO_ID}.m4a"
        text = render_download_config(ASSET_URL, output, POLICY)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "asset.curl"
            path.write_text(text, encoding="utf-8")
            self.assertEqual(
                read_download_config(path, output, POLICY), ASSET_URL
            )
        self.assertIn('proto = "=https"', text)
        self.assertIn('proto-redir = "=https"', text)

    def test_asset_url_rejects_config_injection_and_unapproved_hosts(self):
        for url in [
            ASSET_URL + '\noutput = "/tmp/stolen"',
            "file:///etc/passwd",
            "https://" + "zjcdn.com.evil.example/media/audio.mp4",
            f"https://user:password@{ASSET_HOST}/media/audio.mp4",
            "https://[broken/media/audio.mp4",
        ]:
            with self.subTest(url=url), self.assertRaises(MediaAssetError):
                validate_asset_url(url, POLICY)

    def test_page_and_batch_paths_are_scoped(self):
        self.assertEqual(validate_batch_name("batch-049"), "batch-049")
        validate_page_url(
            f"https://www.douyin.com/video/{VIDEO_ID}?from=profile", VIDEO_ID
        )
        with self.assertRaises(MediaAssetError):
            validate_batch_name("../../outside")
        with self.assertRaises(MediaAssetError):
            validate_page_url(
                "https://www.douyin.com/video/999999999999999999", VIDEO_ID
            )

    def test_media_snapshot_must_be_fresh_and_match_the_page(self):
        now = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
        snapshot = {
            "video_id": VIDEO_ID,
            "page_url": f"https://www.douyin.com/video/{VIDEO_ID}",
            "collected_at": (now - timedelta(minutes=5)).isoformat(),
            "assets": [{"kind": "video", "url": ASSET_URL}],
        }
        self.assertEqual(
            validate_media_snapshot(snapshot, VIDEO_ID, POLICY, current_time=now),
            5.0,
        )
        snapshot["collected_at"] = (now - timedelta(minutes=21)).isoformat()
        with self.assertRaisesRegex(MediaAssetError, "stale"):
            validate_media_snapshot(snapshot, VIDEO_ID, POLICY, current_time=now)

    def test_download_rejects_error_pages_and_tiny_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "media.m4a"
            path.write_bytes(b"tiny")
            self.assertIn("too small", downloaded_media_error(path, 8))
            path.write_bytes(b"<!doctype html><html>expired</html>" + b"x" * 100)
            self.assertIn("not media", downloaded_media_error(path, 8))
            path.write_bytes(b"\x00\x00\x00\x18ftypM4A " + b"x" * 100)
            self.assertIsNone(downloaded_media_error(path, 8))
            path.write_bytes(b"not a media file" + b"x" * 100)
            self.assertIn("recognized media signature", downloaded_media_error(path, 8))

    def test_logs_redact_short_lived_media_urls(self):
        self.assertNotIn(
            "token=secret", redact_urls(f"curl failed for {ASSET_URL}")
        )


if __name__ == "__main__":
    unittest.main()
