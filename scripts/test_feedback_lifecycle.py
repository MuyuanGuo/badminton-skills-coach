#!/usr/bin/env python3
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "evaluate_feedback_lifecycle.py"


def load_module():
    spec = importlib.util.spec_from_file_location(
        "feedback_lifecycle_test", MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FeedbackLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_repository_feedback_contracts_pass(self):
        result = self.module.evaluate()
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["queue_statuses"], 5)
        self.assertGreaterEqual(result["adversarial_contract_checks"], 7)
        self.assertEqual(result["contract_accuracy"], 1.0)
        self.assertEqual(result["leaked_private_fields"], [])


if __name__ == "__main__":
    unittest.main()
