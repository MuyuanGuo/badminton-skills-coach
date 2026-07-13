#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

from douyin_pipeline import PRE_MEDIA_STATUSES, compute_status_counts, now_iso, write_json


ROOT = Path(__file__).resolve().parents[1]
QUEUE_PATH = ROOT / "data" / "processing" / "douyin_queue.json"
TMP_ROOT = ROOT / "data" / "tmp"
RAW_ROOT = ROOT / "data" / "raw_videos" / "douyin"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def select_asset(snapshot, prefer):
    assets = snapshot.get("assets") or []
    preferred_key = f"preferred_{prefer}"
    if snapshot.get(preferred_key):
        return snapshot[preferred_key]
    for asset in assets:
        if asset.get("kind") == prefer:
            return asset
    fallback = "video" if prefer == "audio" else "audio"
    for asset in assets:
        if asset.get("kind") == fallback:
            return asset
    return None


def curl_config(url, output_path):
    return "\n".join(
        [
            f'url = "{url}"',
            f'output = "{output_path}"',
            "location",
            "fail",
            "retry = 2",
            "connect-timeout = 20",
            "max-time = 300",
            'user-agent = "Mozilla/5.0"',
            "",
        ]
    )


def main():
    parser = argparse.ArgumentParser(
        description="Convert a Douyin video media-asset snapshot into a curl config and mark the queue item media_ready."
    )
    parser.add_argument("--input", type=Path, required=True, help="JSON from douyin_video_media_assets_dom.js")
    parser.add_argument("--batch", required=True, help="Batch name, for example batch-049")
    parser.add_argument("--prefer", choices=["audio", "video"], default="audio")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing curl config and media_path")
    args = parser.parse_args()

    input_path = args.input if args.input.is_absolute() else ROOT / args.input
    snapshot = load_json(input_path)
    video_id = str(snapshot.get("video_id") or "")
    if not video_id:
        raise SystemExit(f"Missing video_id in {input_path}")

    asset = select_asset(snapshot, args.prefer)
    if not asset or not asset.get("url"):
        raise SystemExit(f"No usable media asset found for {video_id}")

    queue = load_json(QUEUE_PATH)
    item = next((row for row in queue["items"] if str(row["video_id"]) == video_id), None)
    if not item:
        raise SystemExit(f"Video {video_id} is not in the processing queue")
    if item.get("status") not in PRE_MEDIA_STATUSES and not args.force:
        raise SystemExit(f"Refusing to prepare media for {video_id} with status {item.get('status')}")

    suffix = ".m4a" if asset.get("kind") == "audio" else ".mp4"
    relative_output = Path("data") / "raw_videos" / "douyin" / args.batch / f"{video_id}{suffix}"
    curl_path = TMP_ROOT / args.batch / f"{video_id}.curl"
    raw_dir = RAW_ROOT / args.batch
    raw_dir.mkdir(parents=True, exist_ok=True)
    curl_path.parent.mkdir(parents=True, exist_ok=True)
    if curl_path.exists() and not args.force:
        raise SystemExit(f"Curl config already exists: {curl_path.relative_to(ROOT)}")

    curl_path.write_text(curl_config(asset["url"], str(relative_output)), encoding="utf-8")
    item["status"] = "media_ready"
    item["media_path"] = str(relative_output)
    item["media_asset_kind"] = asset.get("kind")
    item["media_asset_source"] = str(input_path.relative_to(ROOT) if input_path.is_relative_to(ROOT) else input_path)
    item["error"] = None
    queue["counts"] = compute_status_counts(queue["items"])
    queue["updated_at"] = now_iso()
    write_json(QUEUE_PATH, queue)
    print(
        json.dumps(
            {
                "video_id": video_id,
                "status": "media_ready",
                "curl": str(curl_path.relative_to(ROOT)),
                "media_path": str(relative_output),
                "asset_kind": asset.get("kind"),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
