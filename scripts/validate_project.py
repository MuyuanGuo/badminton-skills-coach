#!/usr/bin/env python3
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

json_paths = [
    "data/douyin_teaching_filtered.json",
    "data/douyin_video_index.json",
    "data/knowledge/pilot_knowledge_base.json",
    "data/knowledge/pilot_teaching_notes.json",
    "data/knowledge/douyin_knowledge_base.json",
    "data/knowledge/topic_index.json",
    "data/evaluation/golden_questions.json",
    "data/review/visual_review_annotations.json",
    "data/review/visual_review_queue.json",
    "data/pilot_25_videos.json",
    "data/processing/douyin_queue.json",
    "output/liuhui-skill-retrieval-evaluation.json",
    "skills/liuhui-badminton-coach/references/knowledge-base.json",
]
for relative_path in json_paths:
    path = ROOT / relative_path
    with path.open(encoding="utf-8") as file:
        json.load(file)

ET.parse(ROOT / "output" / "liuhui-pilot-knowledge-map.drawio")

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
if len(queue["items"]) < 405:
    raise SystemExit(f"Expected at least 405 teaching videos in queue, found {len(queue['items'])}")
if sum(queue["counts"].values()) != len(queue["items"]):
    raise SystemExit("Douyin queue counts do not sum to the queue length")

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

topic_index = json.loads(
    (ROOT / "data" / "knowledge" / "topic_index.json").read_text(encoding="utf-8")
)
golden_questions = json.loads(
    (ROOT / "data" / "evaluation" / "golden_questions.json").read_text(encoding="utf-8")
)
if len(golden_questions.get("cases", [])) < 18:
    raise SystemExit("Golden question set has too few cases")

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

topic_markdown = ROOT / "skills" / "liuhui-badminton-coach" / "references" / "topic-index.md"
if not topic_markdown.exists():
    raise SystemExit("Skill topic index markdown is missing")
if "## Topic Map" not in topic_markdown.read_text(encoding="utf-8"):
    raise SystemExit("Skill topic index markdown is missing the topic map")

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

print("Validated JSON, Draw.io, Skill metadata, full skill sync, topic index, practice template, and visual review queue.")
