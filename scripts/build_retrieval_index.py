#!/usr/bin/env python3
import hashlib
import json
import re
from collections import Counter, defaultdict
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


CHINESE_VARIANTS = str.maketrans(
    {
        "後": "后",
        "場": "场",
        "動": "动",
        "發": "发",
        "無": "无",
        "願": "愿",
        "這": "这",
        "個": "个",
        "來": "来",
        "麼": "么",
        "們": "们",
        "線": "线",
        "轉": "转",
        "頂": "顶",
        "軸": "轴",
        "裡": "里",
        "擊": "击",
        "盤": "盘",
        "隨": "随",
        "隱": "隐",
        "繼": "继",
        "續": "续",
        "變": "变",
        "順": "顺",
        "實": "实",
        "話": "话",
        "學": "学",
        "習": "习",
        "會": "会",
        "處": "处",
        "標": "标",
        "準": "准",
        "運": "运",
        "員": "员",
        "對": "对",
        "還": "还",
        "從": "从",
        "種": "种",
        "進": "进",
        "階": "阶",
        "單": "单",
        "雙": "双",
        "網": "网",
        "體": "体",
        "術": "术",
        "區": "区",
        "應": "应",
        "讓": "让",
        "過": "过",
        "遠": "远",
        "邊": "边",
        "壓": "压",
    }
)


def normalize(text):
    normalized = str(text).lower().translate(CHINESE_VARIANTS)
    return "".join(re.findall(r"[\u4e00-\u9fff]+|[a-z0-9]+", normalized))


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


CHUNK_TARGET_SECONDS = 45.0
CHUNK_MINIMUM_SECONDS = 25.0
CHUNK_MAXIMUM_SECONDS = 75.0
CHUNK_CONTEXT_RADIUS_SEGMENTS = 2
CHUNK_SIMHASH_BANDS = 8
CHUNK_SIMHASH_BAND_BITS = 64 // CHUNK_SIMHASH_BANDS
CHUNK_SIMHASH_MAX_DISTANCE = 6
CHUNK_SHINGLE_SIZE = 5
CHUNK_CLUSTER_MIN_JACCARD = 0.78
CHUNK_INDEX_SOURCE_ALLOWLIST = {
    "bilibili_video",
    "douyin_video",
}
CHUNK_FIRST_SOURCE_ALLOWLIST = {"bilibili_video"}


def encode_video_ngram_postings(postings):
    """Store one video's (record index, field mask) postings compactly."""

    return ";".join(f"{record_index},{channel_mask}" for record_index, channel_mask in postings)


def encode_chunk_ngram_postings(indexes):
    """Store one chunk posting list without per-integer JSON objects."""

    return ",".join(str(index) for index in indexes)


def segment_start(segment):
    return float(segment.get("start") or 0.0)


def segment_end(segment):
    return float(segment.get("end") or segment_start(segment))


def chunk_duration(segments, start_index, end_index):
    if start_index >= end_index:
        return 0.0
    return max(
        0.0,
        segment_end(segments[end_index - 1]) - segment_start(segments[start_index]),
    )


def deterministic_chunk_ranges(
    segments,
    target_seconds=CHUNK_TARGET_SECONDS,
    minimum_seconds=CHUNK_MINIMUM_SECONDS,
    maximum_seconds=CHUNK_MAXIMUM_SECONDS,
):
    """Return stable, gap-free segment ranges with a 25-75s target envelope."""

    if not segments:
        return []
    ranges = []
    start_index = 0
    while start_index < len(segments):
        chosen_end = None
        for end_index in range(start_index + 1, len(segments) + 1):
            duration = chunk_duration(segments, start_index, end_index)
            previous_duration = chunk_duration(
                segments,
                start_index,
                end_index - 1,
            )
            if (
                duration > maximum_seconds
                and previous_duration >= minimum_seconds
            ):
                chosen_end = end_index - 1
                break
            if duration >= target_seconds:
                if (
                    previous_duration >= minimum_seconds
                    and abs(previous_duration - target_seconds)
                    <= abs(duration - target_seconds)
                ):
                    chosen_end = end_index - 1
                else:
                    chosen_end = end_index
                break
        if chosen_end is None:
            chosen_end = len(segments)
        ranges.append([start_index, chosen_end])
        start_index = chosen_end

    if len(ranges) >= 2:
        final_start, final_end = ranges[-1]
        if chunk_duration(segments, final_start, final_end) < minimum_seconds:
            previous_start, previous_end = ranges[-2]
            if (
                chunk_duration(segments, previous_start, final_end)
                <= maximum_seconds
            ):
                ranges[-2:] = [[previous_start, final_end]]
            else:
                while (
                    final_start > previous_start + 1
                    and chunk_duration(segments, final_start, final_end)
                    < minimum_seconds
                    and chunk_duration(
                        segments, previous_start, final_start - 1
                    )
                    >= minimum_seconds
                ):
                    final_start -= 1
                ranges[-2:] = [
                    [previous_start, final_start],
                    [final_start, final_end],
                ]
    return [tuple(item) for item in ranges]


def text_shingles(text, size=CHUNK_SHINGLE_SIZE):
    if not text:
        return set()
    if len(text) <= size:
        return {text}
    return {
        text[index : index + size]
        for index in range(len(text) - size + 1)
    }


def simhash64(shingles):
    if not shingles:
        return 0
    weights = [0] * 64
    for shingle in sorted(shingles):
        value = int.from_bytes(
            hashlib.blake2b(
                shingle.encode("utf-8"), digest_size=8
            ).digest(),
            "big",
        )
        for bit in range(64):
            weights[bit] += 1 if value & (1 << bit) else -1
    result = 0
    for bit, weight in enumerate(weights):
        if weight >= 0:
            result |= 1 << bit
    return result


def hamming_distance(left, right):
    return (left ^ right).bit_count()


def shingle_jaccard(left, right):
    if not left and not right:
        return 1.0
    return len(left & right) / max(1, len(left | right))


def assign_content_clusters(chunks):
    """Assign chunks to representative-bounded near-duplicate clusters."""

    clusters = []
    buckets = defaultdict(list)
    for index, chunk in enumerate(chunks):
        simhash = chunk["_simhash"]
        candidate_cluster_indexes = set()
        for band in range(CHUNK_SIMHASH_BANDS):
            key = (
                band,
                (
                    simhash >> (band * CHUNK_SIMHASH_BAND_BITS)
                )
                & ((1 << CHUNK_SIMHASH_BAND_BITS) - 1),
            )
            candidate_cluster_indexes.update(buckets[key])

        matches = []
        for cluster_index in sorted(candidate_cluster_indexes):
            representative_index = clusters[cluster_index]["representative"]
            representative = chunks[representative_index]
            length_ratio = chunk["normalized_length"] / max(
                1, representative["normalized_length"]
            )
            if not 0.7 <= length_ratio <= 1.3:
                continue
            distance = hamming_distance(
                simhash,
                representative["_simhash"],
            )
            if distance > CHUNK_SIMHASH_MAX_DISTANCE:
                continue
            similarity = shingle_jaccard(
                chunk["_shingles"],
                representative["_shingles"],
            )
            if similarity < CHUNK_CLUSTER_MIN_JACCARD:
                continue
            matches.append(
                (
                    -similarity,
                    distance,
                    representative["chunk_id"],
                    cluster_index,
                )
            )

        if matches:
            cluster_index = min(matches)[-1]
            clusters[cluster_index]["members"].append(index)
            continue

        cluster_index = len(clusters)
        clusters.append(
            {
                "representative": index,
                "members": [index],
            }
        )
        for band in range(CHUNK_SIMHASH_BANDS):
            key = (
                band,
                (
                    simhash >> (band * CHUNK_SIMHASH_BAND_BITS)
                )
                & ((1 << CHUNK_SIMHASH_BAND_BITS) - 1),
            )
            buckets[key].append(cluster_index)

    for cluster in clusters:
        representative = chunks[cluster["representative"]]
        fingerprint = hashlib.sha256(
            representative["_normalized_text"].encode("utf-8")
        ).hexdigest()
        cluster_id = "CC" + fingerprint[:16]
        for index in cluster["members"]:
            chunks[index]["cluster_id"] = cluster_id
    return len(clusters)


def build_chunk_index(records, knowledge, lexicon, sizes):
    chunks = []
    normalized_lexicon = [
        (term, normalize(term)) for term in sorted(lexicon)
    ]
    record_indexes = {
        record["video_id"]: index for index, record in enumerate(records)
    }
    for video in knowledge["videos"]:
        if (
            video.get("processing_status") != "ready"
            or video.get("source_type") not in CHUNK_INDEX_SOURCE_ALLOWLIST
            or video.get("video_id") not in record_indexes
        ):
            continue
        video_index = record_indexes[video["video_id"]]
        segments = video.get("transcript_segments") or []
        if not segments:
            continue
        for start_index, end_index in deterministic_chunk_ranges(segments):
            selected = segments[start_index:end_index]
            raw_text = "".join(str(item.get("text") or "") for item in selected)
            normalized_text = normalize(raw_text)
            start_ms = max(0, round(segment_start(selected[0]) * 1000))
            end_ms = max(start_ms, round(segment_end(selected[-1]) * 1000))
            chunk_id = (
                f"{video['evidence_id']}#t{start_ms:09d}-{end_ms:09d}"
            )
            frequencies = {
                term: normalized_text.count(normalized_term)
                for term, normalized_term in normalized_lexicon
                if normalized_term in normalized_text
            }
            matched_terms = list(frequencies)
            shingles = text_shingles(normalized_text)
            simhash = simhash64(shingles)
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "video_index": video_index,
                    "start_segment": start_index,
                    "end_segment": end_index,
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "normalized_length": len(normalized_text),
                    "text_sha256": hashlib.sha256(
                        raw_text.encode("utf-8")
                    ).hexdigest(),
                    "simhash64": f"{simhash:016x}",
                    "field_term_frequencies": frequencies,
                    "_normalized_text": normalized_text,
                    "_shingles": shingles,
                    "_simhash": simhash,
                }
            )

    stable_chunk_indexes = [
        index
        for index, chunk in enumerate(chunks)
        if records[chunk["video_index"]].get(
            "retrieval_cohort", "stable_baseline"
        )
        == "stable_baseline"
    ]
    stable_chunks = [
        dict(chunks[index]) for index in stable_chunk_indexes
    ]
    stable_cluster_count = (
        assign_content_clusters(stable_chunks) if stable_chunks else 0
    )
    for chunk_index, stable_chunk in zip(
        stable_chunk_indexes, stable_chunks
    ):
        chunks[chunk_index]["stable_cluster_id"] = stable_chunk[
            "cluster_id"
        ]
    cluster_count = assign_content_clusters(chunks) if chunks else 0
    term_postings = defaultdict(list)
    term_clusters = defaultdict(set)
    stable_term_clusters = defaultdict(set)
    ngram_postings = defaultdict(list)
    for chunk_index, chunk in enumerate(chunks):
        for term in chunk["field_term_frequencies"]:
            term_postings[term].append(chunk_index)
            term_clusters[term].add(chunk["cluster_id"])
            if chunk.get("stable_cluster_id"):
                stable_term_clusters[term].add(
                    chunk["stable_cluster_id"]
                )
        for gram in sorted(hashed_ngrams(chunk["_normalized_text"], sizes)):
            ngram_postings[gram].append(chunk_index)
    vocabulary = sorted(ngram_postings)
    public_chunks = [
        {
            key: value
            for key, value in chunk.items()
            if not key.startswith("_")
        }
        for chunk in chunks
    ]
    return {
        "schema_version": 2,
        "config": {
            "target_seconds": CHUNK_TARGET_SECONDS,
            "minimum_seconds": CHUNK_MINIMUM_SECONDS,
            "maximum_seconds": CHUNK_MAXIMUM_SECONDS,
            "context_radius_segments": CHUNK_CONTEXT_RADIUS_SEGMENTS,
            "source_allowlist": sorted(CHUNK_FIRST_SOURCE_ALLOWLIST),
            "cluster_source_allowlist": sorted(
                CHUNK_INDEX_SOURCE_ALLOWLIST
            ),
            "legacy_fallback": True,
            "second_cluster_weight": 0.15,
            "clustering": {
                "algorithm": (
                    "simhash64_lsh_representative_bounded_"
                    "shingle_jaccard_v2"
                ),
                "simhash_bands": CHUNK_SIMHASH_BANDS,
                "simhash_band_bits": CHUNK_SIMHASH_BAND_BITS,
                "simhash_max_distance": CHUNK_SIMHASH_MAX_DISTANCE,
                "shingle_size": CHUNK_SHINGLE_SIZE,
                "minimum_jaccard": CHUNK_CLUSTER_MIN_JACCARD,
            },
        },
        "chunk_count": len(public_chunks),
        "cluster_count": cluster_count,
        "stable_cluster_count": stable_cluster_count,
        "average_chunk_length": round(
            sum(item["normalized_length"] for item in public_chunks)
            / max(1, len(public_chunks)),
            4,
        ),
        "stable_average_chunk_length": round(
            sum(
                public_chunks[index]["normalized_length"]
                for index in stable_chunk_indexes
            )
            / max(1, len(stable_chunk_indexes)),
            4,
        ),
        "term_cluster_document_frequency": {
            term: len(cluster_ids)
            for term, cluster_ids in sorted(term_clusters.items())
        },
        "stable_term_cluster_document_frequency": {
            term: len(cluster_ids)
            for term, cluster_ids in sorted(
                stable_term_clusters.items()
            )
        },
        "term_postings": {
            term: indexes for term, indexes in sorted(term_postings.items())
        },
        "ngram_vocabulary": vocabulary,
        "ngram_postings_encoding": "comma_delimited_indexes_v1",
        "ngram_postings": [
            encode_chunk_ngram_postings(ngram_postings[gram])
            for gram in vocabulary
        ],
        "chunks": public_chunks,
    }


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
    stable_term_document_frequency = Counter()
    field_document_counts = Counter()
    field_term_document_frequency = {
        field: Counter()
        for field in ("title", "teaching_note", "transcript")
    }
    field_length_totals = Counter()
    stable_field_document_counts = Counter()
    stable_field_term_document_frequency = {
        field: Counter()
        for field in ("title", "teaching_note", "transcript")
    }
    stable_field_length_totals = Counter()
    missing_runtime_segments = []
    ngram_posting_masks = defaultdict(dict)
    term_postings = defaultdict(list)
    topic_postings = defaultdict(list)
    for video in knowledge["videos"]:
        if video["processing_status"] != "ready":
            continue
        segments = video.get("transcript_segments") or []
        transcript_backed = video.get("confidence") != "visual_reviewed"
        if transcript_backed and not segments:
            missing_runtime_segments.append(video["video_id"])
            continue
        full_text = "".join(segment.get("text", "") for segment in segments)
        chunk_first_transcript = (
            video.get("source_type") in CHUNK_FIRST_SOURCE_ALLOWLIST
        )
        # Bilibili automatic notes are extracted from the same transcript
        # windows that feed the chunk index. Indexing them again at video
        # level repeats high-frequency technique terms and can let a generic
        # long clip outrank a concise, symptom-specific source. Chunk-first
        # sources therefore use the title for video-level recall and the
        # bounded chunk index for transcript evidence.
        video_level_teaching_note = (
            ""
            if chunk_first_transcript
            else flatten(searchable_teaching_note(video["teaching_note"]))
        )
        field_text = {
            "title": normalize(video.get("retrieval_title") or video["title"]),
            "teaching_note": normalize(video_level_teaching_note),
            "transcript": (
                "" if chunk_first_transcript else normalize(full_text)
            ),
        }
        evidence_searchable = "".join(field_text.values())
        matched_terms = sorted(
            term for term in lexicon if normalize(term) in evidence_searchable
        )
        field_term_frequencies = {}
        for field, text in field_text.items():
            frequencies = {
                # Treat title presence as binary. Repeating a technique name
                # in a promotional title must not act like independent
                # evidence or outrank a concise symptom-specific source.
                term: (
                    1
                    if (
                        field == "title"
                        and video.get("retrieval_cohort")
                        == "automatic_expansion"
                    )
                    else text.count(normalize(term))
                )
                for term in matched_terms
                if normalize(term) in text
            }
            field_term_frequencies[field] = frequencies
            field_length_totals[field] += len(text)
            if text:
                field_document_counts[field] += 1
                field_term_document_frequency[field].update(
                    frequencies.keys()
                )
                if video.get("retrieval_cohort") != "automatic_expansion":
                    stable_field_document_counts[field] += 1
                    stable_field_term_document_frequency[field].update(
                        frequencies.keys()
                    )
                    stable_field_length_totals[field] += len(text)
        term_document_frequency.update(matched_terms)
        if video.get("retrieval_cohort") != "automatic_expansion":
            stable_term_document_frequency.update(matched_terms)
        matched_topics = []
        for topic in topics:
            if video["video_id"] in topic["video_ids"]:
                matched_topics.append(topic["topic_id"])
                topic_counts[topic["topic_id"]] += 1
        record_index = len(records)
        channel_ngrams = {
            "title": hashed_ngrams(
                video.get("retrieval_title") or video["title"], sizes
            ),
            "teaching_note": hashed_ngrams(video_level_teaching_note, sizes),
            "transcript": (
                set()
                if chunk_first_transcript
                else hashed_ngrams(full_text, sizes)
            ),
        }
        for mask, channel in [(1, "title"), (2, "teaching_note"), (4, "transcript")]:
            for gram in channel_ngrams[channel]:
                ngram_posting_masks[gram][record_index] = (
                    ngram_posting_masks[gram].get(record_index, 0) | mask
                )
        for term in matched_terms:
            term_postings[term].append(record_index)
        for topic_id in matched_topics:
            topic_postings[topic_id].append(record_index)
        records.append(
            {
                "video_id": video["video_id"],
                "evidence_id": video["evidence_id"],
                "source_type": video["source_type"],
                "retrieval_cohort": video.get(
                    "retrieval_cohort", "stable_baseline"
                ),
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
                "ngram_counts": {
                    channel: len(grams)
                    for channel, grams in channel_ngrams.items()
                },
            }
        )

    if missing_runtime_segments:
        raise SystemExit(
            "Missing runtime transcript segments for indexable videos: "
            + ", ".join(missing_runtime_segments)
        )

    ngram_vocabulary = sorted(ngram_posting_masks)
    chunk_index = build_chunk_index(records, knowledge, lexicon, sizes)
    stable_indexable_video_count = sum(
        record.get("retrieval_cohort", "stable_baseline")
        == "stable_baseline"
        for record in records
    )
    return {
        "schema_version": 2,
        "version": rules["version"],
        "source": str(KNOWLEDGE_PATH.relative_to(ROOT)),
        "source_updated_at": knowledge["updated_at"],
        "indexable_video_count": len(records),
        "stable_indexable_video_count": stable_indexable_video_count,
        "full_transcript_text_included": False,
        "runtime_transcript_segments_in_knowledge": True,
        "term_document_frequency": dict(sorted(term_document_frequency.items())),
        "stable_term_document_frequency": dict(
            sorted(stable_term_document_frequency.items())
        ),
        "field_document_counts": {
            field: field_document_counts[field]
            for field in (
                "teaching_note",
                "title",
                "transcript",
            )
        },
        "field_term_document_frequency": {
            field: dict(sorted(frequencies.items()))
            for field, frequencies in sorted(
                field_term_document_frequency.items()
            )
        },
        "stable_field_document_counts": {
            field: stable_field_document_counts[field]
            for field in (
                "teaching_note",
                "title",
                "transcript",
            )
        },
        "stable_field_term_document_frequency": {
            field: dict(sorted(frequencies.items()))
            for field, frequencies in sorted(
                stable_field_term_document_frequency.items()
            )
        },
        "average_field_lengths": {
            field: round(
                field_length_totals[field]
                / max(1, field_document_counts[field]),
                4,
            )
            for field in (
                "teaching_note",
                "title",
                "transcript",
            )
        },
        "stable_average_field_lengths": {
            field: round(
                stable_field_length_totals[field]
                / max(1, stable_indexable_video_count),
                4,
            )
            for field in (
                "teaching_note",
                "title",
                "transcript",
            )
        },
        "evidence_fields": ["title", "teaching_note", "transcript"],
        "screening_fields_excluded": ["category", "tags"],
        "legacy_transcript_fields_excluded_sources": sorted(
            CHUNK_FIRST_SOURCE_ALLOWLIST
        ),
        "transcript_ngram_sizes": sizes,
        "inverted_index_schema": (
            "parallel_ngram_vocabulary_compact_string_postings_v2"
        ),
        "ngram_vocabulary": ngram_vocabulary,
        "ngram_postings_encoding": (
            "semicolon_delimited_index_mask_pairs_v1"
        ),
        "ngram_postings": [
            encode_video_ngram_postings(
                sorted(ngram_posting_masks[gram].items())
            )
            for gram in ngram_vocabulary
        ],
        "term_postings": {
            term: indexes for term, indexes in sorted(term_postings.items())
        },
        "topic_postings": {
            topic_id: indexes
            for topic_id, indexes in sorted(topic_postings.items())
        },
        "topics": [
            {
                **{key: value for key, value in topic.items() if key != "video_ids"},
                "video_count": topic_counts[topic["topic_id"]],
            }
            for topic in topics
        ],
        "videos": records,
        "chunk_index": chunk_index,
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
