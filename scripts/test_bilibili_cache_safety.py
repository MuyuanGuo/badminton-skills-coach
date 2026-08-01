#!/usr/bin/env python3
import tempfile
import unittest
from pathlib import Path

import build_bilibili_knowledge as builder
import process_bilibili_candidates as acquisition
from bilibili_storage import (
    lexical_absolute,
    media_storage_key,
    resolve_queue_media_path,
)


class BilibiliCachePathSafetyTests(unittest.TestCase):
    def test_lexical_absolute_collapses_dot_segments_without_resolving_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            link = project / "cache-link"
            link.symlink_to(root / "external", target_is_directory=True)

            normalized = lexical_absolute(
                Path("cache-link") / ".." / "media",
                root=project,
            )

            self.assertEqual(normalized, project / "media")
            self.assertNotIn("external", normalized.parts)

    def test_relative_queue_media_path_cannot_escape_project_root(self):
        video_id = "BV1test"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            outside = root / "outside"
            project.mkdir()
            outside.mkdir()
            media = outside / f"{media_storage_key(video_id)}.m4a"
            media.write_bytes(b"audio")

            with self.assertRaisesRegex(ValueError, "escapes the project root"):
                resolve_queue_media_path(
                    {
                        "media_path": str(
                            Path("..") / "outside" / media.name
                        ),
                    },
                    video_id,
                    project_root=project,
                )

    def test_normalized_traversal_is_not_within_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "cache"
            cache.mkdir()

            self.assertFalse(
                acquisition.path_is_within(
                    cache / ".." / "outside" / "video.m4a",
                    cache,
                )
            )


class BilibiliBuildPolicySafetyTests(unittest.TestCase):
    def test_required_queue_item_is_admitted(self):
        builder.validate_queue_classification_policy(
            {"items": [{"video_id": "BV1required"}]},
            {
                "videos": [
                    {
                        "bvid": "BV1required",
                        "decision": "required_transcription_policy",
                    }
                ]
            },
        )

    def test_excluded_orphan_in_queue_fails_closed(self):
        with self.assertRaisesRegex(
            ValueError,
            "BV1excluded:excluded_transcription_policy",
        ):
            builder.validate_queue_classification_policy(
                {"items": [{"video_id": "BV1excluded"}]},
                {
                    "videos": [
                        {
                            "bvid": "BV1excluded",
                            "decision": "excluded_transcription_policy",
                        }
                    ]
                },
            )

    def test_missing_or_nonrequired_queue_item_fails_closed(self):
        for ledger, expected in [
            ({"videos": []}, "BV1missing:missing"),
            (
                {
                    "videos": [
                        {
                            "bvid": "BV1candidate",
                            "decision": "candidate_liuhui_teaching",
                        }
                    ]
                },
                "BV1candidate:candidate_liuhui_teaching",
            ),
        ]:
            video_id = expected.split(":", 1)[0]
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(ValueError, expected):
                    builder.validate_queue_classification_policy(
                        {"items": [{"video_id": video_id}]},
                        ledger,
                    )


if __name__ == "__main__":
    unittest.main()
