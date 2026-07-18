#!/usr/bin/env python3
import hashlib
import json
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_PATH = ROOT / "data" / "knowledge" / "douyin_knowledge_base.json"
TOPIC_INDEX_PATH = ROOT / "data" / "knowledge" / "topic_index.json"
RULES_PATH = ROOT / "config" / "retrieval_rules.json"
OUTPUT_PATH = ROOT / "data" / "knowledge" / "retrieval_index.json"


def flatten(value):
    if isinstance(value, dict):
        return " ".join(flatten(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(flatten(item) for item in value)
    return str(value or "")


def normalize(text):
    return "".join(re.findall(r"[\u4e00-\u9fff]+|[a-z0-9]+", text.lower()))


def ngram_hash(value):
    return hashlib.blake2b(value.encode("utf-8"), digest_size=6).hexdigest()


def hashed_ngrams(text, sizes):
    normalized = normalize(text)
    grams = set()
    for size in sizes:
        for index in range(len(normalized) - size + 1):
            grams.add(ngram_hash(normalized[index : index + size]))
    return grams


def topic_definitions(topic_index):
    topics = []
    for category in topic_index["categories"]:
        for subtopic in category["subtopics"]:
            topics.append(
                {
                    "topic_id": f"{category['name']}/{subtopic['name']}",
                    "category": category["name"],
                    "subtopic": subtopic["name"],
                    "keywords": subtopic["keywords"],
                    "video_ids": set(subtopic["video_ids"]),
                }
            )
    return topics


def build_index(knowledge, topic_index, rules):
    topics = topic_definitions(topic_index)
    lexicon = {
        term
        for group in rules["synonym_groups"]
        for term in group
        if len(normalize(term)) >= 2
    }
    for topic in topics:
        lexicon.update(topic["keywords"])
        lexicon.add(topic["subtopic"])
        lexicon.add(topic["category"])

    sizes = rules["retrieval"]["transcript_ngram_sizes"]
    records = []
    topic_counts = Counter()
    missing_transcripts = []
    for video in knowledge["videos"]:
        if video["processing_status"] != "ready":
            continue
        transcript_path = ROOT / video["transcript_file"]
        if not transcript_path.exists():
            missing_transcripts.append(video["video_id"])
            continue
        transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
        full_text = transcript.get("full_text", "")
        evidence_searchable = normalize(
            flatten(
                {
                    "title": video["title"],
                    "teaching_note": video["teaching_note"],
                    "transcript": full_text,
                }
            )
        )
        matched_terms = sorted(
            term for term in lexicon if normalize(term) in evidence_searchable
        )
        matched_topics = []
        for topic in topics:
            if video["video_id"] in topic["video_ids"]:
                matched_topics.append(topic["topic_id"])
                topic_counts[topic["topic_id"]] += 1
        records.append(
            {
                "video_id": video["video_id"],
                "topic_ids": matched_topics,
                "lexicon_terms": matched_terms,
                "transcript_ngrams": sorted(hashed_ngrams(full_text, sizes)),
            }
        )

    if missing_transcripts:
        raise SystemExit(
            "Missing transcripts for indexable videos: " + ", ".join(missing_transcripts)
        )

    return {
        "version": rules["version"],
        "source": str(KNOWLEDGE_PATH.relative_to(ROOT)),
        "source_updated_at": knowledge["updated_at"],
        "indexable_video_count": len(records),
        "full_transcript_text_included": False,
        "evidence_fields": ["title", "teaching_note", "transcript"],
        "screening_fields_excluded": ["category", "tags"],
        "transcript_ngram_sizes": sizes,
        "topics": [
            {
                **{key: value for key, value in topic.items() if key != "video_ids"},
                "video_count": topic_counts[topic["topic_id"]],
            }
            for topic in topics
        ],
        "videos": records,
    }


def main():
    knowledge = json.loads(KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    topic_index = json.loads(TOPIC_INDEX_PATH.read_text(encoding="utf-8"))
    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    index = build_index(knowledge, topic_index, rules)
    OUTPUT_PATH.write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(OUTPUT_PATH.relative_to(ROOT)),
                "indexable_video_count": index["indexable_video_count"],
                "topics": len(index["topics"]),
                "full_transcript_text_included": False,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
