#!/usr/bin/env python3
import json
import tempfile
import unittest
from pathlib import Path

from check_release_metadata import validate_release_metadata


class ReleaseMetadataTests(unittest.TestCase):
    def write_rules(self, root, project, skill=None):
        paths = (
            root / "config" / "feedback_rules.json",
            root
            / "skills"
            / "liuhui-badminton-coach"
            / "references"
            / "feedback-rules.json",
        )
        for path, payload in zip(paths, (project, skill or project)):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload), encoding="utf-8")

    def test_stable_tag_matches_both_metadata_copies(self):
        metadata = {
            "skill_version": "2.1.1",
            "channel": "stable",
            "stable_version": "2.1.1",
        }
        with tempfile.TemporaryDirectory() as directory:
            self.write_rules(Path(directory), metadata)
            result = validate_release_metadata("v2.1.1", directory)
        self.assertEqual(result["version"], "2.1.1")

    def test_development_or_mismatched_metadata_cannot_release(self):
        development = {
            "skill_version": "2.1.1-dev.1",
            "channel": "development",
            "stable_version": "2.1.0",
        }
        with tempfile.TemporaryDirectory() as directory:
            self.write_rules(Path(directory), development)
            with self.assertRaisesRegex(ValueError, "stable-channel"):
                validate_release_metadata("v2.1.1", directory)

        stable = {
            "skill_version": "2.1.1",
            "channel": "stable",
            "stable_version": "2.1.1",
        }
        with tempfile.TemporaryDirectory() as directory:
            self.write_rules(Path(directory), stable)
            with self.assertRaisesRegex(ValueError, "does not match"):
                validate_release_metadata("v2.1.2", directory)


if __name__ == "__main__":
    unittest.main()
