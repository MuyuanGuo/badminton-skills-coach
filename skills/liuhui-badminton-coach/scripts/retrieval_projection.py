#!/usr/bin/env python3
"""Compact public projections for ranked candidates and lookup evidence."""

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
    why_retrieved = []
    if candidate.get("matched_original_terms"):
        why_retrieved.append(
            "直接命中提问词：" + "、".join(candidate["matched_original_terms"])
        )
    if candidate.get("matched_equivalent_terms"):
        why_retrieved.append(
            "命中同义表达：" + "、".join(candidate["matched_equivalent_terms"])
        )
    if candidate.get("matched_fields"):
        fields = "；".join(
            f"{field}={','.join(terms)}"
            for field, terms in sorted(candidate["matched_fields"].items())
        )
        why_retrieved.append("结构化字段命中：" + fields)
    if candidate.get("matched_topic_details"):
        why_retrieved.append(
            "主题命中："
            + "、".join(
                item["subtopic"] for item in candidate["matched_topic_details"]
            )
        )
    active_ngram_fields = [
        field
        for field, coverage in candidate.get("ngram_coverage_by_field", {}).items()
        if coverage > 0
    ]
    if candidate.get("ngram_match") and active_ngram_fields:
        why_retrieved.append("字符片段命中：" + "、".join(active_ngram_fields))
    if candidate.get("feedback_adjustment"):
        why_retrieved.append("用户反馈参与排序")
    if candidate.get("matched_excluded_terms"):
        why_retrieved.append(
            "同时命中排除词，已降权："
            + "、".join(candidate["matched_excluded_terms"])
        )
    if candidate.get("retrieval_policy_eligible") is False:
        why_retrieved.append(
            "仅保留在穷举召回清单，不能作为当前问题证据："
            + "、".join(candidate.get("retrieval_policy_reasons", []))
        )
    if candidate.get("transcript_retrieval", {}).get("mode") == "chunk_first":
        why_retrieved.append("B站长转写按相关片段命中")
    result = {
        "video_id": candidate["video_id"],
        "title": candidate["title"],
        "url": candidate["url"],
        "score": candidate["score"],
        "relevance_tier": candidate["relevance_tier"],
        "intrinsic_relevance_tier": candidate["intrinsic_relevance_tier"],
        "review_priority": candidate["review_priority"],
        "within_review_budget": candidate["within_review_budget"],
        "category": candidate["category"],
        "confidence": candidate["confidence"],
        "processing_status": candidate["processing_status"],
        "retrieval_cohort": candidate.get(
            "retrieval_cohort", "stable_baseline"
        ),
        "answer_eligibility": candidate.get(
            "answer_eligibility", "primary"
        ),
        "evidence_roles": candidate.get("evidence_roles", ["context"]),
        "metadata_title_trust": candidate.get(
            "metadata_title_trust", "not_applicable"
        ),
        "runtime_evidence_mode": candidate.get(
            "runtime_evidence_mode", "full_transcript"
        ),
        "retrieval_channels": candidate.get("retrieval_channels", []),
        "matched_query_concepts": candidate["matched_query_concepts"],
        "matched_structured_query_concepts": candidate.get(
            "matched_structured_query_concepts", []
        ),
        "matched_original_terms": candidate["matched_original_terms"],
        "matched_equivalent_terms": candidate.get(
            "matched_equivalent_terms", []
        ),
        "matched_terms": candidate.get("matched_terms", []),
        "matched_fields": candidate.get("matched_fields", {}),
        "matched_topics": candidate.get("matched_topics", []),
        "matched_topic_details": candidate.get("matched_topic_details", []),
        "matched_required_intents": candidate.get("matched_required_intents", []),
        "matched_excluded_terms": candidate.get("matched_excluded_terms", []),
        "matched_excluded_seed_terms": candidate.get(
            "matched_excluded_seed_terms", []
        ),
        "ngram_match": candidate.get("ngram_match", False),
        "ngram_coverage_by_field": candidate.get(
            "ngram_coverage_by_field", {}
        ),
        "score_breakdown": candidate.get("score_breakdown", {}),
        "transcript_retrieval": candidate.get(
            "transcript_retrieval", {"mode": "legacy_video"}
        ),
        "retrieval_policy_eligible": candidate.get(
            "retrieval_policy_eligible", True
        ),
        "retrieval_policy_reasons": candidate.get(
            "retrieval_policy_reasons", []
        ),
        "why_retrieved": why_retrieved,
    }
    if candidate.get("feedback_adjustment"):
        result["feedback_adjustment"] = candidate["feedback_adjustment"]
    return result

def compact_quality(quality):
    if not quality:
        return None
    transcript = quality.get("transcript", {})
    automatic = quality.get("automatic_evidence", {})
    return {
        "transcript": {
            "passed": transcript.get("passed"),
            "issues": transcript.get("issues", []),
            "language_probability": transcript.get("language_probability"),
            "segment_count": transcript.get("segment_count"),
            "text_characters": transcript.get("text_characters"),
        },
        "automatic_evidence": {
            "passed": automatic.get("passed"),
            "issues": automatic.get("issues", []),
            "key_evidence_count": automatic.get("key_evidence_count"),
            "teaching_term_matches": automatic.get("teaching_term_matches"),
        },
    }

def compact_teaching_note(note):
    evidence_fields = {
        "key_evidence",
        "coverage_evidence",
        "error_evidence",
        "action_cues",
        "principles",
        "visual_review_evidence",
    }
    summary = {key: value for key, value in note.items() if key not in evidence_fields}
    evidence_by_content = {}
    for role in evidence_fields:
        values = note.get(role)
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, dict) or not value.get("text"):
                continue
            marker = (str(value.get("timestamp") or ""), str(value["text"]))
            if marker not in evidence_by_content:
                evidence_by_content[marker] = {
                    "timestamp": marker[0],
                    "text": marker[1],
                    "roles": [],
                }
            evidence_by_content[marker]["roles"].append(role)
    evidence = sorted(
        evidence_by_content.values(),
        key=lambda item: (item["timestamp"], item["text"]),
    )
    for item in evidence:
        item["roles"].sort()
    return {"summary": summary, "evidence": evidence}

def rank_bounded_note_evidence(evidence, query, expansion, limit=4):
    """Rank committed timestamped note windows without treating titles as proof."""

    if not query.strip() or limit <= 0:
        return []
    query_normalized = normalize(query)
    query_grams = character_grams(query)
    term_weights = expansion.get("term_weights", {}) if expansion else {}
    scored = []
    for item in evidence:
        text_value = str(item.get("text") or "")
        normalized_value = normalize(text_value)
        if not normalized_value:
            continue
        matched_terms = sorted(
            term
            for term in term_weights
            if normalize(term) and normalize(term) in normalized_value
        )
        shared_grams = query_grams & character_grams(text_value)
        gram_coverage = len(shared_grams) / max(1, len(query_grams))
        exact_match = bool(
            query_normalized and query_normalized in normalized_value
        )
        if not exact_match and not matched_terms and len(shared_grams) < 2:
            continue
        scored.append(
            {
                "score": round(
                    (100.0 if exact_match else 0.0)
                    + sum(term_weights[term] for term in matched_terms)
                    + gram_coverage * 25.0,
                    4,
                ),
                "timestamp": item.get("timestamp"),
                "text": text_value,
                "roles": item.get("roles", []),
                "matched_terms": matched_terms,
                "query_ngram_coverage": round(gram_coverage, 4),
                "exact_query_match": exact_match,
            }
        )
    scored.sort(
        key=lambda item: (-item["score"], item.get("timestamp") or "", item["text"])
    )
    return scored[:limit]

def rank_transcript_evidence(
    video,
    query,
    expansion,
    limit=6,
    context_radius=2,
    chunk_hints=None,
):
    """Return query-matched timestamped transcript windows from one finalist video."""

    segments = video.get("transcript_segments") or []
    if not query.strip() or not segments or limit <= 0:
        return []
    query_normalized = normalize(query)
    query_grams = character_grams(query)
    term_weights = expansion.get("term_weights", {}) if expansion else {}
    scored = []
    candidate_indexes = set(range(len(segments)))
    if chunk_hints:
        candidate_indexes = {
            index
            for hint in chunk_hints
            for index in range(
                max(0, int(hint.get("start_segment", 0)) - context_radius),
                min(
                    len(segments),
                    int(hint.get("end_segment", len(segments)))
                    + context_radius,
                ),
            )
        }
        hinted_text = normalize(
            "".join(
                str(segments[index].get("text") or "")
                for index in sorted(candidate_indexes)
            )
        )
        original_terms = list(
            dict.fromkeys(
                term
                for term in (expansion or {}).get("original_terms", [])
                if normalize(term)
            )
        )
        unmet_terms = [
            term
            for term in original_terms
            if normalize(term) not in hinted_text
        ]
        if unmet_terms:
            normalized_segments = [
                normalize(segment.get("text") or "")
                for segment in segments
            ]
            for term in unmet_terms:
                normalized_term = normalize(term)
                fallback_centers = []
                for index, normalized_segment in enumerate(
                    normalized_segments
                ):
                    adjacent = (
                        normalized_segment
                        + (
                            normalized_segments[index + 1]
                            if index + 1 < len(normalized_segments)
                            else ""
                        )
                    )
                    if normalized_term not in adjacent:
                        continue
                    fallback_centers.append(index)
                    if len(fallback_centers) == 2:
                        break
                for center in fallback_centers:
                    candidate_indexes.update(
                        range(
                            max(0, center - context_radius),
                            min(
                                len(segments),
                                center + context_radius + 2,
                            ),
                        )
                    )
    for index in sorted(candidate_indexes):
        start_index = max(0, index - context_radius)
        end_index = min(len(segments), index + context_radius + 1)
        window = segments[start_index:end_index]
        text_value = "".join(str(item.get("text") or "") for item in window)
        normalized_value = normalize(text_value)
        if not normalized_value:
            continue
        matched_terms = sorted(
            term
            for term in term_weights
            if normalize(term) and normalize(term) in normalized_value
        )
        shared_grams = query_grams & character_grams(text_value)
        gram_coverage = len(shared_grams) / max(1, len(query_grams))
        exact_match = bool(query_normalized and query_normalized in normalized_value)
        score = (
            (100.0 if exact_match else 0.0)
            + sum(term_weights[term] for term in matched_terms)
            + gram_coverage * 25.0
        )
        if not exact_match and not matched_terms and len(shared_grams) < 2:
            continue
        scored.append(
            {
                "score": round(score, 4),
                "start_index": start_index,
                "end_index": end_index,
                "timestamp": (
                    f"{window[0]['timestamp'].split('-', 1)[0]}-"
                    f"{window[-1]['timestamp'].rsplit('-', 1)[-1]}"
                ),
                "text": text_value,
                "matched_terms": matched_terms,
                "query_ngram_coverage": round(gram_coverage, 4),
                "exact_query_match": exact_match,
            }
        )
    scored.sort(
        key=lambda item: (
            -item["score"],
            item["start_index"],
            item["text"],
        )
    )
    selected = []
    for item in scored:
        overlaps = any(
            item["start_index"] < current["end_index"]
            and current["start_index"] < item["end_index"]
            for current in selected
        )
        if overlaps:
            continue
        selected.append(item)
        if len(selected) == limit:
            break
    for item in selected:
        item.pop("start_index", None)
        item.pop("end_index", None)
    return selected

def compact_lookup_feedback(feedback_guidance, video_ids):
    if not feedback_guidance:
        return None
    requested = set(video_ids)
    return {
        "matched_global_signal_count": feedback_guidance["global"][
            "matched_signal_count"
        ],
        "matched_local_feedback_count": feedback_guidance["local"][
            "matched_feedback_count"
        ],
        "applied_video_adjustments": [
            adjustment
            for adjustment in feedback_guidance["applied_video_adjustments"]
            if adjustment["video_id"] in requested
        ],
        "answer_preferences": feedback_guidance["answer_preferences"],
    }
