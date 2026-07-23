#!/usr/bin/env python3
"""Shared status accounting and derived-artifact synchronization."""

import json
import os
import re
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SKILL_REFERENCE_PATHS = (
    (
        Path("data/knowledge/douyin_knowledge_base.json"),
        Path("skills/liuhui-badminton-coach/references/knowledge-base.json"),
    ),
    (
        Path("data/knowledge/knowledge_graph_summary.json"),
        Path("skills/liuhui-badminton-coach/references/topic-map.json"),
    ),
    (
        Path("data/knowledge/retrieval_index.json"),
        Path("skills/liuhui-badminton-coach/references/retrieval-index.json"),
    ),
    (
        Path("config/retrieval_rules.json"),
        Path("skills/liuhui-badminton-coach/references/retrieval-rules.json"),
    ),
    (
        Path("config/answer_modality_rules.json"),
        Path("skills/liuhui-badminton-coach/references/answer-modality-rules.json"),
    ),
    (
        Path("config/answer_selection_rules.json"),
        Path("skills/liuhui-badminton-coach/references/answer-selection-rules.json"),
    ),
    (
        Path("config/diagnostic_answer_rules.json"),
        Path("skills/liuhui-badminton-coach/references/diagnostic-answer-rules.json"),
    ),
    (
        Path("config/reviewed_evidence_signals.json"),
        Path("skills/liuhui-badminton-coach/references/reviewed-evidence-signals.json"),
    ),
    (
        Path("config/practice_plan_rules.json"),
        Path("skills/liuhui-badminton-coach/references/practice-plan-rules.json"),
    ),
    (
        Path("config/feedback_rules.json"),
        Path("skills/liuhui-badminton-coach/references/feedback-rules.json"),
    ),
    (
        Path("config/feedback_signals.json"),
        Path("skills/liuhui-badminton-coach/references/feedback-signals.json"),
    ),
    (
        Path("data/knowledge/build_manifest.json"),
        Path("skills/liuhui-badminton-coach/references/build-manifest.json"),
    ),
)

READY_STATUSES = {"ready"}
PENDING_KNOWLEDGE_STATUSES = {"needs_visual_review", "needs_correction"}
EXCLUDED_KNOWLEDGE_STATUSES = {"not_teaching", "low_value"}
ALLOWED_KNOWLEDGE_STATUSES = (
    READY_STATUSES | PENDING_KNOWLEDGE_STATUSES | EXCLUDED_KNOWLEDGE_STATUSES
)
VIDEO_ID_PATTERN = re.compile(r"\d{18,20}")
SOURCE_TYPE_PATTERN = re.compile(r"[a-z][a-z0-9_]*")


class ArtifactConsistencyError(ValueError):
    """Raised when source artifacts cannot form one consistent project state."""


def validate_evidence_records(records, label="Knowledge base"):
    """Validate source-neutral evidence identity and clip provenance."""

    evidence_ids = []
    for record in records:
        missing = [
            field
            for field in [
                "evidence_id",
                "source_type",
                "canonical_url",
                "parent_source_id",
                "clip_start_seconds",
                "clip_end_seconds",
            ]
            if field not in record
        ]
        if missing:
            raise ArtifactConsistencyError(
                f"{label} record is missing evidence fields: {', '.join(missing)}"
            )
        evidence_id = record["evidence_id"]
        source_type = record["source_type"]
        canonical_url = record["canonical_url"]
        if not isinstance(evidence_id, str) or not evidence_id.strip():
            raise ArtifactConsistencyError(f"{label} has an empty evidence ID")
        if not isinstance(source_type, str) or not SOURCE_TYPE_PATTERN.fullmatch(
            source_type
        ):
            raise ArtifactConsistencyError(
                f"{label} evidence {evidence_id!r} has an invalid source type"
            )
        if not isinstance(canonical_url, str) or not re.match(
            r"https?://", canonical_url
        ):
            raise ArtifactConsistencyError(
                f"{label} evidence {evidence_id!r} has an invalid canonical URL"
            )
        parent_source_id = record["parent_source_id"]
        start = record["clip_start_seconds"]
        end = record["clip_end_seconds"]
        if parent_source_id is not None and (
            not isinstance(parent_source_id, str) or not parent_source_id.strip()
        ):
            raise ArtifactConsistencyError(
                f"{label} evidence {evidence_id!r} has an invalid parent source"
            )
        if (start is None) != (end is None):
            raise ArtifactConsistencyError(
                f"{label} evidence {evidence_id!r} has a partial clip range"
            )
        if start is not None and (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, (int, float))
            or not isinstance(end, (int, float))
            or start < 0
            or end <= start
        ):
            raise ArtifactConsistencyError(
                f"{label} evidence {evidence_id!r} has an invalid clip range"
            )
        if source_type.endswith("_clip") and (
            parent_source_id is None or start is None
        ):
            raise ArtifactConsistencyError(
                f"{label} clip {evidence_id!r} is missing parent provenance"
            )
        if source_type == "douyin_video":
            video_id = str(record.get("video_id", ""))
            expected_url = f"https://www.douyin.com/video/{video_id}"
            if (
                evidence_id != video_id
                or not VIDEO_ID_PATTERN.fullmatch(video_id)
                or canonical_url != expected_url
                or record.get("url") != expected_url
                or parent_source_id is not None
                or start is not None
            ):
                raise ArtifactConsistencyError(
                    f"{label} Douyin evidence {evidence_id!r} is not canonical"
                )
        evidence_ids.append(evidence_id)
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ArtifactConsistencyError(f"{label} contains duplicate evidence IDs")
    return evidence_ids


def _record_ids(records, label):
    ids = [str(record["video_id"]) for record in records]
    if len(ids) != len(set(ids)):
        raise ArtifactConsistencyError(f"{label} contains duplicate video IDs")
    for record, video_id in zip(records, ids):
        if not VIDEO_ID_PATTERN.fullmatch(video_id):
            raise ArtifactConsistencyError(
                f"{label} contains an invalid video ID: {video_id!r}"
            )
        expected_url = f"https://www.douyin.com/video/{video_id}"
        if record.get("url") != expected_url:
            raise ArtifactConsistencyError(
                f"{label} video {video_id} does not use its canonical Douyin URL"
            )
    return ids


def _non_negative_count(counts, key):
    value = counts.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ArtifactConsistencyError(f"Teaching-filter count {key!r} is invalid")
    return value


def derive_project_status(video_index, teaching_filter, knowledge):
    """Return a reconciled, mutually exclusive status partition for all videos."""

    index_ids = _record_ids(video_index.get("videos", []), "Video index")
    teaching_ids = _record_ids(
        teaching_filter.get("videos", []), "Teaching-filter output"
    )
    knowledge_ids = _record_ids(knowledge.get("videos", []), "Knowledge base")

    counts = teaching_filter.get("counts", {})
    collected = len(index_ids)
    filter_total = _non_negative_count(counts, "total")
    kept_teaching = _non_negative_count(counts, "kept_teaching")
    filter_review = _non_negative_count(counts, "review")
    excluded_ads = _non_negative_count(counts, "excluded_ads")
    excluded_non_teaching = _non_negative_count(counts, "excluded_non_teaching")

    if filter_total != collected:
        raise ArtifactConsistencyError(
            "Teaching-filter total does not match the collected video index"
        )
    if kept_teaching != len(teaching_ids):
        raise ArtifactConsistencyError(
            "Teaching-filter kept count does not match its retained video records"
        )
    if filter_total != (
        kept_teaching + filter_review + excluded_ads + excluded_non_teaching
    ):
        raise ArtifactConsistencyError(
            "Teaching-filter counts do not form a complete partition"
        )

    index_id_set = set(index_ids)
    teaching_id_set = set(teaching_ids)
    knowledge_id_set = set(knowledge_ids)
    if not teaching_id_set.issubset(index_id_set):
        raise ArtifactConsistencyError(
            "Teaching-filter output references videos missing from the index"
        )
    if not knowledge_id_set.issubset(index_id_set):
        raise ArtifactConsistencyError(
            "Knowledge base references videos missing from the collected index"
        )

    status_counts = {status: 0 for status in sorted(ALLOWED_KNOWLEDGE_STATUSES)}
    ready_by_id = {}
    for video in knowledge.get("videos", []):
        status = video.get("processing_status")
        if status not in ALLOWED_KNOWLEDGE_STATUSES:
            raise ArtifactConsistencyError(
                f"Knowledge video {video['video_id']} has unknown status: {status!r}"
            )
        status_counts[status] += 1
        if status in READY_STATUSES:
            ready_by_id[str(video["video_id"])] = video

    ready = sum(status_counts[status] for status in READY_STATUSES)
    ready_ids = {
        str(video["video_id"])
        for video in knowledge.get("videos", [])
        if video.get("processing_status") in READY_STATUSES
    }
    if not ready_ids.issubset(teaching_id_set):
        raise ArtifactConsistencyError(
            "Ready knowledge videos must be retained teaching candidates"
        )
    knowledge_pending_ids = {
        str(video["video_id"])
        for video in knowledge.get("videos", [])
        if video.get("processing_status") in PENDING_KNOWLEDGE_STATUSES
    }
    knowledge_excluded_ids = {
        str(video["video_id"])
        for video in knowledge.get("videos", [])
        if video.get("processing_status") in EXCLUDED_KNOWLEDGE_STATUSES
    }
    knowledge_pending = len(knowledge_pending_ids & teaching_id_set)
    post_pipeline_excluded = len(knowledge_excluded_ids & teaching_id_set)
    pipeline_pending = len(teaching_id_set - knowledge_id_set)
    pre_pipeline_excluded = excluded_ads + excluded_non_teaching
    excluded = pre_pipeline_excluded + post_pipeline_excluded
    pending = filter_review + pipeline_pending + knowledge_pending

    if collected != ready + pending + excluded:
        raise ArtifactConsistencyError(
            "Collected videos do not equal ready plus pending plus excluded videos"
        )
    if len(knowledge_ids) != sum(status_counts.values()):
        raise ArtifactConsistencyError(
            "Knowledge statuses do not form a complete partition"
        )

    latest_ready = next(
        (ready_by_id[video_id] for video_id in index_ids if video_id in ready_by_id),
        None,
    )
    if latest_ready is None:
        raise ArtifactConsistencyError("Knowledge base contains no ready teaching video")

    return {
        "public_videos_collected": collected,
        "excluded_non_teaching_ads_equipment": excluded,
        "pending_human_review_or_processing": pending,
        "ready_teaching_videos": ready,
        "processed_pipeline_videos": len(knowledge_ids),
        "kept_teaching_candidates": kept_teaching,
        "pre_pipeline_excluded": pre_pipeline_excluded,
        "post_pipeline_excluded": post_pipeline_excluded,
        "filter_review_pending": filter_review,
        "pipeline_processing_pending": pipeline_pending,
        "knowledge_review_pending": knowledge_pending,
        "knowledge_status_counts": status_counts,
        "accounting_consistent": True,
        "latest_ready_video": {
            "video_id": str(latest_ready["video_id"]),
            "title": latest_ready["title"],
            "url": latest_ready["url"],
        },
    }


def _stage_bytes(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
        temporary_path.chmod(mode)
        return temporary_path
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def atomic_write_bundle(payloads, replace_func=os.replace):
    """Replace several files as one rollback-capable local transaction."""

    normalized = {Path(path): bytes(data) for path, data in payloads.items()}
    originals = {
        path: path.read_bytes() if path.exists() else None for path in normalized
    }
    staged = {path: _stage_bytes(path, data) for path, data in normalized.items()}
    replaced = []
    try:
        for path, temporary_path in staged.items():
            replace_func(temporary_path, path)
            replaced.append(path)
    except Exception:
        for path in reversed(replaced):
            original = originals[path]
            if original is None:
                path.unlink(missing_ok=True)
            else:
                rollback_path = _stage_bytes(path, original)
                os.replace(rollback_path, path)
        raise
    finally:
        for temporary_path in staged.values():
            temporary_path.unlink(missing_ok=True)


def atomic_write_text(path, text):
    atomic_write_bundle({Path(path): text.encode("utf-8")})


def skill_reference_bytes(source_relative, source_bytes):
    """Build the portable Skill payload for a canonical reference source."""

    source_relative = Path(source_relative)
    if source_relative != Path("data/knowledge/douyin_knowledge_base.json"):
        return source_bytes
    payload = json.loads(source_bytes.decode("utf-8"))
    for video in payload.get("videos", []):
        video.pop("transcript_file", None)
    payload["transcript_files_bundled"] = False
    payload["runtime_transcript_segments_bundled"] = True
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def skill_reference_mismatches(root=ROOT):
    root = Path(root)
    mismatches = []
    for source_relative, destination_relative in SKILL_REFERENCE_PATHS:
        source = root / source_relative
        destination = root / destination_relative
        if not source.exists():
            raise FileNotFoundError(source)
        expected = skill_reference_bytes(source_relative, source.read_bytes())
        if not destination.exists() or expected != destination.read_bytes():
            mismatches.append(str(destination_relative))
    return mismatches


def sync_skill_references(root=ROOT, replace_func=os.replace):
    """Atomically synchronize every bundled Skill reference from canonical sources."""

    root = Path(root)
    payloads = {}
    changed = []
    for source_relative, destination_relative in SKILL_REFERENCE_PATHS:
        source = root / source_relative
        destination = root / destination_relative
        if not source.exists():
            raise FileNotFoundError(source)
        source_bytes = skill_reference_bytes(source_relative, source.read_bytes())
        if not destination.exists() or destination.read_bytes() != source_bytes:
            payloads[destination] = source_bytes
            changed.append(str(destination_relative))
    if payloads:
        atomic_write_bundle(payloads, replace_func=replace_func)
    remaining = skill_reference_mismatches(root)
    if remaining:
        raise ArtifactConsistencyError(
            "Skill reference synchronization failed: " + ", ".join(remaining)
        )
    return changed
