#!/usr/bin/env python3
import argparse
import json
from collections import Counter
from pathlib import Path

from douyin_pipeline import (
    classify_video,
    commit_json_transaction,
    compute_status_counts,
    load_classification_rules,
    now_iso,
    write_json,
)


ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "data" / "douyin_video_index.json"
FILTERED_PATH = ROOT / "data" / "douyin_teaching_filtered.json"
QUEUE_PATH = ROOT / "data" / "processing" / "douyin_queue.json"
KNOWLEDGE_PATH = ROOT / "data" / "knowledge" / "douyin_knowledge_base.json"
REVIEW_PATH = ROOT / "data" / "review" / "visual_review_annotations.json"
RULES_PATH = ROOT / "config" / "douyin_classification_rules.json"
LEDGER_PATH = ROOT / "data" / "douyin_classification_ledger.json"
REPORT_PATH = ROOT / "output" / "classification-drift-report.json"
TRANSACTION_PATH = ROOT / "data" / "processing" / ".classification-migration.json"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def has_transcript_teaching_evidence(record):
    if not record:
        return False
    quality = (record.get("quality") or {}).get("automatic_evidence") or {}
    return quality.get("passed") is True or record.get("confidence") in {
        "curated",
        "reviewed_transcript",
        "visual_reviewed",
    }


def effective_decision(automatic, was_kept, knowledge_record=None, review=None):
    decision = automatic["decision"]
    reason = automatic["decision_reason"]
    action = "accept_current_rules"

    review_status = (review or {}).get("review_status")
    if review_status == "approved":
        return "保留：教学", "既有用户复核确认教学内容", "preserve_reviewed_keep"
    if review_status == "not_teaching":
        return "排除：非教学", "既有用户复核确认非教学", "preserve_reviewed_exclusion"
    if review_status == "low_value":
        return "排除：非教学", "既有用户复核确认教学价值不足", "preserve_reviewed_exclusion"
    if review_status == "needs_correction":
        return "待复核：历史分类漂移", "既有复核要求修正", "preserve_review_queue"

    evidence_backed = has_transcript_teaching_evidence(knowledge_record)
    if not was_kept:
        return decision, reason, action
    if decision == "待复核：教学夹带推广":
        signals = automatic.get("classification_signals", {})
        if evidence_backed and signals.get("ad_strong_hashtag_only"):
            return (
                "保留：教学",
                "品牌只出现在标签中，且历史转写已通过教学证据门槛",
                "preserve_hashtag_only_transcript_teaching",
            )
        return decision, reason, "route_mixed_promotion_to_review"
    if decision == "排除：广告/器材推广" and evidence_backed:
        return (
            "待复核：教学夹带推广",
            "历史转写含教学证据，但当前规则识别出广告或器材推广",
            "route_evidence_backed_promotion_to_review",
        )
    if decision in {"排除：非教学", "待复核：仅通用教学标签"} and evidence_backed:
        return (
            "保留：教学",
            "历史转写已通过教学证据门槛，标题规则不得单独推翻",
            "preserve_transcript_backed_teaching",
        )
    return decision, reason, action


def migrate_catalog(index, previous_filtered, queue, knowledge, reviews, rules):
    migrated_at = now_iso()
    previous_kept = {
        str(item["video_id"]): item for item in previous_filtered.get("videos", [])
    }
    knowledge_by_id = {
        str(item["video_id"]): item for item in knowledge.get("videos", [])
    }
    reviews_by_id = {
        str(item["video_id"]): item
        for item in reviews.get("items", [])
        if item.get("review_status") != "pending"
    }
    ledger_items = []
    drift = []
    for video in index["videos"]:
        video_id = str(video["video_id"])
        automatic = classify_video(video, rules)
        previous_decision = (
            previous_kept.get(video_id, {}).get("decision")
            if video_id in previous_kept
            else "legacy_excluded_unknown"
        )
        decision, reason, action = effective_decision(
            automatic,
            video_id in previous_kept,
            knowledge_by_id.get(video_id),
            reviews_by_id.get(video_id),
        )
        item = {
            **automatic,
            "automatic_decision": automatic["decision"],
            "automatic_decision_reason": automatic["decision_reason"],
            "previous_decision": previous_decision,
            "decision": decision,
            "decision_reason": reason,
            "migration_action": action,
            "classified_at": migrated_at,
        }
        ledger_items.append(item)
        if previous_decision != decision:
            drift.append(
                {
                    "video_id": video_id,
                    "title": video["title"],
                    "previous_decision": previous_decision,
                    "automatic_decision": automatic["decision"],
                    "effective_decision": decision,
                    "migration_action": action,
                }
            )

    decision_counts = Counter(item["decision"] for item in ledger_items)
    rules_identity = rules["_rules_identity"]
    ledger = {
        "version": 1,
        "generated_at": migrated_at,
        "source": str(INDEX_PATH.relative_to(ROOT)),
        "classification_rules": rules_identity,
        "counts": dict(sorted(decision_counts.items())),
        "videos": ledger_items,
    }
    kept = [item for item in ledger_items if item["decision"] == "保留：教学"]
    filtered = {
        "generated_at": migrated_at,
        "source_profile": previous_filtered.get("source_profile"),
        "classification_rules": rules_identity,
        "methodology": previous_filtered.get("methodology", []),
        "counts": {
            "total": len(ledger_items),
            "kept_teaching": len(kept),
            "review": sum(item["decision"].startswith("待复核") for item in ledger_items),
            "excluded_ads": decision_counts["排除：广告/器材推广"],
            "excluded_non_teaching": decision_counts["排除：非教学"],
        },
        "videos": kept,
    }

    ledger_by_id = {item["video_id"]: item for item in ledger_items}
    queue_items = []
    for old_item in queue["items"]:
        item = dict(old_item)
        classification = ledger_by_id.get(str(item["video_id"]))
        if classification:
            item.update(
                {
                    "classification_decision": classification["decision"],
                    "classification_reason": classification["decision_reason"],
                    "classification_rules_version": rules_identity["version"],
                    "classification_rules_hash": rules_identity["sha256"],
                    "classified_at": migrated_at,
                }
            )
            if classification.get("primary_category"):
                item["category"] = classification["primary_category"]
            if classification.get("tags"):
                item["tags"] = classification["tags"]
        queue_items.append(item)
    queue_payload = {
        **queue,
        "updated_at": migrated_at,
        "classification_rules": rules_identity,
        "counts": compute_status_counts(queue_items),
        "items": queue_items,
    }
    report = {
        "generated_at": migrated_at,
        "classification_rules": rules_identity,
        "catalog_videos": len(ledger_items),
        "previous_kept": len(previous_kept),
        "effective_counts": dict(sorted(decision_counts.items())),
        "drift_count": len(drift),
        "drift": drift,
    }
    return ledger, filtered, queue_payload, report


def main():
    parser = argparse.ArgumentParser(
        description="Reclassify the full historical Douyin catalog with versioned rules."
    )
    parser.add_argument("--rules", type=Path, default=RULES_PATH)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Atomically write the classification ledger, filtered list, and queue metadata.",
    )
    args = parser.parse_args()
    rules = load_classification_rules(args.rules)
    payloads = migrate_catalog(
        load_json(INDEX_PATH),
        load_json(FILTERED_PATH),
        load_json(QUEUE_PATH),
        load_json(KNOWLEDGE_PATH),
        load_json(REVIEW_PATH),
        rules,
    )
    ledger, filtered, queue, report = payloads
    report_path = args.report if args.report.is_absolute() else ROOT / args.report
    write_json(report_path, {**report, "applied": args.apply})
    if args.apply:
        commit_json_transaction(
            {
                LEDGER_PATH: ledger,
                FILTERED_PATH: filtered,
                QUEUE_PATH: queue,
            },
            TRANSACTION_PATH,
        )
    print(
        json.dumps(
            {
                "applied": args.apply,
                "catalog_videos": report["catalog_videos"],
                "drift_count": report["drift_count"],
                "effective_counts": report["effective_counts"],
                "report": str(report_path.relative_to(ROOT)),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
