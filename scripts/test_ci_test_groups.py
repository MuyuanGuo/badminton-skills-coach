#!/usr/bin/env python3
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "run_ci_tests.py"


def load_module():
    spec = importlib.util.spec_from_file_location("ci_test_groups_tested", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CiTestGroupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_every_python_test_has_exactly_one_group(self):
        groups = self.module.test_groups()
        assigned = [name for files in groups.values() for name in files]
        self.assertEqual(set(assigned), self.module.discover_test_files())
        self.assertEqual(len(assigned), len(set(assigned)))

    def test_context_regressions_are_split_without_loss_or_overlap(self):
        test_ids = [test.id() for test in self.module.context_tests()]
        partitions = self.module.partition_context_test_ids(3)
        assigned = [test_id for shard in partitions for test_id in shard]
        self.assertGreaterEqual(len(test_ids), 55)
        self.assertEqual(set(assigned), set(test_ids))
        self.assertEqual(len(assigned), len(set(assigned)))
        self.assertLessEqual(max(map(len, partitions)) - min(map(len, partitions)), 1)

    def test_compatibility_tests_are_a_fast_group_subset(self):
        groups = self.module.test_groups()
        self.assertTrue(self.module.COMPATIBILITY_TEST_FILES)
        self.assertTrue(
            self.module.COMPATIBILITY_TEST_FILES.issubset(groups["fast"])
        )

    def test_parallel_runner_keeps_resource_heavy_tests_serial(self):
        groups = self.module.test_groups()
        self.assertTrue(self.module.SERIAL_TEST_FILES)
        self.assertTrue(self.module.SERIAL_TEST_FILES.issubset(groups["fast"]))


if __name__ == "__main__":
    unittest.main()
