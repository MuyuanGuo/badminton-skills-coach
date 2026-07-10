#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


parser = argparse.ArgumentParser()
parser.add_argument("query")
parser.add_argument("--limit", type=int, default=5)
args = parser.parse_args()

knowledge_path = Path(__file__).resolve().parents[1] / "references" / "knowledge-base.json"
data = json.loads(knowledge_path.read_text(encoding="utf-8"))

synonyms = {
    "被动": ["被动", "来不及", "后高点", "后场"],
    "杀球": ["杀球", "突击", "压球", "落点"],
    "架拍": ["架拍", "框架", "抬拍"],
    "步法": ["步法", "启动", "移动", "回动", "侧身"],
    "侧身": ["侧身", "高速对抗", "步法", "移动"],
    "抽挡": ["抽挡", "平抽挡", "高速对抗", "防守"],
    "网前": ["网前", "搓球", "勾球", "扑球"],
    "双打": ["双打", "轮转", "防守", "封网"],
    "发球": ["发球", "接发", "抓球"],
    "发力": ["发力", "放松", "挥拍", "旋转"],
}

terms = set(re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]+", args.query.lower()))
for key, values in synonyms.items():
    if key in args.query:
        terms.update(values)


def flatten(value):
    if isinstance(value, dict):
        return " ".join(flatten(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(flatten(item) for item in value)
    return str(value)


def score(video):
    searchable = flatten({
        "title": video["title"],
        "category": video["category"],
        "tags": video["tags"],
        "note": video["teaching_note"],
    }).lower()
    value = 0
    matched = []
    for term in terms:
        count = searchable.count(term.lower())
        if count:
            value += min(count, 3)
            matched.append(term)
    if video["confidence"] == "curated":
        value += 2
    if video["processing_status"] == "needs_visual_review":
        value -= 3
    return value, sorted(matched)


ranked = []
for video in data["videos"]:
    value, matched = score(video)
    if value > 0 and matched:
        ranked.append({
            "score": value,
            "matched_terms": matched,
            "video_id": video["video_id"],
            "title": video["title"],
            "category": video["category"],
            "confidence": video["confidence"],
            "processing_status": video["processing_status"],
            "url": video["url"],
            "teaching_note": video["teaching_note"],
        })

ranked.sort(key=lambda item: (-item["score"], item["title"]))
print(json.dumps({
    "query": args.query,
    "terms": sorted(terms),
    "results": ranked[:args.limit],
}, ensure_ascii=False, indent=2))
