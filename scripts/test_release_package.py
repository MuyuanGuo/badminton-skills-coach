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
from package_skill_release import (
    archive_name,
    is_cloud_conflict_copy,
    package_skill,
    release_files,
)


ROOT = Path(__file__).resolve().parents[1]
CURRENT_VERSION = json.loads(
    (ROOT / "config" / "feedback_rules.json").read_text(encoding="utf-8")
)["skill_version"]
RELEASE_VERSION = f"v{CURRENT_VERSION}"


class ReleasePackageTests(unittest.TestCase):
    def test_cloud_conflict_copy_is_ignored_only_when_canonical_file_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            canonical = root / "build-manifest.json"
            conflict = root / "build-manifest 2.json"
            conflict.write_text("cloud placeholder", encoding="utf-8")
            self.assertFalse(is_cloud_conflict_copy(conflict))
            canonical.write_text("canonical", encoding="utf-8")
            self.assertTrue(is_cloud_conflict_copy(conflict))
            self.assertFalse(is_cloud_conflict_copy(canonical))

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
                self.assertIn("liuhui-badminton-coach/LICENSE", names)
                self.assertIn("liuhui-badminton-coach/NOTICE", names)
                self.assertIn(
                    "liuhui-badminton-coach/references/runtime-store.sqlite3",
                    names,
                )
                self.assertNotIn(
                    "liuhui-badminton-coach/references/knowledge-base.json",
                    names,
                )
                self.assertNotIn(
                    "liuhui-badminton-coach/references/retrieval-index.json",
                    names,
                )
                self.assertNotIn(
                    "liuhui-badminton-coach/references/evidence-graph.json",
                    names,
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
            file_components = [
                item for item in first["components"] if item["type"] == "file"
            ]
            optional_components = [
                item for item in first["components"] if item.get("scope") == "optional"
            ]
            self.assertEqual(len(file_components), len(release_files()))
            self.assertGreater(len(optional_components), 20)
            self.assertTrue(
                all(item["purl"].startswith("pkg:pypi/") for item in optional_components)
            )
            self.assertTrue(
                all(
                    component["hashes"][0]["alg"] == "SHA-256"
                    for component in file_components
                )
            )

    def test_unexpected_skill_file_fails_closed(self):
        unexpected = ROOT / "skills" / "liuhui-badminton-coach" / "unexpected.tmp"
        unexpected.write_text("must be explicitly allowlisted\n", encoding="utf-8")
        try:
            with self.assertRaisesRegex(ValueError, "unexpected Skill files"):
                release_files()
        finally:
            unexpected.unlink()

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
