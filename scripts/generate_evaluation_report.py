#!/usr/bin/env python3
"""Build deterministic machine-readable and human-readable evaluation reports."""

import argparse
import concurrent.futures
import hashlib
import html
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import evaluate_answer_context
import evaluate_answer_audit
import evaluate_answer_policy
import evaluate_answer_quality
import evaluate_bilibili_canaries
import evaluate_diagnostic_answer_contract
import evaluate_forward_test_results
import evaluate_feedback_lifecycle
import evaluate_query_equivalence
import evaluate_query_understanding
import evaluate_retrieval
import evaluate_metamorphic_robustness
import evaluate_video_comprehension
import validate_live_generation_results
from release_inventory import MAINTAINER_ONLY_SKILL_PATHS, RUNTIME_SKILL_PATHS


ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / "data" / "evaluation" / "evaluation_baselines.json"
REPORT_PATH = ROOT / "data" / "evaluation" / "evaluation_report.json"
HTML_PATH = ROOT / "docs" / "evaluation" / "index.html"
EVALUATION_RESULTS_SCHEMA_VERSION = 1
EVALUATION_SUITE_ORDER = (
    "answer_policy",
    "answer_context",
    "answer_quality",
    "query_equivalence",
    "query_understanding",
    "diagnostic_answer_contract",
    "answer_audit",
    "bilibili_positive_retrieval",
    "feedback_lifecycle",
    "retrieval",
    "metamorphic_robustness",
    "video_comprehension",
    "forward_tests",
    "live_generation",
)
EVALUATION_SUITES = set(EVALUATION_SUITE_ORDER)
EVALUATION_EXECUTION_ORDER = (
    "answer_context",
    "bilibili_positive_retrieval",
    "metamorphic_robustness",
    "query_equivalence",
    "diagnostic_answer_contract",
    "retrieval",
    "live_generation",
    "video_comprehension",
    "feedback_lifecycle",
    "query_understanding",
    "answer_audit",
    "answer_policy",
)
CORE_EVALUATORS = (
    "build_douyin_knowledge.py",
    "evaluate_answer_audit.py",
    "evaluate_answer_context.py",
    "evaluate_answer_policy.py",
    "evaluate_answer_quality.py",
    "evaluate_bilibili_canaries.py",
    "evaluate_diagnostic_answer_contract.py",
    "evaluate_forward_test_results.py",
    "evaluate_feedback_lifecycle.py",
    "evaluate_query_equivalence.py",
    "evaluate_query_understanding.py",
    "evaluate_retrieval.py",
    "evaluate_metamorphic_robustness.py",
    "evaluate_video_comprehension.py",
    "generate_release_answer_results.py",
    "release_inventory.py",
    "validate_live_generation_results.py",
)
EVALUATION_INPUTS = (
    "config/answer_audit_rules.json",
    "config/answer_quality_rules.json",
    "config/diagnostic_answer_rules.json",
    "config/feedback_rules.json",
    "config/knowledge_quality_rules.json",
    "data/evaluation/answer_audit_cases.json",
    "data/evaluation/answer_modality_cases.json",
    "data/evaluation/answer_quality_answers.json",
    "data/evaluation/answer_quality_cases.json",
    "data/evaluation/bilibili_canary_cases.json",
    "data/evaluation/critical_answer_snapshots.json",
    "data/evaluation/diagnostic_answer_cases.json",
    "data/evaluation/diagnostic_answer_continuation_cases.json",
    "data/evaluation/delivery_release_cases.json",
    "data/evaluation/evaluation_baselines.json",
    "data/evaluation/forward_test_results.json",
    "data/evaluation/live_generation_results.json",
    "data/evaluation/query_equivalence_cases.json",
    "data/evaluation/query_understanding_cases.json",
    "data/evaluation/runtime_generation_cases.json",
    "data/knowledge/douyin_knowledge_base.json",
    "data/knowledge/retrieval_index.json",
)

REQUIRED_QUALITY_HARD_GATE_METRICS = frozenset(
    {
        "answer_context.synthesis_video_recall",
        "answer_context.core_video_recall",
        "bilibili_positive_retrieval.passed",
        "bilibili_positive_retrieval.pass_rate",
        "bilibili_positive_retrieval.claim_mapping_rate",
        "bilibili_positive_retrieval.failure_count",
        "feedback_lifecycle.status",
        "feedback_lifecycle.contract_accuracy",
        "feedback_lifecycle.leaked_private_fields",
        "feedback_lifecycle.signals_missing_reverified_provenance",
        "feedback_lifecycle.failures",
        "metamorphic_robustness.base_cases",
        "metamorphic_robustness.variants",
        "metamorphic_robustness.passed",
        "metamorphic_robustness.pass_rate",
        "metamorphic_robustness.failed",
        "live_generation.critical_cases",
    }
)


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def ensure_deterministic_hash_seed():
    if os.environ.get("PYTHONHASHSEED") == "0":
        return
    environment = dict(os.environ)
    environment["PYTHONHASHSEED"] = "0"
    os.execvpe(sys.executable, [sys.executable, *sys.argv], environment)


def json_bytes(payload):
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def hash_paths(paths, root=ROOT):
    digest = hashlib.sha256()
    for path in sorted(Path(item) for item in paths):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def fingerprint_paths(root=ROOT):
    root = Path(root)
    input_paths = [root / relative for relative in EVALUATION_INPUTS]
    runtime_paths = [root / "scripts" / name for name in CORE_EVALUATORS]
    skill_root = root / "skills" / "liuhui-badminton-coach"
    runtime_paths.extend(
        skill_root / relative
        for relative in sorted(
            RUNTIME_SKILL_PATHS | MAINTAINER_ONLY_SKILL_PATHS
        )
    )
    return {
        "inputs_sha256": hash_paths(input_paths, root),
        "runtime_sha256": hash_paths(runtime_paths, root),
    }


def summarize_generation_validation(live_payload, root=ROOT):
    """Report reproducible-generation freshness and automated audit status."""

    root = Path(root)
    snapshot = validate_live_generation_results.inspect_generation_snapshot(
        live_payload, root=root
    )
    current = snapshot["current_runtime_match"]
    validated = (
        validate_live_generation_results.validate_results(
            live_payload,
            root=root,
            rerun_runtime=True,
        )
        if current
        else snapshot
    )
    return {
        "measurement_type": (
            "current_runtime_automated_generation_validation"
            if current
            else "historical_generation_snapshot"
        ),
        "validation_status": (
            "current_validated" if current else "historical_stale"
        ),
        "snapshot_integrity_status": snapshot["status"],
        "current_runtime_match": current,
        "current_runtime_generation_claimed": current,
        "release_eligible": current,
        "runtime_fingerprint": snapshot[
            "current_answer_runtime_fingerprint"
        ],
        "runtime_fingerprint_scope": "answer_semantics",
        "generation_answer_runtime_fingerprint": snapshot[
            "generation_answer_runtime_fingerprint"
        ],
        "current_answer_runtime_fingerprint": snapshot[
            "current_answer_runtime_fingerprint"
        ],
        "generation_artifact_runtime_fingerprint": snapshot[
            "generation_artifact_runtime_fingerprint"
        ],
        "current_artifact_runtime_fingerprint": snapshot[
            "current_artifact_runtime_fingerprint"
        ],
        "current_answer_runtime_match": snapshot[
            "current_answer_runtime_match"
        ],
        "current_artifact_runtime_match": snapshot[
            "current_artifact_runtime_match"
        ],
        "generator_implementation_match": snapshot[
            "generator_implementation_match"
        ],
        "validator_implementation_match": snapshot[
            "validator_implementation_match"
        ],
        "critical_cases": snapshot["critical_cases"],
        "generated_answers": snapshot["generated_answers"],
        "automatically_validated": (
            validated["automatically_validated"] if current else 0
        ),
        "automated_audit_pass_rate": (
            validated["automated_audit_pass_rate"] if current else None
        ),
        "current_runtime_audits_rerun": validated[
            "current_runtime_audits_rerun"
        ],
        "current_renderer_reproduced": validated[
            "current_renderer_reproduced"
        ],
        "passed": validated["automatically_validated"] if current else 0,
        "failed": [],
        "generator": {
            key: live_payload["generator"][key]
            for key in ("type", "implementation", "implementation_sha256")
        },
        "validation": dict(live_payload["validation"]),
    }


def evaluate_independent_suite(name, root=ROOT):
    root = Path(root)
    if name == "answer_policy":
        return evaluate_answer_policy.evaluate()
    if name == "answer_context":
        return evaluate_answer_context.evaluate()
    if name == "query_equivalence":
        return evaluate_query_equivalence.evaluate()
    if name == "query_understanding":
        return evaluate_query_understanding.evaluate()
    if name == "diagnostic_answer_contract":
        return evaluate_diagnostic_answer_contract.evaluate()
    if name == "answer_audit":
        return evaluate_answer_audit.evaluate()
    if name == "bilibili_positive_retrieval":
        return evaluate_bilibili_canaries.evaluate()
    if name == "feedback_lifecycle":
        return evaluate_feedback_lifecycle.evaluate()
    if name == "retrieval":
        return evaluate_retrieval.evaluate(12)
    if name == "metamorphic_robustness":
        return evaluate_metamorphic_robustness.evaluate()
    if name == "video_comprehension":
        return evaluate_video_comprehension.evaluate(
            run_retrieval_roundtrip=True,
            run_semantic_probes=False,
        )
    if name == "live_generation":
        payload = validate_live_generation_results.load_json(
            root / "data/evaluation/live_generation_results.json"
        )
        return summarize_generation_validation(payload, root=root)
    raise ValueError(f"unsupported independent evaluation suite: {name}")


def timed_independent_suite(name, root=ROOT):
    started = time.perf_counter()
    result = evaluate_independent_suite(name, root=root)
    return name, result, time.perf_counter() - started


def run_independent_suite_subprocess(name, root=ROOT):
    root = Path(root)
    with tempfile.TemporaryDirectory(
        prefix=f"badminton-evaluation-{name}-"
    ) as directory:
        output = Path(directory) / "result.json"
        completed = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--suite-worker",
                name,
                "--suite-root",
                str(root),
                "--suite-output",
                str(output),
            ],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode:
            detail = (completed.stderr or completed.stdout).strip()
            raise RuntimeError(f"evaluation suite {name} failed: {detail}")
        payload = load_json(output)
    if payload.get("suite") != name:
        raise RuntimeError(f"evaluation suite {name} returned mismatched output")
    return name, payload["result"], payload["duration_seconds"]


def collect_independent_suites(root=ROOT, workers=1):
    if workers < 1:
        raise ValueError("evaluation workers must be positive")
    root = Path(root)
    results = {}
    timings = {}
    if workers == 1:
        completed = (
            timed_independent_suite(name, root)
            for name in EVALUATION_EXECUTION_ORDER
        )
        for name, result, duration in completed:
            results[name] = result
            timings[name] = duration
        return results, timings

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(workers, len(EVALUATION_EXECUTION_ORDER))
    ) as executor:
        futures = {
            executor.submit(run_independent_suite_subprocess, name, root): name
            for name in EVALUATION_EXECUTION_ORDER
        }
        for future in concurrent.futures.as_completed(futures):
            name, result, duration = future.result()
            results[name] = result
            timings[name] = duration
    return results, timings


def collect_evaluations(root=ROOT, workers=1, timings=None):
    root = Path(root)
    answer_quality_started = time.perf_counter()
    registry = evaluate_answer_quality.load_json(
        root / "data/evaluation/answer_quality_cases.json"
    )
    rules = evaluate_answer_quality.load_json(root / "config/answer_quality_rules.json")
    knowledge = evaluate_answer_quality.load_json(
        root / "data/knowledge/douyin_knowledge_base.json"
    )
    ready_ids = evaluate_answer_quality.ready_video_ids(knowledge)
    all_video_ids = {video["video_id"] for video in knowledge["videos"]}
    registry_result = evaluate_answer_quality.validate_registry(
        registry,
        rules,
        ready_ids,
        minimum_cases=57,
        all_video_ids=all_video_ids,
    )
    answers_payload = evaluate_answer_quality.load_json(
        root / "data/evaluation/answer_quality_answers.json"
    )
    answers_result = evaluate_answer_quality.evaluate_answers(
        registry,
        answers_payload,
        rules,
        ready_ids,
        require_manual_review=True,
        evidence_urls=evaluate_answer_quality.ready_evidence_url_map(knowledge),
    )
    critical_ids = evaluate_answer_quality.validate_snapshot_requirements(
        evaluate_answer_quality.load_json(
            root / "data/evaluation/critical_answer_snapshots.json"
        ),
        registry,
    )
    supplied_ids = {answer["case_id"] for answer in answers_payload["answers"]}
    answers_result["critical_snapshot_requirements"] = len(critical_ids)
    answers_result["missing_critical_case_ids"] = sorted(critical_ids - supplied_ids)
    answer_quality_duration = time.perf_counter() - answer_quality_started

    forward_started = time.perf_counter()
    forward_fingerprint = evaluate_forward_test_results.runtime_fingerprint(root)
    forward_result = evaluate_forward_test_results.validate_forward_results(
        evaluate_forward_test_results.load_json(
            root / "data/evaluation/forward_test_results.json"
        ),
        evaluate_forward_test_results.load_json(
            root / "data/evaluation/critical_answer_snapshots.json"
        ),
        registry,
        evaluate_forward_test_results.load_json(
            root / "data/evaluation/query_understanding_cases.json"
        ),
        forward_fingerprint,
        evaluate_forward_test_results.load_json(
            root / "data/evaluation/diagnostic_answer_cases.json"
        ),
        evaluate_forward_test_results.load_json(
            root / "data/evaluation/diagnostic_answer_continuation_cases.json"
        ),
        require_current_runtime=False,
    )
    forward_duration = time.perf_counter() - forward_started

    independent, independent_timings = collect_independent_suites(
        root=root,
        workers=workers,
    )
    if timings is not None:
        timings.update(independent_timings)
        timings["answer_quality"] = answer_quality_duration
        timings["forward_tests"] = forward_duration

    policy = independent["answer_policy"]
    context = independent["answer_context"]
    equivalence = independent["query_equivalence"]
    understanding = independent["query_understanding"]
    diagnostic = independent["diagnostic_answer_contract"]
    answer_audit = independent["answer_audit"]
    bilibili_positive = independent["bilibili_positive_retrieval"]
    feedback_lifecycle = independent["feedback_lifecycle"]
    retrieval = independent["retrieval"]
    metamorphic = independent["metamorphic_robustness"]
    comprehension = independent["video_comprehension"]
    live_result = independent["live_generation"]

    return {
        "answer_policy": {
            "cases": policy["cases"],
            "correct": policy["correct"],
            "accuracy": policy["accuracy"],
            "mode_contracts_complete": policy["mode_contracts_complete"],
            "global_contract_complete": policy["global_contract_complete"],
        },
        "answer_context": {
            key: context[key]
            for key in (
                "cases",
                "expected_videos",
                "candidate_recall",
                "semantic_answerable_video_recall",
                "selected_video_recall",
                "claim_mapped_video_recall",
                "synthesis_video_recall",
                "complete_related_video_recall",
                "synthesis_display_expected_videos",
                "core_video_recall",
                "mean_video_count_by_layer",
                "primary_selected_rate",
                "answer_mode_accuracy",
                "context_evidence_coverage",
                "hard_negative_selected_violations",
                "selection_truncated_cases",
                "retrieval_query_budget_truncated_cases",
                "retrieval_query_omitted_count",
                "evaluation_fixture_isolation",
            )
        },
        "answer_quality": {
            "measurement_type": "reviewed_static_answer_snapshots",
            "current_model_generation_claimed": False,
            **registry_result,
            **{
                key: answers_result[key]
                for key in (
                    "answers_supplied",
                    "snapshot_coverage",
                    "passed",
                    "automatic_pass_rate",
                    "critical_snapshot_requirements",
                    "missing_critical_case_ids",
                )
            },
        },
        "query_equivalence": {
            key: equivalence[key]
            for key in (
                "families",
                "variants",
                "negative_controls",
                "passed_families",
                "failed_families",
            )
        },
        "query_understanding": {
            key: understanding[key]
            for key in (
                "cases",
                "reviewed_cases",
                "adversarial_cases",
                "passed",
                "accuracy",
            )
        },
        "diagnostic_answer_contract": {
            key: diagnostic[key]
            for key in ("cases", "passed", "accuracy")
        },
        "answer_audit": {
            key: answer_audit[key]
            for key in (
                "cases",
                "passed",
                "accuracy",
                "expected_violations",
                "expected_violations_detected",
                "violation_detection_rate",
            )
        },
        "bilibili_positive_retrieval": {
            key: bilibili_positive[key]
            for key in (
                "measurement_type",
                "runtime_use_forbidden",
                "source_type",
                "case_count",
                "passed",
                "pass_rate",
                "retrieval_hit_rate_at_k",
                "claim_mapping_rate",
                "failure_count",
            )
        },
        "feedback_lifecycle": {
            key: feedback_lifecycle[key]
            for key in (
                "status",
                "queue_statuses",
                "promoted_signals",
                "promoted_regression_cases",
                "adversarial_contract_checks",
                "adversarial_contracts_passed",
                "contract_accuracy",
                "leaked_private_fields",
                "signals_missing_reverified_provenance",
                "failures",
            )
        },
        "retrieval": {
            key: retrieval[key]
            for key in (
                "cases",
                "expected_videos",
                "found_videos",
                "candidate_recall",
                "primary_top_k",
                "mean_reciprocal_rank",
                "mean_ndcg_at_k",
                "mean_known_precision_at_k",
                "average_review_candidate_count",
                "hard_negative_count",
                "hard_negative_top_k_violations",
                "hard_negative_review_violations",
                "unjudged_new_source_exposure",
                "evaluation_views",
                "stable_regression",
                "top_k",
            )
        },
        "metamorphic_robustness": {
            key: metamorphic[key]
            for key in (
                "base_cases",
                "variants",
                "case_types",
                "passed",
                "pass_rate",
                "failure_taxonomy",
                "failed",
            )
        },
        "video_comprehension": {
            key: comprehension[key]
            for key in (
                "ready_videos",
                "understood_videos",
                "understanding_coverage",
                "transcript_backed",
                "automatic_transcript",
                "reviewed_transcript",
                "visual_review_fallback",
                "evidence_provenance",
                "automated_review_backlog",
                "runtime_lookup_coverage",
                "failure_count",
            )
        },
        "forward_tests": {
            key: forward_result[key]
            for key in (
                "measurement_type",
                "current_runtime_match",
                "current_runtime_generation_claimed",
                "critical_cases",
                "blind_passes",
                "unseen_rounds",
                "unseen_cases",
                "consecutive_passes",
                "failed",
            )
        },
        "live_generation": live_result,
    }


def metric_value(evaluations, path):
    value = evaluations
    for part in path.split("."):
        value = value[part]
    return value


def compare_baseline(evaluations, baseline):
    comparisons = []
    invalidated = set(baseline.get("invalidated_metrics", {}))
    for path, contract in baseline["metrics"].items():
        if path in invalidated:
            continue
        current = metric_value(evaluations, path)
        expected_source = contract.get("value_source")
        if expected_source is None:
            expected = contract["value"]
            contract_source = "stable_baseline"
        else:
            expected = metric_value(evaluations, expected_source)
            contract_source = expected_source
        tolerance = contract.get("tolerance", 0)
        direction = contract["direction"]
        if direction == "at_least":
            passed = current + tolerance >= expected
        elif direction == "at_most":
            passed = current - tolerance <= expected
        elif direction == "equal":
            passed = current == expected
        else:
            raise ValueError(f"Unsupported baseline direction: {direction}")
        comparisons.append(
            {
                "metric": path,
                "current": current,
                "baseline": expected,
                "direction": direction,
                "tolerance": tolerance,
                "contract_source": contract_source,
                "passed": passed,
            }
        )
    return comparisons


def validate_quality_hard_gate_contract(baseline):
    metrics = set(baseline.get("metrics", {}))
    invalidated = set(baseline.get("invalidated_metrics", {}))
    missing = sorted(REQUIRED_QUALITY_HARD_GATE_METRICS - metrics)
    disabled = sorted(REQUIRED_QUALITY_HARD_GATE_METRICS & invalidated)
    if missing or disabled:
        details = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if disabled:
            details.append("invalidated=" + ",".join(disabled))
        raise ValueError(
            "quality hard-gate baseline contract is incomplete: "
            + "; ".join(details)
        )


def load_evaluation_results(path, root=ROOT):
    payload = load_json(path)
    if payload.get("schema_version") != EVALUATION_RESULTS_SCHEMA_VERSION:
        raise ValueError("evaluation results schema version is unsupported")
    expected_fingerprints = fingerprint_paths(root)
    if payload.get("build") != expected_fingerprints:
        raise ValueError("evaluation results do not match the current inputs and runtime")
    evaluations = payload.get("evaluations")
    if not isinstance(evaluations, dict) or set(evaluations) != EVALUATION_SUITES:
        raise ValueError("evaluation results do not contain the required suites")
    return evaluations


def build_report(root=ROOT, evaluations=None):
    root = Path(root)
    versions = load_json(root / "config/feedback_rules.json")
    baselines = load_json(root / "data/evaluation/evaluation_baselines.json")
    stable_version = versions["stable_version"]
    baseline_key = f"v{stable_version}"
    baseline = baselines["baselines"][baseline_key]
    validate_quality_hard_gate_contract(baseline)
    evaluations = evaluations if evaluations is not None else collect_evaluations(root)
    comparisons = compare_baseline(evaluations, baseline)
    regressions = [item for item in comparisons if not item["passed"]]
    fingerprints = fingerprint_paths(root)
    build_seed = (
        versions["skill_version"]
        + stable_version
        + fingerprints["inputs_sha256"]
        + fingerprints["runtime_sha256"]
    )
    build_id = hashlib.sha256(build_seed.encode("utf-8")).hexdigest()[:16]
    return {
        "schema_version": 1,
        "project": "badminton-skills-coach",
        "development_version": versions["skill_version"],
        "baseline_version": baseline_key,
        "build": {"id": build_id, **fingerprints},
        "summary": {
            "status": "pass" if not regressions else "fail",
            "suites": len(evaluations),
            "baseline_metrics": len(comparisons),
            "regressions": len(regressions),
            "invalidated_baseline_metrics": len(
                baseline.get("invalidated_metrics", {})
            ),
        },
        "invalidated_baseline_metrics": baseline.get(
            "invalidated_metrics", {}
        ),
        "evaluations": evaluations,
        "baseline_comparison": comparisons,
    }


def display_value(value):
    if isinstance(value, float):
        if 0 <= value <= 1:
            return f"{value * 100:.1f}%"
        return f"{value:.3f}"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, list):
        return "None" if not value else ", ".join(map(str, value))
    return str(value)


def render_html(report):
    evaluations = report["evaluations"]
    retrieval = evaluations["retrieval"]
    answer_quality = evaluations["answer_quality"]
    video = evaluations["video_comprehension"]
    understanding = evaluations["query_understanding"]
    suite_names = {
        "answer_policy": "Answer policy",
        "answer_context": "Answer context",
        "answer_quality": "Answer snapshots",
        "query_equivalence": "Query equivalence",
        "query_understanding": "Query understanding",
        "diagnostic_answer_contract": "Diagnostic answer contract",
        "answer_audit": "Final-answer audit",
        "bilibili_positive_retrieval": "Bilibili positive retrieval gold",
        "feedback_lifecycle": "Feedback lifecycle",
        "retrieval": "Evidence retrieval",
        "metamorphic_robustness": "Metamorphic robustness",
        "video_comprehension": "Video comprehension",
        "forward_tests": "Historical generation reviews",
        "live_generation": (
            "Current-runtime release answers"
            if evaluations["live_generation"].get(
                "current_runtime_generation_claimed"
            )
            else "Historical release-answer snapshot"
        ),
    }
    featured = {
        "answer_policy": ("accuracy", "Mode accuracy"),
        "answer_context": ("candidate_recall", "Leakage-free candidate recall"),
        "answer_quality": ("automatic_pass_rate", "Snapshot pass rate"),
        "query_equivalence": ("passed_families", "Families passed"),
        "query_understanding": ("accuracy", "Intent accuracy"),
        "diagnostic_answer_contract": ("accuracy", "Diagnostic contract accuracy"),
        "answer_audit": ("violation_detection_rate", "Violation detection"),
        "bilibili_positive_retrieval": (
            "retrieval_hit_rate_at_k",
            "Source-reviewed hit rate@3",
        ),
        "feedback_lifecycle": ("contract_accuracy", "Feedback contracts"),
        "retrieval": (
            "stable_regression.mean_ndcg_at_k",
            "Stable-view nDCG@12",
        ),
        "metamorphic_robustness": ("pass_rate", "Harmless variants passed"),
        "video_comprehension": ("understanding_coverage", "Evidence coverage"),
        "forward_tests": ("consecutive_passes", "Consecutive rounds"),
        "live_generation": (
            "automated_audit_pass_rate",
            "Automated full-context audit",
        ),
    }
    rows = []
    comparisons_by_suite = {}
    for item in report["baseline_comparison"]:
        comparisons_by_suite.setdefault(item["metric"].split(".")[0], []).append(item)
    for suite, metrics in evaluations.items():
        key, label = featured[suite]
        featured_value = metric_value(metrics, key)
        historical_review = (
            suite == "live_generation"
            and not metrics.get("current_runtime_generation_claimed", True)
        )
        status = all(
            item["passed"] for item in comparisons_by_suite.get(suite, [])
        )
        status_class = (
            "review" if historical_review else "pass" if status else "fail"
        )
        status_text = (
            "REVIEW" if historical_review else "PASS" if status else "FAIL"
        )
        rows.append(
            f'<tr><th scope="row">{suite_names[suite]}</th>'
            f'<td>{html.escape(label)}</td><td class="value">{html.escape(display_value(featured_value))}</td>'
            f'<td><span class="status {status_class}">{status_text}</span></td></tr>'
        )
    status = report["summary"]["status"]
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="Deterministic evaluation report for Badminton Skills Coach.">
  <title>Evaluation Report | Badminton Skills Coach</title>
  <link rel="icon" href="../favicon.svg" type="image/svg+xml">
  <style>
    :root {{ color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; --bg:#090d0c; --panel:#111816; --ink:#f3f6f4; --muted:#a7b0ac; --line:rgba(255,255,255,.12); --mint:#79dbc5; --yellow:#f3dc55; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; color:var(--ink); background:var(--bg); line-height:1.55; }} a {{ color:var(--mint); }} a:focus-visible {{ outline:3px solid var(--yellow); outline-offset:3px; }} .shell {{ width:min(1080px,calc(100% - 32px)); margin:auto; }} .skip-link {{ position:fixed; left:8px; top:8px; transform:translateY(-180%); padding:8px 12px; color:#07110e; background:var(--yellow); z-index:5; }} .skip-link:focus {{ transform:none; }}
    header {{ border-bottom:1px solid var(--line); background:#0d1311; }} nav {{ min-height:64px; display:flex; align-items:center; justify-content:space-between; gap:20px; }} nav a {{ text-decoration:none; font-weight:750; }}
    main {{ padding:64px 0 80px; }} .eyebrow {{ color:var(--mint); font:800 12px/1.2 ui-monospace,monospace; text-transform:uppercase; letter-spacing:.12em; }} h1 {{ max-width:780px; margin:14px 0 18px; font-size:clamp(38px,7vw,72px); line-height:1.02; letter-spacing:0; }} .lede {{ max-width:760px; color:var(--muted); font-size:18px; }}
    .summary {{ display:grid; grid-template-columns:repeat(4,1fr); margin:44px 0 62px; border-block:1px solid var(--line); }} .summary div {{ padding:22px 18px; border-right:1px solid var(--line); }} .summary div:last-child {{ border:0; }} .summary strong,.summary span {{ display:block; }} .summary strong {{ font-size:28px; }} .summary span {{ color:var(--muted); font-size:13px; }}
    h2 {{ margin:54px 0 18px; font-size:28px; letter-spacing:0; }} .table-wrap {{ overflow-x:auto; border:1px solid var(--line); border-radius:8px; }} table {{ width:100%; border-collapse:collapse; background:var(--panel); }} th,td {{ padding:17px 18px; text-align:left; border-bottom:1px solid var(--line); white-space:nowrap; }} tr:last-child th,tr:last-child td {{ border-bottom:0; }} td.value {{ font:750 15px/1 ui-monospace,monospace; }} .status {{ display:inline-block; min-width:54px; padding:5px 8px; border-radius:4px; text-align:center; font:800 11px/1 ui-monospace,monospace; }} .pass {{ color:#07110e; background:var(--mint); }} .fail,.review {{ color:#1a1400; background:var(--yellow); }}
    .provenance {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }} .provenance div {{ padding:18px; border-left:3px solid var(--mint); background:var(--panel); }} code {{ color:#d8e3df; overflow-wrap:anywhere; }} footer {{ padding:26px 0; color:var(--muted); border-top:1px solid var(--line); font-size:13px; }}
    @media(max-width:700px) {{ main {{ padding-top:42px; }} .summary {{ grid-template-columns:1fr 1fr; }} .summary div:nth-child(2) {{ border-right:0; }} .summary div:nth-child(-n+2) {{ border-bottom:1px solid var(--line); }} .provenance {{ grid-template-columns:1fr; }} .table-wrap {{ overflow:visible; border:0; }} table,tbody,tr,th,td {{ display:block; }} thead {{ display:none; }} tbody tr {{ display:grid; grid-template-columns:1fr auto; gap:8px 16px; margin-bottom:10px; padding:16px; border:1px solid var(--line); border-radius:8px; }} tbody th,tbody td {{ padding:0; border:0; white-space:normal; }} tbody th {{ grid-column:1; grid-row:1; }} tbody td:nth-of-type(1) {{ grid-column:1; grid-row:2; color:var(--muted); }} tbody td:nth-of-type(2) {{ grid-column:2; grid-row:2; }} tbody td:nth-of-type(3) {{ grid-column:2; grid-row:1; }} }}
  </style>
</head>
<body>
  <a class="skip-link" href="#main">Skip to content</a>
  <header><nav class="shell" aria-label="Evaluation navigation"><a href="../">Badminton Skills Coach</a><a href="https://github.com/MuyuanGuo/badminton-skills-coach/blob/main/data/evaluation/evaluation_report.json">Raw JSON</a></nav></header>
  <main class="shell" id="main">
    <p class="eyebrow">EvalOps / build {report["build"]["id"]}</p>
    <h1>Evidence quality, measured against a released baseline.</h1>
    <p class="lede">This deterministic report compares the {html.escape(report["development_version"])} runtime with the versioned {html.escape(report["baseline_version"])} baseline. Retrieval growth is measured through an all-source production view plus a stable-source regression view and a separate unjudged-source exposure budget. Static snapshots and historical generations remain labeled as such. Metrics known to have been produced by evaluation-to-runtime leakage are explicitly invalidated, never silently treated as current quality claims. Tagged releases regenerate every critical answer with the trusted renderer, bind it to the full and answer-semantic runtime fingerprints, and rerun the full-context audit.</p>
    <section class="summary" aria-label="Evaluation summary">
      <div><strong>{status.upper()}</strong><span>Regression gate</span></div>
      <div><strong>{video["ready_videos"]}</strong><span>Ready videos</span></div>
      <div><strong>{answer_quality["passed"]}/{answer_quality["answers_supplied"]}</strong><span>Reviewed snapshots</span></div>
      <div><strong>{retrieval["hard_negative_top_k_violations"]}</strong><span>Hard-negative violations</span></div>
    </section>
    <h2>Evaluation suites</h2>
    <div class="table-wrap"><table><thead><tr><th>Suite</th><th>Featured metric</th><th>Current</th><th>Gate</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
    <h2>Coverage at a glance</h2>
    <div class="provenance">
      <div><strong>{understanding["passed"]}/{understanding["cases"]}</strong><br><span>query-understanding cases passed, including {understanding["adversarial_cases"]} adversarial cases</span></div>
      <div><strong>{retrieval["found_videos"]}/{retrieval["expected_videos"]}</strong><br><span>expected evidence videos reached the candidate set</span></div>
      <div><strong>{video["transcript_backed"]}</strong><br><span>transcript-backed videos, plus {video["visual_review_fallback"]} reviewed visual fallbacks</span></div>
      <div><strong>{report["summary"]["baseline_metrics"]}</strong><br><span>versioned metrics enforced by the regression gate</span></div>
    </div>
    <h2>Reproducibility</h2>
    <p>Input SHA-256<br><code>{report["build"]["inputs_sha256"]}</code></p>
    <p>Runtime SHA-256<br><code>{report["build"]["runtime_sha256"]}</code></p>
  </main>
  <footer><div class="shell">Generated from committed artifacts. No wall-clock timestamp or external service is used.</div></footer>
</body>
</html>
'''.encode("utf-8")


def check_artifact(path, expected):
    if not path.exists():
        return f"missing: {path.relative_to(ROOT)}"
    if path.read_bytes() != expected:
        return f"stale: {path.relative_to(ROOT)}"
    return None


def main():
    ensure_deterministic_hash_seed()
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="Update committed reports.")
    mode.add_argument("--check", action="store_true", help="Fail when reports are stale.")
    mode.add_argument(
        "--suite-worker",
        choices=EVALUATION_EXECUTION_ORDER,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--suite-root", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--suite-output", type=Path, help=argparse.SUPPRESS)
    parser.add_argument(
        "--evaluations",
        type=Path,
        help="Read precomputed evaluator results instead of running evaluators.",
    )
    args = parser.parse_args()

    if args.suite_worker:
        if not args.suite_output:
            parser.error("--suite-worker requires --suite-output")
        name, result, duration = timed_independent_suite(
            args.suite_worker,
            root=args.suite_root or ROOT,
        )
        args.suite_output.parent.mkdir(parents=True, exist_ok=True)
        args.suite_output.write_text(
            json.dumps(
                {
                    "suite": name,
                    "duration_seconds": duration,
                    "result": result,
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        return
    if args.suite_root or args.suite_output:
        parser.error("--suite-root and --suite-output require --suite-worker")

    evaluations = (
        load_evaluation_results(args.evaluations) if args.evaluations else None
    )
    report = build_report(evaluations=evaluations)
    report_content = json_bytes(report)
    html_content = render_html(report)
    if args.write:
        REPORT_PATH.write_bytes(report_content)
        HTML_PATH.parent.mkdir(parents=True, exist_ok=True)
        HTML_PATH.write_bytes(html_content)
    elif args.check:
        failures = [
            item
            for item in (
                check_artifact(REPORT_PATH, report_content),
                check_artifact(HTML_PATH, html_content),
            )
            if item
        ]
        if failures:
            raise SystemExit("Evaluation artifacts are not current: " + ", ".join(failures))
    else:
        print(report_content.decode("utf-8"), end="")

    regressions = [
        item for item in report["baseline_comparison"] if not item["passed"]
    ]
    if regressions:
        details = ", ".join(
            f'{item["metric"]}={item["current"]} ({item["direction"]} {item["baseline"]})'
            for item in regressions
        )
        raise SystemExit("Evaluation regression gate failed: " + details)


if __name__ == "__main__":
    main()
