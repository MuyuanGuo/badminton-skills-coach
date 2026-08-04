#!/usr/bin/env python3
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "generate_release_answer_results.py"


def load_module():
    spec = importlib.util.spec_from_file_location(
        "release_answer_generation_test", MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReleaseAnswerGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_current_runtime_generation_is_reproducible_and_release_eligible(self):
        payload = self.module.build_results(generated_at="2026-08-03")
        result = self.module.validate_results(payload, rerun_runtime=True)
        self.assertEqual(payload["schema_version"], 3)
        self.assertEqual(len(payload["cases"]), 3)
        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["release_eligible"])
        self.assertTrue(result["current_renderer_reproduced"])
        self.assertEqual(result["automated_audit_pass_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
