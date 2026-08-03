#!/usr/bin/env python3
"""Candidate scoring, evidence tiers, review budgets, and retrieval policy."""

import bisect
import math
from collections import Counter
from types import SimpleNamespace

def searchable_teaching_note(note):
    return {
        key: value
        for key, value in note.items()
        if key != "coverage_evidence"
    }

def field_values(video):
    return {
        "title": video.get("retrieval_title") or video["title"],
        "teaching_note": flatten(searchable_teaching_note(video["teaching_note"])),
    }


def match_fields(video, term_weights, field_weights):
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
                score += weight * field_weights[field] * occurrences
                matched_terms.add(term)
                field_terms.append(term)
        if field_terms:
            matched_fields[field] = sorted(set(field_terms))
    return score, sorted(matched_terms), matched_fields


def dynamic_term_statistics(
    knowledge,
    terms,
    transcript_excluded_video_ids=None,
    include_field_document_frequency=False,
    retrieval_cohort=None,
):
    terms = {term for term in terms if normalize(term)}
    transcript_excluded_video_ids = set(
        transcript_excluded_video_ids or ()
    )
    document_frequency = Counter()
    field_document_frequency = Counter()
    by_video = {}
    if not terms:
        if include_field_document_frequency:
            return (
                document_frequency,
                by_video,
                {
                    field: Counter()
                    for field in (
                        "title",
                        "teaching_note",
                        "transcript",
                    )
                },
            )
        return document_frequency, by_video
    for video in iter_search_videos(knowledge):
        if video.get("processing_status") != "ready":
            continue
        if (
            retrieval_cohort is not None
            and video.get("retrieval_cohort", "stable_baseline")
            != retrieval_cohort
        ):
            continue
        field_text = {
            "title": normalize(video.get("retrieval_title") or video["title"]),
            "teaching_note": (
                ""
                if video["video_id"] in transcript_excluded_video_ids
                else normalize(
                    flatten(
                        searchable_teaching_note(video["teaching_note"])
                    )
                )
            ),
        }
        if video["video_id"] not in transcript_excluded_video_ids:
            search_transcript = video.get("_runtime_search_transcript")
            field_text["transcript"] = normalize(
                search_transcript
                if search_transcript is not None
                else "".join(
                    segment.get("text", "")
                    for segment in video.get("transcript_segments", [])
                )
            )
        video_frequencies = {}
        video_terms = set()
        for field, text_value in field_text.items():
            frequencies = {
                term: text_value.count(normalize(term))
                for term in terms
                if normalize(term) in text_value
            }
            if frequencies:
                video_frequencies[field] = frequencies
                video_terms.update(frequencies)
                field_document_frequency.update(
                    (field, term) for term in frequencies
                )
        if video_frequencies:
            by_video[video["video_id"]] = video_frequencies
            document_frequency.update(video_terms)
    if include_field_document_frequency:
        return (
            document_frequency,
            by_video,
            {
                field: Counter(
                    {
                        term: count
                        for (term_field, term), count
                        in field_document_frequency.items()
                        if term_field == field
                    }
                )
                for field in (
                    "title",
                    "teaching_note",
                    "transcript",
                )
            },
        )
    return document_frequency, by_video


def bm25_record_fields(
    record,
    term_weights,
    retrieval_index,
    rules,
    dynamic_document_frequency=None,
    dynamic_field_document_frequency=None,
    dynamic_field_frequencies=None,
    excluded_fields=None,
):
    excluded_fields = set(excluded_fields or ())
    stable_cohort = (
        record.get("retrieval_cohort", "stable_baseline")
        == "stable_baseline"
        and retrieval_index.get("stable_field_document_counts")
    )
    legacy_document_count = max(
        1,
        int(
            retrieval_index.get(
                (
                    "stable_indexable_video_count"
                    if stable_cohort
                    else "indexable_video_count"
                ),
                retrieval_index["indexable_video_count"],
            )
        ),
    )
    legacy_document_frequency = dict(
        retrieval_index.get(
            (
                "stable_term_document_frequency"
                if stable_cohort
                else "term_document_frequency"
            ),
            retrieval_index.get("term_document_frequency", {}),
        )
    )
    legacy_document_frequency.update(dynamic_document_frequency or {})
    field_document_counts = retrieval_index.get(
        (
            "stable_field_document_counts"
            if stable_cohort
            else "field_document_counts"
        ),
        {},
    )
    field_document_frequency = retrieval_index.get(
        (
            "stable_field_term_document_frequency"
            if stable_cohort
            else "field_term_document_frequency"
        ),
        {},
    )
    average_lengths = retrieval_index.get(
        (
            "stable_average_field_lengths"
            if stable_cohort
            else "average_field_lengths"
        ),
        {},
    )
    k1 = rules["retrieval"].get("bm25_k1", 1.2)
    b = rules["retrieval"].get("bm25_b", 0.75)
    matched_fields = {}
    matched_terms = set()
    score = 0.0
    for field, field_weight in rules["field_weights"].items():
        if field in excluded_fields:
            continue
        if stable_cohort:
            # Stable records retain the pre-expansion global-DF scorer. The
            # dedicated stable statistics make its scores invariant as new
            # automatic sources are appended, while automatic expansion
            # records use the more selective field-specific model below.
            document_count = legacy_document_count
            document_frequency = legacy_document_frequency
        else:
            document_count = max(
                1,
                int(
                    field_document_counts.get(
                        field,
                        legacy_document_count,
                    )
                ),
            )
            document_frequency = {
                **legacy_document_frequency,
                **field_document_frequency.get(field, {}),
                **(dynamic_field_document_frequency or {}).get(field, {}),
            }
        frequencies = record.get("field_term_frequencies", {}).get(field, {})
        frequencies = {
            **frequencies,
            **(dynamic_field_frequencies or {}).get(field, {}),
        }
        document_length = record.get("field_lengths", {}).get(field, 0)
        average_length = max(1.0, average_lengths.get(field, 1.0))
        field_matches = []
        for term, query_weight in term_weights.items():
            frequency = frequencies.get(term, 0)
            if frequency <= 0:
                continue
            frequency = min(frequency, 8)
            frequency_normalized = (
                frequency * (k1 + 1)
                / (
                    frequency
                    + k1 * (1 - b + b * document_length / average_length)
                )
            )
            df = document_frequency.get(term, 0)
            inverse_frequency = math.log(
                1 + (document_count - df + 0.5) / (df + 0.5)
            )
            score += (
                query_weight
                * field_weight
                * inverse_frequency
                * frequency_normalized
            )
            matched_terms.add(term)
            field_matches.append(term)
        if field_matches:
            matched_fields[field] = sorted(field_matches)
    return score, sorted(matched_terms), matched_fields


def chunk_first_config(retrieval_index):
    chunk_index = retrieval_index.get("chunk_index") or {}
    config = chunk_index.get("config") or {}
    return {
        "enabled": bool(chunk_index.get("chunks")),
        "source_allowlist": set(
            config.get("source_allowlist") or ["bilibili_video"]
        ),
        "legacy_fallback": bool(config.get("legacy_fallback", True)),
        "second_cluster_weight": float(
            config.get("second_cluster_weight", 0.15)
        ),
    }


def chunk_gram_postings(chunk_index, gram):
    posting_lookup = getattr(chunk_index, "lookup_ngram_postings", None)
    if posting_lookup is not None:
        encoded = posting_lookup([gram]).get(gram)
        return [] if encoded is None else decode_chunk_ngram_postings(encoded)
    vocabulary = chunk_index.get("ngram_vocabulary") or []
    postings = chunk_index.get("ngram_postings") or []
    position = bisect.bisect_left(vocabulary, gram)
    if position >= len(vocabulary) or vocabulary[position] != gram:
        return []
    return decode_chunk_ngram_postings(postings[position])


def chunk_query_scores(retrieval_index, expansion, query_grams, rules):
    """Rank transcript chunks and aggregate at most two distinct clusters/video."""

    chunk_index = retrieval_index.get("chunk_index") or {}
    chunks = chunk_index.get("chunks") or []
    if not chunks:
        return {}
    config = chunk_first_config(retrieval_index)
    prepared_index = prepared_retrieval_index(retrieval_index)
    records = prepared_index["record_list"]
    prepared_chunk = prepared_index.get("chunk", {})
    allowed_chunk_indexes = prepared_chunk.get(
        "cluster_indexes", frozenset()
    )
    if not allowed_chunk_indexes:
        return {}

    term_weights = expansion["term_weights"]
    candidate_indexes = set()
    for term in term_weights:
        candidate_indexes.update(
            index
            for index in chunk_index.get("term_postings", {}).get(term, [])
            if index in allowed_chunk_indexes
        )
    query_postings = {}
    for gram in query_grams:
        indexes = [
            index
            for index in chunk_gram_postings(chunk_index, gram)
            if index in allowed_chunk_indexes
        ]
        query_postings[gram] = set(indexes)
        candidate_indexes.update(indexes)
    if not candidate_indexes:
        return {}
    get_many_positions = getattr(chunks, "get_many_positions", None)
    candidate_chunks = (
        get_many_positions(sorted(candidate_indexes))
        if get_many_positions is not None
        else {index: chunks[index] for index in sorted(candidate_indexes)}
    )

    cluster_count = max(1, int(chunk_index.get("cluster_count") or 0))
    stable_cluster_count = max(
        1,
        int(
            chunk_index.get(
                "stable_cluster_count", cluster_count
            )
            or 0
        ),
    )
    average_length = max(
        1.0, float(chunk_index.get("average_chunk_length") or 1.0)
    )
    stable_average_length = max(
        1.0,
        float(
            chunk_index.get(
                "stable_average_chunk_length", average_length
            )
            or 1.0
        ),
    )
    term_df = chunk_index.get("term_cluster_document_frequency") or {}
    stable_term_df = (
        chunk_index.get("stable_term_cluster_document_frequency")
        or term_df
    )
    k1 = rules["retrieval"].get("bm25_k1", 1.2)
    b = rules["retrieval"].get("bm25_b", 0.75)
    transcript_weight = rules["field_weights"]["transcript"]
    min_shared = rules["retrieval"]["transcript_ngram_min_shared"]
    min_coverage = rules["retrieval"]["transcript_ngram_min_query_coverage"]

    gram_cluster_df = {}
    gram_weights = {}
    stable_gram_cluster_df = {}
    stable_gram_weights = {}
    for gram, indexes in query_postings.items():
        cluster_ids = {
            candidate_chunks[index]["cluster_id"] for index in indexes
        }
        gram_cluster_df[gram] = len(cluster_ids)
        gram_weights[gram] = math.log(
            1
            + (cluster_count + 1)
            / (gram_cluster_df[gram] + 1)
        )
        stable_cluster_ids = {
            candidate_chunks[index]["stable_cluster_id"]
            for index in indexes
            if candidate_chunks[index].get("stable_cluster_id")
        }
        stable_gram_cluster_df[gram] = len(stable_cluster_ids)
        stable_gram_weights[gram] = math.log(
            1
            + (stable_cluster_count + 1)
            / (stable_gram_cluster_df[gram] + 1)
        )
    total_gram_weight = sum(gram_weights.values())
    stable_total_gram_weight = sum(stable_gram_weights.values())
    matches_by_video = {}
    for chunk_index_value in sorted(candidate_indexes):
        chunk = candidate_chunks[chunk_index_value]
        record = records[chunk["video_index"]]
        stable_chunk = (
            record.get("retrieval_cohort", "stable_baseline")
            == "stable_baseline"
            and chunk.get("stable_cluster_id")
        )
        active_cluster_count = (
            stable_cluster_count if stable_chunk else cluster_count
        )
        active_average_length = (
            stable_average_length if stable_chunk else average_length
        )
        active_term_df = stable_term_df if stable_chunk else term_df
        active_gram_weights = (
            stable_gram_weights if stable_chunk else gram_weights
        )
        active_total_gram_weight = (
            stable_total_gram_weight
            if stable_chunk
            else total_gram_weight
        )
        frequencies = chunk.get("field_term_frequencies") or {}
        matched_terms = []
        bm25_score = 0.0
        for term, query_weight in term_weights.items():
            frequency = min(8, int(frequencies.get(term) or 0))
            if frequency <= 0:
                continue
            normalized_frequency = (
                frequency
                * (k1 + 1)
                / (
                    frequency
                    + k1
                    * (
                        1
                        - b
                        + b
                        * chunk["normalized_length"]
                        / active_average_length
                    )
                )
            )
            df = int(active_term_df.get(term) or 0)
            inverse_frequency = math.log(
                1
                + (
                    active_cluster_count - df + 0.5
                )
                / (df + 0.5)
            )
            bm25_score += (
                query_weight
                * transcript_weight
                * inverse_frequency
                * normalized_frequency
            )
            matched_terms.append(term)

        shared_grams = {
            gram
            for gram, indexes in query_postings.items()
            if chunk_index_value in indexes
        }
        coverage = (
            sum(
                active_gram_weights[gram] for gram in shared_grams
            )
            / max(1.0, active_total_gram_weight)
        )
        required_shared = 1 if len(query_grams) <= 2 else min_shared
        ngram_match = (
            len(shared_grams) >= required_shared and coverage >= min_coverage
        )
        ngram_score = coverage * 8 if ngram_match else 0.0
        total_score = bm25_score + ngram_score
        if total_score <= 0:
            continue
        video_id = record["video_id"]
        matches_by_video.setdefault(video_id, []).append(
            {
                "chunk_id": chunk["chunk_id"],
                "cluster_id": (
                    chunk["stable_cluster_id"]
                    if stable_chunk
                    else chunk["cluster_id"]
                ),
                "score": total_score,
                "bm25_score": bm25_score,
                "ngram_score": ngram_score,
                "ngram_coverage": coverage,
                "shared_grams": shared_grams,
                "matched_terms": set(matched_terms),
                "start_segment": chunk["start_segment"],
                "end_segment": chunk["end_segment"],
                "start_ms": chunk["start_ms"],
                "end_ms": chunk["end_ms"],
            }
        )

    aggregated = {}
    for video_id, matches in matches_by_video.items():
        matches.sort(
            key=lambda item: (
                -item["score"],
                item["chunk_id"],
            )
        )
        selected = [matches[0]]
        second = next(
            (
                item
                for item in matches[1:]
                if item["cluster_id"] != matches[0]["cluster_id"]
            ),
            None,
        )
        if second is not None:
            selected.append(second)
        second_weight = config["second_cluster_weight"]
        aggregated[video_id] = {
            "best_chunk_id": selected[0]["chunk_id"],
            "matched_chunk_ids": [item["chunk_id"] for item in selected],
            "matched_cluster_ids": [item["cluster_id"] for item in selected],
            "chunk_hints": [
                {
                    key: item[key]
                    for key in (
                        "chunk_id",
                        "cluster_id",
                        "start_segment",
                        "end_segment",
                        "start_ms",
                        "end_ms",
                    )
                }
                for item in selected
            ],
            "bm25_score": selected[0]["bm25_score"]
            + (
                second_weight * selected[1]["bm25_score"]
                if len(selected) > 1
                else 0.0
            ),
            "ngram_score": selected[0]["ngram_score"]
            + (
                second_weight * selected[1]["ngram_score"]
                if len(selected) > 1
                else 0.0
            ),
            "ngram_coverage": selected[0]["ngram_coverage"],
            "shared_grams": set().union(
                *(item["shared_grams"] for item in selected)
            ),
            "matched_terms": set().union(
                *(item["matched_terms"] for item in selected)
            ),
        }
    return aggregated


def choose_tier(
    original_matches,
    matched_concepts,
    query_concept_count,
    expanded_matches,
    matched_topics,
    ngram_match,
    title_concept_count,
    title_matches,
    required_intent_count,
    matched_required_intent_count,
):
    if required_intent_count > matched_required_intent_count:
        return "semantic_lead" if ngram_match else "topic_related"

    required_concepts = min(2, query_concept_count) if query_concept_count else 0
    if query_concept_count and title_concept_count >= required_concepts:
        return "direct"
    if not query_concept_count and set(title_matches) & set(original_matches):
        return "direct"
    if query_concept_count and len(matched_concepts) >= required_concepts:
        return "strong_related"
    if title_matches:
        return "strong_related"
    if len(original_matches) >= max(1, required_concepts):
        return "strong_related"
    if expanded_matches and matched_topics:
        return "topic_related"
    if expanded_matches:
        return "topic_related"
    if matched_topics:
        return "topic_related"
    if ngram_match:
        return "semantic_lead"
    return None


def candidate_sort_key(candidate, rules):
    tier_bonus = rules["retrieval"]["tier_score_bonus"]
    intent_penalty = (
        candidate.get("required_intent_miss_count", 0)
        * rules["retrieval"]["required_intent_miss_penalty"]
    )
    cohort_penalty = (
        rules["retrieval"].get(
            "automatic_expansion_score_penalty", 0.0
        )
        if candidate.get("retrieval_cohort") == "automatic_expansion"
        else 0.0
    )
    supplemental_penalty = (
        rules["retrieval"].get("supplemental_score_penalty", 0.0)
        if candidate.get("answer_eligibility") == "supplemental"
        else 0.0
    )
    ranking_score = (
        candidate["score"]
        + tier_bonus[candidate["relevance_tier"]]
        - intent_penalty
        - candidate.get("excluded_query_penalty", 0)
        - cohort_penalty
        - supplemental_penalty
    )
    return (
        -ranking_score,
        TIER_ORDER[candidate["relevance_tier"]],
        candidate["title"],
        candidate["video_id"],
    )


def refresh_score_breakdown(candidate, rules):
    """Keep the displayed score explanation aligned with the actual sort key."""

    breakdown = dict(candidate.get("score_breakdown") or {})
    feedback_delta = (candidate.get("feedback_adjustment") or {}).get(
        "score_delta", 0.0
    )
    tier_bonus = rules["retrieval"]["tier_score_bonus"][
        candidate["relevance_tier"]
    ]
    required_intent_penalty = (
        candidate.get("required_intent_miss_count", 0)
        * rules["retrieval"]["required_intent_miss_penalty"]
    )
    excluded_query_penalty = candidate.get("excluded_query_penalty", 0.0)
    cohort_penalty = (
        rules["retrieval"].get(
            "automatic_expansion_score_penalty", 0.0
        )
        if candidate.get("retrieval_cohort") == "automatic_expansion"
        else 0.0
    )
    supplemental_penalty = (
        rules["retrieval"].get("supplemental_score_penalty", 0.0)
        if candidate.get("answer_eligibility") == "supplemental"
        else 0.0
    )
    breakdown.update(
        {
            "feedback_adjustment": round(feedback_delta, 4),
            "score_after_feedback": round(candidate["score"], 4),
            "tier_bonus": round(tier_bonus, 4),
            "required_intent_penalty": round(required_intent_penalty, 4),
            "excluded_query_penalty": round(excluded_query_penalty, 4),
            "automatic_expansion_score_penalty": round(
                cohort_penalty, 4
            ),
            "supplemental_score_penalty": round(
                supplemental_penalty, 4
            ),
            "effective_ranking_score": round(
                candidate["score"]
                + tier_bonus
                - required_intent_penalty
                - excluded_query_penalty
                - cohort_penalty
                - supplemental_penalty,
                4,
            ),
        }
    )
    candidate["score_breakdown"] = breakdown


def assign_review_budget(ranked, query_concept_count, rules):
    retrieval = rules["retrieval"]
    limit = (
        retrieval["single_concept_review_limit"]
        if query_concept_count <= 1
        else retrieval["multi_concept_review_limit"]
    )
    review_rank = 0
    automatic_review_rank = 0
    automatic_limit = retrieval.get(
        "automatic_expansion_review_limit", limit
    )
    for candidate in ranked:
        candidate.setdefault(
            "intrinsic_relevance_tier", candidate["relevance_tier"]
        )
        if candidate.get("retrieval_policy_eligible") is False:
            candidate["review_rank"] = None
            candidate["within_review_budget"] = False
            candidate["review_priority"] = "policy_rejected"
            continue
        if candidate["relevance_tier"] not in {"direct", "strong_related"}:
            candidate["review_rank"] = None
            candidate["within_review_budget"] = False
            candidate["review_priority"] = "recall_safeguard"
            continue
        if candidate.get("retrieval_cohort") == "automatic_expansion":
            automatic_review_rank += 1
            candidate["cohort_review_rank"] = automatic_review_rank
            if automatic_review_rank > automatic_limit:
                candidate["review_rank"] = None
                candidate["within_review_budget"] = False
                candidate["review_priority"] = "deferred_cohort_review"
                continue
        else:
            candidate["cohort_review_rank"] = None
        review_rank += 1
        candidate["review_rank"] = review_rank
        candidate["within_review_budget"] = review_rank <= limit
        candidate["review_priority"] = (
            "priority_review" if review_rank <= limit else "deferred_review"
        )


def apply_structured_query_expansion(query, expansion, selection_module, rules):
    actor_query = expansion["intent_frame"].get(
        "actor_query", expansion["positive_query"]
    )
    actor_context = selection_module.query_actor_context(
        SimpleNamespace(normalize=normalize), actor_query, rules
    )
    derived_terms = (
        actor_context.get("derived_search_terms", [])
        if actor_context.get("inferred_target_action")
        else []
    )
    for term in derived_terms:
        expansion["term_weights"][term] = max(
            expansion["term_weights"].get(term, 0), 3.5
        )
        if term not in expansion["synonym_terms"]:
            expansion["synonym_terms"].append(term)
    expansion["synonym_terms"].sort()
    expansion["structured_query_context"] = {
        "target_actor": actor_context["target_actor"],
        "target_action_query": actor_context["target_action_query"],
        "requested_action_scopes": actor_context["requested_action_scopes"],
        "derived_search_terms": derived_terms,
        "event_chain": actor_context.get("event_chain", []),
    }
    return actor_context


def rank_candidates(query, knowledge, retrieval_index, rules, mode="hybrid"):
    expansion = expand_query(query, retrieval_index, rules)
    selection_module, selection_rules = load_selection_policy()
    apply_structured_query_expansion(
        query, expansion, selection_module, selection_rules
    )
    boundary = selection_module.classify_boundary(
        expansion["positive_query"], selection_rules
    )
    if boundary["type"] != "none":
        # Boundary language is an answer constraint, not a technical focus signal.
        expansion["focus_shards"] = []
    prepared_index = prepared_retrieval_index(retrieval_index)
    records = prepared_index["records"]
    topic_ids = {item["topic_id"] for item in expansion["matched_topics"]}
    original_terms = set(expansion["original_terms"])
    equivalent_terms = set(expansion["synonym_terms"])
    expanded_terms = set(expansion["term_weights"])
    matched_groups = expansion["matched_synonym_groups"]
    required_intents = expansion["matched_required_intents"]
    topic_details_by_id = {
        item["topic_id"]: {
            "topic_id": item["topic_id"],
            "category": item["category"],
            "subtopic": item["subtopic"],
            "query_match_reasons": item["reasons"],
        }
        for item in expansion["matched_topics"]
    }

    cleaned_query = expansion["positive_query"]
    for phrase in rules["stop_phrases"]:
        cleaned_query = cleaned_query.replace(phrase, " ")
    query_grams = hashed_ngrams(
        cleaned_query,
        retrieval_index["transcript_ngram_sizes"],
    )
    min_shared = rules["retrieval"]["transcript_ngram_min_shared"]
    min_coverage = rules["retrieval"]["transcript_ngram_min_query_coverage"]
    query_gram_document_frequency, query_gram_matches = inverted_ngram_matches(
        retrieval_index, query_grams
    )
    query_gram_weights = {
        gram: math.log(
            1
            + (retrieval_index["indexable_video_count"] + 1)
            / (query_gram_document_frequency.get(gram, 0) + 1)
        )
        for gram in query_grams
    }
    total_query_gram_weight = sum(query_gram_weights.values())
    stable_query_gram_document_frequency = Counter(
        {
            gram: sum(
                any(
                    gram in channel_grams
                    for channel_grams in matches.values()
                )
                and records[video_id].get(
                    "retrieval_cohort", "stable_baseline"
                )
                == "stable_baseline"
                for video_id, matches in query_gram_matches.items()
            )
            for gram in query_grams
        }
    )
    stable_document_count = max(
        1,
        int(
            retrieval_index.get(
                "stable_indexable_video_count",
                retrieval_index["indexable_video_count"],
            )
        ),
    )
    stable_query_gram_weights = {
        gram: math.log(
            1
            + (stable_document_count + 1)
            / (stable_query_gram_document_frequency.get(gram, 0) + 1)
        )
        for gram in query_grams
    }
    stable_total_query_gram_weight = sum(
        stable_query_gram_weights.values()
    )
    chunk_scores = chunk_query_scores(
        retrieval_index,
        expansion,
        query_grams,
        rules,
    )
    chunk_config = chunk_first_config(retrieval_index)
    chunk_indexed_video_ids = set(
        prepared_retrieval_index(retrieval_index)
        .get("chunk", {})
        .get("indexed_video_ids", ())
    )
    dynamic_terms = set(expansion["term_weights"]) - set(
        retrieval_index.get("term_document_frequency", {})
    )
    (
        dynamic_document_frequency,
        dynamic_frequencies_by_video,
        dynamic_field_document_frequency,
    ) = (
        dynamic_term_statistics(
            knowledge,
            dynamic_terms,
            transcript_excluded_video_ids=chunk_indexed_video_ids,
            include_field_document_frequency=True,
        )
    )
    (
        stable_dynamic_document_frequency,
        stable_dynamic_frequencies_by_video,
        stable_dynamic_field_document_frequency,
    ) = (
        dynamic_term_statistics(
            knowledge,
            dynamic_terms,
            transcript_excluded_video_ids=chunk_indexed_video_ids,
            include_field_document_frequency=True,
            retrieval_cohort="stable_baseline",
        )
    )
    candidate_ids = inverted_candidate_ids(
        retrieval_index, expansion, query_grams
    )
    if candidate_ids is not None:
        candidate_ids.update(chunk_scores)
    empty_channel_matches = {
        "title": set(),
        "teaching_note": set(),
        "transcript": set(),
    }

    ranked = []
    for video in iter_search_videos(knowledge):
        if video["processing_status"] in {"not_teaching", "low_value"}:
            continue
        record = records.get(video["video_id"])
        if not record:
            continue
        if candidate_ids is not None and video["video_id"] not in candidate_ids:
            continue
        use_chunk_transcript = (
            chunk_config["enabled"]
            and video.get("source_type") in chunk_config["source_allowlist"]
            and video["video_id"] in chunk_indexed_video_ids
        )
        chunk_match = chunk_scores.get(video["video_id"])
        stable_record = (
            record.get("retrieval_cohort", "stable_baseline")
            == "stable_baseline"
        )
        field_score, field_terms, matched_fields = bm25_record_fields(
            record,
            expansion["term_weights"],
            retrieval_index,
            rules,
            dynamic_document_frequency=(
                stable_dynamic_document_frequency
                if stable_record
                else dynamic_document_frequency
            ),
            dynamic_field_document_frequency=(
                stable_dynamic_field_document_frequency
                if stable_record
                else dynamic_field_document_frequency
            ),
            dynamic_field_frequencies=(
                stable_dynamic_frequencies_by_video
                if stable_record
                else dynamic_frequencies_by_video
            ).get(video["video_id"], {}),
            excluded_fields={"transcript"} if use_chunk_transcript else None,
        )
        if record.get("metadata_title_trust") == "limited":
            # A title/transcript mismatch is an admission advisory, not proof.
            # Keep title text as a weak recall hint while preventing it from
            # dominating evidence-backed note or transcript matches.
            limited_title_terms = set(matched_fields.get("title", []))
            if limited_title_terms:
                trusted_field_score, _, _ = bm25_record_fields(
                    record,
                    expansion["term_weights"],
                    retrieval_index,
                    rules,
                    dynamic_document_frequency=(
                        stable_dynamic_document_frequency
                        if stable_record
                        else dynamic_document_frequency
                    ),
                    dynamic_field_document_frequency=(
                        stable_dynamic_field_document_frequency
                        if stable_record
                        else dynamic_field_document_frequency
                    ),
                    dynamic_field_frequencies=(
                        stable_dynamic_frequencies_by_video
                        if stable_record
                        else dynamic_frequencies_by_video
                    ).get(video["video_id"], {}),
                    excluded_fields={"title", "transcript"}
                    if use_chunk_transcript
                    else {"title"},
                )
                field_score = trusted_field_score + (
                    field_score - trusted_field_score
                ) * rules["retrieval"].get(
                    "limited_title_score_factor", 0.2
                )
        if use_chunk_transcript:
            transcript_terms = set(
                (chunk_match or {}).get("matched_terms", set())
            ) & expanded_terms
            field_score += float((chunk_match or {}).get("bm25_score") or 0)
        else:
            transcript_terms = set(record["lexicon_terms"]) & expanded_terms
        matched_topic_ids = sorted(set(record["topic_ids"]) & topic_ids)
        topic_score = len(matched_topic_ids) * 2.0
        title_focus_length = max(
            [
                len(normalize(term))
                for term in matched_fields.get("title", [])
                if term in expansion["focus_shards"]
            ]
            or [0]
        )
        note_focus_length = max(
            [
                len(normalize(term))
                for term in matched_fields.get("teaching_note", [])
                if term in expansion["focus_shards"]
            ]
            or [0]
        )
        focus_score = (
            min(title_focus_length, 3)
            * rules["retrieval"].get(
                "exact_focus_title_bonus_per_character", 0
            )
            + min(note_focus_length, 3)
            * rules["retrieval"].get("exact_focus_note_bonus_per_character", 0)
        )

        channel_shared_grams = {
            key: set(value)
            for key, value in query_gram_matches.get(
                video["video_id"], empty_channel_matches
            ).items()
        }
        if use_chunk_transcript:
            channel_shared_grams["transcript"] = set(
                (chunk_match or {}).get("shared_grams", set())
            )
        active_query_gram_weights = (
            stable_query_gram_weights
            if record.get("retrieval_cohort", "stable_baseline")
            == "stable_baseline"
            else query_gram_weights
        )
        active_total_query_gram_weight = (
            stable_total_query_gram_weight
            if record.get("retrieval_cohort", "stable_baseline")
            == "stable_baseline"
            else total_query_gram_weight
        )
        channel_ngram_coverage = {
            channel: (
                sum(
                    active_query_gram_weights[gram]
                    for gram in shared
                )
                / max(1.0, active_total_query_gram_weight)
            )
            for channel, shared in channel_shared_grams.items()
        }
        shared_grams = set().union(*channel_shared_grams.values())
        ngram_coverage = max(channel_ngram_coverage.values(), default=0.0)
        required_shared = 1 if len(query_grams) <= 2 else min_shared
        ngram_match = (
            len(shared_grams) >= required_shared and ngram_coverage >= min_coverage
        )
        if use_chunk_transcript:
            structured_ngram_score = (
                channel_ngram_coverage["title"] * 24
                + channel_ngram_coverage["teaching_note"] * 14
                if ngram_match
                else 0.0
            )
            ngram_score = structured_ngram_score + float(
                (chunk_match or {}).get("ngram_score") or 0
            )
            ngram_match = ngram_match or bool(
                (chunk_match or {}).get("ngram_score")
            )
        else:
            ngram_score = (
                channel_ngram_coverage["title"] * 24
                + channel_ngram_coverage["teaching_note"] * 14
                + channel_ngram_coverage["transcript"] * 8
                if ngram_match
                else 0.0
            )

        if mode == "keyword":
            ngram_match = False
            ngram_score = 0.0
        elif mode == "semantic":
            field_score = 0.0
            topic_score = 0.0
            matched_fields = {}
            field_terms = []
            transcript_terms = set()
            matched_topic_ids = []

        original_matches = sorted(
            (set(field_terms) | transcript_terms) & original_terms
        )
        equivalent_matches = sorted(
            ((set(field_terms) | transcript_terms) & equivalent_terms)
            - set(original_matches)
        )
        direct_matches = sorted(set(original_matches) | set(equivalent_matches))
        expanded_matches = sorted(set(field_terms) | transcript_terms)
        candidate_lexicon_terms = (
            set(transcript_terms) | set(field_terms)
            if use_chunk_transcript
            else set(record["lexicon_terms"]) | set(field_terms)
        )
        matched_concepts = sorted(
            {
                group[0]
                for group in matched_groups
                if any(term in candidate_lexicon_terms for term in group)
            }
        )
        structured_terms = set(matched_fields.get("title", [])) | set(
            matched_fields.get("teaching_note", [])
        )
        matched_structured_concepts = sorted(
            {
                group[0]
                for group in matched_groups
                if any(term in structured_terms for term in group)
            }
        )
        title_terms = set(matched_fields.get("title", []))
        trusted_title_terms = (
            set()
            if record.get("metadata_title_trust") == "limited"
            else title_terms
        )
        strong_title_related = {
            term
            for term in trusted_title_terms
            if any(
                item["term"] == term and item["weight"] >= 0.45
                for item in expansion["related_terms"]
            )
        }
        title_concepts = {
            group[0]
            for group in matched_groups
            if any(term in trusted_title_terms for term in group)
        }
        matched_required_intents = sorted(
            intent["name"]
            for intent in required_intents
            if any(term in expanded_matches for term in intent["terms"])
        )
        candidate_searchable = normalize(
            flatten(
                {
                    "title": video["title"],
                    "teaching_note": video["teaching_note"],
                }
            )
        )
        excluded_matches = sorted(
            term
            for term in expansion["intent_frame"]["excluded_terms"]
            if normalize(term)
            and (
                normalize(term) in candidate_searchable
                or term in candidate_lexicon_terms
            )
        )
        excluded_seed_matches = sorted(
            term
            for term in expansion["intent_frame"]["excluded_seed_terms"]
            if normalize(term)
            and (
                normalize(term) in candidate_searchable
                or term in candidate_lexicon_terms
            )
        )
        expanded_only_matches = set(excluded_matches) - set(excluded_seed_matches)
        excluded_query_penalty = (
            min(3, len(excluded_seed_matches))
            * rules["retrieval"].get("excluded_query_term_penalty", 0)
            + min(3, len(expanded_only_matches))
            * rules["retrieval"].get("excluded_related_term_penalty", 0)
        )
        if (
            topic_ids
            and not matched_topic_ids
            and len(matched_concepts) < 2
            and len(original_matches) < 2
            and not equivalent_matches
            and not strong_title_related
            and not ngram_match
        ):
            continue
        tier = choose_tier(
            direct_matches,
            matched_concepts,
            len(matched_groups),
            expanded_matches,
            matched_topic_ids,
            ngram_match,
            len(title_concepts),
            sorted(title_terms),
            len(required_intents),
            len(matched_required_intents),
        )
        if not tier:
            continue

        channels = []
        if matched_fields:
            channels.append("structured_fields")
        if transcript_terms:
            channels.append(
                "chunk_transcript_lexicon"
                if use_chunk_transcript
                else "full_transcript_lexicon"
            )
        if matched_topic_ids:
            channels.append("full_topic_membership")
        if channel_shared_grams["title"]:
            channels.append("title_ngram")
        if channel_shared_grams["teaching_note"]:
            channels.append("teaching_note_ngram")
        if channel_shared_grams["transcript"]:
            channels.append(
                "chunk_transcript_ngram"
                if use_chunk_transcript
                else "full_transcript_ngram"
            )

        score = (
            field_score
            + topic_score
            + ngram_score
            + focus_score
            + len(matched_concepts) * 4.0
        )
        evidence_quality_bonus = rules["retrieval"].get(
            "evidence_quality_bonus", {}
        ).get(
            video["confidence"], 0.0
        )
        score += evidence_quality_bonus
        candidate = {
                "score": round(score, 4),
                "answer_eligibility": record.get(
                    "answer_eligibility", "primary"
                ),
                "evidence_roles": record.get(
                    "evidence_roles", ["context"]
                ),
                "metadata_title_trust": record.get(
                    "metadata_title_trust", "not_applicable"
                ),
                "runtime_evidence_mode": record.get(
                    "runtime_evidence_mode", "full_transcript"
                ),
                "retrieval_cohort": record.get(
                    "retrieval_cohort", "stable_baseline"
                ),
                "relevance_tier": tier,
                "intrinsic_relevance_tier": tier,
                "retrieval_channels": channels,
                "matched_query_concepts": matched_concepts,
                "matched_structured_query_concepts": (
                    matched_structured_concepts
                ),
                "matched_original_terms": original_matches,
                "matched_equivalent_terms": equivalent_matches,
                "matched_terms": expanded_matches,
                "matched_fields": matched_fields,
                "matched_topics": matched_topic_ids,
                "matched_topic_details": [
                    topic_details_by_id[topic_id]
                    for topic_id in matched_topic_ids
                    if topic_id in topic_details_by_id
                ],
                "matched_required_intents": matched_required_intents,
                "required_intent_miss_count": (
                    len(required_intents) - len(matched_required_intents)
                ),
                "matched_excluded_terms": excluded_matches,
                "matched_excluded_seed_terms": excluded_seed_matches,
                "excluded_query_penalty": excluded_query_penalty,
                "transcript_ngram_coverage": round(ngram_coverage, 4),
                "ngram_match": ngram_match,
                "ngram_coverage_by_field": {
                    field: round(value, 4)
                    for field, value in channel_ngram_coverage.items()
                },
                "score_breakdown": {
                    "structured_field_score": round(field_score, 4),
                    "topic_score": round(topic_score, 4),
                    "ngram_score": round(ngram_score, 4),
                    "exact_focus_score": round(focus_score, 4),
                    "matched_concept_score": round(
                        len(matched_concepts) * 4.0, 4
                    ),
                    "evidence_quality_bonus": round(evidence_quality_bonus, 4),
                    "base_score_before_feedback": round(score, 4),
                },
                "video_id": video["video_id"],
                "title": video["title"],
                "category": video["category"],
                "confidence": video["confidence"],
                "processing_status": video["processing_status"],
                "url": video["url"],
                "transcript_retrieval": (
                    {
                        "mode": "chunk_first",
                        "best_chunk_id": chunk_match.get("best_chunk_id"),
                        "matched_chunk_ids": chunk_match.get(
                            "matched_chunk_ids", []
                        ),
                        "matched_cluster_ids": chunk_match.get(
                            "matched_cluster_ids", []
                        ),
                        "chunk_hints": chunk_match.get("chunk_hints", []),
                    }
                    if use_chunk_transcript and chunk_match
                    else {
                        "mode": (
                            "chunk_first_no_match"
                            if use_chunk_transcript
                            else "legacy_video"
                        ),
                        **(
                            {
                                "best_chunk_id": chunk_match.get(
                                    "best_chunk_id"
                                ),
                                "matched_chunk_ids": chunk_match.get(
                                    "matched_chunk_ids", []
                                ),
                                "matched_cluster_ids": chunk_match.get(
                                    "matched_cluster_ids", []
                                ),
                                "chunk_hints": chunk_match.get(
                                    "chunk_hints", []
                                ),
                            }
                            if chunk_match
                            else {}
                        ),
                    }
                ),
            }
        refresh_score_breakdown(candidate, rules)
        ranked.append(candidate)

    ranked.sort(key=lambda item: candidate_sort_key(item, rules))
    assign_review_budget(ranked, len(matched_groups), rules)
    return ranked, expansion


def apply_retrieval_policy(
    query,
    ranked,
    expansion,
    knowledge,
    retrieval_guidance,
    retrieval_rules,
):
    """Partition surfaced evidence from exhaustive recall without deleting it."""

    selection_module, selection_rules = load_selection_policy()
    boundary = selection_module.classify_boundary(
        expansion["positive_query"], selection_rules
    )
    plan = {
        "query": query,
        "query_expansion": {
            key: value for key, value in expansion.items() if key != "term_weights"
        },
        "retrieval_guidance": retrieval_guidance,
    }
    policy_api = SimpleNamespace(normalize=normalize, flatten=flatten)
    videos = knowledge_video_map(
        knowledge,
        [candidate["video_id"] for candidate in ranked],
        full=False,
    )
    rejected_counts = Counter()
    requested_constraints = selection_module.query_constraints(
        policy_api, expansion["positive_query"], selection_rules
    )
    actor_context = selection_module.query_actor_context(
        policy_api, expansion["positive_query"], selection_rules
    )

    for candidate in ranked:
        video = videos[candidate["video_id"]]
        reasons = []
        if boundary["type"] == "pain_or_injury":
            # A technique match is not direct medical evidence. Preserve the
            # candidate for exhaustive audit, but never label generic coaching
            # footage as intrinsically direct for a pain/injury question.
            if candidate["relevance_tier"] == "direct":
                candidate["relevance_tier"] = "strong_related"
                candidate["intrinsic_relevance_tier"] = "strong_related"
                refresh_score_breakdown(candidate, retrieval_rules)
            reasons.append("medical_boundary_has_no_direct_safety_evidence")
        elif boundary["type"] == "endorsement_or_authorship":
            reasons.append("identity_boundary_does_not_need_teaching_video")
        elif (
            boundary["type"] == "insufficient_observation"
            and "唯一原因" in boundary.get("matched_terms", [])
        ):
            reasons.append("unique_cause_cannot_be_established_without_observation")
        elif (
            boundary["type"] == "purchase_advice"
            and video.get("category")
            not in selection_rules["purchase_allowed_categories"]
        ):
            reasons.append("purchase_query_requires_equipment_evidence")

        if not reasons:
            constraint_scope = _VIDEO_CONSTRAINT_SCOPE_CACHE.get(
                candidate["video_id"]
            )
            if constraint_scope is None:
                constraint_scope = selection_module.video_constraint_scope(
                    policy_api, video, selection_rules
                )
                _VIDEO_CONSTRAINT_SCOPE_CACHE[candidate["video_id"]] = (
                    constraint_scope
                )
            (
                allowed,
                failures,
                policy_requested_constraints,
                _,
                constraint_matches,
            ) = selection_module.constraint_decision(
                policy_api,
                query,
                plan,
                video,
                selection_rules,
                requested=requested_constraints,
                scope=constraint_scope,
            )
            if not allowed:
                reasons.extend(failures)
            else:
                reasons.extend(
                    selection_module.required_constraint_support_failures(
                        policy_requested_constraints,
                        constraint_matches,
                        selection_rules,
                    )
                )
            if not reasons and actor_context.get("inferred_target_action"):
                reasons.extend(
                    selection_module.requested_action_scope_failures(
                        policy_api,
                        actor_context,
                        video,
                        selection_rules,
                    )
                )

        title_normalized = normalize(video.get("title", ""))
        if not reasons and any(
            normalize(term) in title_normalized
            for term in selection_rules["incomplete_fragment_terms"]
        ):
            reasons.append("incomplete_series_fragment")

        structured = selection_module.structured_video_text(policy_api, video)
        positive_query = expansion["positive_query"]
        if (
            not reasons
            and expansion["intent_frame"].get("requested_output") == "comparison"
            and "被动" in positive_query
            and normalize("被动") not in structured
        ):
            reasons.append("comparison_missing_passive_scenario")
        if (
            not reasons
            and "姿势" in positive_query
            and "被动" not in positive_query
            and normalize("被动") in title_normalized
        ):
            reasons.append("basic_form_query_conflicts_with_passive_variant")

        eligible = not reasons
        candidate["retrieval_policy_eligible"] = eligible
        candidate["retrieval_policy_reasons"] = reasons
        rejected_counts.update(reasons)

    ranked.sort(
        key=lambda item: (
            0 if item["retrieval_policy_eligible"] else 1,
            candidate_sort_key(item, retrieval_rules),
        )
    )
    assign_review_budget(
        ranked,
        len(expansion["matched_synonym_groups"]),
        retrieval_rules,
    )
    return ranked, {
        "boundary_type": boundary["type"],
        "eligible_candidate_count": sum(
            item["retrieval_policy_eligible"] for item in ranked
        ),
        "rejected_candidate_count": sum(
            not item["retrieval_policy_eligible"] for item in ranked
        ),
        "rejection_reason_counts": dict(sorted(rejected_counts.items())),
        "exhaustive_candidates_preserved": True,
    }
