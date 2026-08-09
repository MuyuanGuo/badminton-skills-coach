#!/usr/bin/env python3
"""Render the branch-specific bilingual README from a trusted profile."""

import argparse
import json
import re
from pathlib import Path

from project_artifacts import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
README_PATH = Path("README.md")
PROFILE_PATHS = {
    "main": Path(".github/readme-profiles/main.md.tmpl"),
    "develop": Path(".github/readme-profiles/develop.md.tmpl"),
}
TOKEN_PATTERN = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
FACT_KEYS = {
    "PROCESSED_PUBLIC_VIDEO_COUNT",
    "BILIBILI_CATALOG_COUNT",
    "BILIBILI_READY_COUNT",
    "BILIBILI_ISOLATED_COUNT",
    "BILIBILI_PENDING_COUNT",
    "READY_VIDEO_COUNT",
    "PRIMARY_VIDEO_COUNT",
    "SUPPLEMENTAL_VIDEO_COUNT",
    "TRANSCRIPT_VIDEO_COUNT",
    "TRANSCRIPT_ITEM_COUNT",
    "BOUNDED_VIDEO_COUNT",
    "BOUNDED_ITEM_COUNT",
    "VISUAL_VIDEO_COUNT",
    "ANSWER_QUALITY_CASE_COUNT",
    "QUERY_UNDERSTANDING_CASE_COUNT",
    "METAMORPHIC_VARIANT_COUNT",
    "HARD_NEGATIVE_COUNT",
    "LIVE_GENERATION_CASE_COUNT",
    "EVALUATION_SUITE_COUNT",
    "BASELINE_METRIC_COUNT",
    "PUBLIC_FEEDBACK_SIGNAL_COUNT",
    "BUILD_ID_SHORT",
}


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def evidence_counts(knowledge):
    ready = [
        item
        for item in knowledge.get("videos", [])
        if item.get("processing_status") == "ready"
    ]
    transcript = [
        item
        for item in ready
        if item.get("runtime_evidence_mode", "full_transcript")
        == "full_transcript"
    ]
    bounded = [
        item
        for item in ready
        if item.get("runtime_evidence_mode") == "bounded_note_windows"
    ]

    def evidence_items(items):
        return sum(
            len((item.get("teaching_note") or {}).get(field) or [])
            for item in items
            for field in ("key_evidence", "error_evidence", "action_cues")
        )

    return {
        "READY_VIDEO_COUNT": len(ready),
        "PRIMARY_VIDEO_COUNT": sum(
            item.get("answer_eligibility") == "primary" for item in ready
        ),
        "SUPPLEMENTAL_VIDEO_COUNT": sum(
            item.get("answer_eligibility") == "supplemental" for item in ready
        ),
        "TRANSCRIPT_VIDEO_COUNT": len(transcript),
        "TRANSCRIPT_ITEM_COUNT": f"{evidence_items(transcript):,}",
        "BOUNDED_VIDEO_COUNT": len(bounded),
        "BOUNDED_ITEM_COUNT": f"{evidence_items(bounded):,}",
        "VISUAL_VIDEO_COUNT": sum(
            item.get("runtime_evidence_mode") == "reviewed_visual_summary"
            or item.get("confidence") == "visual_reviewed"
            for item in ready
        ),
    }


def collect_readme_facts(root=ROOT):
    root = Path(root)
    knowledge = load_json(
        root / "data" / "knowledge" / "douyin_knowledge_base.json"
    )
    douyin_index = load_json(root / "data" / "douyin_video_index.json")
    bilibili_index = load_json(root / "data" / "bilibili_video_index.json")
    bilibili_ledger = load_json(
        root / "data" / "bilibili_classification_ledger.json"
    )
    answer_cases = load_json(
        root / "data" / "evaluation" / "answer_quality_cases.json"
    )
    feedback_signals = load_json(root / "config" / "feedback_signals.json")
    report = load_json(
        root / "data" / "evaluation" / "evaluation_report.json"
    )
    manifest = load_json(root / "data" / "knowledge" / "build_manifest.json")

    facts = evidence_counts(knowledge)
    bilibili_records = [
        item
        for item in knowledge.get("videos", [])
        if item.get("source_type") == "bilibili_video"
    ]
    bilibili_ready = sum(
        item.get("processing_status") == "ready" for item in bilibili_records
    )
    bilibili_policy_excluded = sum(
        item.get("decision") == "excluded_transcription_policy"
        for item in bilibili_ledger.get("videos", [])
    )
    bilibili_quality_isolated = sum(
        item.get("processing_status") != "ready" for item in bilibili_records
    )
    bilibili_isolated = bilibili_policy_excluded + bilibili_quality_isolated
    bilibili_total = len(bilibili_index.get("videos", []))
    evaluations = report.get("evaluations", {})
    query_understanding = evaluations.get("query_understanding", {})
    metamorphic = evaluations.get("metamorphic_robustness", {})
    live_generation = evaluations.get("live_generation", {})
    hard_negative_count = sum(
        len(item.get("gold", {}).get("irrelevant_video_ids", []))
        for item in answer_cases.get("cases", [])
    )
    facts.update(
        {
            "PROCESSED_PUBLIC_VIDEO_COUNT": (
                len(douyin_index.get("videos", [])) + bilibili_total
            ),
            "BILIBILI_CATALOG_COUNT": bilibili_total,
            "BILIBILI_READY_COUNT": bilibili_ready,
            "BILIBILI_ISOLATED_COUNT": bilibili_isolated,
            "BILIBILI_PENDING_COUNT": (
                bilibili_total - bilibili_ready - bilibili_isolated
            ),
            "ANSWER_QUALITY_CASE_COUNT": len(answer_cases.get("cases", [])),
            "QUERY_UNDERSTANDING_CASE_COUNT": query_understanding.get(
                "cases", 0
            ),
            "METAMORPHIC_VARIANT_COUNT": metamorphic.get("variants", 0),
            "HARD_NEGATIVE_COUNT": hard_negative_count,
            "LIVE_GENERATION_CASE_COUNT": live_generation.get(
                "critical_cases", 0
            ),
            "EVALUATION_SUITE_COUNT": report.get("summary", {}).get(
                "suites", 0
            ),
            "BASELINE_METRIC_COUNT": report.get("summary", {}).get(
                "baseline_metrics", 0
            ),
            "PUBLIC_FEEDBACK_SIGNAL_COUNT": len(
                feedback_signals.get("signals", [])
            ),
            "BUILD_ID_SHORT": manifest.get("build_id", "")[:12],
        }
    )
    return {key: str(value) for key, value in facts.items()}


def render_readme(
    profile,
    *,
    root=ROOT,
    stable_version=None,
    development_version=None,
):
    root = Path(root)
    if profile not in PROFILE_PATHS:
        raise ValueError(f"Unknown README profile: {profile}")
    metadata_path = root / "config" / "feedback_rules.json"
    metadata = load_json(metadata_path) if metadata_path.exists() else {}
    stable_version = stable_version or metadata.get("stable_version")
    development_version = development_version or metadata.get("skill_version")
    if not stable_version or not development_version:
        raise ValueError("README versions are unavailable")

    template = (root / PROFILE_PATHS[profile]).read_text(encoding="utf-8")
    values = {
        "STABLE_VERSION": str(stable_version),
        "DEVELOPMENT_VERSION": str(development_version),
    }
    required = set(TOKEN_PATTERN.findall(template))
    unknown = sorted(required - set(values) - FACT_KEYS)
    if unknown:
        raise ValueError("Unknown README tokens: " + ", ".join(unknown))
    if required & FACT_KEYS:
        values.update(collect_readme_facts(root))
    missing = sorted(required - set(values))
    if missing:
        raise ValueError("Unknown README tokens: " + ", ".join(missing))
    rendered = TOKEN_PATTERN.sub(lambda match: values[match.group(1)], template)
    expected_marker = f"<!-- README_PROFILE: {profile} -->"
    if rendered.count(expected_marker) != 1:
        raise ValueError(f"README profile marker is invalid: {profile}")
    unresolved = TOKEN_PATTERN.findall(rendered)
    if unresolved:
        raise ValueError("Unresolved README tokens: " + ", ".join(unresolved))
    return rendered.rstrip() + "\n"


def write_readme_profile(profile, *, root=ROOT, **versions):
    root = Path(root)
    rendered = render_readme(profile, root=root, **versions)
    atomic_write_text(root / README_PATH, rendered)
    return rendered


def profile_for_channel(channel):
    if channel == "stable":
        return "main"
    if channel == "development":
        return "develop"
    raise ValueError(f"Unsupported release channel: {channel}")


def main():
    parser = argparse.ArgumentParser(
        description="Render the canonical bilingual branch README"
    )
    parser.add_argument("--profile", choices=("auto", *PROFILE_PATHS), default="auto")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    metadata = load_json(ROOT / "config" / "feedback_rules.json")
    profile = (
        profile_for_channel(metadata["channel"])
        if args.profile == "auto"
        else args.profile
    )
    rendered = render_readme(profile)
    if args.check:
        if (ROOT / README_PATH).read_text(encoding="utf-8") != rendered:
            raise SystemExit(
                f"README.md is stale for the {profile} audience profile"
            )
        print(json.dumps({"status": "current", "profile": profile}))
        return
    atomic_write_text(ROOT / README_PATH, rendered)
    print(json.dumps({"status": "written", "profile": profile}))


if __name__ == "__main__":
    main()
