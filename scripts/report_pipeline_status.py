#!/usr/bin/env python3
import argparse
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from bilibili_pipeline import extract_bvid
from douyin_pipeline import QUEUE_STATUSES, validate_queue_statuses
from project_artifacts import derive_project_status


ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "data" / "douyin_video_index.json"
TEACHING_PATH = ROOT / "data" / "douyin_teaching_filtered.json"
QUEUE_PATH = ROOT / "data" / "processing" / "douyin_queue.json"
KNOWLEDGE_PATH = ROOT / "data" / "knowledge" / "douyin_knowledge_base.json"
REPORT_PATH = ROOT / "output" / "douyin-update-report.json"
BILIBILI_ARCHIVE_PATH = (
    ROOT / "data" / "snapshots" / "bilibili_profile_full_archive.json"
)
BILIBILI_LEDGER_PATH = ROOT / "data" / "bilibili_classification_ledger.json"
BILIBILI_QUEUE_PATH = ROOT / "data" / "processing" / "bilibili_queue.json"
BILIBILI_KNOWLEDGE_PATH = (
    ROOT / "data" / "knowledge" / "bilibili_knowledge_base.json"
)
BUILD_MANIFEST_PATH = ROOT / "data" / "knowledge" / "build_manifest.json"
INSTALLED_MANIFEST_PATH = (
    Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
    / "skills"
    / "liuhui-badminton-coach"
    / "references"
    / "build-manifest.json"
)


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def relative(path):
    return str(path.relative_to(ROOT))


def failed_queue_items(queue):
    failure_statuses = {
        status for status, meta in QUEUE_STATUSES.items()
        if meta.get("failure")
    }
    return [
        {
            "video_id": item["video_id"],
            "status": item["status"],
            "title": item["title"],
            "error": item.get("error"),
        }
        for item in queue["items"]
        if item.get("status") in failure_statuses
    ]


def next_action(queue, update_report):
    if (
        update_report
        and update_report.get("new", 0)
        and not update_report.get("applied")
    ):
        if update_report.get("teaching", 0):
            return "Review output/douyin-update-report.json, then rerun check_douyin_updates.py with --apply if the teaching candidates are correct."
        return "Review output/douyin-update-report.json. Current new items are not classified as teaching candidates."

    counts = queue["counts"]
    if counts.get("download_failed") or counts.get("extraction_failed"):
        return "Rerun process_douyin_ready_batch.py with --auto-download so failed or expired media extraction uses the isolated browser fallback."
    if counts.get("transcription_failed"):
        return "Inspect failed media files or transcription environment, then rerun batch_transcribe_directory.py or process_douyin_ready_batch.py."
    if counts.get("media_ready"):
        return "Run process_douyin_ready_batch.py for the prepared batch."
    if counts.get("classified_teaching") or counts.get("pending"):
        return "Run process_douyin_ready_batch.py with --auto-download for each queued teaching video; use the manual media snapshot path only if needed."
    return "Capture a fresh Douyin profile snapshot and run check_douyin_updates.py."


def parse_time(value):
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def bilibili_status():
    if not all(
        path.exists()
        for path in [
            BILIBILI_ARCHIVE_PATH,
            BILIBILI_LEDGER_PATH,
            BILIBILI_QUEUE_PATH,
            BILIBILI_KNOWLEDGE_PATH,
        ]
    ):
        return {"available": False}
    archive = load_json(BILIBILI_ARCHIVE_PATH)
    ledger = load_json(BILIBILI_LEDGER_PATH)
    queue = load_json(BILIBILI_QUEUE_PATH)
    knowledge = load_json(BILIBILI_KNOWLEDGE_PATH)
    queue_by_id = {item["video_id"]: item for item in queue["items"]}
    knowledge_by_source_id = {
        item.get("source_video_id"): item for item in knowledge["videos"]
    }
    terminal_knowledge = {
        "ready",
        "low_value",
        "needs_visual_review",
        "needs_correction",
    }
    stage_counts = Counter()
    collection_policy_counts = Counter()
    terminal_counts = Counter()
    retry_due = []
    now = datetime.now(timezone.utc)
    pending = []
    archive_items = archive.get("items") or archive.get("videos") or []
    current_profile_ids = {
        bvid
        for item in archive_items
        if (bvid := extract_bvid(item))
    }
    ledger_by_bvid = {item["bvid"]: item for item in ledger["videos"]}
    missing_ledger_ids = sorted(current_profile_ids - set(ledger_by_bvid))
    for bvid in sorted(current_profile_ids):
        record = ledger_by_bvid.get(bvid)
        if record is None:
            stage_counts["missing_from_ledger"] += 1
            pending.append(bvid)
            continue
        bvid = record["bvid"]
        state = record.get("processing_state") or {}
        collection_policy_counts[
            (record.get("collection_policy") or {}).get(
                "action",
                "missing",
            )
        ] += 1
        stage = state.get("stage") or "unknown"
        queue_item = queue_by_id.get(bvid)
        knowledge_item = knowledge_by_source_id.get(bvid)
        if (
            queue_item
            and queue_item.get("status") == "transcription_quarantined"
            and knowledge_item
            and (
                knowledge_item.get("automatic_admission") or {}
            ).get("disposition")
            == "quarantined_transcription_retry_exhausted"
        ):
            stage = "transcription_quarantined"
            terminal = True
        elif (
            knowledge_item
            and knowledge_item.get("processing_status") in terminal_knowledge
        ):
            stage = f"released_{knowledge_item['processing_status']}"
            terminal = True
        elif state.get("terminal"):
            terminal = True
        elif (
            queue_item
            and queue_item.get("status") == "transcription_quarantined"
        ):
            stage = "transcription_quarantined"
            terminal = True
        else:
            terminal = False
            if queue_item and queue_item.get("status") == "transcribed":
                stage = "transcribed_waiting_release"
        stage_counts[stage] += 1
        if terminal:
            terminal_counts[stage] += 1
        else:
            pending.append(bvid)
        next_retry = parse_time(state.get("next_retry_at"))
        if next_retry and next_retry <= now and not terminal:
            retry_due.append(bvid)

    coverage = archive.get("coverage") or {}
    repo_manifest = (
        load_json(BUILD_MANIFEST_PATH) if BUILD_MANIFEST_PATH.exists() else {}
    )
    installed_manifest = (
        load_json(INSTALLED_MANIFEST_PATH)
        if INSTALLED_MANIFEST_PATH.exists()
        else {}
    )
    total = len(current_profile_ids)
    terminal = sum(terminal_counts.values())
    return {
        "available": True,
        "full_profile_archive": bool(coverage.get("full_profile_archive")),
        "profile_reported_video_count": coverage.get(
            "profile_reported_video_count"
        ),
        "profile_unique_videos": coverage.get("profile_unique_videos"),
        "classification_counts": ledger.get("counts", {}),
        "collection_policy_counts": dict(collection_policy_counts),
        "stage_counts": dict(stage_counts),
        "queue_counts": queue.get("counts", {}),
        "knowledge_counts": knowledge.get("knowledge_counts", {}),
        "terminal_videos": terminal,
        "pending_videos": len(pending),
        "pending_video_ids": pending,
        "missing_ledger_video_ids": missing_ledger_ids,
        "historical_tombstone_videos": len(
            set(ledger_by_bvid) - current_profile_ids
        ),
        "retry_due_video_ids": retry_due,
        "all_videos_terminal": (
            bool(coverage.get("full_profile_archive"))
            and coverage.get("profile_unique_videos") == total
            and not missing_ledger_ids
            and terminal == total
        ),
        "repo_build_id": repo_manifest.get("build_id"),
        "installed_build_id": installed_manifest.get("build_id"),
        "installed_matches_repo": bool(
            repo_manifest.get("build_id")
            and repo_manifest.get("build_id")
            == installed_manifest.get("build_id")
        ),
    }


def bilibili_next_action(status):
    if not status.get("available"):
        return None
    stages = status.get("stage_counts", {})
    if stages.get("blocked_auth"):
        return (
            "Refresh the Bilibili browser authentication, then resume the "
            "blocked BVIDs with process_bilibili_candidates.py --force."
        )
    if (
        stages.get("metadata_pending")
        or stages.get("metadata_ready")
        or stages.get("metadata_verification_failed")
        or stages.get("acquisition_failed")
    ):
        return "Resume required Bilibili metadata verification and media acquisition."
    if stages.get("review_pending"):
        return "Confirm the uncollected Bilibili videos before admitting or excluding them."
    if stages.get("downloaded") or stages.get("transcription_failed"):
        return "Resume the checkpointed Bilibili transcription batch."
    if stages.get("transcription_quarantined"):
        return (
            "Fix the isolated media or transcription environment, then explicitly "
            "retry selected BVIDs with batch_transcribe_directory.py --force "
            "--video-id BVID."
        )
    if stages.get("transcribed_waiting_release"):
        return "Build the Bilibili knowledge generation and run release regressions."
    if status.get("all_videos_terminal") and not status.get("installed_matches_repo"):
        return (
            "Merge the validated PR through protected checks, then atomically "
            "install the merged Skill build."
        )
    return None


def main():
    parser = argparse.ArgumentParser(description="Print a concise Liu Hui Skill pipeline status report.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args()

    video_index = load_json(INDEX_PATH)
    teaching = load_json(TEACHING_PATH)
    queue = load_json(QUEUE_PATH)
    knowledge = load_json(KNOWLEDGE_PATH)
    update_report = load_json(REPORT_PATH) if REPORT_PATH.exists() else None

    validate_queue_statuses(queue["items"])
    project_status = derive_project_status(video_index, teaching, knowledge)
    latest = project_status["latest_ready_video"]
    failures = failed_queue_items(queue)
    bili_status = bilibili_status()
    report = {
        **project_status,
        "bilibili": bili_status,
        "queue_counts": queue["counts"],
        "failed_queue_items": failures,
        "latest_ready_video": {
            "video_id": latest["video_id"],
            "title": latest["title"],
            "url": latest["url"],
        },
        "last_update_check": {
            "path": relative(REPORT_PATH),
            "observed": update_report.get("observed") if update_report else None,
            "new": update_report.get("new") if update_report else None,
            "teaching": update_report.get("teaching") if update_report else None,
            "excluded": update_report.get("excluded") if update_report else None,
            "applied": bool(update_report.get("applied")) if update_report else False,
        },
        "next_action": (
            bilibili_next_action(bili_status)
            or next_action(queue, update_report)
        ),
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    print("Liu Hui Badminton Skill pipeline status")
    print(f"- Public videos collected: {report['public_videos_collected']}")
    print(f"- Excluded non-teaching/ads/equipment: {report['excluded_non_teaching_ads_equipment']}")
    print(f"- Pending review or processing: {report['pending_human_review_or_processing']}")
    print(f"- Ready teaching videos: {report['ready_teaching_videos']}")
    print(f"- Processed pipeline videos: {report['processed_pipeline_videos']}")
    print(f"- Queue counts: {json.dumps(report['queue_counts'], ensure_ascii=False)}")
    print(
        "- Latest ready video: "
        f"{latest['video_id']} {latest['title']} {latest['url']}"
    )
    if update_report:
        print(
            "- Last update check: "
            f"observed={update_report['observed']}, new={update_report['new']}, "
            f"teaching={update_report['teaching']}, excluded={update_report['excluded']}"
        )
    print(f"- Failed queue items: {len(failures)}")
    bilibili = report["bilibili"]
    if bilibili.get("available"):
        print(
            "- Bilibili current profile: "
            f"terminal={bilibili['terminal_videos']}/"
            f"{bilibili['profile_unique_videos']}, "
            f"pending={bilibili['pending_videos']}, "
            f"full_archive={bilibili['full_profile_archive']}"
        )
        print(
            "- Bilibili stages: "
            f"{json.dumps(bilibili['stage_counts'], ensure_ascii=False)}"
        )
        print(
            "- Installed Skill matches repo: "
            f"{bilibili['installed_matches_repo']}"
        )
    print(f"- Next action: {report['next_action']}")


if __name__ == "__main__":
    main()
