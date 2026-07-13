#!/usr/bin/env python3
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from douyin_pipeline import compute_status_counts, validate_queue_statuses, now_iso


ROOT = Path(__file__).resolve().parents[1]
QUEUE_PATH = ROOT / "data" / "processing" / "douyin_queue.json"
RAW_ROOT = ROOT / "data" / "raw_videos" / "douyin"
TRANSCRIPT_ROOT = ROOT / "data" / "transcripts" / "douyin"
TMP_ROOT = ROOT / "data" / "tmp"


def run(command, *, check=True):
    print(f"$ {' '.join(command)}", flush=True)
    return subprocess.run(command, cwd=ROOT, check=check)


def queue_counts():
    queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    return compute_counts(queue)


def compute_counts(queue):
    validate_queue_statuses(queue["items"])
    return compute_status_counts(queue["items"])


def write_queue(queue):
    queue["counts"] = compute_counts(queue)
    queue["updated_at"] = now_iso()
    QUEUE_PATH.write_text(
        json.dumps(queue, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def ready_items(batch):
    prefix = f"data/raw_videos/douyin/{batch}/"
    queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    return [
        item for item in queue["items"]
        if item.get("status") == "media_ready"
        and item.get("media_path", "").startswith(prefix)
    ]


def download_ready_items(batch, items):
    queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    queue_by_id = {item["video_id"]: item for item in queue["items"]}
    downloaded = []
    failed = []
    for item in items:
        video_id = item["video_id"]
        config = TMP_ROOT / batch / f"{video_id}.curl"
        queue_item = queue_by_id[video_id]
        if not config.exists():
            queue_item["status"] = "download_failed"
            queue_item["attempts"] = int(queue_item.get("attempts") or 0) + 1
            queue_item["error"] = f"Missing curl config: {config.relative_to(ROOT)}"
            failed.append(video_id)
            write_queue(queue)
            continue
        completed = subprocess.run(
            ["curl", "-L", "--fail", "--retry", "2", "-K", str(config.relative_to(ROOT))],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        if completed.returncode:
            queue_item["status"] = "download_failed"
            queue_item["attempts"] = int(queue_item.get("attempts") or 0) + 1
            queue_item["error"] = (completed.stderr or completed.stdout or "").strip()[-1200:]
            failed.append(video_id)
        else:
            queue_item["status"] = "downloaded"
            queue_item["error"] = None
            downloaded.append(video_id)
        write_queue(queue)
    return downloaded, failed


def ensure_no_raw_media_left(batch):
    media_dir = RAW_ROOT / batch
    media_dir.mkdir(parents=True, exist_ok=True)
    for path in media_dir.iterdir():
        if path.is_file():
            path.unlink()


def commit_if_changed(message, push):
    status = subprocess.check_output(
        ["git", "status", "--short"],
        cwd=ROOT,
        text=True,
    ).strip()
    if not status:
        print("No tracked changes to commit.", flush=True)
        return
    run(["git", "add", "."])
    run(["git", "diff", "--cached", "--stat"])
    run(["git", "commit", "-m", message])
    if push:
        run(["git", "push"])


def main():
    parser = argparse.ArgumentParser(
        description="Download, transcribe, validate, clean, and commit one Douyin media_ready batch."
    )
    parser.add_argument("batch", help="Batch name, for example batch-009")
    parser.add_argument("--no-push", action="store_true", help="Commit locally but skip git push")
    parser.add_argument(
        "--min-free-gb",
        type=float,
        default=8.0,
        help="Stop before download if available disk space is below this threshold",
    )
    args = parser.parse_args()

    usage = shutil.disk_usage(ROOT)
    free_gb = usage.free / (1024 ** 3)
    if free_gb < args.min_free_gb:
        print(
            json.dumps({"error": "low_disk_space", "free_gb": round(free_gb, 2)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2

    items = ready_items(args.batch)
    if not items:
        print(json.dumps({"batch": args.batch, "media_ready": 0}, ensure_ascii=False))
        return 0

    media_dir = RAW_ROOT / args.batch
    transcript_dir = TRANSCRIPT_ROOT / args.batch
    media_dir.mkdir(parents=True, exist_ok=True)
    transcript_dir.mkdir(parents=True, exist_ok=True)

    print(json.dumps({
        "batch": args.batch,
        "media_ready": len(items),
        "before": queue_counts(),
        "free_gb": round(free_gb, 2),
    }, ensure_ascii=False), flush=True)

    downloaded, failed = download_ready_items(args.batch, items)
    print(json.dumps({
        "downloaded": len(downloaded),
        "download_failed": len(failed),
        "failed_video_ids": failed,
    }, ensure_ascii=False), flush=True)
    if downloaded:
        run([
            ".venv/bin/python",
            "scripts/batch_transcribe_directory.py",
            str(media_dir.relative_to(ROOT)),
            "--output-dir",
            str(transcript_dir.relative_to(ROOT)),
            "--queue",
            str(QUEUE_PATH.relative_to(ROOT)),
        ])
    run(["python3", "scripts/build_douyin_knowledge.py"])
    run(["python3", "scripts/build_topic_index.py"])
    run(["python3", "scripts/build_retrieval_index.py"])
    run(["python3", "scripts/build_visual_review_queue.py"])
    run(["python3", "scripts/generate_knowledge_graph.py"])
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
    run(["python3", "scripts/update_readme_status.py"])
    ensure_no_raw_media_left(args.batch)
    run(["python3", "scripts/evaluate_retrieval.py"])
    run(["python3", "scripts/evaluate_answer_policy.py"])
    run(["python3", "scripts/validate_project.py"])

    commit_if_changed(
        f"Process Douyin teaching {args.batch}",
        push=not args.no_push,
    )

    print(json.dumps({
        "batch": args.batch,
        "after": queue_counts(),
        "pushed": not args.no_push,
    }, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
