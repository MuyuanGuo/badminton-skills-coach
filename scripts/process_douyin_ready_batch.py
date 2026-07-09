#!/usr/bin/env python3
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


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
    counts = {}
    for item in queue["items"]:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return counts


def ready_items(batch):
    prefix = f"data/raw_videos/douyin/{batch}/"
    queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    return [
        item for item in queue["items"]
        if item.get("status") == "media_ready"
        and item.get("media_path", "").startswith(prefix)
    ]


def curl_configs(batch, items):
    configs = []
    for item in items:
        config = TMP_ROOT / batch / f"{item['video_id']}.curl"
        if not config.exists():
            raise FileNotFoundError(config)
        configs.append(config)
    return configs


def download(configs):
    for config in configs:
        run(["curl", "-L", "--fail", "--retry", "2", "-K", str(config.relative_to(ROOT))])


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

    download(curl_configs(args.batch, items))
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
    ensure_no_raw_media_left(args.batch)
    run(["python3", "scripts/validate_project.py"])
    run(["python3", "scripts/evaluate_liuhui_skill.py"])

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
