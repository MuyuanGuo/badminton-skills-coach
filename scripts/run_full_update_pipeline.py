#!/usr/bin/env python3
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from build_update_impact_report import (
    DEFAULT_OUTPUT as IMPACT_REPORT_PATH,
    snapshot as impact_snapshot,
    write_report as write_impact_report,
)
from bilibili_pipeline import (
    PIPELINE_LOCK_OWNER_ENV,
    acquire_bilibili_pipeline_lock,
)
from project_artifacts import (
    SKILL_REFERENCE_PATHS,
    artifact_rollback_guard,
    atomic_write_text,
    sync_skill_references,
)


ROOT = Path(__file__).resolve().parents[1]
UPDATE_ARTIFACT_PATHS = (
    ROOT / "data/knowledge/bilibili_knowledge_base.json",
    ROOT / "data/knowledge/douyin_knowledge_base.json",
    ROOT / "data/knowledge/topic_index.json",
    ROOT / "skills/liuhui-badminton-coach/references/topic-index.md",
    ROOT / "data/knowledge/retrieval_index.json",
    ROOT / "data/knowledge/evidence_graph.json",
    ROOT / "data/knowledge/knowledge_graph_summary.json",
    ROOT / "data/knowledge/build_manifest.json",
    ROOT / "data/evaluation/evaluation_report.json",
    ROOT / "data/evaluation/supplemental_evidence_report.json",
    ROOT / "data/review/visual_review_queue.json",
    ROOT / "config/reviewed_evidence_signals.json",
    ROOT / "output/visual_review_queue.md",
    ROOT / "output/liuhui-full-knowledge-map.drawio",
    ROOT / "output/liuhui-knowledge-map.mmd",
    ROOT / "output/liuhui-knowledge-map.html",
    ROOT / "output/answer_quality_review_queue.md",
    ROOT / "output/video-link-health.json",
    ROOT / "README.md",
    ROOT / "README.en.md",
    ROOT / "docs/evaluation/index.html",
    ROOT / "skills/liuhui-badminton-coach/SKILL.md",
    ROOT / "skills/liuhui-badminton-coach/agents/openai.yaml",
    IMPACT_REPORT_PATH,
    *(
        ROOT / destination
        for _, destination in SKILL_REFERENCE_PATHS
    ),
)


def run(command, *, env=None):
    normalized = [str(part) for part in command]
    print(f"$ {' '.join(normalized)}", flush=True)
    return subprocess.run(normalized, cwd=ROOT, check=True, env=env)


def build_commands(*, rebuild_bilibili=True):
    commands = [
        [sys.executable, "scripts/migrate_bilibili_evidence_admission.py"],
        [sys.executable, "scripts/build_douyin_knowledge.py"],
        [sys.executable, "scripts/build_topic_index.py"],
        [sys.executable, "scripts/build_retrieval_index.py"],
        [sys.executable, "scripts/build_evidence_graph.py"],
        [sys.executable, "scripts/build_visual_review_queue.py"],
        [sys.executable, "scripts/generate_knowledge_graph.py"],
        [sys.executable, "scripts/build_answer_quality_review_queue.py"],
        [sys.executable, "scripts/build_reviewed_evidence_signals.py"],
    ]
    if rebuild_bilibili:
        commands.insert(
            0,
            [sys.executable, "scripts/build_bilibili_knowledge.py"],
        )
    return commands


def validation_commands(*, raw_transcript_sources=None):
    video_comprehension = [
        sys.executable,
        "scripts/evaluate_video_comprehension.py",
        "--require-raw-transcripts",
    ]
    for source in raw_transcript_sources or ():
        video_comprehension.extend(
            ["--require-raw-transcript-source", source]
        )
    return [
        [sys.executable, "scripts/evaluate_bilibili_canaries.py"],
        [sys.executable, "scripts/evaluate_supplemental_evidence_policy.py"],
        [sys.executable, "scripts/apply_answer_quality_review_notes.py", "--dry-run"],
        [sys.executable, "scripts/evaluate_answer_policy.py"],
        [sys.executable, "scripts/evaluate_answer_context.py"],
        [sys.executable, "scripts/evaluate_answer_audit.py"],
        [sys.executable, "scripts/evaluate_diagnostic_answer_contract.py"],
        [
            sys.executable,
            "scripts/evaluate_answer_quality.py",
            "--answers",
            "data/evaluation/answer_quality_answers.json",
            "--min-approved",
            "57",
            "--min-answer-snapshots",
            "57",
            "--min-answer-snapshot-coverage",
            "1.0",
            "--require-complete-answer-coverage",
            "--require-critical-answer-coverage",
            "--require-manual-review",
        ],
        [sys.executable, "scripts/evaluate_feedback_signals.py"],
        [sys.executable, "scripts/evaluate_feedback_lifecycle.py"],
        [sys.executable, "scripts/evaluate_query_understanding.py"],
        [sys.executable, "scripts/evaluate_query_equivalence.py"],
        [sys.executable, "scripts/evaluate_metamorphic_robustness.py"],
        [sys.executable, "scripts/evaluate_retrieval.py"],
        [sys.executable, "scripts/benchmark_runtime.py"],
        [sys.executable, "scripts/evaluate_forward_test_results.py"],
        video_comprehension,
        [sys.executable, "scripts/build_manifest.py", "--check"],
        [sys.executable, "scripts/check_video_links.py"],
        ["node", "scripts/test_douyin_profile_snapshot_dom.mjs"],
        ["node", "scripts/test_bilibili_profile_snapshot_dom.mjs"],
        ["node", "scripts/test_douyin_video_media_assets_dom.mjs"],
        ["node", "scripts/test_export_douyin_cookies_cdp.mjs"],
        [sys.executable, "scripts/validate_project.py"],
    ]


def rebuild_and_validate(*, rebuild_bilibili=True):
    if not rebuild_bilibili:
        # A Douyin-only update may reuse the committed Bilibili knowledge
        # artifact, but only after its policy partition and release coverage
        # have been checked. Full rebuilds retain the stricter raw-source gate.
        validate_bilibili_release_completeness()
    before = impact_snapshot()
    with artifact_rollback_guard(UPDATE_ARTIFACT_PATHS):
        for command in build_commands(rebuild_bilibili=rebuild_bilibili):
            run(command)
        changed_references = sync_skill_references()
        print(
            json.dumps(
                {"synchronized_skill_references": changed_references},
                ensure_ascii=False,
            )
        )
        run([sys.executable, "scripts/update_readme_status.py"])
        run([sys.executable, "scripts/build_manifest.py"])

        test_environment = dict(os.environ)
        existing_pythonpath = test_environment.get("PYTHONPATH")
        test_environment["PYTHONPATH"] = os.pathsep.join(
            value
            for value in [str(ROOT / "scripts"), existing_pythonpath]
            if value
        )
        run(
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                "scripts",
                "-p",
                "test_*.py",
            ],
            env=test_environment,
        )
        raw_transcript_sources = (
            None if rebuild_bilibili else ("douyin_video",)
        )
        for command in validation_commands(
            raw_transcript_sources=raw_transcript_sources
        ):
            run(command)
        with tempfile.TemporaryDirectory(
            prefix="badminton-evaluations-"
        ) as directory:
            wiring_canaries = Path(directory) / "bilibili-wiring-canaries.json"
            run(
                [
                    sys.executable,
                    "scripts/generate_bilibili_wiring_canaries.py",
                    "--output",
                    wiring_canaries,
                ]
            )
            run(
                [
                    sys.executable,
                    "scripts/evaluate_bilibili_wiring_canaries.py",
                    wiring_canaries,
                ]
            )
            evaluation_results = Path(directory) / "core-evaluations.json"
            run(
                [
                    sys.executable,
                    "scripts/collect_evaluation_results.py",
                    "--output",
                    evaluation_results,
                ]
            )
            run(
                [
                    sys.executable,
                    "scripts/generate_evaluation_report.py",
                    "--write",
                    "--evaluations",
                    evaluation_results,
                ]
            )
        impact = write_impact_report(before, impact_snapshot())
        print(json.dumps({"update_impact": impact}, ensure_ascii=False))
    return changed_references


def validate_bilibili_release_completeness(root=None):
    """Fail closed unless every required Bilibili video reached the build."""

    root = ROOT if root is None else Path(root)

    def load(relative_path):
        return json.loads(
            (Path(root) / relative_path).read_text(encoding="utf-8")
        )

    ledger = load("data/bilibili_classification_ledger.json")
    queue = load("data/processing/bilibili_queue.json")
    knowledge = load("data/knowledge/bilibili_knowledge_base.json")
    manifest = load("data/knowledge/build_manifest.json")

    required_ids = {
        item["bvid"]
        for item in ledger.get("videos", [])
        if item.get("decision") == "required_transcription_policy"
    }
    excluded_ids = {
        item["bvid"]
        for item in ledger.get("videos", [])
        if item.get("decision") == "excluded_transcription_policy"
    }
    queue_items = queue.get("items") or []
    queue_ids = [item.get("video_id") for item in queue_items]
    transcribed_ids = {
        item.get("video_id")
        for item in queue_items
        if item.get("status") == "transcribed"
    }
    knowledge_ids = [
        item.get("source_video_id")
        for item in knowledge.get("videos", [])
    ]
    if not required_ids or not excluded_ids or required_ids & excluded_ids:
        raise ValueError(
            "Bilibili classification ledger is empty or overlapping"
        )
    if len(queue_ids) != len(set(queue_ids)):
        raise ValueError("Bilibili release queue contains duplicate video IDs")
    if set(queue_ids) != required_ids or transcribed_ids != required_ids:
        raise ValueError(
            "Bilibili release requires every policy-required video to be "
            "transcribed"
        )
    if len(knowledge_ids) != len(set(knowledge_ids)):
        raise ValueError(
            "Bilibili release knowledge base contains duplicate video IDs"
        )
    if set(knowledge_ids) != required_ids:
        raise ValueError(
            "Bilibili release knowledge base does not cover the required set"
        )
    if excluded_ids & (set(queue_ids) | set(knowledge_ids)):
        raise ValueError(
            "Policy-excluded Bilibili video entered the release corpus"
        )
    if manifest.get("corpus", {}).get("pending_count") != 0:
        raise ValueError("Validated build manifest still contains pending work")
    return {
        "required": len(required_ids),
        "excluded": len(excluded_ids),
    }


def write_validation_receipt(path):
    validate_bilibili_release_completeness()
    manifest = json.loads(
        (ROOT / "data/knowledge/build_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    build_id = str(manifest.get("build_id") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", build_id):
        raise ValueError("Validated build manifest has no valid build_id")
    atomic_write_text(
        Path(path),
        json.dumps(
            {
                "schema_version": 1,
                "build_id": build_id,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
    )
    return build_id


def main():
    parser = argparse.ArgumentParser(
        description="Run the local Liu Hui Skill update pipeline from an optional profile snapshot through validation."
    )
    parser.add_argument("--snapshot", type=Path, help="Optional Douyin profile snapshot JSON")
    parser.add_argument("--apply-snapshot", action="store_true", help="Apply new teaching candidates from --snapshot")
    parser.add_argument("--batch", help="Optional prepared media batch to download and transcribe")
    parser.add_argument(
        "--auto-download",
        action="store_true",
        help="Let the batch processor download classified/failed videos through isolated anonymous Chrome",
    )
    parser.add_argument(
        "--video-id",
        action="append",
        default=[],
        help="Limit --auto-download to one queued video ID; repeatable",
    )
    parser.add_argument("--no-push", action="store_true", help="Pass through to process_douyin_ready_batch.py")
    parser.add_argument(
        "--validation-receipt",
        type=Path,
        help="Write the validated build ID after the complete rebuild succeeds",
    )
    args = parser.parse_args()
    if args.video_id and not args.auto_download:
        parser.error("--video-id requires --auto-download")
    if args.batch and args.validation_receipt:
        parser.error("--validation-receipt requires a complete rebuild")
    pipeline_lock = acquire_bilibili_pipeline_lock()
    os.environ[PIPELINE_LOCK_OWNER_ENV] = "1"

    if args.snapshot:
        command = [
            sys.executable,
            "scripts/check_douyin_updates.py",
            "--input",
            str(args.snapshot),
            "--report",
            "output/douyin-update-report.json",
        ]
        if args.apply_snapshot:
            command.append("--apply")
        run(command)

    run([sys.executable, "scripts/reclassify_douyin_catalog.py", "--apply"])

    if args.batch:
        command = [sys.executable, "scripts/process_douyin_ready_batch.py", args.batch]
        if args.auto_download:
            command.append("--auto-download")
        for video_id in args.video_id:
            command.extend(["--video-id", video_id])
        if args.no_push:
            command.append("--no-push")
        run(command)
    else:
        rebuild_and_validate()
        if args.validation_receipt:
            write_validation_receipt(args.validation_receipt)

    print(json.dumps({"status": "ok"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
