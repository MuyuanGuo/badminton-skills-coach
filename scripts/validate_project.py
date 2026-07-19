#!/usr/bin/env python3
import json
import re
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

from evaluate_answer_quality import validate_registry as validate_answer_quality_registry
from build_manifest import manifest_bytes
from douyin_pipeline import QUEUE_STATUSES, load_classification_rules, validate_queue_statuses
from media_assets import load_media_policy
from project_artifacts import (
    derive_project_status,
    skill_reference_bytes,
    skill_reference_mismatches,
)
from update_readme_status import (
    update_agent_metadata_text,
    update_readme_text,
    update_skill_status_text,
)


ROOT = Path(__file__).resolve().parents[1]

workflow_text = (ROOT / ".github" / "workflows" / "validate.yml").read_text(
    encoding="utf-8"
)
for test_path in sorted((ROOT / "scripts").glob("test_*.py")):
    relative_test_path = str(test_path.relative_to(ROOT))
    if f"python {relative_test_path}" not in workflow_text:
        raise SystemExit(f"Regression test is not executed by CI: {relative_test_path}")
for compiled_helper in [
    "scripts/media_assets.py",
    "scripts/project_artifacts.py",
    "scripts/package_skill_release.py",
]:
    if compiled_helper not in workflow_text:
        raise SystemExit(f"Core helper is not compiled by CI: {compiled_helper}")

json_paths = [
    "config/answer_modality_rules.json",
    "config/answer_selection_rules.json",
    "config/answer_quality_rules.json",
    "config/douyin_classification_rules.json",
    "config/douyin_source.json",
    "config/feedback_rules.json",
    "config/feedback_signals.json",
    "config/knowledge_quality_rules.json",
    "config/practice_plan_rules.json",
    "config/retrieval_rules.json",
    "config/reviewed_evidence_signals.json",
    "data/knowledge/build_manifest.json",
    "data/douyin_teaching_filtered.json",
    "data/douyin_classification_ledger.json",
    "data/douyin_video_index.json",
    "data/evaluation/answer_modality_cases.json",
    "data/evaluation/answer_quality_answers.json",
    "data/evaluation/answer_quality_cases.json",
    "data/evaluation/feedback_parser_cases.json",
    "data/evaluation/feedback_relevance_cases.json",
    "data/evaluation/query_understanding_cases.json",
    "data/evaluation/retrieval_cases.json",
    "data/knowledge/pilot_teaching_notes.json",
    "data/knowledge/douyin_knowledge_base.json",
    "data/knowledge/retrieval_index.json",
    "data/knowledge/topic_index.json",
    "data/knowledge/knowledge_graph_summary.json",
    "data/review/visual_review_annotations.json",
    "data/review/visual_review_queue.json",
    "data/processing/douyin_queue.json",
    "data/processing/douyin_discovery_state.json",
    "skills/liuhui-badminton-coach/references/answer-modality-rules.json",
    "skills/liuhui-badminton-coach/references/answer-selection-rules.json",
    "skills/liuhui-badminton-coach/references/build-manifest.json",
    "skills/liuhui-badminton-coach/references/practice-plan-rules.json",
    "skills/liuhui-badminton-coach/references/feedback-rules.json",
    "skills/liuhui-badminton-coach/references/feedback-signals.json",
    "skills/liuhui-badminton-coach/references/knowledge-base.json",
    "skills/liuhui-badminton-coach/references/retrieval-index.json",
    "skills/liuhui-badminton-coach/references/retrieval-rules.json",
    "skills/liuhui-badminton-coach/references/reviewed-evidence-signals.json",
    "skills/liuhui-badminton-coach/references/topic-map.json",
]
for relative_path in json_paths:
    path = ROOT / relative_path
    with path.open(encoding="utf-8") as file:
        json.load(file)
if not (ROOT / "scripts" / "apply_answer_quality_review_notes.py").exists():
    raise SystemExit("Answer quality review application script is missing")
for runtime_file in [
    ROOT / "requirements-transcription.txt",
    ROOT / "scripts" / "doctor.py",
    ROOT / "scripts" / "install_skill.py",
    ROOT / "scripts" / "media_assets.py",
    ROOT / "scripts" / "package_skill_release.py",
    ROOT / "scripts" / "build_manifest.py",
    ROOT / "scripts" / "check_video_links.py",
    ROOT / "skills" / "liuhui-badminton-coach" / "scripts" / "doctor.py",
    ROOT / "skills" / "liuhui-badminton-coach" / "scripts" / "install.py",
    ROOT
    / "skills"
    / "liuhui-badminton-coach"
    / "scripts"
    / "prepare_answer_context.py",
]:
    if not runtime_file.exists():
        raise SystemExit(f"Runtime setup file is missing: {runtime_file.relative_to(ROOT)}")

expected_manifest = manifest_bytes()
for manifest_path in [
    ROOT / "data" / "knowledge" / "build_manifest.json",
    ROOT
    / "skills"
    / "liuhui-badminton-coach"
    / "references"
    / "build-manifest.json",
]:
    if manifest_path.read_bytes() != expected_manifest:
        raise SystemExit(
            f"Build manifest is stale: {manifest_path.relative_to(ROOT)}"
        )

ET.parse(ROOT / "output" / "liuhui-full-knowledge-map.drawio")

social_preview = ROOT / ".github" / "assets" / "social-preview.png"
preview_bytes = social_preview.read_bytes()
if not preview_bytes.startswith(b"\x89PNG\r\n\x1a\n") or len(preview_bytes) < 24:
    raise SystemExit("Social preview is missing or is not a valid PNG")
preview_width, preview_height = struct.unpack(">II", preview_bytes[16:24])
if (preview_width, preview_height) != (1280, 640):
    raise SystemExit(
        f"Social preview must be 1280x640, found {preview_width}x{preview_height}"
    )
if len(preview_bytes) > 2 * 1024 * 1024:
    raise SystemExit("Social preview exceeds the 2 MB repository media budget")

def validate_skill_frontmatter(skill_name):
    skill_path = ROOT / "skills" / skill_name / "SKILL.md"
    skill_text = skill_path.read_text(encoding="utf-8")
    frontmatter = re.match(r"\A---\n(.*?)\n---\n", skill_text, re.DOTALL)
    if not frontmatter:
        raise SystemExit(f"{skill_name}/SKILL.md is missing YAML frontmatter")
    if not re.search(rf"^name:\s+{re.escape(skill_name)}$", frontmatter.group(1), re.MULTILINE):
        raise SystemExit(f"{skill_name}/SKILL.md has an invalid name")
    if not re.search(r"^description:\s+\S+", frontmatter.group(1), re.MULTILINE):
        raise SystemExit(f"{skill_name}/SKILL.md is missing a description")


validate_skill_frontmatter("liuhui-badminton-coach")

queue = json.loads(
    (ROOT / "data" / "processing" / "douyin_queue.json").read_text(encoding="utf-8")
)
validate_queue_statuses(queue["items"])
if len(queue["items"]) < 405:
    raise SystemExit(f"Expected at least 405 teaching videos in queue, found {len(queue['items'])}")
if sum(queue["counts"].values()) != len(queue["items"]):
    raise SystemExit("Douyin queue counts do not sum to the queue length")
if not {"classified_teaching", "media_ready", "transcribed", "download_failed", "transcription_failed"}.issubset(QUEUE_STATUSES):
    raise SystemExit("Queue status contract is missing expected pipeline states")
for item in queue["items"]:
    if item.get("status") == "transcribed" and (
        item.get("media_path") is not None
        or "media_asset_kind" in item
        or "media_asset_source" in item
    ):
        raise SystemExit(
            f"Transcribed queue item retains temporary media state: {item['video_id']}"
        )
    if item.get("status") == "transcribed":
        provenance_fields = [
            "transcript_source_sha256",
            "transcript_source_bytes",
            "transcript_model",
            "transcript_language",
            "transcript_text_characters",
        ]
        present = [field in item and item.get(field) is not None for field in provenance_fields]
        if any(present) and not all(present):
            raise SystemExit(
                f"Transcribed queue item has partial source provenance: {item['video_id']}"
            )
        if all(present) and (
            not re.fullmatch(r"[0-9a-f]{64}", item["transcript_source_sha256"])
            or not isinstance(item["transcript_source_bytes"], int)
            or item["transcript_source_bytes"] <= 0
            or not isinstance(item["transcript_text_characters"], int)
            or item["transcript_text_characters"] < 0
        ):
            raise SystemExit(
                f"Transcribed queue item has invalid source provenance: {item['video_id']}"
            )

media_policy = load_media_policy()
if media_policy["minimum_download_bytes"] < 4096:
    raise SystemExit("Media download size gate is too small to reject error responses")
if not 1 <= media_policy["snapshot_max_age_minutes"] <= 60:
    raise SystemExit("Media snapshot age gate must be between 1 and 60 minutes")

rules = load_classification_rules()
for required_signal in [
    "ad_strong",
    "commerce",
    "equipment",
    "teaching",
    "teaching_hashtag",
    "non_teaching",
]:
    if required_signal not in rules["signals"]:
        raise SystemExit(f"Classification rules missing signal: {required_signal}")
if len(rules["taxonomy"]) < 8:
    raise SystemExit("Classification taxonomy is missing expected top-level categories")

video_index = json.loads(
    (ROOT / "data" / "douyin_video_index.json").read_text(encoding="utf-8")
)
teaching_filter = json.loads(
    (ROOT / "data" / "douyin_teaching_filtered.json").read_text(encoding="utf-8")
)
classification_ledger = json.loads(
    (ROOT / "data" / "douyin_classification_ledger.json").read_text(
        encoding="utf-8"
    )
)
rules_identity = rules["_rules_identity"]
if classification_ledger.get("classification_rules") != rules_identity:
    raise SystemExit("Classification ledger rules identity is stale")
if teaching_filter.get("classification_rules") != rules_identity:
    raise SystemExit("Teaching filter rules identity is stale")
index_ids = {item["video_id"] for item in video_index["videos"]}
ledger_ids = {item["video_id"] for item in classification_ledger["videos"]}
if ledger_ids != index_ids:
    raise SystemExit("Classification ledger does not cover the full video index")
if any(
    item.get("classification_rules_hash") != rules_identity["sha256"]
    or item.get("classification_rules_version") != rules_identity["version"]
    for item in classification_ledger["videos"]
):
    raise SystemExit("Classification ledger contains mixed rule identities")
if any(
    item.get("classification_rules_hash") != rules_identity["sha256"]
    or item.get("classification_rules_version") != rules_identity["version"]
    for item in queue["items"]
):
    raise SystemExit("Processing queue contains stale classification metadata")
douyin_knowledge = json.loads(
    (ROOT / "data" / "knowledge" / "douyin_knowledge_base.json").read_text(encoding="utf-8")
)
if len(douyin_knowledge["videos"]) < 25:
    raise SystemExit("Full Douyin knowledge base regressed below pilot size")
if len(douyin_knowledge["videos"]) < 405:
    raise SystemExit(f"Expected at least 405 full Douyin knowledge videos, found {len(douyin_knowledge['videos'])}")

skill_knowledge = json.loads(
    (
        ROOT
        / "skills"
        / "liuhui-badminton-coach"
        / "references"
        / "knowledge-base.json"
    ).read_text(encoding="utf-8")
)
expected_skill_knowledge = json.loads(
    skill_reference_bytes(
        Path("data/knowledge/douyin_knowledge_base.json"),
        (ROOT / "data" / "knowledge" / "douyin_knowledge_base.json").read_bytes(),
    )
)
if skill_knowledge != expected_skill_knowledge:
    raise SystemExit("Skill knowledge base is out of sync with its portable source")
if skill_knowledge.get("transcript_files_bundled") is not False or any(
    "transcript_file" in video for video in skill_knowledge["videos"]
):
    raise SystemExit("Skill package exposes transcript paths that are not bundled")

retrieval_rules = json.loads(
    (ROOT / "config" / "retrieval_rules.json").read_text(encoding="utf-8")
)
skill_retrieval_rules = json.loads(
    (
        ROOT
        / "skills"
        / "liuhui-badminton-coach"
        / "references"
        / "retrieval-rules.json"
    ).read_text(encoding="utf-8")
)
if skill_retrieval_rules != retrieval_rules:
    raise SystemExit("Skill retrieval rules are out of sync with project config")
retrieval_intent = retrieval_rules.get("intent", {})
required_retrieval_intent_fields = {
    "practice_request_terms",
    "practice_schedule_terms",
    "practice_context_terms",
    "practice_plan_nouns",
    "practice_plan_request_terms",
    "diagnosis_request_terms",
    "comparison_request_terms",
}
if not required_retrieval_intent_fields.issubset(retrieval_intent):
    raise SystemExit("Retrieval intent routing rules are incomplete")
if any(
    not retrieval_intent[field]
    for field in required_retrieval_intent_fields
):
    raise SystemExit("Retrieval intent routing rules cannot be empty")

answer_selection_rules = json.loads(
    (ROOT / "config" / "answer_selection_rules.json").read_text(
        encoding="utf-8"
    )
)
skill_answer_selection_rules = json.loads(
    (
        ROOT
        / "skills"
        / "liuhui-badminton-coach"
        / "references"
        / "answer-selection-rules.json"
    ).read_text(encoding="utf-8")
)
if skill_answer_selection_rules != answer_selection_rules:
    raise SystemExit("Skill answer selection rules are out of sync")
actor_markers = answer_selection_rules.get("query_actor_markers", {})
if set(actor_markers) != {"player", "opponent"} or any(
    not actor_markers[actor] for actor in actor_markers
):
    raise SystemExit("Query actor markers are incomplete")
if set(actor_markers["player"]) & set(actor_markers["opponent"]):
    raise SystemExit("Query actor markers cannot identify both actors")
all_actor_markers = set(actor_markers["player"]) | set(actor_markers["opponent"])
for marker, suppressions in answer_selection_rules.get(
    "query_actor_marker_suppressions", {}
).items():
    if marker not in all_actor_markers or not suppressions:
        raise SystemExit("Query actor marker suppression references an unknown marker")
    if any(marker not in phrase for phrase in suppressions):
        raise SystemExit("Query actor marker suppression must contain its marker")
if not answer_selection_rules.get("query_actor_clause_separators"):
    raise SystemExit("Query actor clause separators are missing")
constraint_axes = {
    axis["name"]: axis
    for axis in answer_selection_rules.get("constraint_axes", [])
}
required_derived_axes = set(
    answer_selection_rules.get(
        "derived_player_constraint_required_match_axes", []
    )
)
if not required_derived_axes or not required_derived_axes.issubset(constraint_axes):
    raise SystemExit("Derived player constraint match axes are incomplete")
for axis in constraint_axes.values():
    allowed_values = set(axis.get("values", {}))
    for field in [
        "opponent_query_value_additions",
        "query_value_suppressions",
    ]:
        configured_values = set(axis.get(field, {}))
        if not configured_values.issubset(allowed_values):
            raise SystemExit(f"{field} contains an unknown constraint value")
        if any(not terms for terms in axis.get(field, {}).values()):
            raise SystemExit(f"{field} contains an empty term list")
required_implication_fields = {
    "opponent_axis",
    "opponent_values",
    "player_axis",
    "player_values",
    "response_terms",
    "search_terms",
}
for implication in answer_selection_rules.get(
    "opponent_response_implications", []
):
    if set(implication) != required_implication_fields:
        raise SystemExit("Opponent response implication contract is incomplete")
    for prefix in ["opponent", "player"]:
        axis_name = implication[f"{prefix}_axis"]
        if axis_name not in constraint_axes:
            raise SystemExit("Opponent response implication uses an unknown axis")
        allowed_values = set(constraint_axes[axis_name]["values"])
        if not set(implication[f"{prefix}_values"]).issubset(allowed_values):
            raise SystemExit("Opponent response implication uses an unknown value")
    if not implication["response_terms"] or not implication["search_terms"]:
        raise SystemExit("Opponent response implication has no retrieval trigger")
boundary_terms = answer_selection_rules.get("boundary_terms", {})
expected_boundary_groups = {
    "pain_or_injury",
    "endorsement_or_authorship",
    "purchase_advice",
    "visual_confirmation",
    "insufficient_observation",
}
if set(boundary_terms) != expected_boundary_groups:
    raise SystemExit("Answer selection boundary groups are incomplete")
flattened_boundary_terms = [
    term for terms in boundary_terms.values() for term in terms
]
if len(flattened_boundary_terms) != len(set(flattened_boundary_terms)):
    raise SystemExit("Answer selection boundary terms must be unambiguous")
pain_terms = set(boundary_terms["pain_or_injury"])
if not pain_terms.issubset(retrieval_intent["literal_symptom_terms"]):
    raise SystemExit("Pain boundaries are missing from literal symptoms")

answer_modality_rules = json.loads(
    (ROOT / "config" / "answer_modality_rules.json").read_text(encoding="utf-8")
)
skill_answer_modality_rules = json.loads(
    (
        ROOT
        / "skills"
        / "liuhui-badminton-coach"
        / "references"
        / "answer-modality-rules.json"
    ).read_text(encoding="utf-8")
)
if skill_answer_modality_rules != answer_modality_rules:
    raise SystemExit("Skill answer modality rules are out of sync with project config")
if set(answer_modality_rules["modes"]) != {
    "text_primary",
    "balanced",
    "video_primary",
}:
    raise SystemExit("Answer modality rules must define all three answer modes")
if set(answer_modality_rules.get("workflow", {})) != {
    "boundary_signals",
    "systematic_signals",
    "diagnostic_signals",
    "scenario_focused_requested_outputs",
    "multi_issue_separators",
    "multi_issue_connectors",
    "relational_signals",
    "minimum_multi_issue_concepts",
}:
    raise SystemExit("Answer workflow routing rules are incomplete")
if set(
    answer_modality_rules["workflow"][
        "scenario_focused_requested_outputs"
    ]
) != {"coaching_answer", "comparison", "practice"}:
    raise SystemExit(
        "Scenario-focused workflow outputs are incomplete"
    )
if set(answer_modality_rules["workflow"]["boundary_signals"]) != set(
    flattened_boundary_terms
):
    raise SystemExit(
        "Answer workflow boundary signals differ from final boundary rules"
    )
if not pain_terms.issubset(
    answer_modality_rules["workflow"]["diagnostic_signals"]
):
    raise SystemExit("Pain boundaries are missing from diagnostic signals")
text_primary_boundary_terms = set().union(
    boundary_terms["pain_or_injury"],
    boundary_terms["endorsement_or_authorship"],
    boundary_terms["purchase_advice"],
)
if set(
    answer_modality_rules["decision"]["decisive_text_boundary_terms"]
) != text_primary_boundary_terms:
    raise SystemExit(
        "Text-primary boundary signals differ from boundary categories"
    )

practice_plan_rules = json.loads(
    (ROOT / "config" / "practice_plan_rules.json").read_text(encoding="utf-8")
)
if set(practice_plan_rules.get("levels", {})) != {
    "beginner",
    "intermediate",
    "advanced",
    "unknown",
}:
    raise SystemExit("Practice plan rules have incomplete level adaptations")
if set(practice_plan_rules.get("practice_setups", {})) != {
    "solo",
    "partner",
    "coach",
    "unknown",
}:
    raise SystemExit("Practice plan rules have incomplete setup adaptations")
if set(practice_plan_rules.get("discipline_boundaries", {})) != {
    "singles",
    "doubles",
    "both",
    "unknown",
}:
    raise SystemExit("Practice plan rules have incomplete discipline boundaries")
minimum_minutes, maximum_minutes = practice_plan_rules.get(
    "session_minutes_range", [0, 0]
)
if not 1 <= minimum_minutes <= practice_plan_rules.get(
    "default_session_minutes", 0
) <= maximum_minutes:
    raise SystemExit("Practice plan duration defaults are invalid")

feedback_rules = json.loads(
    (ROOT / "config" / "feedback_rules.json").read_text(encoding="utf-8")
)
skill_feedback_rules = json.loads(
    (
        ROOT
        / "skills"
        / "liuhui-badminton-coach"
        / "references"
        / "feedback-rules.json"
    ).read_text(encoding="utf-8")
)
if skill_feedback_rules != feedback_rules:
    raise SystemExit("Skill feedback rules are out of sync with project config")
skill_version = feedback_rules.get("skill_version", "")
release_channel = feedback_rules.get("channel", "")
stable_version = feedback_rules.get("stable_version", "")
if not re.fullmatch(r"\d+\.\d+\.\d+", stable_version):
    raise SystemExit("Stable Skill version has an invalid format")
if release_channel == "development":
    if not re.fullmatch(r"\d+\.\d+\.\d+-dev\.\d+", skill_version):
        raise SystemExit("Development Skill version has an invalid format")
elif release_channel == "stable":
    if not re.fullmatch(r"\d+\.\d+\.\d+", skill_version):
        raise SystemExit("Stable-channel Skill version has an invalid format")
    if skill_version != stable_version:
        raise SystemExit("Stable-channel Skill version must equal stable_version")
else:
    raise SystemExit("Skill release channel must be development or stable")
if set(feedback_rules["queue_statuses"]) != {
    "pending_review",
    "needs_clarification",
    "accepted",
    "rejected",
    "superseded",
}:
    raise SystemExit("Feedback queue status contract is incomplete")
if not feedback_rules.get("contrast_separators"):
    raise SystemExit("Feedback rules must define contrast clause separators")
if not feedback_rules.get("comparative_video_cues"):
    raise SystemExit("Feedback rules must define comparative video cues")
personalization = feedback_rules.get("personalization", {})
if not 0 < personalization.get("query_similarity_threshold", 0) < 1:
    raise SystemExit("Feedback query similarity threshold is invalid")
if personalization.get("local_preference_min_count", 0) < 2:
    raise SystemExit("Local style preferences require repeated accepted feedback")
feedback_weights = personalization.get("weights", {})
if any(feedback_weights.get(key, 0) <= 0 for key in [
    "global_helpful",
    "global_missing",
    "local_helpful",
    "local_missing",
]):
    raise SystemExit("Positive feedback weights must be positive")
if any(feedback_weights.get(key, 0) >= 0 for key in [
    "global_irrelevant",
    "local_irrelevant",
]):
    raise SystemExit("Irrelevant feedback weights must be negative")

project_status = derive_project_status(video_index, teaching_filter, douyin_knowledge)
ready_count = project_status["ready_teaching_videos"]
all_collected_count = project_status["public_videos_collected"]
queue_kept = sum(
    item.get("classification_decision") == "保留：教学"
    for item in queue["items"]
)
if teaching_filter["counts"]["kept_teaching"] != queue_kept:
    raise SystemExit("Teaching filter kept count is out of sync with queue decisions")
if ready_count != douyin_knowledge["knowledge_counts"].get("ready"):
    raise SystemExit("Knowledge ready count is out of sync with video statuses")
knowledge_quality_rules = json.loads(
    (ROOT / "config" / "knowledge_quality_rules.json").read_text(encoding="utf-8")
)
if douyin_knowledge.get("quality_rules_version") != knowledge_quality_rules["version"]:
    raise SystemExit("Knowledge base quality rules version is stale")
for video in douyin_knowledge["videos"]:
    if set(video.get("quality", {})) != {"transcript", "automatic_evidence"}:
        raise SystemExit(f"Knowledge quality audit is missing for {video['video_id']}")
    if video["confidence"] == "medium" and (
        not video["quality"]["transcript"]["passed"]
        or not video["quality"]["automatic_evidence"]["passed"]
    ):
        raise SystemExit(f"Automatic ready video failed quality gates: {video['video_id']}")
    queue_item = next(
        item for item in queue["items"] if item["video_id"] == video["video_id"]
    )
    if video.get("classification", {}).get("decision") != queue_item.get(
        "classification_decision"
    ):
        raise SystemExit(
            f"Knowledge classification is stale for {video['video_id']}"
        )

retrieval_index_text = (ROOT / "data" / "knowledge" / "retrieval_index.json").read_text(
    encoding="utf-8"
)
retrieval_index = json.loads(retrieval_index_text)
skill_retrieval_index = json.loads(
    (
        ROOT
        / "skills"
        / "liuhui-badminton-coach"
        / "references"
        / "retrieval-index.json"
    ).read_text(encoding="utf-8")
)
if skill_retrieval_index != retrieval_index:
    raise SystemExit("Skill retrieval index is out of sync with project data")
if retrieval_index["source_updated_at"] != douyin_knowledge["updated_at"]:
    raise SystemExit("Retrieval index is stale relative to the knowledge base")
if retrieval_index["version"] != retrieval_rules["version"]:
    raise SystemExit("Retrieval index version is out of sync with retrieval rules")
if retrieval_index["indexable_video_count"] != ready_count:
    raise SystemExit("Retrieval index count is out of sync with ready videos")
if retrieval_index.get("full_transcript_text_included") is not False:
    raise SystemExit("Retrieval index must not include full transcript text")
if retrieval_index.get("evidence_fields") != ["title", "teaching_note", "transcript"]:
    raise SystemExit("Retrieval evidence fields must exclude screening metadata")
if retrieval_index.get("screening_fields_excluded") != ["category", "tags"]:
    raise SystemExit("Retrieval index does not declare excluded screening fields")
if set(retrieval_rules.get("field_weights", {})) != {
    "title",
    "teaching_note",
    "transcript",
}:
    raise SystemExit("Retrieval field weights must contain evidence fields only")
if '"full_text"' in retrieval_index_text or '"transcript_text"' in retrieval_index_text:
    raise SystemExit("Retrieval index unexpectedly contains transcript text fields")
allowed_retrieval_video_fields = {
    "video_id",
    "topic_ids",
    "lexicon_terms",
    "field_lengths",
    "field_term_frequencies",
    "title_ngrams",
    "teaching_note_ngrams",
    "transcript_ngrams",
}
if any(set(video) != allowed_retrieval_video_fields for video in retrieval_index["videos"]):
    raise SystemExit("Retrieval index video records contain unexpected fields")
ready_video_ids = {
    video["video_id"]
    for video in douyin_knowledge["videos"]
    if video["processing_status"] == "ready"
}

answer_quality_rules = json.loads(
    (ROOT / "config" / "answer_quality_rules.json").read_text(encoding="utf-8")
)
if set(answer_quality_rules.get("maintainer_decisions", [])) != {
    "pending",
    "approved",
    "rejected",
}:
    raise SystemExit("Answer quality maintainer decisions are incomplete")
answer_quality_cases = json.loads(
    (ROOT / "data" / "evaluation" / "answer_quality_cases.json").read_text(
        encoding="utf-8"
    )
)
answer_quality_summary = validate_answer_quality_registry(
    answer_quality_cases,
    answer_quality_rules,
    ready_video_ids,
    minimum_cases=30,
    all_video_ids={video["video_id"] for video in douyin_knowledge["videos"]},
)
if set(answer_quality_summary["status_counts"]) - set(
    answer_quality_rules["review_statuses"]
):
    raise SystemExit("Answer quality registry contains an unknown review status")
if {
    case["case_type"] for case in answer_quality_cases["cases"]
} != set(answer_quality_rules["case_types"]):
    raise SystemExit("Answer quality registry does not cover every case type")
if {
    case["expected_mode"] for case in answer_quality_cases["cases"]
} != set(answer_quality_rules["answer_modes"]):
    raise SystemExit("Answer quality registry does not cover every answer mode")
retrieval_video_ids = {video["video_id"] for video in retrieval_index["videos"]}
if retrieval_video_ids != ready_video_ids:
    raise SystemExit("Retrieval index video IDs do not match ready knowledge videos")

feedback_signals = json.loads(
    (ROOT / "config" / "feedback_signals.json").read_text(encoding="utf-8")
)
if feedback_signals.get("version") != 1:
    raise SystemExit("Promoted feedback signal schema version is unsupported")
skill_feedback_signals = json.loads(
    (
        ROOT
        / "skills"
        / "liuhui-badminton-coach"
        / "references"
        / "feedback-signals.json"
    ).read_text(encoding="utf-8")
)
if skill_feedback_signals != feedback_signals:
    raise SystemExit("Promoted feedback signals are out of sync with the Skill")
allowed_signal_fields = {
    "signal_id",
    "source_feedback_id",
    "source_type",
    "source_reference",
    "source_body_sha256",
    "source_issue_node_id",
    "source_updated_at",
    "source_reverified_at",
    "public_query",
    "helpful_video_ids",
    "irrelevant_video_ids",
    "missing_video_ids",
    "answer_issue_types",
    "intended_query",
    "source_issue_video_ids",
    "evidence_note",
    "promoted_by",
    "promoted_at",
}
allowed_issue_types = set(feedback_rules["text_issue_cues"])
for signal in feedback_signals["signals"]:
    if set(signal) != allowed_signal_fields:
        raise SystemExit("Promoted feedback signal contains unexpected fields")
    if signal["source_type"] != "github_issue" or not re.fullmatch(
        r"https://github\.com/MuyuanGuo/badminton-skills-coach/issues/[1-9]\d*/?",
        signal["source_reference"],
    ):
        raise SystemExit("Promoted feedback must retain a canonical public issue source")
    if not re.fullmatch(r"[0-9a-f]{64}", signal["source_body_sha256"]):
        raise SystemExit("Promoted feedback must retain its verified Issue body hash")
    if not signal["source_issue_node_id"] or not signal["source_reverified_at"]:
        raise SystemExit("Promoted feedback must retain post-review reverification")
    positive_ids = set(signal["helpful_video_ids"]) | set(signal["missing_video_ids"])
    negative_ids = set(signal["irrelevant_video_ids"])
    if positive_ids & negative_ids:
        raise SystemExit("Promoted feedback contains conflicting video relevance")
    if not (positive_ids | negative_ids).issubset(ready_video_ids):
        raise SystemExit("Promoted feedback references a non-ready video")
    if not set(signal["answer_issue_types"]).issubset(allowed_issue_types):
        raise SystemExit("Promoted feedback contains an unknown answer issue type")
    source_issue_types = {
        "transcript_error",
        "video_misinterpreted",
        "citation_mismatch",
    }
    if "question_misunderstood" in signal["answer_issue_types"] and not signal[
        "intended_query"
    ]:
        raise SystemExit("Promoted question correction lacks an intended query")
    if source_issue_types.intersection(signal["answer_issue_types"]) and not signal[
        "source_issue_video_ids"
    ]:
        raise SystemExit("Promoted source correction lacks a target video")
    if not set(signal["source_issue_video_ids"]).issubset(ready_video_ids):
        raise SystemExit("Promoted source correction references a non-ready video")
    if "raw_feedback" in signal or "question" in signal:
        raise SystemExit("Promoted feedback leaked private raw fields")

feedback_relevance_cases = json.loads(
    (ROOT / "data" / "evaluation" / "feedback_relevance_cases.json").read_text(
        encoding="utf-8"
    )
)
if feedback_relevance_cases.get("version") != 2:
    raise SystemExit("Feedback relevance evaluation schema version is unsupported")
signals_by_id = {signal["signal_id"]: signal for signal in feedback_signals["signals"]}
cases_by_id = {case["case_id"]: case for case in feedback_relevance_cases["cases"]}
if len(signals_by_id) != len(feedback_signals["signals"]):
    raise SystemExit("Promoted feedback signal IDs must be unique")
if len(cases_by_id) != len(feedback_relevance_cases["cases"]):
    raise SystemExit("Promoted feedback evaluation case IDs must be unique")
if len({signal["source_feedback_id"] for signal in feedback_signals["signals"]}) != len(
    feedback_signals["signals"]
):
    raise SystemExit("A feedback record cannot be promoted more than once")
if set(signals_by_id) != set(cases_by_id):
    raise SystemExit("Every promoted feedback signal must have exactly one regression case")
for signal_id, signal in signals_by_id.items():
    case = cases_by_id[signal_id]
    if case["query"] != signal["public_query"]:
        raise SystemExit("Promoted feedback query is out of sync with its regression case")
    if set(case["expected_positive_video_ids"]) != (
        set(signal["helpful_video_ids"]) | set(signal["missing_video_ids"])
    ):
        raise SystemExit("Promoted positive videos are out of sync with evaluation")
    if set(case["expected_negative_video_ids"]) != set(signal["irrelevant_video_ids"]):
        raise SystemExit("Promoted negative videos are out of sync with evaluation")
    if set(case["expected_answer_reminders"]) != set(signal["answer_issue_types"]):
        raise SystemExit("Promoted answer reminders are out of sync with evaluation")
    if case.get("expected_intended_query") != signal["intended_query"]:
        raise SystemExit("Promoted intended query is out of sync with evaluation")
    if set(case.get("expected_source_issue_video_ids", [])) != set(
        signal["source_issue_video_ids"]
    ):
        raise SystemExit("Promoted source recheck targets are out of sync with evaluation")

adversarial_feedback_cases = feedback_relevance_cases.get(
    "adversarial_cases", []
)
adversarial_case_ids = [case["case_id"] for case in adversarial_feedback_cases]
if len(adversarial_case_ids) != len(set(adversarial_case_ids)):
    raise SystemExit("Adversarial feedback case IDs must be unique")
adversarial_check_count = 0
for case in adversarial_feedback_cases:
    signal = case.get("signal", {})
    if signal.get("signal_id") != case["case_id"]:
        raise SystemExit("Adversarial feedback signal ID is out of sync")
    if not signal.get("public_query") or not case.get("checks"):
        raise SystemExit("Adversarial feedback case is incomplete")
    referenced_ids = set(
        signal.get("helpful_video_ids", [])
        + signal.get("irrelevant_video_ids", [])
        + signal.get("missing_video_ids", [])
        + signal.get("source_issue_video_ids", [])
    )
    if not referenced_ids.issubset(ready_video_ids):
        raise SystemExit("Adversarial feedback references a non-ready video")
    for check in case["checks"]:
        adversarial_check_count += 1
        if not check.get("query"):
            raise SystemExit("Adversarial feedback check has no query")
if adversarial_check_count < 7:
    raise SystemExit("Feedback relevance evaluation lacks adversarial checks")

retrieval_cases = json.loads(
    (ROOT / "data" / "evaluation" / "retrieval_cases.json").read_text(encoding="utf-8")
)
for case in retrieval_cases["cases"]:
    expected_ids = set(case["expected_video_ids"])
    if case["primary_video_id"] not in expected_ids:
        raise SystemExit("Retrieval evaluation primary video is not in expected videos")
    if not expected_ids.issubset(ready_video_ids):
        raise SystemExit("Retrieval evaluation references a non-ready or missing video")

answer_modality_cases = json.loads(
    (ROOT / "data" / "evaluation" / "answer_modality_cases.json").read_text(
        encoding="utf-8"
    )
)
allowed_answer_modes = set(answer_modality_rules["modes"])
if len(answer_modality_cases["cases"]) < 15:
    raise SystemExit("Answer modality evaluation has too few cases")
if {
    case["expected_mode"] for case in answer_modality_cases["cases"]
} != allowed_answer_modes:
    raise SystemExit("Answer modality evaluation does not cover all answer modes")
readme_text = (ROOT / "README.md").read_text(encoding="utf-8")
version_contracts = ["releases/latest"]
if release_channel == "development":
    version_contracts.extend(
        [
            f"**{skill_version} 开发分支**",
            f"- 开发版：`develop` / `{skill_version}`",
        ]
    )
else:
    version_contracts.extend(
        [
            f"**{skill_version} 稳定版**",
            f"- 稳定版：`main` / `v{stable_version}`",
            f"releases/tag/v{stable_version}",
        ]
    )
for version_contract in version_contracts:
    if version_contract not in readme_text:
        raise SystemExit(f"README version metadata is stale: {version_contract}")
expected_readme_text = update_readme_text(
    readme_text,
    video_index,
    teaching_filter,
    douyin_knowledge,
    feedback_signals,
)
if expected_readme_text != readme_text:
    raise SystemExit(
        "README current status is stale; run scripts/update_readme_status.py"
    )
skill_status_path = ROOT / "skills" / "liuhui-badminton-coach" / "SKILL.md"
skill_status_text = skill_status_path.read_text(encoding="utf-8")
if update_skill_status_text(skill_status_text, douyin_knowledge) != skill_status_text:
    raise SystemExit(
        "Skill current status is stale; run scripts/update_readme_status.py"
    )
agent_metadata_path = (
    ROOT / "skills" / "liuhui-badminton-coach" / "agents" / "openai.yaml"
)
agent_metadata_text = agent_metadata_path.read_text(encoding="utf-8")
if (
    update_agent_metadata_text(agent_metadata_text, douyin_knowledge)
    != agent_metadata_text
):
    raise SystemExit(
        "Agent metadata status is stale; run scripts/update_readme_status.py"
    )

topic_index = json.loads(
    (ROOT / "data" / "knowledge" / "topic_index.json").read_text(encoding="utf-8")
)
knowledge_graph = json.loads(
    (ROOT / "data" / "knowledge" / "knowledge_graph_summary.json").read_text(encoding="utf-8")
)
skill_topic_map = json.loads(
    (
        ROOT
        / "skills"
        / "liuhui-badminton-coach"
        / "references"
        / "topic-map.json"
    ).read_text(encoding="utf-8")
)
if topic_index["video_count"] != len(douyin_knowledge["videos"]):
    raise SystemExit("Topic index video count is out of sync with full knowledge base")
if topic_index["indexable_video_count"] != ready_count:
    raise SystemExit("Topic index indexable count is out of sync with review statuses")
if topic_index["assigned_video_count"] < 300:
    raise SystemExit(
        f"Topic index assigned too few videos: {topic_index['assigned_video_count']}"
    )
if len(topic_index["categories"]) < 8:
    raise SystemExit("Topic index is missing expected top-level categories")
retrieval_topics_by_id = {
    topic["topic_id"]: topic for topic in retrieval_index["topics"]
}
retrieval_videos_by_topic = {
    topic_id: {
        video["video_id"]
        for video in retrieval_index["videos"]
        if topic_id in video["topic_ids"]
    }
    for topic_id in retrieval_topics_by_id
}
for category in topic_index["categories"]:
    for subtopic in category["subtopics"]:
        topic_id = f"{category['name']}/{subtopic['name']}"
        expected_ids = set(subtopic.get("video_ids", []))
        if len(expected_ids) != subtopic["video_count"]:
            raise SystemExit(f"Topic index membership count is invalid: {topic_id}")
        if retrieval_videos_by_topic.get(topic_id) != expected_ids:
            raise SystemExit(
                f"Retrieval topic membership is out of sync with topic index: {topic_id}"
            )
        if retrieval_topics_by_id.get(topic_id, {}).get("video_count") != len(
            expected_ids
        ):
            raise SystemExit(f"Retrieval topic count is invalid: {topic_id}")
if knowledge_graph["source_updated_at"] != topic_index["source_updated_at"]:
    raise SystemExit("Knowledge graph summary is stale relative to the topic index")
if knowledge_graph["indexable_video_count"] != topic_index["indexable_video_count"]:
    raise SystemExit("Knowledge graph summary is out of sync with the topic index")
if skill_topic_map != knowledge_graph:
    raise SystemExit("Skill topic map is out of sync with the knowledge graph summary")
if len(knowledge_graph["categories"]) != len(topic_index["categories"]):
    raise SystemExit("Knowledge graph summary category count is out of sync")
for graph_output in [
    ROOT / "output" / "liuhui-knowledge-map.mmd",
    ROOT / "output" / "liuhui-knowledge-map.html",
]:
    text = graph_output.read_text(encoding="utf-8")
    if "刘辉羽毛球" not in text or "后场技术" not in text:
        raise SystemExit(f"{graph_output.name} is missing expected topic-map content")

topic_markdown = ROOT / "skills" / "liuhui-badminton-coach" / "references" / "topic-index.md"
if not topic_markdown.exists():
    raise SystemExit("Skill topic index markdown is missing")
if "## Topic Map" not in topic_markdown.read_text(encoding="utf-8"):
    raise SystemExit("Skill topic index markdown is missing the topic map")

skill_text = (
    ROOT / "skills" / "liuhui-badminton-coach" / "SKILL.md"
).read_text(encoding="utf-8")
for required_answer_contract in [
    "text_primary",
    "balanced",
    "video_primary",
    "Never return a link-only answer",
    "核心视频与观看重点",
    "video ID",
    "temporary CDN media URLs",
    "完整相关视频",
    "V1",
    "scripts/feedback.py record",
    "feedback_guidance",
    "global_promoted_feedback",
    "local_accepted_feedback",
    "--no-local-personalization",
    "--plan-only",
    "retrieval_guidance",
    "export-github --confirm-public",
    "did not upload anything",
    "Never upload local feedback without explicit consent",
    "scoped to that answer turn only",
]:
    if required_answer_contract not in skill_text:
        raise SystemExit(
            f"Skill text/video answer contract is missing: {required_answer_contract}"
        )

feedback_script = (
    ROOT / "skills" / "liuhui-badminton-coach" / "scripts" / "feedback.py"
)
feedback_workflow = (
    ROOT
    / "skills"
    / "liuhui-badminton-coach"
    / "references"
    / "feedback-workflow.md"
)
if not feedback_script.exists() or not feedback_workflow.exists():
    raise SystemExit("Skill feedback scripts or workflow are missing")
feedback_script_text = feedback_script.read_text(encoding="utf-8")
for required_export_contract in [
    "export-github",
    "fetch_github_issue",
    "GITHUB_ISSUE_PATTERN",
    '"method": "github_api"',
    "--confirm-public",
    '"uploaded": False',
    '"original_question_included": False',
    '"raw_feedback_included": False',
    '"clause_assignments": parsed["clause_assignments"]',
    '"turn_id": turn_id',
]:
    if required_export_contract not in feedback_script_text:
        raise SystemExit(
            f"Skill feedback export contract is missing: {required_export_contract}"
        )
feedback_workflow_text = feedback_workflow.read_text(encoding="utf-8")
for required_workflow_contract in [
    "sanitized public version",
    "does not upload anything",
    "real public Issue URL",
]:
    if required_workflow_contract not in feedback_workflow_text:
        raise SystemExit(
            f"Skill feedback workflow is missing: {required_workflow_contract}"
        )
for project_feedback_script in [
    ROOT / "scripts" / "promote_feedback.py",
    ROOT / "scripts" / "evaluate_feedback_signals.py",
    ROOT / "scripts" / "test_feedback_personalization.py",
    ROOT / "scripts" / "test_feedback_promotion.py",
    ROOT / "scripts" / "test_public_feedback_e2e.py",
]:
    if not project_feedback_script.exists():
        raise SystemExit(f"Feedback pipeline script is missing: {project_feedback_script.name}")

promotion_script_text = (ROOT / "scripts" / "promote_feedback.py").read_text(
    encoding="utf-8"
)
for required_promotion_guard in [
    "exclusive_promotion_lock",
    "atomic_write_bundle",
    "verified through the API",
    "liuhui-feedback-promotion",
]:
    if required_promotion_guard not in promotion_script_text:
        raise SystemExit(
            f"Public feedback promotion guard is missing: {required_promotion_guard}"
        )

feedback_issue_form = ROOT / ".github" / "ISSUE_TEMPLATE" / "skill-feedback.yml"
if not feedback_issue_form.exists():
    raise SystemExit("GitHub Skill feedback issue form is missing")
feedback_issue_text = feedback_issue_form.read_text(encoding="utf-8")
for required_issue_field in [
    "用户问题",
    "用户真实意图",
    "最有价值的视频",
    "明确不相关的视频",
    "遗漏的视频",
    "需重新核对的视频",
    "文字回答问题",
    "隐私确认",
]:
    if required_issue_field not in feedback_issue_text:
        raise SystemExit(f"GitHub feedback form is missing: {required_issue_field}")
if f"placeholder: {skill_version}" not in feedback_issue_text:
    raise SystemExit("GitHub feedback form version placeholder is stale")
bug_issue_text = (
    ROOT / ".github" / "ISSUE_TEMPLATE" / "bug-report.yml"
).read_text(encoding="utf-8")
if f"v{skill_version}" not in bug_issue_text:
    raise SystemExit("GitHub bug report version placeholder is stale")

feedback_cases = json.loads(
    (ROOT / "data" / "evaluation" / "feedback_parser_cases.json").read_text(
        encoding="utf-8"
    )
)
if len(feedback_cases["cases"]) < 8:
    raise SystemExit("Feedback parser evaluation has too few cases")
if not set(feedback_cases["video_map"].values()).issubset(ready_video_ids):
    raise SystemExit("Feedback parser evaluation references a non-ready video")

practice_template = (
    ROOT
    / "skills"
    / "liuhui-badminton-coach"
    / "references"
    / "practice-plan-template.md"
)
if not practice_template.exists():
    raise SystemExit("Skill practice-plan template is missing")
practice_template_text = practice_template.read_text(encoding="utf-8")
for required_heading in [
    "今日 15 分钟",
    "3 天修正",
    "2 周巩固",
    "来源证据",
    "fallback, not a fixed prescription",
    "solo fallback",
]:
    if required_heading not in practice_template_text:
        raise SystemExit(f"Practice-plan template is missing {required_heading}")

review_queue = json.loads(
    (ROOT / "data" / "review" / "visual_review_queue.json").read_text(encoding="utf-8")
)
review_annotations = json.loads(
    (ROOT / "data" / "review" / "visual_review_annotations.json").read_text(encoding="utf-8")
)
if review_annotations["reviewed_count"] < 25:
    raise SystemExit("Expected at least 25 visual review annotations")
review_status_mapping = {
    "approved": "ready",
    "needs_correction": "needs_correction",
    "not_teaching": "not_teaching",
    "low_value": "low_value",
}
knowledge_by_id = {video["video_id"]: video for video in douyin_knowledge["videos"]}
for annotation in review_annotations["items"]:
    if annotation["review_status"] not in review_status_mapping:
        raise SystemExit("Visual review annotations contain an unknown status")
    video = knowledge_by_id.get(annotation["video_id"])
    if not video or video["processing_status"] != review_status_mapping[annotation["review_status"]]:
        raise SystemExit(
            f"Visual review status was mapped incorrectly: {annotation['video_id']}"
        )
expected_review_count = sum(
    video["processing_status"] in {"needs_visual_review", "needs_correction"}
    for video in douyin_knowledge["videos"]
)
if review_queue["total_pending"] != expected_review_count:
    raise SystemExit("Visual review queue is out of sync with needs_visual_review videos")
if review_queue.get("source_updated_at") != douyin_knowledge["updated_at"]:
    raise SystemExit("Visual review queue is stale relative to the knowledge base")
if len(review_queue["items"]) != expected_review_count:
    raise SystemExit("Visual review queue item count does not match pending count")
if any(item["review_status"] not in review_queue["allowed_review_statuses"] for item in review_queue["items"]):
    raise SystemExit("Visual review queue contains an invalid review status")

review_markdown = ROOT / "output" / "visual_review_queue.md"
if not review_markdown.exists():
    raise SystemExit("Visual review queue markdown is missing")
if "## Top Priority Items" not in review_markdown.read_text(encoding="utf-8"):
    raise SystemExit("Visual review queue markdown is missing top-priority items")

answer_quality_review_markdown = ROOT / "output" / "answer_quality_review_queue.md"
if not answer_quality_review_markdown.exists():
    raise SystemExit("Answer quality review queue markdown is missing")
answer_quality_review_text = answer_quality_review_markdown.read_text(encoding="utf-8")
if f"知识库版本：`{douyin_knowledge['updated_at']}`" not in answer_quality_review_text:
    raise SystemExit("Answer quality review queue is stale relative to the knowledge base")
if answer_quality_review_text.count("## AQ") != len(answer_quality_cases["cases"]):
    raise SystemExit("Answer quality review queue is out of sync with the case registry")
for required_review_contract in [
    "maintainer_decision",
    "required_text_points",
    "required_boundary_points",
    "forbidden_claims",
]:
    if required_review_contract not in answer_quality_review_text:
        raise SystemExit(
            f"Answer quality review queue is missing: {required_review_contract}"
        )
if answer_quality_review_text.count('"maintainer_decision"') != len(
    answer_quality_cases["cases"]
):
    raise SystemExit("Answer quality review queue lacks one structured block per case")

knowledge_map_html = (ROOT / "output" / "liuhui-knowledge-map.html").read_text(
    encoding="utf-8"
)
for unsafe_html_contract in ["innerHTML", "insertAdjacentHTML", "document.write"]:
    if unsafe_html_contract in knowledge_map_html:
        raise SystemExit(
            f"Knowledge-map HTML uses an unsafe DOM sink: {unsafe_html_contract}"
        )
for required_html_guard in [
    "Content-Security-Policy",
    "safeVideoUrl",
    "textContent",
    "noopener noreferrer",
]:
    if required_html_guard not in knowledge_map_html:
        raise SystemExit(f"Knowledge-map HTML is missing guard: {required_html_guard}")

reference_mismatches = skill_reference_mismatches(ROOT)
if reference_mismatches:
    raise SystemExit(
        "Skill reference bundle is out of sync: " + ", ".join(reference_mismatches)
    )

print(
    "Validated JSON, Draw.io, knowledge graph, Skill metadata, full skill sync, "
    "topic index, answer modality contract, answer quality gold registry, local "
    "feedback personalization, public feedback promotion, practice template, and "
    "visual review queue."
)
