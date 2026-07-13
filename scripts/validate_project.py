#!/usr/bin/env python3
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from douyin_pipeline import QUEUE_STATUSES, load_classification_rules, validate_queue_statuses


ROOT = Path(__file__).resolve().parents[1]

json_paths = [
    "config/answer_modality_rules.json",
    "config/douyin_classification_rules.json",
    "config/retrieval_rules.json",
    "data/douyin_teaching_filtered.json",
    "data/douyin_video_index.json",
    "data/evaluation/answer_modality_cases.json",
    "data/evaluation/retrieval_cases.json",
    "data/knowledge/pilot_teaching_notes.json",
    "data/knowledge/douyin_knowledge_base.json",
    "data/knowledge/retrieval_index.json",
    "data/knowledge/topic_index.json",
    "data/knowledge/knowledge_graph_summary.json",
    "data/review/visual_review_annotations.json",
    "data/review/visual_review_queue.json",
    "data/processing/douyin_queue.json",
    "skills/liuhui-badminton-coach/references/answer-modality-rules.json",
    "skills/liuhui-badminton-coach/references/knowledge-base.json",
    "skills/liuhui-badminton-coach/references/retrieval-index.json",
    "skills/liuhui-badminton-coach/references/retrieval-rules.json",
    "skills/liuhui-badminton-coach/references/topic-map.json",
]
for relative_path in json_paths:
    path = ROOT / relative_path
    with path.open(encoding="utf-8") as file:
        json.load(file)

ET.parse(ROOT / "output" / "liuhui-full-knowledge-map.drawio")

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

rules = load_classification_rules()
for required_signal in ["ad_strong", "equipment", "teaching", "non_teaching"]:
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
if skill_knowledge != douyin_knowledge:
    raise SystemExit("Skill knowledge base is out of sync with full Douyin knowledge base")

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

ready_count = sum(video["processing_status"] == "ready" for video in douyin_knowledge["videos"])
review_excluded_count = sum(
    video["processing_status"] in {"not_teaching", "low_value"}
    for video in douyin_knowledge["videos"]
)
pre_pipeline_excluded_count = (
    teaching_filter["counts"].get("excluded_ads", 0)
    + teaching_filter["counts"].get("excluded_non_teaching", 0)
    + teaching_filter["counts"].get("review", 0)
)
all_collected_count = len(video_index["videos"])
if all_collected_count != ready_count + review_excluded_count + pre_pipeline_excluded_count:
    raise SystemExit(
        "Collected-video accounting is inconsistent: expected all videos to equal "
        "ready teaching evidence plus excluded videos"
    )
if teaching_filter["counts"]["kept_teaching"] != len(queue["items"]):
    raise SystemExit("Teaching filter kept count is out of sync with processing queue")
if ready_count != douyin_knowledge["knowledge_counts"].get("ready"):
    raise SystemExit("Knowledge ready count is out of sync with video statuses")

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
if '"full_text"' in retrieval_index_text or '"transcript_text"' in retrieval_index_text:
    raise SystemExit("Retrieval index unexpectedly contains transcript text fields")
allowed_retrieval_video_fields = {
    "video_id",
    "topic_ids",
    "lexicon_terms",
    "transcript_ngrams",
}
if any(set(video) != allowed_retrieval_video_fields for video in retrieval_index["videos"]):
    raise SystemExit("Retrieval index video records contain unexpected fields")
ready_video_ids = {
    video["video_id"]
    for video in douyin_knowledge["videos"]
    if video["processing_status"] == "ready"
}
retrieval_video_ids = {video["video_id"] for video in retrieval_index["videos"]}
if retrieval_video_ids != ready_video_ids:
    raise SystemExit("Retrieval index video IDs do not match ready knowledge videos")

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
latest_ready = next(
    video for video in douyin_knowledge["videos"]
    if video["processing_status"] == "ready"
)
for expected in [
    f"获取到的抖音公开视频：`{all_collected_count}`",
    f"已排除非教学/广告器材内容：`{pre_pipeline_excluded_count + review_excluded_count}`",
    latest_ready["video_id"],
    latest_ready["url"],
]:
    if expected not in readme_text:
        raise SystemExit(f"README current status is missing: {expected}")
ready_count_labels = [
    f"已加入 Skill 知识库的教学视频：`{ready_count}`",
    f"可加入 Skill 知识库的教学视频：`{ready_count}`",
]
if not any(label in readme_text for label in ready_count_labels):
    raise SystemExit(
        "README current status is missing a ready teaching video count; expected one of: "
        + " | ".join(ready_count_labels)
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
if topic_index["indexable_video_count"] != sum(
    video["processing_status"] not in {"not_teaching", "low_value"}
    for video in douyin_knowledge["videos"]
):
    raise SystemExit("Topic index indexable count is out of sync with review statuses")
if topic_index["assigned_video_count"] < 300:
    raise SystemExit(
        f"Topic index assigned too few videos: {topic_index['assigned_video_count']}"
    )
if len(topic_index["categories"]) < 8:
    raise SystemExit("Topic index is missing expected top-level categories")
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
    "完整相关视频",
]:
    if required_answer_contract not in skill_text:
        raise SystemExit(
            f"Skill text/video answer contract is missing: {required_answer_contract}"
        )

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
for required_heading in ["今日 15 分钟", "3 天修正", "2 周巩固", "来源证据"]:
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
expected_review_count = sum(
    video["processing_status"] == "needs_visual_review"
    for video in douyin_knowledge["videos"]
)
if review_queue["total_pending"] != expected_review_count:
    raise SystemExit("Visual review queue is out of sync with needs_visual_review videos")
if len(review_queue["items"]) != expected_review_count:
    raise SystemExit("Visual review queue item count does not match pending count")
if any(item["review_status"] not in review_queue["allowed_review_statuses"] for item in review_queue["items"]):
    raise SystemExit("Visual review queue contains an invalid review status")

review_markdown = ROOT / "output" / "visual_review_queue.md"
if not review_markdown.exists():
    raise SystemExit("Visual review queue markdown is missing")
if "## Top Priority Items" not in review_markdown.read_text(encoding="utf-8"):
    raise SystemExit("Visual review queue markdown is missing top-priority items")

print(
    "Validated JSON, Draw.io, knowledge graph, Skill metadata, full skill sync, "
    "topic index, answer modality contract, practice template, and visual review queue."
)
