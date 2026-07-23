#!/usr/bin/env python3
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "generate_evaluation_report.py"


def load_module():
    spec = importlib.util.spec_from_file_location("evaluation_report_tested", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EvaluationReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_json_bytes_are_deterministic_and_end_with_newline(self):
        payload = {"z": 1, "text": "羽毛球"}
        first = self.module.json_bytes(payload)
        self.assertEqual(first, self.module.json_bytes(payload))
        self.assertTrue(first.endswith(b"\n"))
        self.assertEqual(json.loads(first), payload)

    def test_hash_seed_guard_reexecs_only_when_needed(self):
        with mock.patch.dict("os.environ", {"PYTHONHASHSEED": "0"}, clear=True):
            with mock.patch("os.execvpe") as execute:
                self.module.ensure_deterministic_hash_seed()
        execute.assert_not_called()

        with mock.patch.dict("os.environ", {}, clear=True):
            with mock.patch("os.execvpe") as execute:
                self.module.ensure_deterministic_hash_seed()
        execute.assert_called_once()
        self.assertEqual(execute.call_args.args[2]["PYTHONHASHSEED"], "0")

    def test_hash_paths_includes_relative_path_and_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            left = root / "a.json"
            right = root / "b.json"
            left.write_text("one", encoding="utf-8")
            right.write_text("two", encoding="utf-8")
            original = self.module.hash_paths([right, left], root)
            self.assertEqual(original, self.module.hash_paths([left, right], root))
            right.write_text("changed", encoding="utf-8")
            self.assertNotEqual(original, self.module.hash_paths([left, right], root))

    def test_input_fingerprint_uses_explicit_committed_inputs(self):
        self.assertIn(
            "data/evaluation/evaluation_baselines.json",
            self.module.EVALUATION_INPUTS,
        )
        self.assertNotIn(
            "data/evaluation/evaluation_report.json",
            self.module.EVALUATION_INPUTS,
        )
        self.assertNotIn(
            "data/knowledge/liuhui_badminton_map.json",
            self.module.EVALUATION_INPUTS,
        )

    def test_baseline_comparison_honors_direction_and_tolerance(self):
        evaluations = {"suite": {"score": 0.98, "errors": 0, "ready": True}}
        baseline = {
            "metrics": {
                "suite.score": {
                    "value": 1.0,
                    "direction": "at_least",
                    "tolerance": 0.02,
                },
                "suite.errors": {"value": 0, "direction": "at_most"},
                "suite.ready": {"value": True, "direction": "equal"},
            }
        }
        comparisons = self.module.compare_baseline(evaluations, baseline)
        self.assertTrue(all(item["passed"] for item in comparisons))

    def test_baseline_comparison_reports_regression(self):
        evaluations = {"suite": {"score": 0.8}}
        baseline = {
            "metrics": {
                "suite.score": {"value": 0.9, "direction": "at_least"}
            }
        }
        comparison = self.module.compare_baseline(evaluations, baseline)[0]
        self.assertFalse(comparison["passed"])
        self.assertEqual(comparison["metric"], "suite.score")

    def test_rendered_html_exposes_summary_and_hashes(self):
        report = {
            "development_version": "1.4.0-dev.1",
            "baseline_version": "v1.3.0",
            "build": {
                "id": "abc123",
                "inputs_sha256": "a" * 64,
                "runtime_sha256": "b" * 64,
            },
            "summary": {"status": "pass", "baseline_metrics": 8},
            "evaluations": {
                "answer_policy": {"accuracy": 1.0},
                "answer_context": {"selected_video_recall": 1.0},
                "answer_quality": {
                    "automatic_pass_rate": 1.0,
                    "passed": 57,
                    "answers_supplied": 57,
                },
                "query_equivalence": {"passed_families": 4},
                "query_understanding": {
                    "accuracy": 1.0,
                    "passed": 143,
                    "cases": 143,
                    "adversarial_cases": 86,
                },
                "diagnostic_answer_contract": {"accuracy": 1.0},
                "retrieval": {
                    "mean_ndcg_at_k": 0.86,
                    "hard_negative_top_k_violations": 0,
                    "found_videos": 173,
                    "expected_videos": 173,
                },
                "video_comprehension": {
                    "understanding_coverage": 1.0,
                    "ready_videos": 353,
                    "transcript_backed": 334,
                    "visual_review_fallback": 19,
                },
                "forward_tests": {"consecutive_passes": 3},
            },
            "baseline_comparison": [
                {"metric": f"{suite}.metric", "passed": True}
                for suite in (
                    "answer_policy",
                    "answer_context",
                    "answer_quality",
                    "query_equivalence",
                    "query_understanding",
                    "diagnostic_answer_contract",
                    "retrieval",
                    "video_comprehension",
                    "forward_tests",
                )
            ],
        }
        page = self.module.render_html(report).decode("utf-8")
        self.assertIn("Evidence quality", page)
        self.assertIn("abc123", page)
        self.assertIn("a" * 64, page)
        self.assertIn("57/57", page)
        self.assertEqual(page.count(">PASS<"), 10)
        self.assertIn("tbody td:nth-of-type(3)", page)

    def test_check_artifact_distinguishes_missing_stale_and_current(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / "report.json"
            self.assertIn("missing", self.module.check_artifact(path, b"ok"))
            path.write_bytes(b"old")
            self.assertIn("stale", self.module.check_artifact(path, b"ok"))
            path.write_bytes(b"ok")
            self.assertIsNone(self.module.check_artifact(path, b"ok"))


if __name__ == "__main__":
    unittest.main()
