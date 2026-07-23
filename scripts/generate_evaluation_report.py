#!/usr/bin/env python3
"""Build deterministic machine-readable and human-readable evaluation reports."""

import argparse
import hashlib
import html
import json
import os
import sys
from pathlib import Path

import evaluate_answer_context
import evaluate_answer_policy
import evaluate_answer_quality
import evaluate_forward_test_results
import evaluate_query_equivalence
import evaluate_query_understanding
import evaluate_retrieval
import evaluate_video_comprehension


ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / "data" / "evaluation" / "evaluation_baselines.json"
REPORT_PATH = ROOT / "data" / "evaluation" / "evaluation_report.json"
HTML_PATH = ROOT / "docs" / "evaluation" / "index.html"
CORE_EVALUATORS = (
    "build_douyin_knowledge.py",
    "evaluate_answer_context.py",
    "evaluate_answer_policy.py",
    "evaluate_answer_quality.py",
    "evaluate_forward_test_results.py",
    "evaluate_query_equivalence.py",
    "evaluate_query_understanding.py",
    "evaluate_retrieval.py",
    "evaluate_video_comprehension.py",
)
EVALUATION_INPUTS = (
    "config/answer_quality_rules.json",
    "config/feedback_rules.json",
    "config/knowledge_quality_rules.json",
    "data/evaluation/answer_modality_cases.json",
    "data/evaluation/answer_quality_answers.json",
    "data/evaluation/answer_quality_cases.json",
    "data/evaluation/critical_answer_snapshots.json",
    "data/evaluation/evaluation_baselines.json",
    "data/evaluation/forward_test_results.json",
    "data/evaluation/query_equivalence_cases.json",
    "data/evaluation/query_understanding_cases.json",
    "data/knowledge/douyin_knowledge_base.json",
    "data/knowledge/retrieval_index.json",
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
    runtime_paths.extend(
        path
        for path in (root / "skills" / "liuhui-badminton-coach").rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    )
    return {
        "inputs_sha256": hash_paths(input_paths, root),
        "runtime_sha256": hash_paths(runtime_paths, root),
    }


def collect_evaluations(root=ROOT):
    root = Path(root)
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
    )

    policy = evaluate_answer_policy.evaluate()
    context = evaluate_answer_context.evaluate()
    equivalence = evaluate_query_equivalence.evaluate()
    understanding = evaluate_query_understanding.evaluate()
    retrieval = evaluate_retrieval.evaluate(12)
    comprehension = evaluate_video_comprehension.evaluate(
        run_retrieval_roundtrip=True,
        run_semantic_probes=False,
    )

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
                "selected_video_recall",
                "primary_selected_rate",
                "answer_mode_accuracy",
                "context_evidence_coverage",
                "hard_negative_selected_violations",
                "selection_truncated_cases",
            )
        },
        "answer_quality": {
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
                "top_k",
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
                "runtime_lookup_coverage",
                "failure_count",
            )
        },
        "forward_tests": {
            key: forward_result[key]
            for key in (
                "critical_cases",
                "blind_passes",
                "unseen_rounds",
                "unseen_cases",
                "consecutive_passes",
                "failed",
            )
        },
    }


def metric_value(evaluations, path):
    value = evaluations
    for part in path.split("."):
        value = value[part]
    return value


def compare_baseline(evaluations, baseline):
    comparisons = []
    for path, contract in baseline["metrics"].items():
        current = metric_value(evaluations, path)
        expected = contract["value"]
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
                "passed": passed,
            }
        )
    return comparisons


def build_report(root=ROOT):
    root = Path(root)
    versions = load_json(root / "config/feedback_rules.json")
    baselines = load_json(root / "data/evaluation/evaluation_baselines.json")
    stable_version = versions["stable_version"]
    baseline_key = f"v{stable_version}"
    baseline = baselines["baselines"][baseline_key]
    evaluations = collect_evaluations(root)
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
        },
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
        "retrieval": "Evidence retrieval",
        "video_comprehension": "Video comprehension",
        "forward_tests": "Forward tests",
    }
    featured = {
        "answer_policy": ("accuracy", "Mode accuracy"),
        "answer_context": ("selected_video_recall", "Selected-video recall"),
        "answer_quality": ("automatic_pass_rate", "Snapshot pass rate"),
        "query_equivalence": ("passed_families", "Families passed"),
        "query_understanding": ("accuracy", "Intent accuracy"),
        "retrieval": ("mean_ndcg_at_k", "nDCG@12"),
        "video_comprehension": ("understanding_coverage", "Evidence coverage"),
        "forward_tests": ("consecutive_passes", "Consecutive rounds"),
    }
    rows = []
    comparisons_by_suite = {}
    for item in report["baseline_comparison"]:
        comparisons_by_suite.setdefault(item["metric"].split(".")[0], []).append(item)
    for suite, metrics in evaluations.items():
        key, label = featured[suite]
        status = all(item["passed"] for item in comparisons_by_suite.get(suite, []))
        rows.append(
            f'<tr><th scope="row">{suite_names[suite]}</th>'
            f'<td>{html.escape(label)}</td><td class="value">{html.escape(display_value(metrics[key]))}</td>'
            f'<td><span class="status {"pass" if status else "fail"}">{"PASS" if status else "FAIL"}</span></td></tr>'
        )
    status = report["summary"]["status"]
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="Deterministic evaluation report for Badminton Skills Coach.">
  <title>Evaluation Report | Badminton Skills Coach</title>
  <style>
    :root {{ color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; --bg:#090d0c; --panel:#111816; --ink:#f3f6f4; --muted:#a7b0ac; --line:rgba(255,255,255,.12); --mint:#79dbc5; --yellow:#f3dc55; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; color:var(--ink); background:var(--bg); line-height:1.55; }} a {{ color:var(--mint); }} .shell {{ width:min(1080px,calc(100% - 32px)); margin:auto; }}
    header {{ border-bottom:1px solid var(--line); background:#0d1311; }} nav {{ min-height:64px; display:flex; align-items:center; justify-content:space-between; gap:20px; }} nav a {{ text-decoration:none; font-weight:750; }}
    main {{ padding:64px 0 80px; }} .eyebrow {{ color:var(--mint); font:800 12px/1.2 ui-monospace,monospace; text-transform:uppercase; letter-spacing:.12em; }} h1 {{ max-width:780px; margin:14px 0 18px; font-size:clamp(38px,7vw,72px); line-height:1.02; letter-spacing:0; }} .lede {{ max-width:760px; color:var(--muted); font-size:18px; }}
    .summary {{ display:grid; grid-template-columns:repeat(4,1fr); margin:44px 0 62px; border-block:1px solid var(--line); }} .summary div {{ padding:22px 18px; border-right:1px solid var(--line); }} .summary div:last-child {{ border:0; }} .summary strong,.summary span {{ display:block; }} .summary strong {{ font-size:28px; }} .summary span {{ color:var(--muted); font-size:13px; }}
    h2 {{ margin:54px 0 18px; font-size:28px; letter-spacing:0; }} .table-wrap {{ overflow-x:auto; border:1px solid var(--line); border-radius:8px; }} table {{ width:100%; border-collapse:collapse; background:var(--panel); }} th,td {{ padding:17px 18px; text-align:left; border-bottom:1px solid var(--line); white-space:nowrap; }} tr:last-child th,tr:last-child td {{ border-bottom:0; }} td.value {{ font:750 15px/1 ui-monospace,monospace; }} .status {{ display:inline-block; min-width:54px; padding:5px 8px; border-radius:4px; text-align:center; font:800 11px/1 ui-monospace,monospace; }} .pass {{ color:#07110e; background:var(--mint); }} .fail {{ color:#1a1400; background:var(--yellow); }}
    .provenance {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }} .provenance div {{ padding:18px; border-left:3px solid var(--mint); background:var(--panel); }} code {{ color:#d8e3df; overflow-wrap:anywhere; }} footer {{ padding:26px 0; color:var(--muted); border-top:1px solid var(--line); font-size:13px; }}
    @media(max-width:700px) {{ main {{ padding-top:42px; }} .summary {{ grid-template-columns:1fr 1fr; }} .summary div:nth-child(2) {{ border-right:0; }} .summary div:nth-child(-n+2) {{ border-bottom:1px solid var(--line); }} .provenance {{ grid-template-columns:1fr; }} .table-wrap {{ overflow:visible; border:0; }} table,tbody,tr,th,td {{ display:block; }} thead {{ display:none; }} tbody tr {{ display:grid; grid-template-columns:1fr auto; gap:8px 16px; margin-bottom:10px; padding:16px; border:1px solid var(--line); border-radius:8px; }} tbody th,tbody td {{ padding:0; border:0; white-space:normal; }} tbody th {{ grid-column:1; grid-row:1; }} tbody td:nth-of-type(1) {{ grid-column:1; grid-row:2; color:var(--muted); }} tbody td:nth-of-type(2) {{ grid-column:2; grid-row:2; }} tbody td:nth-of-type(3) {{ grid-column:2; grid-row:1; }} }}
  </style>
</head>
<body>
  <header><nav class="shell"><a href="../">Badminton Skills Coach</a><a href="https://github.com/MuyuanGuo/badminton-skills-coach/blob/develop/data/evaluation/evaluation_report.json">Raw JSON</a></nav></header>
  <main class="shell">
    <p class="eyebrow">EvalOps / build {report["build"]["id"]}</p>
    <h1>Evidence quality, measured against a released baseline.</h1>
    <p class="lede">This deterministic report compares the {html.escape(report["development_version"])} runtime with the versioned {html.escape(report["baseline_version"])} baseline. It covers the complete path from query interpretation to reviewed answers and blind forward tests.</p>
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
    args = parser.parse_args()

    report = build_report()
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
