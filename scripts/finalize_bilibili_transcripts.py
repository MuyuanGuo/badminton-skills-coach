#!/usr/bin/env python3
"""Reconcile Bilibili transcript outputs into the durable processing queue."""

import argparse
import json
from collections import Counter
from pathlib import Path

from batch_transcribe_directory import load_valid_transcript, mark_transcribed
from bilibili_pipeline import acquire_bilibili_pipeline_lock
from bilibili_storage import (
    BILIBILI_MEDIA_CACHE_ENV,
    BILIBILI_TRANSCRIPT_CACHE_ENV,
    bilibili_media_cache_root,
    bilibili_transcript_cache_root,
    bilibili_transcript_roots,
    index_exact_transcript_candidates,
    media_storage_key,
    resolve_queue_media_path,
)
from douyin_pipeline import normalize_transcribed_media_state, now_iso, write_json


ROOT = Path(__file__).resolve().parents[1]
QUEUE_PATH = ROOT / "data" / "processing" / "bilibili_queue.json"
MEDIA_ROOT = bilibili_media_cache_root(ROOT)
TRANSCRIPT_ROOT = bilibili_transcript_cache_root(ROOT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--media-cache-dir",
        type=Path,
        help=(
            "Preferred Bilibili media cache "
            f"(default: {BILIBILI_MEDIA_CACHE_ENV} or repository data)"
        ),
    )
    parser.add_argument(
        "--transcript-cache-dir",
        type=Path,
        help=(
            "Preferred Bilibili transcript cache "
            f"(default: {BILIBILI_TRANSCRIPT_CACHE_ENV} or repository data)"
        ),
    )
    args = parser.parse_args()
    pipeline_lock = acquire_bilibili_pipeline_lock()
    media_root = (
        bilibili_media_cache_root(ROOT, override=args.media_cache_dir)
        if args.media_cache_dir is not None
        else MEDIA_ROOT
    )
    queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    transcript_candidates = index_exact_transcript_candidates(
        bilibili_transcript_roots(
            ROOT,
            override=args.transcript_cache_dir,
        )
    )
    completed = []
    changed = False
    media_by_stem = {}
    if media_root.exists():
        for path in media_root.iterdir():
            if path.is_file():
                media_by_stem.setdefault(path.stem, []).append(path)
    for item in queue["items"]:
        bvid = item["video_id"]
        if item.get("status") == "transcribed":
            continue
        candidate_paths = transcript_candidates.get(bvid, [])
        media_candidates = []
        if item.get("media_path") or item.get("media_cache_key"):
            configured = resolve_queue_media_path(
                item,
                bvid,
                project_root=ROOT,
                cache_root=media_root,
                require_legacy_identity=False,
            )
            if configured.is_file():
                media_candidates.append(configured)
        for stem in (media_storage_key(bvid), bvid):
            media_candidates.extend(media_by_stem.get(stem, []))
        media = next(
            (
                path
                for path in media_candidates
                if path.suffix.lower() in {".m4a", ".mp3", ".webm", ".wav", ".mp4"}
                and not path.name.endswith(".part")
            ),
            None,
        )
        if not candidate_paths or media is None:
            continue
        payload = None
        for transcript_path in candidate_paths:
            try:
                payload = load_valid_transcript(transcript_path, bvid, media)
            except OSError:
                continue
            break
        if payload is None:
            continue
        item_changed = mark_transcribed(item, payload)
        item_changed = normalize_transcribed_media_state(item) or item_changed
        if item.get("platform") != "bilibili":
            item["platform"] = "bilibili"
            item_changed = True
        if item_changed or not item.get("media_validated_at"):
            item["media_validated_at"] = now_iso()
            item_changed = True
        changed = changed or item_changed
        completed.append(bvid)
    counts = dict(Counter(item["status"] for item in queue["items"]))
    if queue.get("counts") != counts:
        queue["counts"] = counts
        changed = True
    if changed:
        queue["updated_at"] = now_iso()
        write_json(QUEUE_PATH, queue)
    print(json.dumps({
        "completed": len(completed),
        "video_ids": completed,
        "counts": queue["counts"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
