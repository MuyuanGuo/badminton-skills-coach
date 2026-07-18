#!/usr/bin/env python3
import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "liuhui-badminton-coach"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DoctorAndInstallerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doctor = load_module("doctor_test_module", SKILL_ROOT / "scripts" / "doctor.py")
        cls.installer = load_module("installer_test_module", SKILL_ROOT / "scripts" / "install.py")

    def test_packaged_skill_passes_dependency_free_doctor_profile(self):
        checks = self.doctor.skill_checks(SKILL_ROOT, run_smoke=True)
        result = self.doctor.summarize("skill", checks)
        self.assertTrue(result["ok"])
        self.assertFalse(result["api_key_required"])
        self.assertEqual(result["summary"]["failed"], 0)

    def test_transcription_python_override_has_priority(self):
        with tempfile.TemporaryDirectory() as temporary:
            fake_python = Path(temporary) / "custom-python"
            fake_python.touch()
            resolved = self.doctor.resolve_transcription_python(
                ROOT, override=fake_python
            )
            self.assertEqual(resolved, fake_python.absolute())
            self.assertIsNone(
                self.doctor.resolve_transcription_python(
                    ROOT, override=Path(temporary) / "missing-python"
                )
            )

    def test_all_profile_has_unique_check_names(self):
        checks = self.doctor.skill_checks(SKILL_ROOT, run_smoke=False)
        checks.extend(
            self.doctor.maintainer_checks(ROOT, transcription=True)
        )
        names = [item["name"] for item in checks]
        self.assertEqual(len(names), len(set(names)))

    def test_atomic_installer_replaces_stale_files_and_runs_doctor(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "skills" / "liuhui-badminton-coach"
            destination.mkdir(parents=True)
            (destination / "stale-file.txt").write_text("old", encoding="utf-8")
            result = self.installer.install_skill(SKILL_ROOT, destination)
            self.assertEqual(result["status"], "installed")
            self.assertTrue(result["stale_files_removed"])
            self.assertFalse((destination / "stale-file.txt").exists())
            self.assertTrue((destination / "scripts" / "doctor.py").exists())
            self.assertEqual(result["doctor"]["failed"], 0)


if __name__ == "__main__":
    unittest.main()
