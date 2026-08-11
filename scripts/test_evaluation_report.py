#!/usr/bin/env python3
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "generate_evaluation_report.py"


def load_module():
    scripts_dir = str(MODULE_PATH.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
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

    def test_runtime_fingerprint_uses_release_inventory_not_directory_scan(self):
        self.assertIn("release_inventory.py", self.module.CORE_EVALUATORS)
        expected = (
            self.module.RUNTIME_SKILL_PATHS
            | self.module.MAINTAINER_ONLY_SKILL_PATHS
        )
        self.assertIn("scripts/render_answer.py", expected)
        self.assertIn("references/knowledge-base.json", expected)

    def test_parallel_evaluation_plan_is_complete_and_bounded(self):
        self.assertEqual(
            set(self.module.EVALUATION_EXECUTION_ORDER)
            | {"answer_quality", "forward_tests"},
            self.module.EVALUATION_SUITES,
        )
        with self.assertRaisesRegex(ValueError, "workers must be positive"):
            self.module.collect_independent_suites(workers=0)

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

    def test_baseline_comparison_reports_non_numeric_range_metrics(self):
        evaluations = {
            "suite": {
                "stale_score": None,
                "score": 0.8,
                "limits": {"minimum_score": None},
            }
        }
        baseline = {
            "metrics": {
                "suite.stale_score": {
                    "value": 1.0,
                    "direction": "at_least",
                },
                "suite.score": {
                    "value_source": "suite.limits.minimum_score",
                    "direction": "at_least",
                },
            }
        }
        comparisons = self.module.compare_baseline(evaluations, baseline)
        self.assertEqual(
            [item["failure_reason"] for item in comparisons],
            ["non_numeric_current", "non_numeric_baseline"],
        )
        self.assertTrue(all(not item["passed"] for item in comparisons))

    def test_baseline_comparison_skips_explicitly_invalidated_metrics(self):
        evaluations = {"suite": {"contaminated": 0.1, "valid": 1.0}}
        baseline = {
            "invalidated_metrics": {
                "suite.contaminated": "evaluation fixture leakage"
            },
            "metrics": {
                "suite.contaminated": {
                    "value": 1.0,
                    "direction": "at_least",
                },
                "suite.valid": {"value": 1.0, "direction": "at_least"},
            },
        }
        comparisons = self.module.compare_baseline(evaluations, baseline)
        self.assertEqual([item["metric"] for item in comparisons], ["suite.valid"])

    def test_baseline_comparison_can_use_fingerprinted_policy_limit(self):
        evaluations = {
            "suite": {
                "score": 0.11,
                "limits": {"maximum_score": 0.12},
            }
        }
        baseline = {
            "metrics": {
                "suite.score": {
                    "value_source": "suite.limits.maximum_score",
                    "direction": "at_most",
                }
            }
        }
        comparison = self.module.compare_baseline(
            evaluations,
            baseline,
        )[0]
        self.assertTrue(comparison["passed"])
        self.assertEqual(comparison["baseline"], 0.12)
        self.assertEqual(
            comparison["contract_source"],
            "suite.limits.maximum_score",
        )
        evaluations["suite"]["score"] = 0.13
        self.assertFalse(
            self.module.compare_baseline(evaluations, baseline)[0]["passed"]
        )

    def test_current_baseline_cannot_drop_quality_hard_gates(self):
        versions = self.module.load_json(
            ROOT / "config" / "feedback_rules.json"
        )
        baselines = self.module.load_json(self.module.BASELINE_PATH)
        baseline = baselines["baselines"][
            f"v{versions['stable_version']}"
        ]
        self.module.validate_quality_hard_gate_contract(baseline)

        missing = {
            **baseline,
            "metrics": dict(baseline["metrics"]),
        }
        removed = next(
            iter(self.module.REQUIRED_QUALITY_HARD_GATE_METRICS)
        )
        missing["metrics"].pop(removed)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.module.validate_quality_hard_gate_contract(missing)

    def test_each_quality_hard_gate_detects_a_regression(self):
        report = self.module.load_json(self.module.REPORT_PATH)
        versions = self.module.load_json(
            ROOT / "config" / "feedback_rules.json"
        )
        baseline = self.module.load_json(self.module.BASELINE_PATH)["baselines"][
            f"v{versions['stable_version']}"
        ]

        for metric in self.module.REQUIRED_QUALITY_HARD_GATE_METRICS:
            with self.subTest(metric=metric):
                evaluations = json.loads(json.dumps(report["evaluations"]))
                contract = baseline["metrics"][metric]
                expected = contract["value"]
                direction = contract["direction"]
                if direction == "at_least":
                    regressed = expected - 1
                elif direction == "at_most":
                    regressed = expected + 1
                elif isinstance(expected, bool):
                    regressed = not expected
                elif isinstance(expected, list):
                    regressed = ["forced_regression"]
                elif isinstance(expected, str):
                    regressed = "forced_regression"
                else:
                    regressed = expected + 1

                target = evaluations
                parts = metric.split(".")
                for part in parts[:-1]:
                    target = target[part]
                target[parts[-1]] = regressed
                comparisons = {
                    item["metric"]: item
                    for item in self.module.compare_baseline(
                        evaluations,
                        baseline,
                    )
                }
                self.assertFalse(comparisons[metric]["passed"])

    def test_precomputed_evaluations_require_current_fingerprints(self):
        committed = self.module.load_json(self.module.REPORT_PATH)["evaluations"]
        payload = {
            "schema_version": self.module.EVALUATION_RESULTS_SCHEMA_VERSION,
            "build": self.module.fingerprint_paths(),
            "evaluations": committed,
        }
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / "evaluations.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(
                self.module.load_evaluation_results(path),
                committed,
            )
            payload["build"]["runtime_sha256"] = "0" * 64
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "current inputs and runtime"):
                self.module.load_evaluation_results(path)

    def test_build_report_does_not_recollect_precomputed_evaluations(self):
        committed = self.module.load_json(
            self.module.REPORT_PATH
        )["evaluations"]
        committed["answer_context"].setdefault(
            "evaluation_fixture_isolation", True
        )
        exposure = committed["retrieval"][
            "unjudged_new_source_exposure"
        ]
        if "limits" not in exposure:
            retrieval_rules = self.module.load_json(
                ROOT / "config" / "retrieval_rules.json"
            )["retrieval"]
            exposure["limits"] = {
                "max_top_k_rate": retrieval_rules[
                    "automatic_expansion_max_top_k_rate"
                ],
                "max_top_k_per_case": retrieval_rules[
                    "automatic_expansion_surface_limit"
                ],
                "max_review_rate": retrieval_rules[
                    "automatic_expansion_max_review_rate"
                ],
                "max_review_per_case": retrieval_rules[
                    "automatic_expansion_review_limit"
                ],
            }
        with mock.patch.object(self.module, "collect_evaluations") as collect:
            report = self.module.build_report(evaluations=committed)
        collect.assert_not_called()
        self.assertEqual(report["evaluations"], committed)

    def test_historical_generation_summary_never_runs_current_runtime_audit(self):
        payload = {
            "cases": [{"case_id": "AQ055"}],
            "generator": {
                "type": "deterministic_answer_renderer",
                "implementation": "skills/example/render_answer.py",
                "implementation_sha256": "a" * 64,
            },
            "validation": {
                "method": "current_runtime_full_context_audit",
                "implementation": "skills/example/audit_answer.py",
                "implementation_sha256": "b" * 64,
            },
        }
        snapshot = {
            "status": "valid_generation_snapshot",
            "current_runtime_match": False,
            "current_answer_runtime_match": False,
            "current_artifact_runtime_match": False,
            "generation_answer_runtime_fingerprint": "generated-answer",
            "current_answer_runtime_fingerprint": "current-answer",
            "generation_artifact_runtime_fingerprint": "generated-artifact",
            "current_artifact_runtime_fingerprint": "current-artifact",
            "generator_implementation_match": False,
            "validator_implementation_match": False,
            "critical_cases": 1,
            "generated_answers": 1,
            "current_runtime_audits_rerun": False,
            "current_renderer_reproduced": False,
        }
        with mock.patch.object(
            self.module.validate_live_generation_results,
            "inspect_generation_snapshot",
            return_value=snapshot,
        ), mock.patch.object(
            self.module.validate_live_generation_results,
            "validate_results",
        ) as strict:
            summary = self.module.summarize_generation_validation(payload)
        strict.assert_not_called()
        self.assertEqual(
            summary["measurement_type"], "historical_generation_snapshot"
        )
        self.assertEqual(summary["validation_status"], "historical_stale")
        self.assertFalse(summary["current_runtime_generation_claimed"])
        self.assertFalse(summary["release_eligible"])
        self.assertFalse(summary["current_runtime_audits_rerun"])

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
                "answer_context": {
                    "candidate_recall": 1.0,
                    "selected_video_recall": 1.0,
                },
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
                "answer_audit": {"violation_detection_rate": 1.0},
                "feedback_lifecycle": {"contract_accuracy": 1.0},
                "retrieval": {
                    "mean_ndcg_at_k": 0.86,
                    "stable_regression": {"mean_ndcg_at_k": 0.86},
                    "hard_negative_top_k_violations": 0,
                    "found_videos": 173,
                    "expected_videos": 173,
                },
                "metamorphic_robustness": {"pass_rate": 1.0},
                "video_comprehension": {
                    "understanding_coverage": 1.0,
                    "ready_videos": 353,
                    "transcript_backed": 334,
                    "visual_review_fallback": 19,
                },
                "forward_tests": {"consecutive_passes": 3},
                "live_generation": {"automated_audit_pass_rate": 1.0},
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
                    "answer_audit",
                    "feedback_lifecycle",
                    "retrieval",
                    "metamorphic_robustness",
                    "video_comprehension",
                    "forward_tests",
                    "live_generation",
                )
            ],
        }
        page = self.module.render_html(report).decode("utf-8")
        self.assertIn("Evidence quality", page)
        self.assertIn("abc123", page)
        self.assertIn("a" * 64, page)
        self.assertIn("57/57", page)
        self.assertEqual(page.count(">PASS<"), 14)
        self.assertIn("tbody td:nth-of-type(3)", page)

    def test_rendered_html_labels_stale_generation_snapshot_as_informational(self):
        report = self.module.load_json(self.module.REPORT_PATH)
        report["evaluations"]["live_generation"][
            "current_runtime_generation_claimed"
        ] = False
        report["evaluations"]["live_generation"][
            "automated_audit_pass_rate"
        ] = None
        page = self.module.render_html(report).decode("utf-8")
        self.assertIn("Historical release-answer snapshot", page)
        self.assertIn(">REVIEW<", page)

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
