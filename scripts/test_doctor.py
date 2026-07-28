#!/usr/bin/env python3
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


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
        self.assertEqual(result["version"]["installed_version"], "2.0.0-dev.1")
        self.assertRegex(result["version"]["build_id"], r"^[0-9a-f]{64}$")
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
            self.doctor.maintainer_checks(
                ROOT,
                transcription=True,
                override=Path(sys.executable),
            )
        )
        names = [item["name"] for item in checks]
        self.assertEqual(len(names), len(set(names)))
        self.assertIn("pyyaml", names)
        self.assertIn("yt_dlp", names)

    def test_diagnostic_subprocess_timeout_becomes_a_failure_result(self):
        with mock.patch.object(
            self.doctor.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["slow"], 1),
        ):
            result = self.doctor.run_diagnostic_command(
                ["slow"],
                timeout=1,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 124)
        self.assertIn("timed out after 1 seconds", result.stderr)

    def test_atomic_installer_replaces_stale_files_and_runs_doctor(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "skills" / "liuhui-badminton-coach"
            destination.mkdir(parents=True)
            (destination / "stale-file.txt").write_text("old", encoding="utf-8")
            build_id = self.installer.source_build_id(SKILL_ROOT)
            result = self.installer.install_skill(
                SKILL_ROOT,
                destination,
                expected_build_id=build_id,
            )
            self.assertEqual(result["status"], "installed")
            self.assertEqual(result["build_id"], build_id)
            self.assertTrue(result["stale_files_removed"])
            self.assertFalse((destination / "stale-file.txt").exists())
            self.assertTrue((destination / "scripts" / "doctor.py").exists())
            self.assertEqual(result["doctor"]["failed"], 0)

    def test_expected_build_id_mismatch_refuses_install_without_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "skills" / "liuhui-badminton-coach"
            with self.assertRaisesRegex(ValueError, "changed after validation"):
                self.installer.install_skill(
                    SKILL_ROOT,
                    destination,
                    expected_build_id="0" * 64,
                )
            self.assertFalse(destination.exists())

    def test_keyboard_interrupt_during_swap_restores_old_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "skills" / "liuhui-badminton-coach"
            destination.mkdir(parents=True)
            marker = destination / "old-install.txt"
            marker.write_text("keep me", encoding="utf-8")
            build_id = self.installer.source_build_id(SKILL_ROOT)
            doctor_result = {
                "version": {"build_id": build_id},
                "summary": {"failed": 0},
            }
            real_replace = self.installer.os.replace
            replace_count = 0

            def interrupt_new_install(source, target):
                nonlocal replace_count
                replace_count += 1
                if replace_count == 2:
                    raise KeyboardInterrupt()
                real_replace(source, target)

            with (
                mock.patch.object(
                    self.installer,
                    "run_doctor",
                    return_value=doctor_result,
                ),
                mock.patch.object(
                    self.installer.os,
                    "replace",
                    side_effect=interrupt_new_install,
                ),
                self.assertRaises(KeyboardInterrupt),
            ):
                self.installer.install_skill(
                    SKILL_ROOT,
                    destination,
                    expected_build_id=build_id,
                )
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep me")
            self.assertFalse((destination / "scripts" / "doctor.py").exists())

    def test_concurrent_install_lock_refuses_second_writer(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "skills" / "liuhui-badminton-coach"
            destination.parent.mkdir(parents=True)
            with self.installer.installation_lock(destination):
                with self.assertRaisesRegex(ValueError, "Another install"):
                    self.installer.install_skill(SKILL_ROOT, destination)
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
