#!/usr/bin/env python3
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "evaluate_metamorphic_robustness.py"


def load_module():
    spec = importlib.util.spec_from_file_location(
        "metamorphic_robustness_test", MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MetamorphicRobustnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_harmless_variants_preserve_the_original_query(self):
        variants = self.module.harmless_variants("杀球不重怎么办？")
        self.assertEqual(
            [item["transformation"] for item in variants],
            ["polite_prefix", "conversational_suffix"],
        )
        self.assertTrue(all("杀球不重怎么办" in item["query"] for item in variants))

    def test_balanced_selection_covers_every_case_type(self):
        selected = self.module.select_balanced_cases(
            self.module.load_cases(),
            cases_per_type=3,
        )
        counts = {}
        for case in selected:
            counts[case["case_type"]] = counts.get(case["case_type"], 0) + 1
        self.assertEqual(len(selected), 15)
        self.assertEqual(set(counts.values()), {3})


if __name__ == "__main__":
    unittest.main()
