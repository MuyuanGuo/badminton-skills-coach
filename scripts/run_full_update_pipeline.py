#!/usr/bin/env python3
import argparse
import json
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(command):
    print(f"$ {' '.join(command)}", flush=True)
    return subprocess.run(command, cwd=ROOT, check=True)


def sync_skill_references():
    shutil.copyfile(
        ROOT / "data" / "knowledge" / "douyin_knowledge_base.json",
        ROOT / "skills" / "liuhui-badminton-coach" / "references" / "knowledge-base.json",
    )
    shutil.copyfile(
        ROOT / "data" / "knowledge" / "knowledge_graph_summary.json",
        ROOT / "skills" / "liuhui-badminton-coach" / "references" / "topic-map.json",
    )
    shutil.copyfile(
        ROOT / "data" / "knowledge" / "retrieval_index.json",
        ROOT / "skills" / "liuhui-badminton-coach" / "references" / "retrieval-index.json",
    )
    shutil.copyfile(
        ROOT / "config" / "retrieval_rules.json",
        ROOT / "skills" / "liuhui-badminton-coach" / "references" / "retrieval-rules.json",
    )
    shutil.copyfile(
        ROOT / "config" / "answer_modality_rules.json",
        ROOT / "skills" / "liuhui-badminton-coach" / "references" / "answer-modality-rules.json",
    )
    shutil.copyfile(
        ROOT / "config" / "feedback_rules.json",
        ROOT / "skills" / "liuhui-badminton-coach" / "references" / "feedback-rules.json",
    )


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
            "python3",
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
        command = ["python3", "scripts/process_douyin_ready_batch.py", args.batch]
        if args.no_push:
            command.append("--no-push")
        run(command)
    else:
        for command in [
            ["python3", "scripts/build_douyin_knowledge.py"],
            ["python3", "scripts/build_topic_index.py"],
            ["python3", "scripts/build_retrieval_index.py"],
            ["python3", "scripts/build_visual_review_queue.py"],
            ["python3", "scripts/generate_knowledge_graph.py"],
        ]:
            run(command)
        sync_skill_references()
        run(["python3", "scripts/update_readme_status.py"])
        run(["python3", "scripts/evaluate_retrieval.py"])
        run(["python3", "scripts/evaluate_answer_policy.py"])
        run(["python3", "scripts/test_feedback_pipeline.py"])
        run(["python3", "scripts/validate_project.py"])

    print(json.dumps({"status": "ok"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
