#!/usr/bin/env python3
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ValidateWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = (ROOT / ".github" / "workflows" / "validate.yml").read_text(
            encoding="utf-8"
        )

    def test_change_scope_controls_expensive_jobs(self):
        self.assertIn("python scripts/classify_ci_scope.py", self.workflow)
        self.assertIn("needs.changes.outputs.static == 'true'", self.workflow)
        self.assertIn("needs.changes.outputs.artifact == 'true'", self.workflow)
        self.assertIn("needs.changes.outputs.quality == 'true'", self.workflow)
        self.assertIn("needs.changes.outputs.docs_only == 'true'", self.workflow)

    def test_canary_matrix_has_six_shards(self):
        self.assertEqual(self.workflow.count("kind: canary"), 6)
        self.assertEqual(self.workflow.count("shard_count: 6"), 6)
        for shard in range(1, 7):
            self.assertIn(f"name: bilibili-canary-{shard}", self.workflow)
        self.assertIn("--shard-index ${{ matrix.shard_index }}", self.workflow)
        self.assertIn("--shard-count ${{ matrix.shard_count }}", self.workflow)

    def test_expensive_static_tools_run_once(self):
        self.assertEqual(self.workflow.count("if: matrix.python == '3.12'"), 2)
        self.assertIn("Lint Python sources", self.workflow)
        self.assertIn("Type-check architecture-critical modules", self.workflow)


if __name__ == "__main__":
    unittest.main()
