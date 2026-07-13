#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_PATH = ROOT / "references" / "knowledge-base.json"
RETRIEVAL_INDEX_PATH = ROOT / "references" / "retrieval-index.json"
RULES_PATH = ROOT / "references" / "retrieval-rules.json"

FIELD_WEIGHTS = {
    "title": 4.0,
    "category": 2.0,
    "tags": 2.5,
    "teaching_note": 1.5,
}
TIER_ORDER = {
    "direct": 0,
    "strong_related": 1,
    "topic_related": 2,
    "semantic_lead": 3,
}


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


def load_resources():
    knowledge = json.loads(KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    retrieval_index = json.loads(RETRIEVAL_INDEX_PATH.read_text(encoding="utf-8"))
    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    return knowledge, retrieval_index, rules


def build_lexicon(retrieval_index, rules):
    lexicon = {
        term
        for group in rules["synonym_groups"]
        for term in group
        if len(normalize(term)) >= 2
    }
    for topic in retrieval_index["topics"]:
        lexicon.update(topic["keywords"])
        lexicon.add(topic["category"])
        lexicon.add(topic["subtopic"])
    return lexicon


def fallback_shards(query, rules):
    cleaned = query.lower()
    for phrase in rules["stop_phrases"]:
        cleaned = cleaned.replace(phrase.lower(), " ")
    shards = set(re.findall(r"[a-z0-9]{2,}", cleaned))
    for chunk in re.findall(r"[\u4e00-\u9fff]+", cleaned):
        if 2 <= len(chunk) <= 6:
            shards.add(chunk)
            continue
        for size in (2, 3, 4):
            for index in range(len(chunk) - size + 1):
                shard = chunk[index : index + size]
                if shard not in rules["stop_phrases"]:
                    shards.add(shard)
    return shards


def expand_query(query, retrieval_index, rules):
    query_normalized = normalize(query)
    lexicon = build_lexicon(retrieval_index, rules)
    original_terms = {
        term for term in lexicon if normalize(term) in query_normalized
    }
    query_shards = set() if original_terms else fallback_shards(query, rules)

    synonym_terms = set()
    matched_groups = []
    for group in rules["synonym_groups"]:
        if any(normalize(term) in query_normalized for term in group):
            synonym_terms.update(group)
            matched_groups.append(group)

    topic_matches = []
    seed_terms = original_terms | synonym_terms | query_shards
    seed_normalized = {normalize(term) for term in seed_terms}
    for topic in retrieval_index["topics"]:
        score = 0
        reasons = []
        if normalize(topic["subtopic"]) in query_normalized:
            score += 10
            reasons.append(topic["subtopic"])
        if normalize(topic["category"]) in query_normalized:
            score += 5
            reasons.append(topic["category"])
        for keyword in topic["keywords"]:
            keyword_normalized = normalize(keyword)
            if keyword_normalized in query_normalized:
                score += 8
                reasons.append(keyword)
            elif keyword_normalized in seed_normalized:
                score += 4
                reasons.append(keyword)
        if score:
            topic_matches.append(
                {
                    "topic_id": topic["topic_id"],
                    "category": topic["category"],
                    "subtopic": topic["subtopic"],
                    "keywords": topic["keywords"],
                    "score": score,
                    "reasons": sorted(set(reasons)),
                    "video_count": topic["video_count"],
                }
            )
    topic_matches.sort(
        key=lambda item: (-item["score"], item["video_count"], item["topic_id"])
    )
    if topic_matches:
        best_topic_score = topic_matches[0]["score"]
        topic_threshold = max(
            rules["retrieval"]["topic_min_score"],
            best_topic_score * rules["retrieval"]["topic_relative_score"],
        )
        topic_matches = [
            item for item in topic_matches if item["score"] >= topic_threshold
        ]
    topic_matches = topic_matches[: rules["retrieval"]["max_topics"]]
    topic_terms = {
        keyword for topic in topic_matches for keyword in topic["keywords"]
    }

    term_weights = {}
    for term in query_shards:
        term_weights[term] = max(term_weights.get(term, 0), 1.0)
    for term in topic_terms:
        term_weights[term] = max(term_weights.get(term, 0), 1.2)
    for term in synonym_terms:
        term_weights[term] = max(term_weights.get(term, 0), 1.8)
    for term in original_terms:
        term_weights[term] = max(term_weights.get(term, 0), 3.0)

    return {
        "original_terms": sorted(original_terms),
        "query_shards": sorted(query_shards),
        "synonym_terms": sorted(synonym_terms),
        "topic_terms": sorted(topic_terms),
        "term_weights": term_weights,
        "matched_synonym_groups": matched_groups,
        "matched_topics": topic_matches,
    }


def field_values(video):
    return {
        "title": video["title"],
        "category": video["category"],
        "tags": flatten(video["tags"]),
        "teaching_note": flatten(video["teaching_note"]),
    }


def match_fields(video, term_weights):
    matched_fields = {}
    matched_terms = set()
    score = 0.0
    for field, value in field_values(video).items():
        normalized_value = normalize(value)
        field_terms = []
        for term, weight in term_weights.items():
            normalized_term = normalize(term)
            if normalized_term and normalized_term in normalized_value:
                occurrences = min(normalized_value.count(normalized_term), 3)
                score += weight * FIELD_WEIGHTS[field] * occurrences
                matched_terms.add(term)
                field_terms.append(term)
        if field_terms:
            matched_fields[field] = sorted(set(field_terms))
    return score, sorted(matched_terms), matched_fields


def choose_tier(
    original_matches,
    matched_concepts,
    query_concept_count,
    expanded_matches,
    matched_topics,
    ngram_match,
):
    if query_concept_count and len(matched_concepts) >= min(2, query_concept_count):
        return "direct"
    if not query_concept_count and original_matches:
        return "direct"
    if matched_concepts and matched_topics:
        return "strong_related"
    if matched_concepts:
        return "strong_related"
    if expanded_matches and matched_topics:
        return "strong_related"
    if expanded_matches:
        return "strong_related"
    if matched_topics:
        return "topic_related"
    if ngram_match:
        return "semantic_lead"
    return None


def rank_candidates(query, knowledge, retrieval_index, rules, mode="hybrid"):
    expansion = expand_query(query, retrieval_index, rules)
    records = {item["video_id"]: item for item in retrieval_index["videos"]}
    topic_ids = {item["topic_id"] for item in expansion["matched_topics"]}
    original_terms = set(expansion["original_terms"])
    expanded_terms = set(expansion["term_weights"])
    matched_groups = expansion["matched_synonym_groups"]

    cleaned_query = query
    for phrase in rules["stop_phrases"]:
        cleaned_query = cleaned_query.replace(phrase, " ")
    query_grams = hashed_ngrams(
        cleaned_query,
        retrieval_index["transcript_ngram_sizes"],
    )
    min_shared = rules["retrieval"]["transcript_ngram_min_shared"]
    min_coverage = rules["retrieval"]["transcript_ngram_min_query_coverage"]

    ranked = []
    for video in knowledge["videos"]:
        if video["processing_status"] in {"not_teaching", "low_value"}:
            continue
        record = records.get(video["video_id"])
        if not record:
            continue
        field_score, field_terms, matched_fields = match_fields(
            video, expansion["term_weights"]
        )
        transcript_terms = set(record["lexicon_terms"]) & expanded_terms
        transcript_score = sum(
            expansion["term_weights"].get(term, 1.0) for term in transcript_terms
        ) * 1.5
        matched_topic_ids = sorted(set(record["topic_ids"]) & topic_ids)
        topic_score = len(matched_topic_ids) * 4.0

        shared_grams = query_grams & set(record["transcript_ngrams"])
        ngram_coverage = len(shared_grams) / max(1, len(query_grams))
        required_shared = 1 if len(query_grams) <= 2 else min_shared
        ngram_match = (
            len(shared_grams) >= required_shared and ngram_coverage >= min_coverage
        )
        ngram_score = ngram_coverage * 12 if ngram_match else 0.0

        if mode == "keyword":
            ngram_match = False
            ngram_score = 0.0
        elif mode == "semantic":
            field_score = 0.0
            transcript_score = 0.0
            topic_score = 0.0
            matched_fields = {}
            field_terms = []
            transcript_terms = set()
            matched_topic_ids = []

        original_matches = sorted(
            (set(field_terms) | transcript_terms) & original_terms
        )
        expanded_matches = sorted(set(field_terms) | transcript_terms)
        candidate_lexicon_terms = set(record["lexicon_terms"]) | set(field_terms)
        matched_concepts = sorted(
            {
                group[0]
                for group in matched_groups
                if any(term in candidate_lexicon_terms for term in group)
            }
        )
        if (
            topic_ids
            and not matched_topic_ids
            and len(matched_concepts) < 2
            and not ngram_match
        ):
            continue
        tier = choose_tier(
            original_matches,
            matched_concepts,
            len(matched_groups),
            expanded_matches,
            matched_topic_ids,
            ngram_match,
        )
        if not tier:
            continue

        channels = []
        if matched_fields:
            channels.append("structured_fields")
        if transcript_terms:
            channels.append("full_transcript_lexicon")
        if matched_topic_ids:
            channels.append("full_topic_membership")
        if ngram_match:
            channels.append("full_transcript_ngram")

        score = (
            field_score
            + transcript_score
            + topic_score
            + ngram_score
            + len(matched_concepts) * 8.0
        )
        if video["confidence"] == "curated":
            score += 0.75
        elif video["confidence"] == "visual_reviewed":
            score += 0.35
        ranked.append(
            {
                "score": round(score, 4),
                "relevance_tier": tier,
                "retrieval_channels": channels,
                "matched_query_concepts": matched_concepts,
                "matched_original_terms": original_matches,
                "matched_terms": expanded_matches,
                "matched_fields": matched_fields,
                "matched_topics": matched_topic_ids,
                "transcript_ngram_coverage": round(ngram_coverage, 4),
                "video_id": video["video_id"],
                "title": video["title"],
                "category": video["category"],
                "confidence": video["confidence"],
                "processing_status": video["processing_status"],
                "url": video["url"],
            }
        )

    ranked.sort(
        key=lambda item: (
            TIER_ORDER[item["relevance_tier"]],
            -item["score"],
            item["title"],
        )
    )
    return ranked, expansion


def ranked_result(candidate, video):
    return {
        **compact_candidate(candidate),
        "category": video["category"],
        "confidence": video["confidence"],
        "processing_status": video["processing_status"],
        "duration_seconds": video["duration_seconds"],
        "matched_topics": candidate["matched_topics"],
        "retrieval_channels": candidate["retrieval_channels"],
    }


def compact_candidate(candidate):
    return {
        "video_id": candidate["video_id"],
        "title": candidate["title"],
        "url": candidate["url"],
        "score": candidate["score"],
        "relevance_tier": candidate["relevance_tier"],
        "matched_query_concepts": candidate["matched_query_concepts"],
        "matched_original_terms": candidate["matched_original_terms"],
    }


def search(
    query,
    limit=12,
    mode="hybrid",
    recall_mode="exhaustive",
    manifest_offset=0,
    manifest_limit=None,
):
    knowledge, retrieval_index, rules = load_resources()
    ranked, expansion = rank_candidates(
        query,
        knowledge,
        retrieval_index,
        rules,
        mode=mode,
    )
    videos = {video["video_id"]: video for video in knowledge["videos"]}
    if manifest_limit is None:
        manifest_limit = (
            len(ranked)
            if recall_mode == "exhaustive"
            else max(limit, rules["retrieval"]["balanced_manifest_limit"])
        )
    manifest_end = min(len(ranked), manifest_offset + manifest_limit)
    manifest = ranked[manifest_offset:manifest_end]
    next_manifest_offset = manifest_end if manifest_end < len(ranked) else None
    tier_counts = Counter(item["relevance_tier"] for item in ranked)
    channel_counts = Counter(
        channel for item in ranked for channel in item["retrieval_channels"]
    )
    return {
        "query": query,
        "mode": mode,
        "recall_mode": recall_mode,
        "query_expansion": (
            {
                key: value
                for key, value in expansion.items()
                if key != "term_weights"
            }
            if manifest_offset == 0
            else {"pagination": True, "see_manifest_offset": 0}
        ),
        "coverage": {
            "indexable_videos": retrieval_index["indexable_video_count"],
            "candidate_count": len(ranked),
            "candidate_manifest_count": len(manifest),
            "manifest_offset": manifest_offset,
            "manifest_truncated": manifest_offset > 0 or manifest_end < len(ranked),
            "next_manifest_offset": next_manifest_offset,
            "tier_counts": dict(tier_counts),
            "channel_counts": dict(channel_counts),
            "coverage_claim": "high_recall_candidate_set_not_proof_of_semantic_completeness",
        },
        "results": [
            ranked_result(item, videos[item["video_id"]])
            for item in (ranked[:limit] if manifest_offset == 0 else [])
        ],
        "candidate_manifest": [compact_candidate(item) for item in manifest],
    }


def lookup_videos(video_ids, query=""):
    knowledge, retrieval_index, rules = load_resources()
    videos = {video["video_id"]: video for video in knowledge["videos"]}
    records = {item["video_id"]: item for item in retrieval_index["videos"]}
    candidates = {}
    if query:
        ranked, _ = rank_candidates(query, knowledge, retrieval_index, rules)
        candidates = {item["video_id"]: item for item in ranked}
    results = []
    missing = []
    for video_id in video_ids:
        video = videos.get(video_id)
        if not video:
            missing.append(video_id)
            continue
        result = {
            "video_id": video_id,
            "title": video["title"],
            "category": video["category"],
            "confidence": video["confidence"],
            "processing_status": video["processing_status"],
            "url": video["url"],
            "duration_seconds": video["duration_seconds"],
            "teaching_note": video["teaching_note"],
            "retrieval_index": records.get(video_id),
        }
        if video_id in candidates:
            result["query_match"] = candidates[video_id]
        results.append(result)
    return {"query": query, "results": results, "missing_video_ids": missing}


def main():
    parser = argparse.ArgumentParser(
        description="High-recall retrieval over the Liu Hui badminton knowledge base."
    )
    parser.add_argument("query", nargs="?", default="")
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument(
        "--mode", choices=["hybrid", "keyword", "semantic"], default="hybrid"
    )
    parser.add_argument(
        "--recall-mode",
        choices=["exhaustive", "balanced"],
        default="exhaustive",
    )
    parser.add_argument(
        "--video-id",
        action="append",
        default=[],
        help="Return full stored evidence for a candidate video ID; repeat as needed.",
    )
    parser.add_argument("--manifest-offset", type=int, default=0)
    parser.add_argument("--manifest-limit", type=int, default=20)
    args = parser.parse_args()
    if args.video_id:
        payload = lookup_videos(args.video_id, query=args.query)
    else:
        if not args.query.strip():
            parser.error("query is required unless --video-id is provided")
        payload = search(
            args.query,
            limit=args.limit,
            mode=args.mode,
            recall_mode=args.recall_mode,
            manifest_offset=args.manifest_offset,
            manifest_limit=args.manifest_limit,
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
