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

skill_path = ROOT / "skills" / "liuhui-badminton-coach" / "SKILL.md"
skill_text = skill_path.read_text(encoding="utf-8")
frontmatter = re.match(r"\A---\n(.*?)\n---\n", skill_text, re.DOTALL)
if not frontmatter:
    raise SystemExit("SKILL.md is missing YAML frontmatter")
if not re.search(r"^name:\s+liuhui-badminton-coach$", frontmatter.group(1), re.MULTILINE):
    raise SystemExit("SKILL.md has an invalid name")
if not re.search(r"^description:\s+\S+", frontmatter.group(1), re.MULTILINE):
    raise SystemExit("SKILL.md is missing a description")

knowledge = json.loads(
    (ROOT / "data" / "knowledge" / "pilot_knowledge_base.json").read_text(encoding="utf-8")
)
if len(knowledge["videos"]) != 25:
    raise SystemExit(f"Expected 25 pilot videos, found {len(knowledge['videos'])}")

queue = json.loads(
    (ROOT / "data" / "processing" / "douyin_queue.json").read_text(encoding="utf-8")
)
if len(queue["items"]) != 405:
    raise SystemExit(f"Expected 405 teaching videos in queue, found {len(queue['items'])}")
if sum(queue["counts"].values()) != 405:
    raise SystemExit("Douyin queue counts do not sum to 405")

douyin_knowledge = json.loads(
    (ROOT / "data" / "knowledge" / "douyin_knowledge_base.json").read_text(encoding="utf-8")
)
if len(douyin_knowledge["videos"]) < 25:
    raise SystemExit("Full Douyin knowledge base regressed below pilot size")

skill_knowledge = json.loads(
    (
        ROOT
        / "skills"
        / "liuhui-badminton-coach"
        / "references"
        / "knowledge-base.json"
    ).read_text(encoding="utf-8")
)
if skill_knowledge != knowledge:
    raise SystemExit("Skill knowledge base is out of sync with project knowledge base")

print("Validated JSON, Draw.io, Skill metadata, and 25-video knowledge sync.")
