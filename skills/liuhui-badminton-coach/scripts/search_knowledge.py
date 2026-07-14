#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_PATH = ROOT / "references" / "knowledge-base.json"
RETRIEVAL_INDEX_PATH = ROOT / "references" / "retrieval-index.json"
RULES_PATH = ROOT / "references" / "retrieval-rules.json"
ANSWER_RULES_PATH = ROOT / "references" / "answer-modality-rules.json"
FEEDBACK_RULES_PATH = ROOT / "references" / "feedback-rules.json"
FEEDBACK_SIGNALS_PATH = ROOT / "references" / "feedback-signals.json"

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


def load_answer_rules():
    return json.loads(ANSWER_RULES_PATH.read_text(encoding="utf-8"))


def classify_answer_mode(query, rules=None):
    rules = rules or load_answer_rules()
    query_normalized = normalize(query)
    scores = {}
    matched_signals = {}
    for mode, config in rules["modes"].items():
        matched = []
        score = 0.0
        for term, weight in config["signals"].items():
            if normalize(term) in query_normalized:
                matched.append(term)
                score += weight
        scores[mode] = score
        matched_signals[mode] = matched

    decisive_text = [
        term
        for term in rules["decision"]["decisive_text_terms"]
        if normalize(term) in query_normalized
    ]
    decisive_video = [
        term
        for term in rules["decision"]["decisive_video_terms"]
        if normalize(term) in query_normalized
    ]
    if decisive_text and decisive_video:
        mode = "balanced"
        reason = "query_contains_both_textual_decision_and_visual_form_signals"
    elif decisive_video:
        mode = "video_primary"
        reason = "query_contains_visual_form_signal"
    elif decisive_text:
        mode = "text_primary"
        reason = "query_contains_textual_decision_signal"
    else:
        ranked_modes = sorted(scores, key=lambda item: (-scores[item], item))
        top_mode = ranked_modes[0]
        second_score = scores[ranked_modes[1]]
        if scores[top_mode] <= 0:
            mode = rules["default_mode"]
            reason = "no_mode_signal_defaulted_to_balanced"
        elif top_mode == "balanced":
            mode = "balanced"
            reason = "execution_and_demonstration_signals_dominate"
        elif scores[top_mode] - second_score >= rules["decision"]["minimum_score_margin"]:
            mode = top_mode
            reason = "one_mode_has_clear_score_margin"
        else:
            mode = "balanced"
            reason = "mixed_signals_without_clear_margin"

    config = rules["modes"][mode]
    return {
        "mode": mode,
        "label": config["label"],
        "reason": reason,
        "scores": scores,
        "matched_signals": matched_signals,
        "decisive_text_terms": decisive_text,
        "decisive_video_terms": decisive_video,
        "text_obligations": config["text_obligations"],
        "video_obligations": config["video_obligations"],
        "global_obligations": rules["global_obligations"],
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


def load_feedback_rules():
    return json.loads(FEEDBACK_RULES_PATH.read_text(encoding="utf-8"))


def default_feedback_dir():
    override = os.environ.get("LIUHUI_FEEDBACK_DIR")
    if override:
        return Path(override).expanduser()
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    return codex_home / "feedback" / "liuhui-badminton-coach"


def character_grams(text, size=2):
    normalized = normalize(text)
    if len(normalized) <= size:
        return {normalized} if normalized else set()
    return {
        normalized[index : index + size]
        for index in range(len(normalized) - size + 1)
    }


def jaccard(left, right):
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def feedback_signature(query, expansion):
    terms = {
        normalize(term)
        for key in ["original_terms", "query_shards", "synonym_terms", "topic_terms"]
        for term in expansion[key]
        if normalize(term)
    }
    topics = {topic["topic_id"] for topic in expansion["matched_topics"]}
    return {
        "normalized": normalize(query),
        "terms": terms,
        "topics": topics,
        "character_grams": character_grams(query),
    }


def feedback_query_similarity(
    current_signature,
    feedback_query,
    retrieval_index,
    retrieval_rules,
):
    feedback_expansion = expand_query(feedback_query, retrieval_index, retrieval_rules)
    feedback_signature_value = feedback_signature(feedback_query, feedback_expansion)
    if (
        current_signature["normalized"]
        and current_signature["normalized"] == feedback_signature_value["normalized"]
    ):
        return 1.0
    term_score = jaccard(current_signature["terms"], feedback_signature_value["terms"])
    topic_score = jaccard(current_signature["topics"], feedback_signature_value["topics"])
    character_score = jaccard(
        current_signature["character_grams"],
        feedback_signature_value["character_grams"],
    )
    score = term_score * 0.55 + topic_score * 0.25 + character_score * 0.20
    return round(min(1.0, score), 4)


def load_global_feedback_records():
    if not FEEDBACK_SIGNALS_PATH.exists():
        return [], {"signal_count": 0, "updated_at": None}
    payload = json.loads(FEEDBACK_SIGNALS_PATH.read_text(encoding="utf-8"))
    return payload["signals"], {
        "signal_count": len(payload["signals"]),
        "updated_at": payload.get("updated_at"),
    }


def load_local_feedback_records(feedback_dir=None):
    queue_dir = Path(feedback_dir or default_feedback_dir()) / "queue"
    records = []
    stats = {
        "queue_file_count": 0,
        "accepted_record_count": 0,
        "usable_record_count": 0,
        "skipped_record_count": 0,
    }
    for path in sorted(queue_dir.glob("*.json")):
        stats["queue_file_count"] += 1
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            stats["skipped_record_count"] += 1
            continue
        if record.get("status") != "accepted":
            continue
        if record.get("source", {}).get("type") != "local":
            continue
        stats["accepted_record_count"] += 1
        if record.get("parser_warnings") or not record.get("question"):
            stats["skipped_record_count"] += 1
            continue
        records.append(record)
    stats["usable_record_count"] = len(records)
    return records, stats


def feedback_record_values(record, layer):
    if layer == "global":
        return {
            "record_id": record["signal_id"],
            "query": record["public_query"],
            "helpful_video_ids": record.get("helpful_video_ids", []),
            "irrelevant_video_ids": record.get("irrelevant_video_ids", []),
            "missing_video_ids": record.get("missing_video_ids", []),
            "text_issue_types": record.get("answer_issue_types", []),
            "outcome": None,
        }
    signals = record.get("signals", {})
    return {
        "record_id": record["feedback_id"],
        "query": record["question"],
        "helpful_video_ids": signals.get("helpful_video_ids", []),
        "irrelevant_video_ids": signals.get("irrelevant_video_ids", []),
        "missing_video_ids": signals.get("missing_video_ids", []),
        "text_issue_types": signals.get("text_issue_types", []),
        "outcome": signals.get("outcome"),
    }


def build_feedback_adjustments(
    layer,
    records,
    current_signature,
    retrieval_index,
    retrieval_rules,
    feedback_rules,
):
    config = feedback_rules["personalization"]
    weights = config["weights"]
    threshold = config["query_similarity_threshold"]
    adjustments = defaultdict(
        lambda: {
            "delta": 0.0,
            "positive_strength": 0.0,
            "negative_strength": 0.0,
            "max_positive_similarity": 0.0,
            "max_negative_similarity": 0.0,
            "record_ids": set(),
            "reasons": set(),
        }
    )
    matched_ids = []
    reminders = set()
    for record in records:
        values = feedback_record_values(record, layer)
        similarity = feedback_query_similarity(
            current_signature,
            values["query"],
            retrieval_index,
            retrieval_rules,
        )
        if similarity < threshold:
            continue
        matched_ids.append(values["record_id"])
        reminders.update(values["text_issue_types"])
        if values["outcome"] == "unresolved":
            reminders.add("hard_to_apply")
        elif values["outcome"] == "misunderstood":
            reminders.add("scenario_mismatch")

        helpful_ids = set(values["helpful_video_ids"])
        missing_ids = set(values["missing_video_ids"]) - helpful_ids
        signal_groups = [
            (helpful_ids, weights[f"{layer}_helpful"], "helpful"),
            (missing_ids, weights[f"{layer}_missing"], "missing"),
            (
                set(values["irrelevant_video_ids"]),
                weights[f"{layer}_irrelevant"],
                "irrelevant",
            ),
        ]
        for video_ids, weight, reason in signal_groups:
            for video_id in video_ids:
                adjustment = adjustments[video_id]
                weighted_delta = similarity * weight
                adjustment["delta"] += weighted_delta
                adjustment["record_ids"].add(values["record_id"])
                adjustment["reasons"].add(reason)
                if weight > 0:
                    adjustment["positive_strength"] += abs(weighted_delta)
                    adjustment["max_positive_similarity"] = max(
                        adjustment["max_positive_similarity"], similarity
                    )
                else:
                    adjustment["negative_strength"] += abs(weighted_delta)
                    adjustment["max_negative_similarity"] = max(
                        adjustment["max_negative_similarity"], similarity
                    )

    max_delta = config["max_abs_delta_per_layer"]
    for adjustment in adjustments.values():
        adjustment["delta"] = max(-max_delta, min(max_delta, adjustment["delta"]))
        adjustment["record_ids"] = sorted(adjustment["record_ids"])
        adjustment["reasons"] = sorted(adjustment["reasons"])
    return dict(adjustments), sorted(matched_ids), sorted(reminders)


def local_answer_preferences(records, matched_reminders, public_reminders, feedback_rules):
    issue_counts = Counter(
        issue_type
        for record in records
        for issue_type in record.get("signals", {}).get("text_issue_types", [])
    )
    outcome_counts = Counter(
        record.get("signals", {}).get("outcome")
        for record in records
        if record.get("signals", {}).get("outcome")
    )
    minimum = feedback_rules["personalization"]["local_preference_min_count"]
    concise_count = issue_counts["too_verbose"]
    detailed_count = sum(
        issue_counts[issue_type]
        for issue_type in ["missing_content", "too_vague", "hard_to_apply"]
    )
    if concise_count >= minimum and concise_count > detailed_count:
        verbosity = "concise"
    elif detailed_count >= minimum and detailed_count > concise_count:
        verbosity = "detailed"
    else:
        verbosity = "default"
    reminders = sorted(set(matched_reminders) | set(public_reminders))
    return {
        "preferred_verbosity": verbosity,
        "query_reminders": reminders,
        "needs_more_boundaries": (
            "scenario_mismatch" in reminders
            or issue_counts["scenario_mismatch"] >= minimum
            or outcome_counts["misunderstood"] >= minimum
        ),
        "needs_more_action_steps": (
            "hard_to_apply" in reminders
            or issue_counts["hard_to_apply"] >= minimum
            or outcome_counts["unresolved"] >= minimum
        ),
        "preference_evidence_counts": {
            "too_verbose": concise_count,
            "detail_needed": detailed_count,
            "scenario_mismatch": issue_counts["scenario_mismatch"],
            "unresolved": outcome_counts["unresolved"],
        },
    }


def feedback_only_candidate(video):
    return {
        "score": 0.0,
        "relevance_tier": "strong_related",
        "retrieval_channels": [],
        "matched_query_concepts": [],
        "matched_original_terms": [],
        "matched_terms": [],
        "matched_fields": {},
        "matched_topics": [],
        "transcript_ngram_coverage": 0.0,
        "video_id": video["video_id"],
        "title": video["title"],
        "category": video["category"],
        "confidence": video["confidence"],
        "processing_status": video["processing_status"],
        "url": video["url"],
    }


def apply_feedback_layers(
    query,
    ranked,
    expansion,
    knowledge,
    retrieval_index,
    retrieval_rules,
    local_personalization=True,
    feedback_dir=None,
):
    feedback_rules = load_feedback_rules()
    current_signature = feedback_signature(query, expansion)
    global_records, global_stats = load_global_feedback_records()
    global_adjustments, global_matches, public_reminders = build_feedback_adjustments(
        "global",
        global_records,
        current_signature,
        retrieval_index,
        retrieval_rules,
        feedback_rules,
    )
    if local_personalization:
        local_records, local_stats = load_local_feedback_records(feedback_dir)
        local_adjustments, local_matches, local_reminders = build_feedback_adjustments(
            "local",
            local_records,
            current_signature,
            retrieval_index,
            retrieval_rules,
            feedback_rules,
        )
    else:
        local_records = []
        local_adjustments = {}
        local_matches = []
        local_reminders = []
        local_stats = {
            "queue_file_count": 0,
            "accepted_record_count": 0,
            "usable_record_count": 0,
            "skipped_record_count": 0,
        }

    videos = {
        video["video_id"]: video
        for video in knowledge["videos"]
        if video["processing_status"] == "ready"
    }
    candidates = {item["video_id"]: dict(item) for item in ranked}
    adjusted_video_ids = set(global_adjustments) | set(local_adjustments)
    exact_threshold = feedback_rules["personalization"]["exact_query_threshold"]
    applied = []
    for video_id in adjusted_video_ids:
        global_value = global_adjustments.get(video_id)
        local_value = local_adjustments.get(video_id)
        global_delta = global_value["delta"] if global_value else 0.0
        local_delta = local_value["delta"] if local_value else 0.0
        total_delta = global_delta + local_delta
        candidate = candidates.get(video_id)
        if candidate is None:
            if total_delta <= 0 or video_id not in videos:
                continue
            candidate = feedback_only_candidate(videos[video_id])
            candidates[video_id] = candidate

        original_tier = candidate["relevance_tier"]
        original_score = candidate["score"]
        tier_decided = False
        for value in [local_value, global_value]:
            if not value:
                continue
            if (
                value["negative_strength"] > value["positive_strength"]
                and value["max_negative_similarity"] >= exact_threshold
            ):
                candidate["relevance_tier"] = "semantic_lead"
                tier_decided = True
                break
            if (
                value["positive_strength"] > value["negative_strength"]
                and value["max_positive_similarity"] >= exact_threshold
            ):
                candidate["relevance_tier"] = "direct"
                tier_decided = True
                break
        if (
            not tier_decided
            and total_delta > 0
            and TIER_ORDER[candidate["relevance_tier"]] > TIER_ORDER["strong_related"]
        ):
            candidate["relevance_tier"] = "strong_related"

        sources = []
        signal_ids = []
        reasons = []
        if global_value:
            sources.append("global_promoted_feedback")
            signal_ids.extend(global_value["record_ids"])
            reasons.extend(f"global_{reason}" for reason in global_value["reasons"])
            candidate["retrieval_channels"] = sorted(
                set(candidate["retrieval_channels"]) | {"global_promoted_feedback"}
            )
        if local_value:
            sources.append("local_accepted_feedback")
            signal_ids.extend(local_value["record_ids"])
            reasons.extend(f"local_{reason}" for reason in local_value["reasons"])
            candidate["retrieval_channels"] = sorted(
                set(candidate["retrieval_channels"]) | {"local_accepted_feedback"}
            )
        candidate["score"] = round(original_score + total_delta, 4)
        candidate["feedback_adjustment"] = {
            "score_delta": round(total_delta, 4),
            "global_delta": round(global_delta, 4),
            "local_delta": round(local_delta, 4),
            "sources": sources,
            "signal_ids": sorted(set(signal_ids)),
            "reasons": sorted(set(reasons)),
            "original_tier": original_tier,
            "adjusted_tier": candidate["relevance_tier"],
        }
        applied.append(
            {
                "video_id": video_id,
                **candidate["feedback_adjustment"],
            }
        )

    reranked = list(candidates.values())
    reranked.sort(
        key=lambda item: (
            TIER_ORDER[item["relevance_tier"]],
            -item["score"],
            item["title"],
        )
    )
    answer_preferences = local_answer_preferences(
        local_records,
        local_reminders,
        public_reminders,
        feedback_rules,
    )
    guidance = {
        "global": {
            **global_stats,
            "matched_signal_count": len(global_matches),
            "matched_signal_ids": global_matches,
        },
        "local": {
            "enabled": bool(local_personalization),
            **local_stats,
            "matched_feedback_count": len(local_matches),
            "matched_feedback_ids": local_matches,
        },
        "applied_video_adjustments": sorted(
            applied,
            key=lambda item: (-abs(item["score_delta"]), item["video_id"]),
        ),
        "answer_preferences": answer_preferences,
        "guardrails": [
            "feedback_changes_ranking_and_answer_presentation_only",
            "feedback_never_overrides_source_evidence",
            "negative_feedback_remains_in_exhaustive_manifest",
            "only_accepted_local_and_promoted_global_feedback_is_used",
        ],
    }
    return reranked, guidance


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
    result = {
        "video_id": candidate["video_id"],
        "title": candidate["title"],
        "url": candidate["url"],
        "score": candidate["score"],
        "relevance_tier": candidate["relevance_tier"],
        "matched_query_concepts": candidate["matched_query_concepts"],
        "matched_original_terms": candidate["matched_original_terms"],
    }
    if candidate.get("feedback_adjustment"):
        result["feedback_adjustment"] = candidate["feedback_adjustment"]
    return result


def search(
    query,
    limit=12,
    mode="hybrid",
    recall_mode="exhaustive",
    manifest_offset=0,
    manifest_limit=None,
    local_personalization=True,
    feedback_dir=None,
):
    knowledge, retrieval_index, rules = load_resources()
    answer_guidance = classify_answer_mode(query)
    ranked, expansion = rank_candidates(
        query,
        knowledge,
        retrieval_index,
        rules,
        mode=mode,
    )
    ranked, feedback_guidance = apply_feedback_layers(
        query,
        ranked,
        expansion,
        knowledge,
        retrieval_index,
        rules,
        local_personalization=local_personalization,
        feedback_dir=feedback_dir,
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
        "answer_guidance": (
            answer_guidance
            if manifest_offset == 0
            else {
                "pagination": True,
                "mode": answer_guidance["mode"],
                "see_manifest_offset": 0,
            }
        ),
        "feedback_guidance": (
            feedback_guidance
            if manifest_offset == 0
            else {
                "pagination": True,
                "local_personalization_enabled": bool(local_personalization),
                "see_manifest_offset": 0,
            }
        ),
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


def lookup_videos(
    video_ids,
    query="",
    local_personalization=True,
    feedback_dir=None,
):
    knowledge, retrieval_index, rules = load_resources()
    videos = {video["video_id"]: video for video in knowledge["videos"]}
    records = {item["video_id"]: item for item in retrieval_index["videos"]}
    candidates = {}
    feedback_guidance = None
    if query:
        ranked, expansion = rank_candidates(query, knowledge, retrieval_index, rules)
        ranked, feedback_guidance = apply_feedback_layers(
            query,
            ranked,
            expansion,
            knowledge,
            retrieval_index,
            rules,
            local_personalization=local_personalization,
            feedback_dir=feedback_dir,
        )
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
    return {
        "query": query,
        "answer_guidance": classify_answer_mode(query) if query else None,
        "feedback_guidance": feedback_guidance,
        "results": results,
        "missing_video_ids": missing,
    }


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
    parser.add_argument(
        "--no-local-personalization",
        action="store_true",
        help="Ignore accepted feedback in the current user's local feedback queue.",
    )
    parser.add_argument(
        "--feedback-dir",
        type=Path,
        help="Override the local feedback directory for this search.",
    )
    args = parser.parse_args()
    if args.video_id:
        payload = lookup_videos(
            args.video_id,
            query=args.query,
            local_personalization=not args.no_local_personalization,
            feedback_dir=args.feedback_dir,
        )
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
            local_personalization=not args.no_local_personalization,
            feedback_dir=args.feedback_dir,
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
