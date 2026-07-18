#!/usr/bin/env python3
"""Build a deterministic manifest for the portable Skill release."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from project_artifacts import atomic_write_bundle, derive_project_status


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "liuhui-badminton-coach"
OUTPUT_PATH = ROOT / "data" / "knowledge" / "build_manifest.json"
SKILL_OUTPUT_PATH = SKILL_ROOT / "references" / "build-manifest.json"
VIDEO_ID_PATTERN = re.compile(r"\d{18,20}")
SELF_PATHS = {
    "references/build-manifest.json",
}
SKIPPED_PARTS = {".DS_Store", "__pycache__"}


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def sha256_file(path):
    return sha256_bytes(Path(path).read_bytes())


def canonical_json_bytes(payload):
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def load_json(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def skill_artifacts():
    artifacts = []
    for path in sorted(SKILL_ROOT.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(SKILL_ROOT).as_posix()
        if relative in SELF_PATHS:
            continue
        if any(part in SKIPPED_PARTS for part in path.relative_to(SKILL_ROOT).parts):
            continue
        if path.suffix in {".pyc", ".pyo"}:
            continue
        artifacts.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return artifacts


def rule_artifacts():
    paths = [
        "config/answer_modality_rules.json",
        "config/answer_selection_rules.json",
        "config/douyin_classification_rules.json",
        "config/feedback_rules.json",
        "config/knowledge_quality_rules.json",
        "config/practice_plan_rules.json",
        "config/retrieval_rules.json",
    ]
    rules = []
    for relative in paths:
        payload = load_json(relative)
        rules.append(
            {
                "path": relative,
                "version": payload.get("version"),
                "sha256": sha256_file(ROOT / relative),
            }
        )
    return rules


def link_integrity(video_index, knowledge):
    indexed = video_index["videos"]
    indexed_ids = [str(item["video_id"]) for item in indexed]
    invalid = []
    for item in indexed:
        video_id = str(item["video_id"])
        expected = f"https://www.douyin.com/video/{video_id}"
        if not VIDEO_ID_PATTERN.fullmatch(video_id) or item.get("url") != expected:
            invalid.append(video_id)
    knowledge_invalid = []
    for item in knowledge["videos"]:
        video_id = str(item["video_id"])
        if item.get("url") != f"https://www.douyin.com/video/{video_id}":
            knowledge_invalid.append(video_id)
    return {
        "indexed_url_count": len(indexed),
        "unique_indexed_url_count": len(set(indexed_ids)),
        "knowledge_url_count": len(knowledge["videos"]),
        "canonical_syntax_invalid_video_ids": sorted(set(invalid)),
        "knowledge_url_invalid_video_ids": sorted(set(knowledge_invalid)),
        "network_sample": {
            "status": "not_run_in_deterministic_build",
            "command": "python3 scripts/check_video_links.py --network",
        },
    }


def build_manifest_payload():
    video_index = load_json("data/douyin_video_index.json")
    teaching_filter = load_json("data/douyin_teaching_filtered.json")
    knowledge = load_json("data/knowledge/douyin_knowledge_base.json")
    status = derive_project_status(video_index, teaching_filter, knowledge)
    ready = [
        item for item in knowledge["videos"] if item["processing_status"] == "ready"
    ]
    visual = sum(item.get("confidence") == "visual_reviewed" for item in ready)
    payload = {
        "schema_version": 1,
        "skill_name": "liuhui-badminton-coach",
        "source_timestamps": {
            "douyin_collected_at": video_index.get("collected_at"),
            "knowledge_updated_at": knowledge.get("updated_at"),
        },
        "corpus": {
            "public_video_count": status["public_videos_collected"],
            "processed_video_count": status["processed_pipeline_videos"],
            "ready_video_count": status["ready_teaching_videos"],
            "transcript_backed_ready_count": len(ready) - visual,
            "visual_reviewed_ready_count": visual,
            "pending_count": status["pending_human_review_or_processing"],
            "excluded_count": status["excluded_non_teaching_ads_equipment"],
            "latest_ready_video": status["latest_ready_video"],
            "source_hashes": {
                relative: sha256_file(ROOT / relative)
                for relative in [
                    "data/douyin_video_index.json",
                    "data/douyin_teaching_filtered.json",
                    "data/douyin_classification_ledger.json",
                    "data/knowledge/douyin_knowledge_base.json",
                    "data/knowledge/retrieval_index.json",
                    "data/knowledge/topic_index.json",
                    "data/knowledge/knowledge_graph_summary.json",
                ]
            },
        },
        "rules": rule_artifacts(),
        "link_integrity": link_integrity(video_index, knowledge),
        "skill_artifacts": skill_artifacts(),
        "reproducibility": {
            "canonical_json": "utf8_sorted_keys_compact_separators_newline",
            "volatile_wall_clock_fields": False,
            "manifest_self_hash_excluded": True,
        },
    }
    payload["build_id"] = sha256_bytes(canonical_json_bytes(payload))
    return payload


def manifest_bytes():
    return canonical_json_bytes(build_manifest_payload())


def write_manifest():
    content = manifest_bytes()
    atomic_write_bundle({OUTPUT_PATH: content, SKILL_OUTPUT_PATH: content})
    return json.loads(content)


def main():
    parser = argparse.ArgumentParser(
        description="Build or verify the deterministic Skill build manifest."
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = manifest_bytes()
    if args.check:
        stale = [
            str(path.relative_to(ROOT))
            for path in [OUTPUT_PATH, SKILL_OUTPUT_PATH]
            if not path.exists() or path.read_bytes() != expected
        ]
        if stale:
            raise SystemExit("Stale build manifest: " + ", ".join(stale))
        payload = json.loads(expected)
    else:
        payload = write_manifest()
    print(
        json.dumps(
            {
                "build_id": payload["build_id"],
                "ready_video_count": payload["corpus"]["ready_video_count"],
                "skill_artifact_count": len(payload["skill_artifacts"]),
                "canonical_link_errors": len(
                    payload["link_integrity"][
                        "canonical_syntax_invalid_video_ids"
                    ]
                ),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
