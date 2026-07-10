#!/usr/bin/env python3
import argparse
from collections import Counter
import json
import math
import re
from pathlib import Path


parser = argparse.ArgumentParser()
parser.add_argument("query")
parser.add_argument("--limit", type=int, default=5)
parser.add_argument("--mode", choices=["hybrid", "keyword", "semantic"], default="hybrid")
args = parser.parse_args()

knowledge_path = Path(__file__).resolve().parents[1] / "references" / "knowledge-base.json"
data = json.loads(knowledge_path.read_text(encoding="utf-8"))

synonyms = {
    "被动": ["被动", "来不及", "后高点", "后场"],
    "底线": ["底线", "后场", "被动", "高远"],
    "压住": ["压住", "被动", "后场", "摆脱"],
    "偷时间": ["偷时间", "来不及", "架拍", "被动"],
    "杀球": ["杀球", "突击", "压球", "落点"],
    "没威胁": ["没威胁", "杀球", "落点", "发力"],
    "平挡": ["平挡", "杀球", "防守反击", "落点"],
    "架拍": ["架拍", "框架", "抬拍"],
    "举拍": ["举拍", "架拍", "抬拍", "框架"],
    "步法": ["步法", "启动", "移动", "回动", "侧身"],
    "侧身": ["侧身", "高速对抗", "步法", "移动"],
    "抽挡": ["抽挡", "平抽挡", "高速对抗", "防守"],
    "网前": ["网前", "搓球", "勾球", "扑球"],
    "双打": ["双打", "轮转", "防守", "封网"],
    "发球": ["发球", "接发", "抓球"],
    "发力": ["发力", "放松", "挥拍", "旋转"],
    "衔接": ["衔接", "回动", "连贯", "下一拍"],
}

domain_phrases = {
    "被压到底线": ["被动", "后场", "高远", "摆脱"],
    "来不及举拍": ["来不及", "架拍", "抬拍", "框架"],
    "来不及抬拍": ["来不及", "架拍", "抬拍", "框架"],
    "后场被压": ["后场", "被动", "高远", "摆脱"],
    "偷出时间": ["偷时间", "来不及", "架拍", "被动"],
    "杀球不重": ["杀球", "发力", "落点", "压球"],
    "杀球没威胁": ["杀球", "落点", "平挡", "防守反击"],
    "双打接发": ["双打", "接发", "发接发", "抓球"],
}


def flatten(value):
    if isinstance(value, dict):
        return " ".join(flatten(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(flatten(item) for item in value)
    return str(value)


def tokenize(text):
    tokens = set()
    for token in re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]+", text.lower()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", token) and len(token) > 8:
            continue
        tokens.add(token)
    return tokens


def expand_terms(query):
    expanded = set(tokenize(query))
    for key, values in synonyms.items():
        if key in query:
            expanded.update(values)
    for phrase, values in domain_phrases.items():
        if phrase in query:
            expanded.update(values)
    return expanded


terms = expand_terms(args.query)
expanded_query = " ".join([args.query, *sorted(terms)])


def searchable_text(video):
    return flatten({
        "title": video["title"],
        "category": video["category"],
        "tags": video["tags"],
        "note": video["teaching_note"],
    }).lower()


def char_ngrams(text, min_n=2, max_n=4):
    normalized = re.sub(r"\s+", "", text.lower())
    chunks = re.findall(r"[\u4e00-\u9fff]+|[a-z0-9]+", normalized)
    grams = Counter()
    for chunk in chunks:
        if re.fullmatch(r"[a-z0-9]+", chunk):
            grams[chunk] += 1
            continue
        for size in range(min_n, max_n + 1):
            if len(chunk) < size:
                continue
            for index in range(0, len(chunk) - size + 1):
                grams[chunk[index:index + size]] += 1
    return grams


def cosine(left, right):
    if not left or not right:
        return 0.0
    shared = set(left) & set(right)
    dot = sum(left[key] * right[key] for key in shared)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


query_vector = char_ngrams(expanded_query)


def keyword_score(searchable):
    value = 0
    matched = []
    for term in terms:
        count = searchable.count(term.lower())
        if count:
            value += min(count, 3)
            matched.append(term)
    return value, sorted(matched)


def score(video):
    searchable = searchable_text(video)
    keyword_value, matched = keyword_score(searchable)
    semantic_value = cosine(query_vector, char_ngrams(searchable))
    if args.mode == "keyword":
        value = float(keyword_value)
    elif args.mode == "semantic":
        value = semantic_value * 20
    else:
        value = keyword_value + semantic_value * 12
    if video["confidence"] == "curated":
        value += 2
    if video["processing_status"] == "needs_visual_review":
        value -= 3
    return value, keyword_value, semantic_value, matched


ranked = []
for video in data["videos"]:
    value, keyword_value, semantic_value, matched = score(video)
    if value > 0 and (matched or semantic_value > 0.08):
        ranked.append({
            "score": round(value, 4),
            "keyword_score": keyword_value,
            "semantic_score": round(semantic_value, 4),
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
    "mode": args.mode,
    "terms": sorted(terms),
    "results": ranked[:args.limit],
}, ensure_ascii=False, indent=2))
