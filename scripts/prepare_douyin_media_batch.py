#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

from douyin_pipeline import PRE_MEDIA_STATUSES, compute_status_counts, now_iso, write_json
from media_assets import (
    MediaAssetError,
    load_media_policy,
    render_download_config,
    validate_batch_name,
    validate_media_snapshot,
    validate_asset_url,
    validate_video_id,
)
from project_artifacts import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
QUEUE_PATH = ROOT / "data" / "processing" / "douyin_queue.json"
TMP_ROOT = ROOT / "data" / "tmp"
RAW_ROOT = ROOT / "data" / "raw_videos" / "douyin"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def select_asset(snapshot, prefer, policy):
    assets = snapshot.get("assets") or []
    preferred_key = f"preferred_{prefer}"
    preferred = snapshot.get(preferred_key)
    candidates = []
    if preferred and any(
        asset.get("url") == preferred.get("url")
        and asset.get("kind") == preferred.get("kind")
        for asset in assets
    ):
        candidates.append(preferred)
    candidates.extend(asset for asset in assets if asset.get("kind") == prefer)
    fallback = "video" if prefer == "audio" else "audio"
    candidates.extend(asset for asset in assets if asset.get("kind") == fallback)
    seen_urls = set()
    for asset in candidates:
        url = asset.get("url")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        try:
            validate_asset_url(url, policy)
        except MediaAssetError:
            continue
        return asset
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Convert a Douyin video media-asset snapshot into a curl config and mark the queue item media_ready."
    )
    parser.add_argument("--input", type=Path, required=True, help="JSON from douyin_video_media_assets_dom.js")
    parser.add_argument("--batch", required=True, help="Batch name, for example batch-049")
    parser.add_argument("--prefer", choices=["audio", "video"], default="video")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing curl config and media_path")
    args = parser.parse_args()

    try:
        batch = validate_batch_name(args.batch)
        media_policy = load_media_policy()
    except MediaAssetError as error:
        raise SystemExit(str(error)) from error
    input_path = args.input if args.input.is_absolute() else ROOT / args.input
    snapshot = load_json(input_path)
    try:
        video_id = validate_video_id(snapshot.get("video_id"))
        snapshot_age_minutes = validate_media_snapshot(
            snapshot, video_id, media_policy
        )
    except MediaAssetError as error:
        raise SystemExit(str(error)) from error

    asset = select_asset(snapshot, args.prefer, media_policy)
    if not asset or not asset.get("url"):
        raise SystemExit(f"No usable media asset found for {video_id}")
    if asset.get("kind") not in {"audio", "video"}:
        raise SystemExit(f"Selected media asset has an invalid kind for {video_id}")

    queue = load_json(QUEUE_PATH)
    item = next((row for row in queue["items"] if str(row["video_id"]) == video_id), None)
    if not item:
        raise SystemExit(f"Video {video_id} is not in the processing queue")
    if item.get("status") not in PRE_MEDIA_STATUSES and not args.force:
        raise SystemExit(f"Refusing to prepare media for {video_id} with status {item.get('status')}")

    suffix = ".m4a" if asset.get("kind") == "audio" else ".mp4"
    relative_output = Path("data") / "raw_videos" / "douyin" / batch / f"{video_id}{suffix}"
    curl_path = TMP_ROOT / batch / f"{video_id}.curl"
    raw_dir = RAW_ROOT / batch
    raw_dir.mkdir(parents=True, exist_ok=True)
    curl_path.parent.mkdir(parents=True, exist_ok=True)
    if curl_path.exists() and not args.force:
        raise SystemExit(f"Curl config already exists: {curl_path.relative_to(ROOT)}")

    try:
        config_text = render_download_config(
            asset["url"], relative_output, media_policy
        )
    except MediaAssetError as error:
        raise SystemExit(str(error)) from error
    atomic_write_text(curl_path, config_text)
    item["status"] = "media_ready"
    item["media_path"] = str(relative_output)
    item["media_asset_kind"] = asset.get("kind")
    item["media_asset_source"] = (
        str(input_path.relative_to(ROOT))
        if input_path.is_relative_to(ROOT)
        else f"external:{input_path.name}"
    )
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
                "snapshot_age_minutes": snapshot_age_minutes,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
