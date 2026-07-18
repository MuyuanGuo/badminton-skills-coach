#!/usr/bin/env python3
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "knowledge" / "douyin_knowledge_base.json"
JSON_OUTPUT = ROOT / "data" / "knowledge" / "topic_index.json"
SKILL_MARKDOWN_OUTPUT = (
    ROOT / "skills" / "liuhui-badminton-coach" / "references" / "topic-index.md"
)
TAXONOMY_PATH = ROOT / "config" / "topic_taxonomy.json"


def load_taxonomy(path=TAXONOMY_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def flatten(value):
    if isinstance(value, dict):
        return " ".join(flatten(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(flatten(item) for item in value)
    return str(value)


def video_text_fields(video):
    note = video.get("teaching_note") or {}
    focus = {
        key: note[key]
        for key in ["title", "topic", "problem"]
        if note.get(key)
    }
    evidence = {
        key: value
        for key, value in note.items()
        if key not in {"title", "topic", "problem", "video_id", "url", "category"}
    }
    return {
        "title": str(video.get("retrieval_title") or video["title"]).lower(),
        "focus": flatten(focus).lower(),
        "evidence": flatten(evidence).lower(),
    }


def keyword_hits(text, keywords):
    return sum(text.count(keyword.lower()) for keyword in keywords)


def contains_any(text_fields, terms):
    combined = " ".join(text_fields.values())
    return any(term.lower() in combined for term in terms)


def video_score(text_fields, rule, field_weights, default_minimum_score):
    if rule.get("fallback"):
        return 0, {"title": 0, "focus": 0, "evidence": 0}
    if rule.get("context_any") and not contains_any(
        text_fields, rule["context_any"]
    ):
        return 0, {"title": 0, "focus": 0, "evidence": 0}
    if rule.get("excluded_any") and contains_any(
        text_fields, rule["excluded_any"]
    ):
        return 0, {"title": 0, "focus": 0, "evidence": 0}
    keywords = rule["keywords"]
    hits = {
        "title": keyword_hits(text_fields["title"], keywords),
        "focus": keyword_hits(text_fields["focus"], keywords),
        "evidence": keyword_hits(text_fields["evidence"], keywords),
    }
    score = sum(hits[field] * field_weights[field] for field in hits)
    minimum = rule.get("minimum_score", default_minimum_score)
    if score < minimum:
        return 0, hits
    return score, hits


def compact_video(video, score, match_basis, assignment_method="rule_match"):
    note = video.get("teaching_note") or {}
    return {
        "video_id": video["video_id"],
        "title": video["title"],
        "url": video["url"],
        "category": video["category"],
        "confidence": video["confidence"],
        "processing_status": video["processing_status"],
        "topic": note.get("topic") or note.get("title") or video["title"],
        "score": score,
        "match_basis": match_basis,
        "assignment_method": assignment_method,
    }


def confidence_order(confidence):
    return {
        "curated": 0,
        "reviewed_transcript": 1,
        "visual_reviewed": 2,
        "medium": 3,
    }.get(confidence, 4)


def build_index(data, taxonomy=None):
    taxonomy = taxonomy or load_taxonomy()
    coverage_counter = Counter()
    videos = [
        video
        for video in data["videos"]
        if video["processing_status"] == "ready"
    ]
    videos_by_id = {video["video_id"]: video for video in videos}
    text_cache = {
        video["video_id"]: video_text_fields(video) for video in videos
    }
    matches_by_topic = defaultdict(list)
    topic_rules = {}
    for category in taxonomy["categories"]:
        for rule in category["subtopics"]:
            topic_id = f"{category['name']}/{rule['name']}"
            topic_rules[topic_id] = (category, rule)
            if rule.get("fallback"):
                continue
            for video in videos:
                score, match_basis = video_score(
                    text_cache[video["video_id"]],
                    rule,
                    taxonomy["field_weights"],
                    taxonomy["default_minimum_score"],
                )
                if score > 0:
                    matches_by_topic[topic_id].append(
                        compact_video(video, score, match_basis)
                    )
                    coverage_counter[video["video_id"]] += 1

    fallback_count = 0
    for video in videos:
        if coverage_counter[video["video_id"]] > 0:
            continue
        topic_id = taxonomy["fallback_by_source_category"].get(video["category"])
        if not topic_id or topic_id not in topic_rules:
            raise ValueError(
                f"No valid fallback topic for source category {video['category']!r}"
            )
        matches_by_topic[topic_id].append(
            compact_video(
                video,
                0,
                {"title": 0, "focus": 0, "evidence": 0},
                assignment_method="category_fallback",
            )
        )
        coverage_counter[video["video_id"]] += 1
        fallback_count += 1

    categories = []
    for category in taxonomy["categories"]:
        subtopics = []
        category_video_ids = set()
        for rule in category["subtopics"]:
            topic_id = f"{category['name']}/{rule['name']}"
            matches = matches_by_topic[topic_id]
            matches.sort(
                key=lambda item: (
                    -item["score"],
                    item["assignment_method"] == "category_fallback",
                    confidence_order(item["confidence"]),
                    item["title"],
                )
            )
            category_video_ids.update(item["video_id"] for item in matches)
            subtopics.append(
                {
                    "name": rule["name"],
                    "keywords": rule["keywords"],
                    "context_any": rule.get("context_any", []),
                    "is_fallback": bool(rule.get("fallback")),
                    "video_count": len(matches),
                    "ready_count": len(matches),
                    "needs_visual_review_count": 0,
                    "video_ids": [item["video_id"] for item in matches],
                    "representative_videos": matches[:5],
                }
            )
        categories.append(
            {
                "name": category["name"],
                "description": category["description"],
                "discipline": category.get("discipline", "general"),
                "video_count": len(category_video_ids),
                "subtopics": subtopics,
            }
        )

    assigned_video_ids = set(coverage_counter)
    unassigned = sorted(set(videos_by_id) - assigned_video_ids)
    return {
        "version": "topic-index-v2",
        "taxonomy_version": taxonomy["version"],
        "taxonomy_source": str(TAXONOMY_PATH.relative_to(ROOT)),
        "source": str(SOURCE.relative_to(ROOT)),
        "scope": data.get("scope"),
        "source_updated_at": data.get("updated_at"),
        "video_count": len(data["videos"]),
        "indexable_video_count": len(videos),
        "assigned_video_count": len(assigned_video_ids),
        "unassigned_video_ids": unassigned,
        "fallback_assigned_video_count": fallback_count,
        "multi_topic_video_count": sum(count > 1 for count in coverage_counter.values()),
        "categories": categories,
    }


def markdown(index):
    lines = [
        "# 刘辉羽毛球主题索引",
        "",
        "Use this index to orient retrieval and answer structure. It is a topic map, not a substitute for timestamped evidence from `knowledge-base.json`.",
        "",
        f"- Source: `{index['source']}`",
        f"- Videos: `{index['video_count']}`",
        f"- Assigned videos: `{index['assigned_video_count']}`",
        f"- Multi-topic videos: `{index['multi_topic_video_count']}`",
        "",
        "## How To Use",
        "",
        "1. Locate the user's issue in the topic map.",
        "2. Run `scripts/search_knowledge.py` with the user's actual words and the closest topic keywords.",
        "3. Use representative videos only as leads; cite timestamped evidence from retrieved entries.",
        "4. Only `ready` videos are included; review-queue items cannot become answer evidence early.",
        "",
        "## Topic Map",
        "",
    ]

    for category in index["categories"]:
        lines.extend(
            [
                f"### {category['name']}",
                "",
                f"{category['description']}",
                "",
                f"- Matched videos: `{category['video_count']}`",
                "",
            ]
        )
        for subtopic in category["subtopics"]:
            lines.append(
                f"- **{subtopic['name']}**: `{subtopic['video_count']}` videos, "
                f"`{subtopic['ready_count']}` ready, "
                f"`{subtopic['needs_visual_review_count']}` needs visual review."
            )
            keywords = ", ".join(subtopic["keywords"]) or "none"
            lines.append(f"  Keywords: {keywords}")
            reps = subtopic["representative_videos"][:3]
            if reps:
                lines.append("  Representative videos:")
                for video in reps:
                    status = video["processing_status"]
                    lines.append(
                        f"  - {video['title']} [{status}] {video['url']}"
                    )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main():
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    index = build_index(data)
    JSON_OUTPUT.write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    SKILL_MARKDOWN_OUTPUT.write_text(markdown(index), encoding="utf-8")
    print(
        json.dumps(
            {
                "video_count": index["video_count"],
                "assigned_video_count": index["assigned_video_count"],
                "categories": len(index["categories"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
