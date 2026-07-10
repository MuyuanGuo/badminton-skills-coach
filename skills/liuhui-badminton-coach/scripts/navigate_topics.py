#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOPIC_MAP = ROOT / "references" / "topic-map.json"

LEARNING_TERMS = [
    "系统学",
    "系统学习",
    "学习路径",
    "从零",
    "入门",
    "进阶",
    "路线",
    "顺序",
    "阶段",
    "怎么学",
]
NAVIGATION_TERMS = ["主题", "知识图谱", "图谱", "结构", "目录", "有哪些", "展开"]


def normalize(text):
    return re.sub(r"\s+", "", text.lower())


def score_text(query, values):
    score = 0
    query_norm = normalize(query)
    for value in values:
        value_norm = normalize(value)
        if not value_norm:
            continue
        if value_norm in query_norm:
            score += 6
        if query_norm and query_norm in value_norm:
            score += 4
        for keyword in re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{2,}", value_norm):
            for index in range(max(1, len(keyword) - 1)):
                shard = keyword[index : index + 2]
                if shard in query_norm:
                    score += 1
        for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", value_norm):
            if token in query_norm:
                score += 2
    return score


def detect_intent(query):
    text = normalize(query)
    if any(term in text for term in LEARNING_TERMS):
        return "learning_path"
    if any(term in text for term in NAVIGATION_TERMS):
        return "topic_navigation"
    return "coaching"


def match_topics(graph, query, limit):
    matches = []
    for category in graph["categories"]:
        category_values = [category["name"], category["description"]]
        category_score = score_text(query, category_values)
        for subtopic in category["subtopics"]:
            values = [
                category["name"],
                category["description"],
                subtopic["name"],
                *subtopic["keywords"],
            ]
            for video in subtopic["representative_videos"]:
                values.extend([video["title"], video["category"], video["confidence"]])
            score = category_score + score_text(query, values)
            if score <= 0:
                continue
            matches.append(
                {
                    "category": category["name"],
                    "category_description": category["description"],
                    "subtopic": subtopic["name"],
                    "keywords": subtopic["keywords"],
                    "video_count": subtopic["video_count"],
                    "ready_count": subtopic["ready_count"],
                    "score": score,
                    "representative_videos": subtopic["representative_videos"][:3],
                }
            )
    matches.sort(key=lambda item: (-item["score"], -item["video_count"], item["category"], item["subtopic"]))
    return matches[:limit]


def suggested_queries(query, matches):
    queries = []
    for match in matches[:3]:
        topic_terms = " ".join([match["category"], match["subtopic"], *match["keywords"][:3]])
        queries.append(f"{query} {topic_terms}")
    return queries


def learning_path(matches):
    if not matches:
        return []
    primary = matches[0]
    reps = primary["representative_videos"]
    return [
        {
            "stage": "基础定位",
            "goal": f"先确认问题属于「{primary['category']} / {primary['subtopic']}」的哪个场景。",
            "evidence_leads": reps[:1],
        },
        {
            "stage": "动作原则",
            "goal": "用最强的一到两个证据视频提炼动作原则，不急着叠加多个细节。",
            "evidence_leads": reps[:2],
        },
        {
            "stage": "单点练习",
            "goal": "把原则拆成一个可观察 cue，并设计 10-15 分钟低压力练习。",
            "evidence_leads": reps[:2],
        },
        {
            "stage": "对抗迁移",
            "goal": "加入来球速度、线路或对手压力，只保留一个自测标准。",
            "evidence_leads": reps[:3],
        },
    ]


def main():
    parser = argparse.ArgumentParser(description="Navigate the Liu Hui badminton topic map.")
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    graph = json.loads(TOPIC_MAP.read_text(encoding="utf-8"))
    matches = match_topics(graph, args.query, args.limit)
    payload = {
        "query": args.query,
        "intent": detect_intent(args.query),
        "source": str(TOPIC_MAP.relative_to(ROOT)),
        "matches": matches,
        "suggested_search_queries": suggested_queries(args.query, matches),
        "learning_path": learning_path(matches),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
