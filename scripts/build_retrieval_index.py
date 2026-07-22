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


def searchable_teaching_note(note):
    return {
        key: value
        for key, value in note.items()
        if key != "coverage_evidence"
    }


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
    for group in rules.get("equivalent_groups", []):
        lexicon.update(term for term in group if len(normalize(term)) >= 2)
    for expansion in rules.get("directed_expansions", []):
        lexicon.update(expansion.get("query_terms", []))
        lexicon.update(expansion.get("expanded_terms", {}))
    intent_rules = rules.get("intent", {})
    for key in ["literal_symptom_terms", "scenario_terms", "level_terms"]:
        lexicon.update(intent_rules.get(key, []))
    for topic in topics:
        lexicon.update(topic["keywords"])
        lexicon.add(topic["subtopic"])
        lexicon.add(topic["category"])

    sizes = rules["retrieval"]["transcript_ngram_sizes"]
    records = []
    topic_counts = Counter()
    term_document_frequency = Counter()
    field_length_totals = Counter()
    missing_runtime_segments = []
    for video in knowledge["videos"]:
        if video["processing_status"] != "ready":
            continue
        segments = video.get("transcript_segments") or []
        transcript_backed = video.get("confidence") != "visual_reviewed"
        if transcript_backed and not segments:
            missing_runtime_segments.append(video["video_id"])
            continue
        full_text = "".join(segment.get("text", "") for segment in segments)
        field_text = {
            "title": normalize(video.get("retrieval_title") or video["title"]),
            "teaching_note": normalize(
                flatten(searchable_teaching_note(video["teaching_note"]))
            ),
            "transcript": normalize(full_text),
        }
        evidence_searchable = "".join(field_text.values())
        matched_terms = sorted(
            term for term in lexicon if normalize(term) in evidence_searchable
        )
        field_term_frequencies = {}
        for field, text in field_text.items():
            frequencies = {
                term: text.count(normalize(term))
                for term in matched_terms
                if normalize(term) in text
            }
            field_term_frequencies[field] = frequencies
            field_length_totals[field] += len(text)
        term_document_frequency.update(matched_terms)
        matched_topics = []
        for topic in topics:
            if video["video_id"] in topic["video_ids"]:
                matched_topics.append(topic["topic_id"])
                topic_counts[topic["topic_id"]] += 1
        records.append(
            {
                "video_id": video["video_id"],
                "evidence_id": video["evidence_id"],
                "source_type": video["source_type"],
                "canonical_url": video["canonical_url"],
                "parent_source_id": video["parent_source_id"],
                "clip_start_seconds": video["clip_start_seconds"],
                "clip_end_seconds": video["clip_end_seconds"],
                "topic_ids": matched_topics,
                "lexicon_terms": matched_terms,
                "field_lengths": {
                    field: len(text) for field, text in field_text.items()
                },
                "field_term_frequencies": field_term_frequencies,
                "title_ngrams": sorted(
                    hashed_ngrams(
                        video.get("retrieval_title") or video["title"], sizes
                    )
                ),
                "teaching_note_ngrams": sorted(
                    hashed_ngrams(
                        flatten(searchable_teaching_note(video["teaching_note"])), sizes
                    )
                ),
                "transcript_ngrams": sorted(hashed_ngrams(full_text, sizes)),
            }
        )

    if missing_runtime_segments:
        raise SystemExit(
            "Missing runtime transcript segments for indexable videos: "
            + ", ".join(missing_runtime_segments)
        )

    return {
        "version": rules["version"],
        "source": str(KNOWLEDGE_PATH.relative_to(ROOT)),
        "source_updated_at": knowledge["updated_at"],
        "indexable_video_count": len(records),
        "full_transcript_text_included": False,
        "runtime_transcript_segments_in_knowledge": True,
        "term_document_frequency": dict(sorted(term_document_frequency.items())),
        "average_field_lengths": {
            field: round(total / max(1, len(records)), 4)
            for field, total in sorted(field_length_totals.items())
        },
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
