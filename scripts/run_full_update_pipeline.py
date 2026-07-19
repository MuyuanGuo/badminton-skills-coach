#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from project_artifacts import sync_skill_references


ROOT = Path(__file__).resolve().parents[1]


def run(command, *, env=None):
    normalized = [str(part) for part in command]
    print(f"$ {' '.join(normalized)}", flush=True)
    return subprocess.run(normalized, cwd=ROOT, check=True, env=env)


def build_commands():
    return [
        [sys.executable, "scripts/build_douyin_knowledge.py"],
        [sys.executable, "scripts/build_topic_index.py"],
        [sys.executable, "scripts/build_retrieval_index.py"],
        [sys.executable, "scripts/build_visual_review_queue.py"],
        [sys.executable, "scripts/generate_knowledge_graph.py"],
        [sys.executable, "scripts/build_answer_quality_review_queue.py"],
        [sys.executable, "scripts/build_reviewed_evidence_signals.py"],
    ]


def validation_commands():
    return [
        [sys.executable, "scripts/apply_answer_quality_review_notes.py", "--dry-run"],
        [sys.executable, "scripts/evaluate_answer_policy.py"],
        [sys.executable, "scripts/evaluate_answer_context.py"],
        [sys.executable, "scripts/evaluate_answer_quality.py"],
        [sys.executable, "scripts/evaluate_feedback_signals.py"],
        [sys.executable, "scripts/evaluate_query_understanding.py"],
        [sys.executable, "scripts/evaluate_retrieval.py"],
        [
            sys.executable,
            "scripts/evaluate_video_comprehension.py",
            "--require-raw-transcripts",
        ],
        [sys.executable, "scripts/build_manifest.py", "--check"],
        [sys.executable, "scripts/check_video_links.py"],
        ["node", "scripts/test_douyin_profile_snapshot_dom.mjs"],
        ["node", "scripts/test_douyin_video_media_assets_dom.mjs"],
        ["node", "scripts/test_export_douyin_cookies_cdp.mjs"],
        [sys.executable, "scripts/validate_project.py"],
    ]


def rebuild_and_validate():
    for command in build_commands():
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
    for command in validation_commands():
        run(command)
    return changed_references


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
    args = parser.parse_args()
    if args.video_id and not args.auto_download:
        parser.error("--video-id requires --auto-download")

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

    print(json.dumps({"status": "ok"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
