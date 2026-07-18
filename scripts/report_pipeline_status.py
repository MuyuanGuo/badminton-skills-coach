#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

from douyin_pipeline import QUEUE_STATUSES, validate_queue_statuses
from project_artifacts import derive_project_status


ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "data" / "douyin_video_index.json"
TEACHING_PATH = ROOT / "data" / "douyin_teaching_filtered.json"
QUEUE_PATH = ROOT / "data" / "processing" / "douyin_queue.json"
KNOWLEDGE_PATH = ROOT / "data" / "knowledge" / "douyin_knowledge_base.json"
REPORT_PATH = ROOT / "output" / "douyin-update-report.json"


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
    report = {
        **project_status,
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
        "next_action": next_action(queue, update_report),
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
    print(f"- Next action: {report['next_action']}")


if __name__ == "__main__":
    main()
