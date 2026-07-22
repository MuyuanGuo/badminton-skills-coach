#!/usr/bin/env python3
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from generate_release_sbom import append_checksum, build_sbom
from package_skill_release import archive_name, package_skill, release_files


ROOT = Path(__file__).resolve().parents[1]
CURRENT_VERSION = json.loads(
    (ROOT / "config" / "feedback_rules.json").read_text(encoding="utf-8")
)["skill_version"]
RELEASE_VERSION = f"v{CURRENT_VERSION}"


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
            first = package_skill(RELEASE_VERSION, first_directory)
            second = package_skill(RELEASE_VERSION, second_directory)
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
                self.assertTrue(knowledge["runtime_transcript_segments_bundled"])
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

    def test_sbom_is_deterministic_and_covers_every_release_file(self):
        with tempfile.TemporaryDirectory() as directory:
            packaged = package_skill(RELEASE_VERSION, directory)
            archive = Path(packaged["archive"])
            first = build_sbom(archive, RELEASE_VERSION)
            second = build_sbom(archive, RELEASE_VERSION)
            self.assertEqual(first, second)
            self.assertEqual(first["bomFormat"], "CycloneDX")
            self.assertEqual(first["specVersion"], "1.6")
            self.assertEqual(len(first["components"]), len(release_files()))
            self.assertTrue(
                all(component["hashes"][0]["alg"] == "SHA-256" for component in first["components"])
            )

    def test_checksum_manifest_uses_downloadable_asset_names(self):
        with tempfile.TemporaryDirectory() as directory:
            packaged = package_skill(RELEASE_VERSION, directory)
            nested = Path(directory) / "dist"
            nested.mkdir()
            sbom_path = nested / "SBOM.cdx.json"
            sbom_path.write_text("{}\n", encoding="utf-8")
            checksum_path = Path(packaged["checksum_file"])

            append_checksum(checksum_path, sbom_path)

            lines = checksum_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertTrue(lines[0].endswith(f"  {Path(packaged['archive']).name}"))
            self.assertTrue(lines[1].endswith("  SBOM.cdx.json"))
            self.assertNotIn("dist/", lines[1])


if __name__ == "__main__":
    unittest.main()
