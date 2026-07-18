#!/usr/bin/env python3
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from package_skill_release import archive_name, package_skill, release_files


class ReleasePackageTests(unittest.TestCase):
    def test_version_cannot_escape_output_directory(self):
        for version in ["", "../1.0.0", "1.0", "release-latest"]:
            with self.subTest(version=version), self.assertRaises(ValueError):
                archive_name(version)

    def test_package_version_must_match_project_metadata(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            ValueError, "configured"
        ):
            package_skill("9.9.9", directory)

    def test_archive_is_deterministic_complete_and_portable(self):
        with tempfile.TemporaryDirectory() as first_directory, tempfile.TemporaryDirectory() as second_directory:
            first = package_skill("1.1.0-dev.3", first_directory)
            second = package_skill("1.1.0-dev.3", second_directory)
            first_archive = Path(first["archive"])
            second_archive = Path(second["archive"])
            self.assertEqual(first_archive.read_bytes(), second_archive.read_bytes())
            self.assertEqual(
                first["sha256"], hashlib.sha256(first_archive.read_bytes()).hexdigest()
            )
            self.assertEqual(first["file_count"], len(release_files()))

            with zipfile.ZipFile(first_archive) as archive:
                self.assertIsNone(archive.testzip())
                names = archive.namelist()
                self.assertEqual(len(names), len(set(names)))
                self.assertTrue(
                    all(name.startswith("liuhui-badminton-coach/") for name in names)
                )
                knowledge = json.loads(
                    archive.read(
                        "liuhui-badminton-coach/references/knowledge-base.json"
                    )
                )
                self.assertFalse(knowledge["transcript_files_bundled"])
                self.assertFalse(
                    any("transcript_file" in video for video in knowledge["videos"])
                )

                extract_root = Path(first_directory) / "extracted"
                archive.extractall(extract_root)
            skill_root = extract_root / "liuhui-badminton-coach"
            completed = subprocess.run(
                [sys.executable, "scripts/doctor.py", "--profile", "skill"],
                cwd=skill_root,
                text=True,
                capture_output=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertTrue(json.loads(completed.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
