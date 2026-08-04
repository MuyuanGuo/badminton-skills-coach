#!/usr/bin/env python3
"""Report whether the committed knowledge pipeline needs maintainer attention."""

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from douyin_pipeline import QUEUE_STATUSES, validate_queue_statuses


ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "data" / "douyin_video_index.json"
KNOWLEDGE_PATH = ROOT / "data" / "knowledge" / "douyin_knowledge_base.json"
QUEUE_PATH = ROOT / "data" / "processing" / "douyin_queue.json"
DISCOVERY_PATH = ROOT / "data" / "processing" / "douyin_discovery_state.json"
FORWARD_TEST_PATH = ROOT / "data" / "evaluation" / "forward_test_results.json"
BILIBILI_ARCHIVE_PATH = (
    ROOT / "data" / "snapshots" / "bilibili_profile_full_archive.json"
)
BILIBILI_KNOWLEDGE_PATH = ROOT / "data" / "knowledge" / "bilibili_knowledge_base.json"
BILIBILI_QUEUE_PATH = ROOT / "data" / "processing" / "bilibili_queue.json"
BUILD_MANIFEST_PATH = ROOT / "data" / "knowledge" / "build_manifest.json"
INSTALLED_MANIFEST_PATH = (
    Path.home()
    / ".codex"
    / "skills"
    / "liuhui-badminton-coach"
    / "references"
    / "build-manifest.json"
)


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def parse_timestamp(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is missing")
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if len(normalized) == 10:
        return parsed.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def age_days(value, field, now):
    age = (now - parse_timestamp(value, field)).total_seconds() / 86400
    if age < -0.01:
        raise ValueError(f"{field} is unexpectedly in the future")
    return round(max(age, 0), 2)


def latest_forward_test_date(payload):
    dates = []
    for section in ("results", "unseen_rounds"):
        for item in payload.get(section, []):
            value = item.get("tested_at")
            if value:
                dates.append(value)
    if not dates:
        return None
    return max(dates)


def build_report(
    *,
    index,
    knowledge,
    queue,
    discovery,
    forward_tests,
    bilibili_archive=None,
    bilibili_knowledge=None,
    bilibili_queue=None,
    repo_manifest=None,
    installed_manifest=None,
    now=None,
    profile_max_age_days=7,
    knowledge_max_age_days=30,
    forward_test_max_age_days=30,
):
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    validate_queue_statuses(queue["items"])

    profile_age = age_days(index.get("collected_at"), "index.collected_at", now)
    knowledge_age = age_days(knowledge.get("updated_at"), "knowledge.updated_at", now)
    forward_date = latest_forward_test_date(forward_tests)
    forward_age = (
        age_days(forward_date, "forward_tests.tested_at", now)
        if forward_date
        else None
    )

    failure_statuses = {
        status for status, metadata in QUEUE_STATUSES.items() if metadata.get("failure")
    }
    failed_items = [
        item["video_id"]
        for item in queue["items"]
        if item.get("status") in failure_statuses
    ]
    ready_statuses = {"classified_teaching", "pending", "media_ready"}
    pending_items = [
        item["video_id"]
        for item in queue["items"]
        if item.get("status") in ready_statuses
    ]
    review_pending = int(discovery.get("counts", {}).get("review_pending", 0))

    bilibili_archive = bilibili_archive or {}
    bilibili_knowledge = bilibili_knowledge or {}
    bilibili_queue = bilibili_queue or {"items": []}
    bilibili_profile_age = (
        age_days(
            bilibili_archive.get("generated_at"),
            "bilibili_archive.generated_at",
            now,
        )
        if bilibili_archive
        else None
    )
    bilibili_knowledge_age = (
        age_days(
            bilibili_knowledge.get("updated_at"),
            "bilibili_knowledge.updated_at",
            now,
        )
        if bilibili_knowledge
        else None
    )
    bilibili_pending = [
        str(item.get("video_id") or "")
        for item in bilibili_queue.get("items", [])
        if item.get("status") not in {
            "transcribed",
            "transcription_quarantined",
            "unavailable",
        }
    ]
    repo_build_id = (repo_manifest or {}).get("build_id")
    installed_build_id = (installed_manifest or {}).get("build_id")

    checks = [
        {
            "id": "douyin_profile_snapshot_freshness",
            "status": "overdue" if profile_age > profile_max_age_days else "healthy",
            "age_days": profile_age,
            "max_age_days": profile_max_age_days,
            "source": "data/douyin_video_index.json",
        },
        {
            "id": "douyin_knowledge_build_freshness",
            "status": "overdue" if knowledge_age > knowledge_max_age_days else "healthy",
            "age_days": knowledge_age,
            "max_age_days": knowledge_max_age_days,
            "source": "data/knowledge/douyin_knowledge_base.json",
        },
        {
            "id": "forward_tests",
            "status": (
                "overdue"
                if forward_age is None or forward_age > forward_test_max_age_days
                else "healthy"
            ),
            "age_days": forward_age,
            "max_age_days": forward_test_max_age_days,
            "source": "data/evaluation/forward_test_results.json",
        },
        {
            "id": "douyin_processing_queue_state",
            "status": "attention" if pending_items or failed_items else "healthy",
            "pending_count": len(pending_items),
            "failed_count": len(failed_items),
            "pending_video_ids": pending_items,
            "failed_video_ids": failed_items,
            "source": "data/processing/douyin_queue.json",
        },
        {
            "id": "douyin_classification_review_state",
            "status": "attention" if review_pending else "healthy",
            "pending_count": review_pending,
            "source": "data/processing/douyin_discovery_state.json",
        },
    ]
    if bilibili_archive:
        checks.extend(
            [
                {
                    "id": "bilibili_profile_snapshot_freshness",
                    "status": (
                        "overdue"
                        if bilibili_profile_age > profile_max_age_days
                        else "healthy"
                    ),
                    "age_days": bilibili_profile_age,
                    "max_age_days": profile_max_age_days,
                    "source": "data/snapshots/bilibili_profile_full_archive.json",
                },
                {
                    "id": "bilibili_knowledge_build_freshness",
                    "status": (
                        "overdue"
                        if bilibili_knowledge_age > knowledge_max_age_days
                        else "healthy"
                    ),
                    "age_days": bilibili_knowledge_age,
                    "max_age_days": knowledge_max_age_days,
                    "source": "data/knowledge/bilibili_knowledge_base.json",
                },
                {
                    "id": "bilibili_processing_queue_state",
                    "status": "attention" if bilibili_pending else "healthy",
                    "pending_count": len(bilibili_pending),
                    "pending_video_ids": bilibili_pending,
                    "source": "data/processing/bilibili_queue.json",
                },
            ]
        )
    if installed_build_id:
        checks.append(
            {
                "id": "installed_skill_build_alignment",
                "status": (
                    "healthy"
                    if repo_build_id and repo_build_id == installed_build_id
                    else "attention"
                ),
                "pending_count": int(repo_build_id != installed_build_id),
                "source": "installed Skill build manifest",
            }
        )

    statuses = {item["status"] for item in checks}
    overall = "overdue" if "overdue" in statuses else (
        "attention" if "attention" in statuses else "healthy"
    )
    if profile_age > profile_max_age_days:
        next_action = "Capture a fresh Douyin profile snapshot and run check_douyin_updates.py."
    elif bilibili_profile_age is not None and bilibili_profile_age > profile_max_age_days:
        next_action = "Capture a fresh Bilibili profile snapshot and run check_bilibili_updates.py."
    elif failed_items:
        next_action = "Inspect failed queue items, then rerun process_douyin_ready_batch.py."
    elif pending_items:
        next_action = "Process queued teaching videos with process_douyin_ready_batch.py."
    elif review_pending:
        next_action = "Resolve pending discovery classifications before processing more videos."
    elif bilibili_pending:
        next_action = "Resume pending Bilibili items with run_bilibili_update_pipeline.py."
    elif forward_age is None or forward_age > forward_test_max_age_days:
        next_action = "Run and record a fresh blind forward-test round."
    elif knowledge_age > knowledge_max_age_days:
        next_action = "Run the full update pipeline and review the rebuilt knowledge artifacts."
    elif bilibili_knowledge_age is not None and bilibili_knowledge_age > knowledge_max_age_days:
        next_action = "Rebuild and review the Bilibili knowledge artifacts."
    elif installed_build_id and installed_build_id != repo_build_id:
        next_action = "Reinstall the Skill so the installed build matches the repository build."
    else:
        next_action = "No maintenance action is currently required."

    return {
        "schema_version": 1,
        "checked_at": now.isoformat(),
        "status": overall,
        "checks": checks,
        "next_action": next_action,
    }


def markdown_summary(report):
    icons = {"healthy": "✅", "attention": "⚠️", "overdue": "❌"}
    lines = [
        "## Knowledge maintenance health",
        "",
        f"Overall: {icons[report['status']]} **{report['status']}**",
        "",
        "| Check | Status | Detail |",
        "| --- | --- | --- |",
    ]
    for item in report["checks"]:
        if "age_days" in item:
            age = "missing" if item["age_days"] is None else f"{item['age_days']} days"
            detail = f"age {age}; limit {item['max_age_days']} days"
        else:
            detail = f"pending {item['pending_count']}"
            if "failed_count" in item:
                detail += f"; failed {item['failed_count']}"
        lines.append(
            f"| `{item['id']}` | {icons[item['status']]} {item['status']} | {detail} |"
        )
    lines.extend(["", f"Next action: {report['next_action']}", ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-max-age-days", type=float, default=7)
    parser.add_argument("--knowledge-max-age-days", type=float, default=30)
    parser.add_argument("--forward-test-max-age-days", type=float, default=30)
    parser.add_argument(
        "--fail-on",
        choices=("never", "attention", "overdue"),
        default="never",
        help="Return exit code 1 at the selected severity.",
    )
    parser.add_argument("--github-summary", action="store_true")
    args = parser.parse_args()

    report = build_report(
        index=load_json(INDEX_PATH),
        knowledge=load_json(KNOWLEDGE_PATH),
        queue=load_json(QUEUE_PATH),
        discovery=load_json(DISCOVERY_PATH),
        forward_tests=load_json(FORWARD_TEST_PATH),
        bilibili_archive=load_json(BILIBILI_ARCHIVE_PATH),
        bilibili_knowledge=load_json(BILIBILI_KNOWLEDGE_PATH),
        bilibili_queue=load_json(BILIBILI_QUEUE_PATH),
        repo_manifest=load_json(BUILD_MANIFEST_PATH),
        installed_manifest=(
            load_json(INSTALLED_MANIFEST_PATH)
            if INSTALLED_MANIFEST_PATH.exists()
            else None
        ),
        profile_max_age_days=args.profile_max_age_days,
        knowledge_max_age_days=args.knowledge_max_age_days,
        forward_test_max_age_days=args.forward_test_max_age_days,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.github_summary and os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as handle:
            handle.write(markdown_summary(report))

    if args.fail_on == "overdue" and report["status"] == "overdue":
        return 1
    if args.fail_on == "attention" and report["status"] != "healthy":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
