#!/usr/bin/env python3
"""Retrieval-query budgeting, reviewed priorities, and candidate merging."""

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from answer_constraints import (
    explicit_constraint_terms,
    query_actor_context,
    required_focus_groups,
)

MAX_MERGED_CHUNK_HINTS = 8

def reviewed_evidence_priorities(
    search_module,
    query,
    plan,
    retrieval_index,
    retrieval_rules,
    rules,
    reviewed_signals=(),
):
    priorities = {}
    current_normalized = search_module.normalize(query)
    current_signature = search_module.feedback_signature(
        query, plan["query_expansion"]
    )
    feedback_rules = search_module.load_feedback_rules()
    current_focus = {
        search_module.normalize(group[0])
        for group in required_focus_groups(search_module, query, rules)
    }
    minimum_similarity = rules.get(
        "reviewed_evidence_min_strict_similarity", 0.35
    )
    for signal in reviewed_signals:
        reviewed_query = signal["query"]
        exact_query = (
            current_normalized
            and current_normalized == search_module.normalize(reviewed_query)
        )
        if not exact_query:
            reviewed_expansion = search_module.expand_query(
                reviewed_query, retrieval_index, retrieval_rules
            )
            reviewed_signature = search_module.feedback_signature(
                reviewed_query, reviewed_expansion
            )
            reviewed_focus = {
                search_module.normalize(group[0])
                for group in required_focus_groups(
                    search_module, reviewed_query, rules
                )
            }
            if (
                current_signature["concepts"]
                != reviewed_signature["concepts"]
                or (
                    current_focus
                    and reviewed_focus
                    and current_focus != reviewed_focus
                )
            ):
                continue
            match = search_module.feedback_query_match(
                current_signature,
                reviewed_query,
                retrieval_index,
                retrieval_rules,
                feedback_rules,
            )
            if not (
                match["strict_compatible"]
                and match["strict_similarity"] >= minimum_similarity
            ):
                continue
        primary_ids = set(signal.get("primary_video_ids", []))
        for video_id in signal.get("required_video_ids", []):
            priority = 0 if video_id in primary_ids else 1
            priorities[video_id] = min(
                priorities.get(video_id, priority), priority
            )
    return priorities


def planned_queries(search_module, plan, original_query, rules=None):
    """Expand a question into focused retrieval units without losing the original."""

    guidance = plan["retrieval_guidance"]
    units = guidance.get("query_units") or []
    queries = [original_query]
    for unit in units or [original_query]:
        unit_plan = search_module.plan_query(unit)
        expansion = unit_plan["query_expansion"]
        unit_queries = [
            unit,
            *expansion.get("primary_terms", []),
            *expansion.get("original_terms", []),
        ]
        symptoms = expansion["intent_frame"].get("literal_symptoms", [])
        if not symptoms:
            unit_queries.extend(
                item["term"]
                for item in expansion.get("related_terms", [])
                if item["weight"] >= 0.45
            )
        if symptoms and expansion.get("primary_terms"):
            unit_queries.append(
                " ".join([expansion["primary_terms"][0], *symptoms])
            )
        if guidance.get("strategy") == "split_multi_issue":
            for group in expansion.get("matched_synonym_groups", []):
                present = [term for term in group if term in unit]
                if present:
                    unit_queries.append(max(present, key=len))
        unit_queries = list(
            dict.fromkeys(
                query.strip() for query in unit_queries if query.strip()
            )
        )
        if not rules:
            queries.extend(unit_queries)
            continue
        intent_frame = unit_plan["retrieval_guidance"]["intent_frame"]
        positive_query = intent_frame.get("positive_query", unit)
        actor_query = intent_frame.get("actor_query", positive_query)
        actor_context = query_actor_context(
            search_module, actor_query, rules
        )
        constraints = explicit_constraint_terms(
            search_module, positive_query, rules
        )
        constrained_unit_queries = []
        for unit_query in unit_queries:
            if unit_query == unit:
                constrained_unit_queries.append(unit_query)
                continue
            normalized_query = search_module.normalize(unit_query)
            missing = [
                term
                for term in constraints
                if search_module.normalize(term) not in normalized_query
            ]
            constrained_unit_queries.append(
                " ".join([*missing, unit_query]).strip()
            )
        constrained_unit_queries.extend(
            unit_query
            for unit_query in unit_queries[1:]
            if unit_query not in constrained_unit_queries
        )
        constrained_unit_queries.extend(actor_context["derived_search_terms"])
        queries.extend(constrained_unit_queries)
    return list(dict.fromkeys(query for query in queries if query.strip()))


def budget_retrieval_queries(search_module, queries, plan, original_query, rules):
    soft_budget = rules.get("retrieval_query_budget", 24)
    hard_limit = rules.get("retrieval_query_hard_limit", 48)
    units = plan["retrieval_guidance"].get("query_units") or []
    protected_texts = [original_query, *units]
    # Actor/action parsing can deliberately reinterpret a symptom query.  Keep
    # those compact semantic anchors inside the budget; otherwise verbose
    # lexical composites can crowd them out and undo the reinterpretation.
    if rules.get("query_actor_markers"):
        for unit in units or [original_query]:
            unit_plan = search_module.plan_query(unit)
            intent = unit_plan["retrieval_guidance"]["intent_frame"]
            positive_query = intent.get("positive_query", unit)
            actor_query = intent.get("actor_query", positive_query)
            actor_context = query_actor_context(
                search_module, actor_query, rules
            )
            protected_texts.extend(
                actor_context.get("derived_search_terms", [])
            )
    protected_texts = list(dict.fromkeys(protected_texts))
    protected_normalized = {
        search_module.normalize(item) for item in protected_texts if item.strip()
    }
    protected = [
        query
        for query in queries
        if search_module.normalize(query) in protected_normalized
    ]
    remaining = [query for query in queries if query not in protected]
    target = min(hard_limit, max(soft_budget, len(protected)))
    if len(protected) < target and remaining:
        term_priority = {}
        low_information_terms = set()
        for unit in units or [original_query]:
            unit_plan = search_module.plan_query(unit)
            expansion = unit_plan["query_expansion"]
            intent = expansion.get("intent_frame", {})
            low_information = {
                *intent.get("scenarios", []),
                *intent.get("levels", []),
            }
            low_information_terms.update(
                search_module.normalize(term) for term in low_information
            )
            primary = set(expansion.get("primary_terms", []))
            synonym_terms = {
                term
                for group in expansion.get("matched_synonym_groups", [])
                for term in group
                if search_module.normalize(term)
                in search_module.normalize(unit)
            }
            related = {
                item["term"]: float(item.get("weight", 0))
                for item in expansion.get("related_terms", [])
            }
            for term in {
                *expansion.get("original_terms", []),
                *primary,
                *synonym_terms,
                *related,
            }:
                score = (
                    (4.0 if term in synonym_terms else 0.0)
                    + (3.0 if term in primary else 0.0)
                    + related.get(term, 0.0) * 4.0
                    - (2.0 if term in low_information else 0.0)
                    + min(len(search_module.normalize(term)), 4) * 0.1
                )
                term_priority[search_module.normalize(term)] = max(
                    term_priority.get(search_module.normalize(term), 0.0), score
                )

        def query_priority(item):
            normalized = search_module.normalize(item)
            matched_term_score = max(
                (
                    score
                    for term, score in term_priority.items()
                    if term and term in normalized
                ),
                default=0.0,
            )
            if (
                normalized in term_priority
                and normalized not in low_information_terms
            ):
                matched_term_score += 6.0
            # Prefer a focused atom/composite over broad profile-only shards.
            return (
                -matched_term_score,
                -min(len(normalized), 24),
                queries.index(item),
            )

        remaining = sorted(remaining, key=query_priority)
    selected = [*protected, *remaining][:target]
    selected_normalized = {
        search_module.normalize(query) for query in selected
    }
    missing_required_units = [
        unit
        for unit in protected_texts
        if search_module.normalize(unit) not in selected_normalized
    ]
    return selected, {
        "configured_budget": soft_budget,
        "hard_limit": hard_limit,
        "generated_query_count": len(queries),
        "executed_query_count": len(selected),
        "truncated": len(selected) < len(queries),
        "omitted_query_count": len(queries) - len(selected),
        "missing_required_units": missing_required_units,
    }


def continuation_query_plan(search_module, effective_query, continuation):
    effective_plan = search_module.plan_query(effective_query)
    if continuation is None:
        return effective_plan, effective_query

    original_query = continuation["original_query"]
    plan = search_module.plan_query(original_query)
    effective_intent = effective_plan["retrieval_guidance"]["intent_frame"]
    plan["answer_guidance"] = effective_plan["answer_guidance"]
    plan["retrieval_guidance"]["intent_frame"] = effective_intent
    plan["query_expansion"]["intent_frame"] = effective_intent
    return plan, original_query


def topic_navigation(navigation_module, query, limit=5):
    graph = json.loads(navigation_module.TOPIC_MAP.read_text(encoding="utf-8"))
    practice_rules = json.loads(
        navigation_module.PRACTICE_RULES.read_text(encoding="utf-8")
    )
    context = navigation_module.build_user_context(query, practice_rules)
    matches = navigation_module.match_topics(graph, query, limit)
    return {
        "intent": navigation_module.detect_intent(query),
        "user_context": context,
        "context_assumptions": [
            field
            for field, source in context["sources"].items()
            if source == "default"
        ],
        "material_clarification_questions": (
            navigation_module.clarification_questions(context)
        ),
        "matches": matches,
        "suggested_search_queries": navigation_module.suggested_queries(
            query, matches
        ),
        "learning_path": navigation_module.learning_path(
            matches, context, practice_rules
        ),
        "practice_adaptation": navigation_module.practice_adaptation(
            context, practice_rules
        ),
    }


def merge_transcript_retrieval(
    preferred,
    matches,
    limit=MAX_MERGED_CHUNK_HINTS,
):
    preferred = dict(preferred or {})
    sources = [preferred, *(item or {} for item in matches)]
    hints = []
    seen_chunk_ids = set()
    for source in sources:
        for hint in source.get("chunk_hints", []):
            chunk_id = str(hint.get("chunk_id") or "")
            marker = chunk_id or (
                int(hint.get("start_segment", 0)),
                int(hint.get("end_segment", 0)),
            )
            if marker in seen_chunk_ids:
                continue
            seen_chunk_ids.add(marker)
            hints.append(dict(hint))
            if len(hints) >= limit:
                break
        if len(hints) >= limit:
            break
    chunk_ids = [
        str(hint["chunk_id"])
        for hint in hints
        if hint.get("chunk_id")
    ]
    cluster_ids = list(
        dict.fromkeys(
            str(hint["cluster_id"])
            for hint in hints
            if hint.get("cluster_id")
        )
    )
    if not hints:
        return preferred
    return {
        **preferred,
        "mode": (
            "chunk_first"
            if any(
                source.get("mode") == "chunk_first"
                for source in sources
            )
            else preferred.get("mode", "legacy_video")
        ),
        "best_chunk_id": (
            preferred.get("best_chunk_id")
            or (chunk_ids[0] if chunk_ids else None)
        ),
        "matched_chunk_ids": chunk_ids,
        "matched_cluster_ids": cluster_ids,
        "chunk_hints": hints,
    }


def merge_candidates(payloads, retrieval_queries):
    merged = {}
    for query_index, (query, payload) in enumerate(
        zip(retrieval_queries, payloads)
    ):
        for rank, candidate in enumerate(payload["candidate_manifest"], start=1):
            video_id = candidate["video_id"]
            entry = merged.setdefault(
                video_id,
                {
                    "candidate": candidate,
                    "matches": [],
                    "best_rank": rank,
                    "best_query_index": query_index,
                    "_transcript_retrieval_matches": [],
                },
            )
            entry["_transcript_retrieval_matches"].append(
                candidate.get("transcript_retrieval") or {}
            )
            entry["matches"].append(
                {
                    "query": query,
                    "query_index": query_index,
                    "rank": rank,
                    "relevance_tier": candidate["relevance_tier"],
                    "within_review_budget": candidate["within_review_budget"],
                    "matched_original_terms": candidate["matched_original_terms"],
                    "matched_equivalent_terms": candidate.get(
                        "matched_equivalent_terms", []
                    ),
                    "matched_query_concepts": candidate.get(
                        "matched_query_concepts", []
                    ),
                    "matched_structured_query_concepts": candidate.get(
                        "matched_structured_query_concepts", []
                    ),
                    "query_concept_count": len(
                        payload["query_expansion"].get(
                            "matched_synonym_groups", []
                        )
                    ),
                }
            )
            candidate_key = (
                0 if candidate["relevance_tier"] == "direct" else 1,
                rank,
                -candidate["score_breakdown"].get(
                    "effective_ranking_score", candidate["score"]
                ),
            )
            current = entry["candidate"]
            current_key = (
                0 if current["relevance_tier"] == "direct" else 1,
                entry["best_rank"],
                -current["score_breakdown"].get(
                    "effective_ranking_score", current["score"]
                ),
            )
            if candidate_key < current_key:
                entry["candidate"] = candidate
                entry["best_rank"] = rank
                entry["best_query_index"] = query_index
            else:
                entry["best_rank"] = min(entry["best_rank"], rank)
    for entry in merged.values():
        candidate = entry["candidate"]
        entry["candidate"] = {
            **candidate,
            "transcript_retrieval": merge_transcript_retrieval(
                candidate.get("transcript_retrieval"),
                entry.pop("_transcript_retrieval_matches"),
            ),
        }
    return merged
