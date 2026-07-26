#!/usr/bin/env python3
"""Reviewed and local feedback matching, ranking adjustments, and preferences."""

from collections import Counter, defaultdict

_FEEDBACK_SIGNATURE_CACHE = {}

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
    frame = expansion["intent_frame"]
    primary_equivalents = set()
    for primary in expansion.get("primary_terms", []):
        normalized_primary = normalize(primary)
        primary_equivalents.add(normalized_primary)
    primary_equivalents.update(
        normalize(term) for term in expansion.get("synonym_terms", [])
    )
    return {
        "normalized": normalize(query),
        "terms": terms,
        "topics": topics,
        "character_grams": character_grams(query),
        "primary_terms": {
            term for term in primary_equivalents if term
        },
        "concepts": {
            normalize(group[0])
            for group in expansion.get("matched_synonym_groups", [])
            if group
        },
        "literal_symptoms": {
            normalize(term) for term in frame.get("literal_symptoms", [])
        },
        "scenarios": {
            normalize(term) for term in frame.get("scenarios", [])
        },
        "levels": {normalize(term) for term in frame.get("levels", [])},
        "excluded_terms": {
            normalize(term) for term in frame.get("excluded_terms", [])
        },
        "requested_output": frame.get("requested_output"),
    }

def feedback_query_match(
    current_signature,
    feedback_query,
    retrieval_index,
    retrieval_rules,
    feedback_rules=None,
):
    feedback_rules = feedback_rules or load_feedback_rules()
    signature_key = (
        feedback_query,
        id(retrieval_index),
        id(retrieval_rules),
    )
    feedback_signature_value = _FEEDBACK_SIGNATURE_CACHE.get(signature_key)
    if feedback_signature_value is None:
        feedback_expansion = expand_query(
            feedback_query, retrieval_index, retrieval_rules
        )
        feedback_signature_value = feedback_signature(
            feedback_query, feedback_expansion
        )
        if len(_FEEDBACK_SIGNATURE_CACHE) >= 2048:
            _FEEDBACK_SIGNATURE_CACHE.clear()
        _FEEDBACK_SIGNATURE_CACHE[signature_key] = feedback_signature_value
    if (
        current_signature["normalized"]
        and current_signature["normalized"] == feedback_signature_value["normalized"]
    ):
        return {
            "semantic_similarity": 1.0,
            "positive_similarity": 1.0,
            "strict_similarity": 1.0,
            "positive_compatible": True,
            "strict_compatible": True,
            "incompatibility_reasons": [],
        }
    term_score = jaccard(current_signature["terms"], feedback_signature_value["terms"])
    topic_score = jaccard(current_signature["topics"], feedback_signature_value["topics"])
    character_score = jaccard(
        current_signature["character_grams"],
        feedback_signature_value["character_grams"],
    )
    semantic_score = min(
        1.0, term_score * 0.55 + topic_score * 0.25 + character_score * 0.20
    )
    primary_score = jaccard(
        current_signature["primary_terms"],
        feedback_signature_value["primary_terms"],
    )
    concept_score = jaccard(
        current_signature["concepts"], feedback_signature_value["concepts"]
    )
    reasons = []
    for left, right in feedback_rules["personalization"].get(
        "scenario_conflicts", []
    ):
        normalized_left = normalize(left)
        normalized_right = normalize(right)
        if (
            normalized_left in current_signature["scenarios"]
            and normalized_right in feedback_signature_value["scenarios"]
        ) or (
            normalized_right in current_signature["scenarios"]
            and normalized_left in feedback_signature_value["scenarios"]
        ):
            reasons.append(f"scenario_conflict:{left}:{right}")
    if current_signature["excluded_terms"] & feedback_signature_value["terms"]:
        reasons.append("current_exclusion_conflicts_with_feedback_positive_intent")
    if feedback_signature_value["excluded_terms"] & current_signature["terms"]:
        reasons.append("feedback_exclusion_conflicts_with_current_positive_intent")

    primary_conflict = bool(
        current_signature["primary_terms"]
        and feedback_signature_value["primary_terms"]
        and primary_score == 0
    )
    if primary_conflict:
        reasons.append("primary_action_mismatch")
    positive_compatible = not reasons

    current_symptoms = current_signature["literal_symptoms"]
    feedback_symptoms = feedback_signature_value["literal_symptoms"]
    symptom_compatible = current_symptoms == feedback_symptoms
    if not symptom_compatible:
        reasons.append("literal_symptom_mismatch")
    scenario_compatible = (
        current_signature["scenarios"] == feedback_signature_value["scenarios"]
    )
    if not scenario_compatible:
        reasons.append("scenario_scope_mismatch")
    output_compatible = (
        current_signature["requested_output"]
        == feedback_signature_value["requested_output"]
    )
    if not output_compatible:
        reasons.append("requested_output_mismatch")
    exclusions_compatible = (
        current_signature["excluded_terms"]
        == feedback_signature_value["excluded_terms"]
    )
    if not exclusions_compatible:
        reasons.append("exclusion_scope_mismatch")
    strict_compatible = (
        positive_compatible
        and symptom_compatible
        and scenario_compatible
        and output_compatible
        and exclusions_compatible
        and (primary_score > 0 or concept_score > 0)
    )
    strict_score = (
        semantic_score * 0.55
        + primary_score * 0.25
        + concept_score * 0.10
        + (0.10 if symptom_compatible else 0.0)
    )
    return {
        "semantic_similarity": round(semantic_score, 4),
        "positive_similarity": round(
            semantic_score if positive_compatible else 0.0, 4
        ),
        "strict_similarity": round(
            strict_score if strict_compatible else 0.0, 4
        ),
        "positive_compatible": positive_compatible,
        "strict_compatible": strict_compatible,
        "incompatibility_reasons": sorted(set(reasons)),
    }

def feedback_query_similarity(
    current_signature,
    feedback_query,
    retrieval_index,
    retrieval_rules,
):
    """Backward-compatible positive similarity used by older integrations."""

    return feedback_query_match(
        current_signature,
        feedback_query,
        retrieval_index,
        retrieval_rules,
    )["positive_similarity"]

def feedback_record_values(record, layer):
    if layer == "global":
        return {
            "record_id": record["signal_id"],
            "query": record["public_query"],
            "helpful_video_ids": record.get("helpful_video_ids", []),
            "irrelevant_video_ids": record.get("irrelevant_video_ids", []),
            "missing_video_ids": record.get("missing_video_ids", []),
            "text_issue_types": record.get("answer_issue_types", []),
            "intended_query": record.get("intended_query"),
            "source_issue_video_ids": record.get("source_issue_video_ids", []),
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
        "intended_query": signals.get("intended_query"),
        "source_issue_video_ids": signals.get("source_issue_video_ids", []),
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
    positive_threshold = config["query_similarity_threshold"]
    strict_threshold = config["strict_intent_similarity_threshold"]
    strict_issue_types = set(config.get("strict_signal_types", [])) - {
        "irrelevant_video"
    }
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
    strict_matched_ids = []
    reminders = set()
    for record in records:
        values = feedback_record_values(record, layer)
        query_match = feedback_query_match(
            current_signature,
            values["query"],
            retrieval_index,
            retrieval_rules,
            feedback_rules,
        )
        positive_similarity = query_match["positive_similarity"]
        strict_similarity = query_match["strict_similarity"]
        positive_match = positive_similarity >= positive_threshold
        strict_match = strict_similarity >= strict_threshold
        broad_issue_types = set(values["text_issue_types"]) - strict_issue_types
        has_positive_signals = bool(
            values["helpful_video_ids"]
            or values["missing_video_ids"]
            or broad_issue_types
            or values["outcome"] in {"unresolved"}
        )
        has_strict_signals = bool(
            values["irrelevant_video_ids"]
            or set(values["text_issue_types"]) & strict_issue_types
            or values["intended_query"]
            or values["source_issue_video_ids"]
            or values["outcome"] == "misunderstood"
        )
        record_matched = (
            positive_match and has_positive_signals
        ) or (strict_match and has_strict_signals)
        if not record_matched:
            continue
        matched_ids.append(values["record_id"])
        if strict_match:
            strict_matched_ids.append(values["record_id"])
        if positive_match:
            reminders.update(broad_issue_types)
        if strict_match:
            reminders.update(set(values["text_issue_types"]) & strict_issue_types)
        if positive_match and values["outcome"] == "unresolved":
            reminders.add("hard_to_apply")
        elif strict_match and values["outcome"] == "misunderstood":
            reminders.add("question_misunderstood")

        helpful_ids = set(values["helpful_video_ids"])
        missing_ids = set(values["missing_video_ids"]) - helpful_ids
        signal_groups = [
            (
                helpful_ids if positive_match else set(),
                weights[f"{layer}_helpful"],
                "helpful",
                positive_similarity,
            ),
            (
                missing_ids if positive_match else set(),
                weights[f"{layer}_missing"],
                "missing",
                positive_similarity,
            ),
            (
                set(values["irrelevant_video_ids"]) if strict_match else set(),
                weights[f"{layer}_irrelevant"],
                "irrelevant",
                strict_similarity,
            ),
        ]
        for video_ids, weight, reason, similarity in signal_groups:
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
    return (
        dict(adjustments),
        sorted(matched_ids),
        sorted(strict_matched_ids),
        sorted(reminders),
    )

def matched_feedback_corrections(records, layer, matched_record_ids):
    matched = set(matched_record_ids)
    corrections = []
    for record in records:
        values = feedback_record_values(record, layer)
        if values["record_id"] not in matched:
            continue
        if values["intended_query"] or values["source_issue_video_ids"]:
            corrections.append(
                {
                    "record_id": values["record_id"],
                    "intended_query": values["intended_query"],
                    "source_issue_video_ids": values["source_issue_video_ids"],
                }
            )
    return corrections

def local_answer_preferences(
    records,
    matched_reminders,
    public_reminders,
    feedback_rules,
    matched_corrections=None,
):
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
    matched_corrections = matched_corrections or []
    query_replan_hints = list(
        dict.fromkeys(
            item["intended_query"]
            for item in matched_corrections
            if item.get("intended_query")
        )
    )
    source_recheck_video_ids = list(
        dict.fromkeys(
            video_id
            for item in matched_corrections
            for video_id in item.get("source_issue_video_ids", [])
        )
    )
    source_issue_types = {
        "transcript_error",
        "video_misinterpreted",
        "citation_mismatch",
    }
    return {
        "preferred_verbosity": verbosity,
        "query_reminders": reminders,
        "needs_query_replan": "question_misunderstood" in reminders,
        "query_replan_hints": query_replan_hints,
        "needs_source_recheck": bool(source_issue_types.intersection(reminders)),
        "source_recheck_video_ids": source_recheck_video_ids,
        "needs_more_boundaries": (
            "scenario_mismatch" in reminders
            or "question_misunderstood" in reminders
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
            "question_misunderstood": issue_counts["question_misunderstood"],
            "unresolved": outcome_counts["unresolved"],
        },
    }

def feedback_only_candidate(video):
    return {
        "score": 0.0,
        "relevance_tier": "strong_related",
        "intrinsic_relevance_tier": "strong_related",
        "retrieval_channels": [],
        "matched_query_concepts": [],
        "matched_structured_query_concepts": [],
        "matched_original_terms": [],
        "matched_equivalent_terms": [],
        "matched_terms": [],
        "matched_fields": {},
        "matched_topics": [],
        "matched_topic_details": [],
        "matched_required_intents": [],
        "required_intent_miss_count": 0,
        "matched_excluded_terms": [],
        "matched_excluded_seed_terms": [],
        "excluded_query_penalty": 0.0,
        "transcript_ngram_coverage": 0.0,
        "ngram_match": False,
        "ngram_coverage_by_field": {},
        "score_breakdown": {
            "structured_field_score": 0.0,
            "topic_score": 0.0,
            "ngram_score": 0.0,
            "exact_focus_score": 0.0,
            "matched_concept_score": 0.0,
            "evidence_quality_bonus": 0.0,
            "base_score_before_feedback": 0.0,
        },
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
    global_feedback_loader=None,
    local_feedback_loader=None,
):
    global_feedback_loader = (
        global_feedback_loader or load_global_feedback_records
    )
    local_feedback_loader = (
        local_feedback_loader or load_local_feedback_records
    )
    feedback_rules = load_feedback_rules()
    current_signature = feedback_signature(query, expansion)
    global_records, global_stats = global_feedback_loader()
    (
        global_adjustments,
        global_matches,
        global_strict_matches,
        public_reminders,
    ) = build_feedback_adjustments(
        "global",
        global_records,
        current_signature,
        retrieval_index,
        retrieval_rules,
        feedback_rules,
    )
    global_corrections = matched_feedback_corrections(
        global_records, "global", global_strict_matches
    )
    if local_personalization:
        local_records, local_stats = local_feedback_loader(feedback_dir)
        (
            local_adjustments,
            local_matches,
            local_strict_matches,
            local_reminders,
        ) = build_feedback_adjustments(
            "local",
            local_records,
            current_signature,
            retrieval_index,
            retrieval_rules,
            feedback_rules,
        )
        local_corrections = matched_feedback_corrections(
            local_records, "local", local_strict_matches
        )
    else:
        local_records = []
        local_adjustments = {}
        local_matches = []
        local_strict_matches = []
        local_reminders = []
        local_corrections = []
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
        refresh_score_breakdown(candidate, retrieval_rules)
        applied.append(
            {
                "video_id": video_id,
                **candidate["feedback_adjustment"],
            }
        )

    reranked = list(candidates.values())
    reranked.sort(key=lambda item: candidate_sort_key(item, retrieval_rules))
    assign_review_budget(
        reranked,
        len(expansion["matched_synonym_groups"]),
        retrieval_rules,
    )
    answer_preferences = local_answer_preferences(
        local_records,
        local_reminders,
        public_reminders,
        feedback_rules,
        matched_corrections=global_corrections + local_corrections,
    )
    guidance = {
        "global": {
            **global_stats,
            "matched_signal_count": len(global_matches),
            "matched_signal_ids": global_matches,
            "strict_intent_match_count": len(global_strict_matches),
        },
        "local": {
            "enabled": bool(local_personalization),
            **local_stats,
            "matched_feedback_count": len(local_matches),
            "matched_feedback_ids": local_matches,
            "strict_intent_match_count": len(local_strict_matches),
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
