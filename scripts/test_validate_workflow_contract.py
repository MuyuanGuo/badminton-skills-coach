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

    def test_quality_gates_run_as_independent_matrix_jobs(self):
        expected_jobs = {
            "quality-report": "evaluations",
            "runtime-performance": "performance",
            "answer-packet": "answer_packet",
        }
        for name, kind in expected_jobs.items():
            self.assertIn(
                f"- name: {name}\n            kind: {kind}",
                self.workflow,
            )

        expected_steps = {
            "matrix.kind == 'evaluations'": 2,
            "matrix.kind == 'performance'": 1,
            "matrix.kind == 'answer_packet'": 1,
        }
        for condition, count in expected_steps.items():
            self.assertEqual(self.workflow.count(f"if: {condition}"), count)

        self.assertEqual(
            self.workflow.count("python scripts/benchmark_runtime.py"),
            1,
        )
        self.assertEqual(
            self.workflow.count("python scripts/evaluate_answer_packet.py"),
            1,
        )

    def test_expensive_static_tools_run_once(self):
        self.assertEqual(self.workflow.count("matrix.python == '3.12'"), 3)
        self.assertIn("Lint Python sources", self.workflow)
        self.assertIn("Type-check architecture-critical modules", self.workflow)

    def test_pull_requests_use_bounded_parallel_fast_and_compatibility_suites(self):
        self.assertIn(
            "if: matrix.python == '3.10' && github.event_name == 'pull_request'",
            self.workflow,
        )
        self.assertIn(
            "if: matrix.python == '3.12' || github.event_name != 'pull_request'",
            self.workflow,
        )
        self.assertIn(
            "python scripts/run_ci_tests.py compatibility --workers 2",
            self.workflow,
        )
        self.assertIn(
            "python scripts/run_ci_tests.py fast --workers 2",
            self.workflow,
        )


if __name__ == "__main__":
    unittest.main()
