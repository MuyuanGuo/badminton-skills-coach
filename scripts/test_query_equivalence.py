#!/usr/bin/env python3
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "evaluate_query_equivalence.py"


def load_module():
    spec = importlib.util.spec_from_file_location(
        "query_equivalence_test", MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class QueryEquivalenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_registry_covers_paraphrases_symptoms_and_negative_controls(self):
        families = self.module.validate_registry(self.module.load_registry())
        self.assertEqual(len(families), 1)
        self.assertEqual(len(families[0]["variants"]), 4)
        self.assertEqual(len(families[0]["negative_controls"]), 3)

    def test_query_equivalence_quality_gate_passes(self):
        result = self.module.evaluate()
        self.assertEqual(result["families"], 1)
        self.assertEqual(result["variants"], 4)
        self.assertEqual(result["negative_controls"], 3)
        self.assertEqual(result["failed_families"], [])


if __name__ == "__main__":
    unittest.main()
