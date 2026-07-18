#!/usr/bin/env python3
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import download_douyin_browser_batch as browser_download


VIDEO_ID = "7663523942439940453"
PROFILE_ID = "MS4wLjABAAAArown2iD4dOZU015mQhaFt43bhkyhMu6c-SOUrTlmSqA"
VIDEO_URL = f"https://www.douyin.com/video/{VIDEO_ID}"


def queue_payload(status="classified_teaching"):
    return {
        "counts": {status: 1},
        "items": [
            {
                "video_id": VIDEO_ID,
                "url": VIDEO_URL,
                "title": "多点位抽球应用",
                "status": status,
                "classification_decision": "保留：教学",
                "attempts": 0,
                "error": None,
                "media_path": None,
            }
        ],
    }


class BrowserDownloadTests(unittest.TestCase):
    def test_metadata_requires_exact_video_and_creator(self):
        line = "\t".join(
            [VIDEO_ID, "104", "69026094140", PROFILE_ID, "mp4", "720p", VIDEO_URL]
        )
        metadata = browser_download.parse_metadata_line(line, VIDEO_ID, PROFILE_ID)
        self.assertEqual(metadata["video_id"], VIDEO_ID)
        self.assertEqual(metadata["duration_seconds"], 104)
        with self.assertRaisesRegex(browser_download.BrowserDownloadError, "configured creator"):
            browser_download.parse_metadata_line(line, VIDEO_ID, "different-profile")
        with self.assertRaisesRegex(browser_download.BrowserDownloadError, "expected"):
            browser_download.parse_metadata_line(line, "7999999999999999999", PROFILE_ID)

    def test_candidate_selection_rejects_non_teaching_and_completed_items(self):
        queue = queue_payload()
        self.assertEqual(
            [item["video_id"] for item in browser_download.select_candidates(queue)],
            [VIDEO_ID],
        )
        queue["items"][0]["classification_decision"] = "排除：非教学"
        with self.assertRaisesRegex(browser_download.BrowserDownloadError, "non-teaching"):
            browser_download.select_candidates(queue, [VIDEO_ID])
        queue["items"][0]["classification_decision"] = "保留：教学"
        queue["items"][0]["status"] = "transcribed"
        with self.assertRaisesRegex(browser_download.BrowserDownloadError, "non-downloadable"):
            browser_download.select_candidates(queue, [VIDEO_ID])

    def test_process_batch_checkpoints_verified_download(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue_path = root / "queue.json"
            source_path = root / "source.json"
            raw_root = root / "raw"
            queue_path.write_text(json.dumps(queue_payload()), encoding="utf-8")
            source_path.write_text(
                json.dumps({"profile_id": PROFILE_ID}), encoding="utf-8"
            )

            @contextmanager
            def fake_browser(*_args, **_kwargs):
                yield "ws://127.0.0.1:1234/devtools/browser/test", object()

            def fake_download(
                _cookies,
                _url,
                video_id,
                profile_id,
                output_dir,
                _policy,
                force=False,
            ):
                self.assertFalse(force)
                self.assertEqual(profile_id, PROFILE_ID)
                path = Path(output_dir) / f"{video_id}.mp4"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"x" * 100)
                return path, {"duration_seconds": 104.0, "format_id": "720p"}

            checks = {
                "ok": True,
                "chrome": "/fake/chrome",
                "node": "/fake/node",
                "node_websocket": True,
                "yt_dlp": True,
                "cookie_exporter": True,
            }
            with patch.object(browser_download, "ROOT", root), patch.object(
                browser_download, "QUEUE_PATH", queue_path
            ), patch.object(
                browser_download, "SOURCE_CONFIG_PATH", source_path
            ), patch.object(browser_download, "RAW_ROOT", raw_root), patch.object(
                browser_download, "preflight", return_value=checks
            ), patch.object(
                browser_download, "anonymous_chrome_session", fake_browser
            ), patch.object(
                browser_download, "export_anonymous_cookies", return_value={"count": 2}
            ), patch.object(
                browser_download, "download_verified_video", side_effect=fake_download
            ), patch.object(
                browser_download,
                "load_media_policy",
                return_value={"minimum_download_bytes": 8},
            ):
                result = browser_download.process_batch("batch-049", [VIDEO_ID])

            saved = json.loads(queue_path.read_text(encoding="utf-8"))["items"][0]
            self.assertEqual(result["downloaded"], [VIDEO_ID])
            self.assertEqual(saved["status"], "downloaded")
            self.assertEqual(saved["duration_seconds"], 104.0)
            self.assertEqual(saved["media_download_method"], "anonymous_chrome_cdp_yt_dlp")
            self.assertEqual(saved["download_attempts"], 1)
            self.assertIsNone(saved["error"])

    def test_cookie_export_failure_is_resumable_queue_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue_path = root / "queue.json"
            source_path = root / "source.json"
            queue_path.write_text(json.dumps(queue_payload()), encoding="utf-8")
            source_path.write_text(
                json.dumps({"profile_id": PROFILE_ID}), encoding="utf-8"
            )

            @contextmanager
            def fake_browser(*_args, **_kwargs):
                yield "ws://127.0.0.1:1234/devtools/browser/test", object()

            checks = {
                "ok": True,
                "chrome": "/fake/chrome",
                "node": "/fake/node",
                "node_websocket": True,
                "yt_dlp": True,
                "cookie_exporter": True,
            }
            with patch.object(browser_download, "ROOT", root), patch.object(
                browser_download, "QUEUE_PATH", queue_path
            ), patch.object(
                browser_download, "SOURCE_CONFIG_PATH", source_path
            ), patch.object(browser_download, "RAW_ROOT", root / "raw"), patch.object(
                browser_download, "preflight", return_value=checks
            ), patch.object(
                browser_download, "anonymous_chrome_session", fake_browser
            ), patch.object(
                browser_download,
                "export_anonymous_cookies",
                side_effect=browser_download.BrowserDownloadError("cookie export failed"),
            ), patch.object(
                browser_download,
                "load_media_policy",
                return_value={"minimum_download_bytes": 8},
            ):
                result = browser_download.process_batch("batch-049", [VIDEO_ID])

            saved = json.loads(queue_path.read_text(encoding="utf-8"))["items"][0]
            self.assertEqual(result["failed"], [VIDEO_ID])
            self.assertEqual(saved["status"], "extraction_failed")
            self.assertEqual(saved["error_stage"], "anonymous_browser")
            self.assertEqual(saved["download_attempts"], 1)


if __name__ == "__main__":
    unittest.main()
