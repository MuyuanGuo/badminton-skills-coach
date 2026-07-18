#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
from pathlib import Path

from project_artifacts import sync_skill_references


ROOT = Path(__file__).resolve().parents[1]


def run(command):
    print(f"$ {' '.join(command)}", flush=True)
    return subprocess.run(command, cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(
        description="Run the local Liu Hui Skill update pipeline from an optional profile snapshot through validation."
    )
    parser.add_argument("--snapshot", type=Path, help="Optional Douyin profile snapshot JSON")
    parser.add_argument("--apply-snapshot", action="store_true", help="Apply new teaching candidates from --snapshot")
    parser.add_argument("--batch", help="Optional prepared media batch to download and transcribe")
    parser.add_argument("--no-push", action="store_true", help="Pass through to process_douyin_ready_batch.py")
    args = parser.parse_args()

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

    if args.batch:
        command = [sys.executable, "scripts/process_douyin_ready_batch.py", args.batch]
        if args.no_push:
            command.append("--no-push")
        run(command)
    else:
        for command in [
            [sys.executable, "scripts/build_douyin_knowledge.py"],
            [sys.executable, "scripts/build_topic_index.py"],
            [sys.executable, "scripts/build_retrieval_index.py"],
            [sys.executable, "scripts/build_visual_review_queue.py"],
            [sys.executable, "scripts/generate_knowledge_graph.py"],
            [sys.executable, "scripts/build_answer_quality_review_queue.py"],
        ]:
            run(command)
        changed_references = sync_skill_references()
        print(
            json.dumps(
                {"synchronized_skill_references": changed_references},
                ensure_ascii=False,
            )
        )
        run([sys.executable, "scripts/update_readme_status.py"])
        run([sys.executable, "scripts/evaluate_retrieval.py"])
        run([sys.executable, "scripts/evaluate_answer_policy.py"])
        run([sys.executable, "scripts/evaluate_feedback_signals.py"])
        run([sys.executable, "scripts/test_feedback_pipeline.py"])
        run([sys.executable, "scripts/test_feedback_personalization.py"])
        run([sys.executable, "scripts/test_feedback_promotion.py"])
        run([sys.executable, "scripts/test_public_feedback_e2e.py"])
        run([sys.executable, "scripts/validate_project.py"])

    print(json.dumps({"status": "ok"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
