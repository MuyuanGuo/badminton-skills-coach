#!/usr/bin/env python3
"""Build a deterministic, evidence-ready context before answer generation."""

import argparse
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
SELECTION_RULES_PATH = ROOT / "references" / "answer-selection-rules.json"
RETRIEVAL_RULES_PATH = ROOT / "references" / "retrieval-rules.json"
REVIEWED_EVIDENCE_PATH = ROOT / "references" / "reviewed-evidence-signals.json"


def load_sibling(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_search_module():
    return load_sibling("liuhui_answer_search", "search_knowledge.py")


def load_navigation_module():
    return load_sibling("liuhui_answer_navigation", "navigate_topics.py")


def load_selection_rules():
    rules = json.loads(SELECTION_RULES_PATH.read_text(encoding="utf-8"))
    retrieval_rules = json.loads(RETRIEVAL_RULES_PATH.read_text(encoding="utf-8"))
    rules["_equivalent_groups"] = retrieval_rules.get("equivalent_groups", [])
    return rules


def load_reviewed_evidence_signals():
    if not REVIEWED_EVIDENCE_PATH.exists():
        return []
    return json.loads(REVIEWED_EVIDENCE_PATH.read_text(encoding="utf-8")).get(
        "signals", []
    )


def reviewed_evidence_priorities(
    search_module,
    query,
    plan,
    retrieval_index,
    retrieval_rules,
    rules,
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
    for signal in load_reviewed_evidence_signals():
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
    queries = [original_query, *units]
    for unit in units or [original_query]:
        unit_plan = search_module.plan_query(unit)
        expansion = unit_plan["query_expansion"]
        queries.extend(expansion.get("primary_terms", []))
        queries.extend(expansion.get("original_terms", []))
        symptoms = expansion["intent_frame"].get("literal_symptoms", [])
        if not symptoms:
            queries.extend(
                item["term"]
                for item in expansion.get("related_terms", [])
                if item["weight"] >= 0.45
            )
        if symptoms and expansion.get("primary_terms"):
            queries.append(
                " ".join([expansion["primary_terms"][0], *symptoms])
            )
        if guidance.get("strategy") == "split_multi_issue":
            for group in expansion.get("matched_synonym_groups", []):
                present = [term for term in group if term in unit]
                if present:
                    queries.append(max(present, key=len))
    queries = list(dict.fromkeys(query.strip() for query in queries if query.strip()))
    if not rules:
        return queries
    positive_query = plan["retrieval_guidance"]["intent_frame"].get(
        "positive_query", original_query
    )
    constraints = explicit_constraint_terms(search_module, positive_query, rules)
    constrained_queries = []
    for query in queries:
        if query == original_query:
            constrained_queries.append(query)
            continue
        normalized_query = search_module.normalize(query)
        missing = [
            term
            for term in constraints
            if search_module.normalize(term) not in normalized_query
        ]
        constrained_queries.append(" ".join([*missing, query]).strip())
    constrained_queries.extend(
        query for query in queries[1:] if query not in constrained_queries
    )
    return list(dict.fromkeys(constrained_queries))


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


def classify_boundary(query, rules):
    normalized = query.replace(" ", "").lower()
    matched = {
        boundary: [term for term in terms if term in normalized]
        for boundary, terms in rules["boundary_terms"].items()
    }
    if matched["pain_or_injury"]:
        boundary_type = "pain_or_injury"
        citation_policy = "no_coaching_video_without_direct_safety_evidence"
        required_statement = "停止引发疼痛的动作，并由合格医疗专业人士评估；本 Skill 不作诊断。"
    elif matched["endorsement_or_authorship"]:
        boundary_type = "endorsement_or_authorship"
        citation_policy = "no_video_needed_for_identity_or_endorsement_boundary"
        required_statement = "Skill 的综合回答不代表刘辉本人审阅、认可或背书。"
    elif matched["purchase_advice"]:
        boundary_type = "purchase_advice"
        citation_policy = "equipment_evidence_only"
        required_statement = "只能总结来源中的选拍原则，不能冒充刘辉给出个性化购买背书。"
    elif matched["visual_confirmation"]:
        boundary_type = "visual_confirmation"
        citation_policy = "technique_video_required_but_user_form_unverified"
        required_statement = "文字和示范视频可以提供检查点，但不能确认用户自己的动作完全正确。"
    elif matched["insufficient_observation"]:
        boundary_type = "insufficient_observation"
        citation_policy = (
            "no_video_needed_for_unique_cause_boundary"
            if "唯一原因" in matched["insufficient_observation"]
            else "literal_problem_evidence_only"
        )
        required_statement = "仅凭文字症状不能确定唯一原因；只能列出证据直接覆盖的可能性和需要补充的观察。"
    else:
        boundary_type = "none"
        citation_policy = "direct_worthwhile_evidence_only"
        required_statement = None
    return {
        "type": boundary_type,
        "matched_terms": matched[boundary_type] if boundary_type != "none" else [],
        "citation_policy": citation_policy,
        "required_statement": required_statement,
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
                },
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
    return merged


def structured_video_text(search_module, video):
    note = {
        key: value
        for key, value in (video.get("teaching_note") or {}).items()
        if key not in {"note", "video_id", "title", "url"}
    }
    return search_module.normalize(
        " ".join(
            [
                video.get("title", ""),
                video.get("category", ""),
                search_module.flatten(note),
            ]
        )
    )


def axis_values(search_module, text, axis):
    normalized = search_module.normalize(text)
    if not normalized:
        return set()
    value_names = set(axis["values"])
    mapped_values = {
        value
        for phrase, values in axis.get("mixed_value_sets", {}).items()
        if search_module.normalize(phrase) in normalized
        for value in values
    }
    if mapped_values:
        return mapped_values
    if any(
        search_module.normalize(term) in normalized
        for term in axis.get("mixed_terms", [])
    ):
        return value_names

    matches = []
    for value, terms in axis["values"].items():
        for term in terms:
            normalized_term = search_module.normalize(term)
            if not normalized_term:
                continue
            start = 0
            while True:
                index = normalized.find(normalized_term, start)
                if index < 0:
                    break
                matches.append(
                    {
                        "value": value,
                        "start": index,
                        "end": index + len(normalized_term),
                        "length": len(normalized_term),
                    }
                )
                start = index + 1
    retained = []
    for match in matches:
        shadowed = any(
            other["value"] != match["value"]
            and other["length"] > match["length"]
            and other["start"] <= match["start"]
            and other["end"] >= match["end"]
            for other in matches
        )
        if not shadowed:
            retained.append(match)
    return {match["value"] for match in retained}


def query_axis_values(search_module, query, axis):
    values = axis_values(search_module, query, axis)
    target_prefixes = [
        search_module.normalize(prefix)
        for prefix in axis.get("query_target_prefixes", [])
        if search_module.normalize(prefix)
    ]
    if not values or not target_prefixes:
        return values

    normalized = search_module.normalize(query)
    max_prefix_length = max(map(len, target_prefixes))
    retained = set()
    for value in values:
        for term in axis["values"][value]:
            normalized_term = search_module.normalize(term)
            if not normalized_term:
                continue
            start = 0
            while True:
                index = normalized.find(normalized_term, start)
                if index < 0:
                    break
                prefix = normalized[max(0, index - max_prefix_length):index]
                if not any(prefix.endswith(item) for item in target_prefixes):
                    retained.add(value)
                    break
                start = index + 1
            if value in retained:
                break
    return retained


def source_axis_values(search_module, text, axis):
    values = axis_values(search_module, text, axis)
    normalized = search_module.normalize(text)
    values.update(
        value
        for value, phrases in axis.get("source_value_additions", {}).items()
        if any(
            search_module.normalize(phrase) in normalized
            for phrase in phrases
        )
    )
    suppressed = {
        value
        for value, phrases in axis.get("source_value_suppressions", {}).items()
        if any(
            search_module.normalize(phrase) in normalized
            for phrase in phrases
        )
    }
    return values - suppressed, suppressed


def query_constraints(search_module, query, rules):
    constraints = {}
    normalized_query = search_module.normalize(query)
    for axis in rules.get("constraint_axes", []):
        values = query_axis_values(search_module, query, axis)
        for value, phrases in axis.get("query_value_suppressions", {}).items():
            if any(
                search_module.normalize(phrase) in normalized_query
                for phrase in phrases
            ):
                values.discard(value)
        if values:
            constraints[axis["name"]] = sorted(values)
    if (
        constraints.get("serve_role") == ["receive"]
        and constraints.get("technique_variant") == ["net_push"]
        and "court_zone" not in constraints
    ):
        constraints["court_zone"] = ["forecourt"]
    if (
        constraints.get("shot_family") == ["smash"]
        and "tactical_phase" not in constraints
        and any(
            search_module.normalize(term) in normalized_query
            for term in ["杀球", "扣杀", "重杀", "点杀", "跳杀", "压球"]
        )
    ):
        constraints["tactical_phase"] = ["attack"]
    return constraints


def explicit_constraint_terms(search_module, query, rules):
    normalized = search_module.normalize(query)
    requested = query_constraints(search_module, query, rules)
    terms = []
    for axis in rules.get("constraint_axes", []):
        requested_values = set(requested.get(axis["name"], []))
        if not requested_values:
            continue
        matched_mixed = [
            term
            for term in axis.get("mixed_terms", [])
            if search_module.normalize(term) in normalized
        ]
        if matched_mixed and len(requested_values) > 1:
            terms.append(max(matched_mixed, key=len))
            continue
        for value, value_terms in axis["values"].items():
            if value not in requested_values:
                continue
            matched = [
                term
                for term in value_terms
                if search_module.normalize(term) in normalized
            ]
            if matched:
                terms.append(max(matched, key=len))
    return list(dict.fromkeys(terms))


def primary_video_constraint_text(search_module, video):
    note = video.get("teaching_note") or {}
    values = [
        video.get("title", ""),
        video.get("retrieval_title", ""),
        note.get("topic", ""),
    ]
    return " ".join(str(value or "") for value in values)


def video_constraint_scope(search_module, video, rules):
    override = rules.get("video_constraint_overrides", {}).get(
        video.get("video_id"), {}
    )
    primary_text = primary_video_constraint_text(search_module, video)
    category_text = video.get("category", "")
    note = video.get("teaching_note") or {}
    reviewed_context = " ".join(
        str(value or "")
        for value in [note.get("review_summary", ""), note.get("problem", "")]
    )
    structured_text = structured_video_text(search_module, video)
    scope = {}
    for axis in rules.get("constraint_axes", []):
        name = axis["name"]
        if name in override:
            scope[name] = {
                "values": sorted(set(override[name])),
                "source": "reviewed_override",
                "basis": override.get("basis", ""),
            }
            continue
        primary, primary_suppressed = source_axis_values(
            search_module, primary_text, axis
        )
        reviewed, reviewed_suppressed = source_axis_values(
            search_module, reviewed_context, axis
        )
        category, category_suppressed = source_axis_values(
            search_module, category_text, axis
        )
        structured, structured_suppressed = source_axis_values(
            search_module, structured_text, axis
        )
        suppressed_values = sorted(
            primary_suppressed
            | reviewed_suppressed
            | category_suppressed
            | structured_suppressed
        )
        if axis.get("combine_primary_and_reviewed") and (primary or reviewed):
            values = primary | reviewed
            source = (
                "primary_and_reviewed"
                if primary and reviewed
                else ("primary_metadata" if primary else "reviewed_context")
            )
        else:
            values = primary or reviewed or category or structured
            source = (
                "primary_metadata" if primary else (
                    "reviewed_context" if reviewed else (
                        "category" if category else (
                            "structured_evidence" if structured else "unspecified"
                        )
                    )
                )
            )
        scope[name] = {
            "values": sorted(values),
            "source": source,
            "suppressed_values": suppressed_values,
        }
    return scope


def constraint_decision(
    search_module,
    query,
    plan,
    video,
    rules,
    requested=None,
    scope=None,
):
    positive_query = plan["retrieval_guidance"]["intent_frame"].get(
        "positive_query", query
    )
    requested = (
        query_constraints(search_module, positive_query, rules)
        if requested is None
        else requested
    )
    scope = (
        video_constraint_scope(search_module, video, rules)
        if scope is None
        else scope
    )
    requested_output = plan["retrieval_guidance"]["intent_frame"].get(
        "requested_output"
    )
    failures = []
    matches = {}
    axes = {axis["name"]: axis for axis in rules.get("constraint_axes", [])}
    for axis_name, requested_values in requested.items():
        scope_details = scope[axis_name]
        video_values = set(scope_details["values"])
        suppressed_values = set(scope_details.get("suppressed_values", []))
        requested_values = set(requested_values)
        if (
            requested_values & suppressed_values
            and not requested_values & video_values
        ):
            failures.append(f"explicit_constraint_conflict:{axis_name}")
            matches[axis_name] = "conflict"
            continue
        if not video_values:
            matches[axis_name] = "unspecified_support"
            continue
        axis = axes[axis_name]
        if (
            scope_details["source"] == "structured_evidence"
            and axis.get("structured_evidence_policy") == "support_only"
        ):
            if requested_values & video_values:
                matches[axis_name] = "incidental_support"
            elif axis.get("structured_mismatch_policy") == "conflict":
                failures.append(f"explicit_constraint_conflict:{axis_name}")
                matches[axis_name] = "conflict"
            else:
                matches[axis_name] = "unspecified_support"
            continue
        if not requested_values & video_values:
            failures.append(f"explicit_constraint_conflict:{axis_name}")
            matches[axis_name] = "conflict"
            continue
        if not requested_values.issubset(video_values):
            matches[axis_name] = "partial_support"
            continue
        if (
            len(requested_values) == 1
            and len(video_values) > 1
            and requested_output != "comparison"
        ):
            matches[axis_name] = "mixed_support"
            continue
        matches[axis_name] = "exact"
    requested_shot_families = set(requested.get("shot_family", []))
    requested_serve_roles = set(requested.get("serve_role", []))
    requested_court_zones = set(requested.get("court_zone", []))
    serve_scope = scope.get("serve_role", {})
    video_serve_roles = set(serve_scope.get("values", []))
    if (
        requested_shot_families - {"short_serve", "deep_serve"}
        and "serve" not in requested_serve_roles
        and video_serve_roles == {"serve"}
        and serve_scope.get("source")
        in {"primary_metadata", "reviewed_override"}
    ):
        failures.append(
            "explicit_cross_axis_conflict:shot_family_vs_serve_role"
        )
    if (
        requested_court_zones
        and "serve" not in requested_serve_roles
        and video_serve_roles == {"serve"}
        and serve_scope.get("source")
        in {"primary_metadata", "reviewed_override"}
    ):
        failures.append(
            "explicit_cross_axis_conflict:court_zone_vs_serve_role"
        )
    return not failures, failures, requested, scope, matches


def unrequested_specific_scope(requested, scope, rules):
    allowed_sources = set(
        rules.get("unrequested_scope_support_only_sources", [])
    )
    return {
        axis_name: scope[axis_name]
        for axis_name in rules.get("unrequested_scope_support_only_axes", [])
        if not requested.get(axis_name)
        and scope.get(axis_name, {}).get("values")
        and (
            not allowed_sources
            or scope[axis_name].get("source") in allowed_sources
        )
    }


def unrequested_ranking_scope(requested, scope, rules):
    return {
        axis_name: scope[axis_name]
        for axis_name in rules.get("unrequested_scope_ranking_axes", [])
        if not requested.get(axis_name)
        and scope.get(axis_name, {}).get("values")
    }


def is_direct_question_match(search_module, plan, match):
    if match.get("query_index") == 0:
        return True
    if plan["retrieval_guidance"].get("strategy") != "split_multi_issue":
        return False
    normalized_match = search_module.normalize(match.get("query", ""))
    for unit in plan["retrieval_guidance"].get("query_units", []):
        normalized_unit = search_module.normalize(unit)
        if normalized_unit and (
            normalized_match == normalized_unit
            or normalized_match.endswith(normalized_unit)
        ):
            return True
    return False


def term_matches_concept(search_module, term, concept, rules):
    normalized_term = search_module.normalize(term)
    normalized_concept = search_module.normalize(concept)
    if not normalized_term or not normalized_concept:
        return False
    if normalized_term in normalized_concept or normalized_concept in normalized_term:
        return True
    for group in rules.get("_equivalent_groups", []):
        normalized_group = {search_module.normalize(item) for item in group}
        if normalized_term in normalized_group and normalized_concept in normalized_group:
            return True
    return False


def required_relationship_group(search_module, query, rules):
    normalized_query = search_module.normalize(query)
    for group in rules.get("relationship_equivalent_groups", []):
        if any(
            search_module.normalize(term) in normalized_query
            for term in group
        ):
            return group
    return []


def video_supports_relationship(search_module, video, group):
    if not group:
        return True
    structured = structured_video_text(search_module, video)
    return any(
        search_module.normalize(term) in structured
        for term in group
    )


def required_focus_groups(search_module, query, rules):
    normalized_query = search_module.normalize(query)
    return [
        group
        for group in rules.get("required_focus_equivalent_groups", [])
        if any(
            search_module.normalize(term) in normalized_query
            for term in group
        )
    ]


def text_supports_focus_group(search_module, text, group, rules):
    normalized = search_module.normalize(text)
    for focus_term, phrases in rules.get(
        "focus_term_source_suppressions", {}
    ).items():
        if not any(
            search_module.normalize(term) == search_module.normalize(focus_term)
            for term in group
        ):
            continue
        for phrase in phrases:
            normalized = normalized.replace(search_module.normalize(phrase), "")
    return any(
        search_module.normalize(term) in normalized
        for term in group
    )


def video_supports_required_focus(search_module, video, groups, rules):
    structured = structured_video_text(search_module, video)
    return all(
        text_supports_focus_group(search_module, structured, group, rules)
        for group in groups
    )


def primary_reviewed_focus_text(search_module, video):
    note = video.get("teaching_note") or {}
    return search_module.normalize(
        " ".join(
            str(value or "")
            for value in [
                primary_video_constraint_text(search_module, video),
                note.get("review_summary", ""),
                note.get("problem", ""),
            ]
        )
    )


def entry_focus_requirements(search_module, plan, entry, rules):
    if plan["retrieval_guidance"].get("strategy") != "split_multi_issue":
        positive_query = plan["retrieval_guidance"]["intent_frame"].get(
            "positive_query", plan.get("query", "")
        )
        groups = required_focus_groups(search_module, positive_query, rules)
        return [[group] for group in groups]
    return [
        groups
        for match in entry.get("matches", [])
        if (
            groups := required_focus_groups(
                search_module, match.get("query", ""), rules
            )
        )
    ]


def entry_focus_match(search_module, plan, entry, video, rules):
    primary_reviewed = primary_reviewed_focus_text(search_module, video)
    structured = structured_video_text(search_module, video)
    best_rank = 3
    requirements = entry_focus_requirements(
        search_module, plan, entry, rules
    )
    for groups in requirements:
        if all(
            text_supports_focus_group(
                search_module, primary_reviewed, group, rules
            )
            for group in groups
        ):
            best_rank = min(best_rank, 0)
        elif all(
            text_supports_focus_group(search_module, structured, group, rules)
            for group in groups
        ):
            best_rank = min(best_rank, 1)
    if not requirements:
        return "not_required"
    return {0: "primary", 1: "structured", 3: "none"}[best_rank]


def symptom_decision(search_module, plan, video, rules):
    symptoms = plan["retrieval_guidance"]["intent_frame"].get(
        "literal_symptoms", []
    )
    if not symptoms:
        return "not_required"
    primary_reviewed = primary_reviewed_focus_text(search_module, video)
    structured = structured_video_text(search_module, video)
    if any(
        search_module.normalize(symptom) in primary_reviewed
        for symptom in symptoms
    ):
        return "direct_primary"
    if any(search_module.normalize(symptom) in structured for symptom in symptoms):
        return "direct_structured"
    support_terms = {
        term
        for symptom in symptoms
        for term in rules.get("literal_symptom_support_terms", {}).get(
            symptom, []
        )
    }
    if any(
        search_module.normalize(term) in primary_reviewed
        for term in support_terms
    ):
        return "mechanism_primary"
    if any(
        search_module.normalize(term) in structured
        for term in support_terms
    ):
        return "mechanism_structured"
    return "none"


def match_has_full_concept_coverage(search_module, match, video, rules):
    concept_count = match.get("query_concept_count", 0)
    structured_count = len(match.get("matched_structured_query_concepts", []))
    if concept_count:
        if structured_count < concept_count:
            return False
        direct_terms = set(match.get("matched_original_terms", [])) | set(
            match.get("matched_equivalent_terms", [])
        )
        concepts_covered = all(
            any(
                term_matches_concept(search_module, term, concept, rules)
                for term in direct_terms
            )
            for concept in match.get("matched_query_concepts", [])
        )
        if not concepts_covered:
            return False
    elif not bool(
        match.get("matched_original_terms")
        or match.get("matched_equivalent_terms")
    ):
        return False
    relationship_group = required_relationship_group(
        search_module, match.get("query", ""), rules
    )
    if not video_supports_relationship(search_module, video, relationship_group):
        return False
    focus_groups = required_focus_groups(
        search_module, match.get("query", ""), rules
    )
    return video_supports_required_focus(
        search_module, video, focus_groups, rules
    )


def match_passes_direct_threshold(search_module, match, video, rules):
    concept_count = match.get("query_concept_count", 0)
    if not match_has_full_concept_coverage(
        search_module, match, video, rules
    ):
        return False
    if match.get("query_index") == 0 or concept_count >= 2:
        return match.get("rank", 10**6) <= rules["top_rank_acceptance"]
    if concept_count == 1:
        return (
            match.get("rank", 10**6)
            <= rules["single_concept_top_rank_acceptance"]
        )
    return match.get("rank", 10**6) <= 3


def match_passes_expansion_threshold(match, rules):
    if match.get("relevance_tier") not in rules["allowed_relevance_tiers"]:
        return False
    concept_count = match.get("query_concept_count", 0)
    structured_count = len(match.get("matched_structured_query_concepts", []))
    if concept_count >= 2:
        return bool(
            structured_count >= concept_count
            and match.get("rank", 10**6) <= rules["top_rank_acceptance"]
        )
    if concept_count == 1:
        return bool(
            structured_count
            and match.get("rank", 10**6)
            <= rules["single_concept_top_rank_acceptance"]
        )
    return bool(
        (
            match.get("matched_original_terms")
            or match.get("matched_equivalent_terms")
        )
        and match.get("rank", 10**6) <= 3
    )


def match_passes_component_threshold(match, rules):
    return bool(
        match.get("relevance_tier") in rules["allowed_relevance_tiers"]
        and match.get("matched_structured_query_concepts")
        and (
            match.get("matched_original_terms")
            or match.get("matched_equivalent_terms")
        )
        and match.get("rank", 10**6)
        <= rules.get("direct_review_rank_acceptance", 24)
    )


def concept_decision(search_module, plan, entry, video, rules):
    direct_matches = [
        match
        for match in entry["matches"]
        if is_direct_question_match(search_module, plan, match)
    ]
    exact_matches = [
        match
        for match in direct_matches
        if match_passes_direct_threshold(search_module, match, video, rules)
    ]
    if any(match.get("query_index") == 0 for match in exact_matches):
        return "exact_question"
    if exact_matches:
        return "exact_query_unit"

    component_matches = [
        match
        for match in direct_matches
        if match.get("query_concept_count", 0) >= 2
        and match.get("matched_structured_query_concepts")
        and match.get("rank", 10**6)
        <= rules.get("direct_review_rank_acceptance", 24)
    ]
    if component_matches:
        return "component_support"

    original_terms = plan.get("query_expansion", {}).get("original_terms", [])
    focused_component_matches = [
        match
        for match in entry["matches"]
        if match not in direct_matches
        and match_passes_component_threshold(match, rules)
        and any(
            term_matches_concept(search_module, term, original_term, rules)
            for term in (
                match.get("matched_original_terms", [])
                + match.get("matched_equivalent_terms", [])
            )
            for original_term in original_terms
        )
    ]
    if focused_component_matches:
        return "component_support"

    expansion_matches = [
        match
        for match in entry["matches"]
        if match not in direct_matches
        and match_passes_expansion_threshold(match, rules)
    ]
    if expansion_matches:
        return "expanded_support"
    if entry.get("reviewed_evidence_rank", 2) <= 1:
        return "reviewed_support"
    return "none"


def selection_decision(
    search_module,
    query,
    plan,
    boundary,
    entry,
    video,
    rules,
    constraint_result=None,
):
    candidate = entry["candidate"]
    reasons = []
    if video.get("processing_status") != "ready":
        return False, ["video_not_ready"]
    if candidate["relevance_tier"] not in rules["allowed_relevance_tiers"]:
        return False, ["recall_safeguard_only"]
    if boundary["type"] == "pain_or_injury":
        return False, ["medical_boundary_has_no_direct_safety_evidence"]
    if boundary["type"] == "endorsement_or_authorship":
        return False, ["identity_boundary_does_not_need_teaching_video"]
    if (
        boundary["type"] == "insufficient_observation"
        and "唯一原因" in boundary.get("matched_terms", [])
    ):
        return False, ["unique_cause_cannot_be_established_without_observation"]
    if (
        boundary["type"] == "purchase_advice"
        and video.get("category") not in rules["purchase_allowed_categories"]
    ):
        return False, ["purchase_query_requires_equipment_evidence"]

    title_normalized = search_module.normalize(video.get("title", ""))
    structured = structured_video_text(search_module, video)
    for term in rules["incomplete_fragment_terms"]:
        normalized_term = search_module.normalize(term)
        if normalized_term in title_normalized or normalized_term in structured:
            return False, ["incomplete_series_fragment"]

    if constraint_result is None:
        constraint_result = constraint_decision(
            search_module, query, plan, video, rules
        )
    (
        constraints_match,
        constraint_failures,
        requested_constraints,
        _,
        constraint_matches,
    ) = constraint_result
    if not constraints_match:
        return False, constraint_failures
    if (
        len(requested_constraints.get("technique_variant", [])) == 1
        and constraint_matches.get("technique_variant") == "unspecified_support"
    ):
        return False, ["specific_technique_not_supported"]
    if (
        requested_constraints.get("serve_role")
        and requested_constraints.get("technique_variant")
        and constraint_matches.get("serve_role") != "exact"
        and constraint_matches.get("technique_variant") != "exact"
    ):
        return False, ["specific_technique_role_not_supported"]

    concept_match = concept_decision(search_module, plan, entry, video, rules)
    if concept_match == "none":
        return False, ["no_direct_or_supporting_question_evidence"]

    positive_query = plan["retrieval_guidance"]["intent_frame"].get(
        "positive_query", query
    )
    query_normalized = search_module.normalize(positive_query)
    symptom_match = symptom_decision(search_module, plan, video, rules)
    if symptom_match == "none":
        return False, ["literal_symptom_or_mechanism_not_supported"]
    focus_match = entry_focus_match(
        search_module, plan, entry, video, rules
    )
    if (
        plan["retrieval_guidance"].get("strategy") != "split_multi_issue"
        and required_focus_groups(search_module, positive_query, rules)
        and focus_match == "none"
    ):
        return False, ["required_focus_not_supported"]

    requested_output = plan["retrieval_guidance"]["intent_frame"].get(
        "requested_output"
    )
    if (
        requested_output == "comparison"
        and "被动" in positive_query
        and search_module.normalize("被动") not in structured
    ):
        return False, ["comparison_missing_passive_scenario"]
    if (
        "姿势" in positive_query
        and "被动" not in positive_query
        and search_module.normalize("被动") in title_normalized
    ):
        return False, ["basic_form_query_conflicts_with_passive_variant"]
    if (
        "接发握拍" in query_normalized
        and search_module.normalize("握拍") in structured
        and search_module.normalize("接发") not in structured
    ):
        adaptation_terms = [
            "调整",
            "变化",
            "变拍",
            "微调",
            "转换",
            "随机应变",
            "千变万化",
            "拍面",
        ]
        if not any(
            search_module.normalize(term) in structured
            for term in adaptation_terms
        ):
            return False, ["receive_grip_query_requires_adaptation_evidence"]

    strategy = plan["retrieval_guidance"]["strategy"]
    symptoms = plan["retrieval_guidance"]["intent_frame"].get(
        "literal_symptoms", []
    )
    if boundary["type"] == "insufficient_observation" and symptoms:
        matched_symptoms = [
            symptom
            for symptom in symptoms
            if search_module.normalize(symptom) in structured
        ]
        if not matched_symptoms:
            return False, ["literal_symptom_not_supported_by_structured_evidence"]
        reasons.append("direct_literal_symptom_evidence")

    if candidate.get("matched_original_terms"):
        reasons.append("matched_original_query_terms")
    if candidate.get("matched_equivalent_terms"):
        reasons.append("matched_equivalent_terms")
    if candidate.get("matched_topics"):
        reasons.append("matched_topic")
    reasons.append("matched_required_constraints")
    if symptom_match.startswith("direct_"):
        reasons.append("matched_literal_symptom")
    elif symptom_match.startswith("mechanism_"):
        reasons.append("matched_literal_symptom_mechanism")
    if any(
        match in {
            "unspecified_support",
            "mixed_support",
            "partial_support",
            "incidental_support",
        }
        for match in constraint_matches.values()
    ):
        reasons.append("generic_constraint_support_only")
    if concept_match == "exact_question":
        reasons.append("matched_full_question_concepts")
    elif concept_match == "exact_query_unit":
        reasons.append("matched_full_query_unit_concepts")
    elif concept_match == "component_support":
        reasons.append("matched_question_component_only")
    elif concept_match == "reviewed_support":
        reasons.append("matched_compatible_reviewed_evidence_signal")
    else:
        reasons.append("matched_expansion_support_only")
    if entry["best_query_index"] == 0:
        reasons.append("ranked_for_original_question")
    else:
        reasons.append("ranked_for_focused_query_unit")
    return True, reasons or ["direct_ranked_evidence"]


def selected_sort_key(entry, rules=None):
    rules = rules or {}
    candidate = entry["candidate"]
    original_match = next(
        (item for item in entry["matches"] if item.get("query_index") == 0),
        None,
    )
    original_core = bool(
        original_match
        and original_match["relevance_tier"] == "direct"
        and original_match["rank"] <= 12
    )
    original_concepts = len(
        original_match["matched_structured_query_concepts"]
        if original_match
        else []
    )
    original_terms = len(
        set(
            (original_match or {}).get("matched_original_terms", [])
            + (original_match or {}).get("matched_equivalent_terms", [])
        )
    )
    constraint_support = any(
        match in {
            "unspecified_support",
            "mixed_support",
            "partial_support",
            "incidental_support",
        }
        for match in entry.get("constraint_match", {}).values()
    ) or bool(entry.get("unrequested_constraint_scope"))
    exact_constraint_count = sum(
        match == "exact" for match in entry.get("constraint_match", {}).values()
    )
    mixed_constraint_count = sum(
        match == "mixed_support"
        for match in entry.get("constraint_match", {}).values()
    )
    concept_match = entry.get("concept_match", "none")
    concept_support_rank = {
        "exact_question": 0,
        "exact_query_unit": 1,
        "component_support": 2,
        "reviewed_support": 3,
        "expanded_support": 4,
        "none": 5,
    }[concept_match]
    focus_match_rank = {
        "primary": 0,
        "structured": 1,
        "not_required": 2,
        "none": 3,
    }.get(entry.get("focus_match", "not_required"), 3)
    symptom_match_rank = {
        "direct_primary": 0,
        "direct_structured": 1,
        "mechanism_primary": 2,
        "mechanism_structured": 3,
        "not_required": 4,
        "none": 5,
    }.get(entry.get("symptom_match", "not_required"), 5)
    reviewed_evidence_rank = entry.get("reviewed_evidence_rank", 2)
    direct_terms = {
        search_term
        for search_term in (
            candidate.get("matched_original_terms", [])
            + candidate.get("matched_equivalent_terms", [])
        )
    }
    matched_fields = candidate.get("matched_fields", {})

    def field_has_direct_term(field):
        return any(
            (
                str(term).replace(" ", "").lower()
                in str(direct_term).replace(" ", "").lower()
                or str(direct_term).replace(" ", "").lower()
                in str(term).replace(" ", "").lower()
            )
            for term in matched_fields.get(field, [])
            for direct_term in direct_terms
        )

    direct_field_rank = (
        0
        if field_has_direct_term("title")
        else (
            1
            if field_has_direct_term("teaching_note")
            else (2 if field_has_direct_term("transcript") else 3)
        )
    )
    return (
        (
            1
            if constraint_support
            or concept_match not in {"exact_question", "exact_query_unit"}
            else 0
        ),
        symptom_match_rank,
        reviewed_evidence_rank,
        -exact_constraint_count,
        mixed_constraint_count,
        focus_match_rank,
        concept_support_rank,
        direct_field_rank,
        len(entry.get("unrequested_ranking_scope", {})),
        0 if candidate["relevance_tier"] == "direct" else 1,
        entry["best_rank"],
        0 if original_core else 1,
        -original_concepts,
        -original_terms,
        -len({item["query"] for item in entry["matches"]}),
        candidate["title"],
    )


def entry_is_core(entry):
    return bool(
        not entry.get("unrequested_constraint_scope")
        and all(
            match == "exact"
            for match in entry["constraint_match"].values()
        )
        and entry["concept_match"] in {"exact_question", "exact_query_unit"}
    )


def question_concept_anchors(search_module, plan):
    positive_query = plan["retrieval_guidance"]["intent_frame"].get(
        "positive_query", plan.get("query", "")
    )
    normalized_query = search_module.normalize(positive_query)
    anchors = []
    for group in plan.get("query_expansion", {}).get(
        "matched_synonym_groups", []
    ):
        explicit_terms = [
            term
            for term in group
            if search_module.normalize(term) in normalized_query
        ]
        if explicit_terms:
            anchors.append((search_module.normalize(group[0]), explicit_terms))
    return anchors


def entry_question_concept_coverage(search_module, plan, entry, rules):
    matched_terms = {
        term
        for match in entry.get("matches", [])
        for term in (
            match.get("matched_original_terms", [])
            + match.get("matched_equivalent_terms", [])
        )
    }
    return {
        key
        for key, anchors in question_concept_anchors(search_module, plan)
        if any(
            term_matches_concept(search_module, term, anchor, rules)
            for term in matched_terms
            for anchor in anchors
        )
    }


def diversify_support_entries(
    search_module, plan, exact_entries, support_entries, rules
):
    coverage_counts = {}
    for concept in (
        concept
        for entry in exact_entries
        for concept in entry_question_concept_coverage(
            search_module, plan, entry, rules
        )
    ):
        coverage_counts[concept] = coverage_counts.get(concept, 0) + 1
    remaining = list(support_entries)
    diversified = []
    while remaining:
        def diversity_key(entry):
            concepts = entry_question_concept_coverage(
                search_module, plan, entry, rules
            )
            new_concepts = sum(
                coverage_counts.get(concept, 0) == 0
                for concept in concepts
            )
            mean_coverage = (
                sum(coverage_counts.get(concept, 0) for concept in concepts)
                / len(concepts)
                if concepts
                else 10**6
            )
            return (
                entry.get("reviewed_evidence_rank", 2),
                -new_concepts,
                mean_coverage,
                selected_sort_key(entry, rules),
            )

        remaining.sort(
            key=diversity_key
        )
        selected = remaining.pop(0)
        diversified.append(selected)
        for concept in entry_question_concept_coverage(
            search_module, plan, selected, rules
        ):
            coverage_counts[concept] = coverage_counts.get(concept, 0) + 1
    return diversified


def prepare_answer_context(
    query,
    max_videos=None,
    segment_limit=None,
    local_personalization=True,
    feedback_dir=None,
    include_rejected=False,
):
    if not query.strip():
        raise ValueError("query cannot be empty")
    search_module = load_search_module()
    navigation_module = load_navigation_module()
    rules = load_selection_rules()
    explicit_max_videos = max_videos is not None
    max_videos = max_videos or rules["default_max_selected_videos"]
    segment_limit = segment_limit or rules["default_segment_limit"]
    if not 1 <= max_videos <= 40:
        raise ValueError("max_videos must be between 1 and 40")
    if not 1 <= segment_limit <= 12:
        raise ValueError("segment_limit must be between 1 and 12")

    plan = search_module.plan_query(query)
    knowledge, retrieval_index, retrieval_rules = search_module.load_resources()
    reviewed_priorities = reviewed_evidence_priorities(
        search_module,
        query,
        plan,
        retrieval_index,
        retrieval_rules,
        rules,
    )
    navigation = None
    retrieval_queries = planned_queries(search_module, plan, query, rules)
    if plan["retrieval_guidance"].get("use_topic_navigation"):
        navigation = topic_navigation(navigation_module, query)
        retrieval_queries.extend(navigation["suggested_search_queries"][:3])
        retrieval_queries = list(dict.fromkeys(retrieval_queries))

    payloads = [
        search_module.search(
            unit,
            limit=rules["top_rank_acceptance"],
            mode="hybrid",
            recall_mode="exhaustive",
            manifest_limit=None,
            local_personalization=local_personalization,
            feedback_dir=feedback_dir,
        )
        for unit in retrieval_queries
    ]
    merged = merge_candidates(payloads, retrieval_queries)
    videos = {video["video_id"]: video for video in knowledge["videos"]}
    positive_query = plan["retrieval_guidance"]["intent_frame"].get(
        "positive_query", query
    )
    requested_constraints = query_constraints(
        search_module, positive_query, rules
    )
    boundary = classify_boundary(positive_query, rules)
    accepted = []
    rejected = []
    for video_id, entry in merged.items():
        entry["reviewed_evidence_rank"] = reviewed_priorities.get(video_id, 2)
        video = videos.get(video_id)
        if not video:
            rejected.append(
                {"video_id": video_id, "reasons": ["video_missing_from_knowledge"]}
            )
            continue
        constraint_scope = video_constraint_scope(search_module, video, rules)
        constraint_result = constraint_decision(
            search_module,
            query,
            plan,
            video,
            rules,
            requested=requested_constraints,
            scope=constraint_scope,
        )
        keep, reasons = selection_decision(
            search_module,
            query,
            plan,
            boundary,
            entry,
            video,
            rules,
            constraint_result=constraint_result,
        )
        unrequested_scope = unrequested_specific_scope(
            constraint_result[2], constraint_scope, rules
        )
        ranking_scope = unrequested_ranking_scope(
            constraint_result[2], constraint_scope, rules
        )
        record = {
            **entry,
            "video_id": video_id,
            "selection_reasons": list(reasons),
            "constraint_scope": constraint_scope,
            "unrequested_constraint_scope": unrequested_scope,
            "unrequested_ranking_scope": ranking_scope,
        }
        record["constraint_match"] = constraint_result[4]
        if keep and unrequested_scope:
            record["selection_reasons"].append(
                "unrequested_specific_scenario_support_only"
            )
        record["concept_match"] = concept_decision(
            search_module, plan, entry, video, rules
        )
        record["focus_match"] = entry_focus_match(
            search_module, plan, entry, video, rules
        )
        record["symptom_match"] = symptom_decision(
            search_module, plan, video, rules
        )
        (accepted if keep else rejected).append(record)

    accepted.sort(key=lambda entry: selected_sort_key(entry, rules))
    exact_entries = [
        entry
        for entry in accepted
        if entry_is_core(entry)
    ]
    support_entries = [entry for entry in accepted if entry not in exact_entries]
    support_limit = min(rules.get("max_supporting_videos", 4), max_videos)
    exact_limit = rules.get("max_exact_videos", max_videos)
    if explicit_max_videos:
        exact_limit = (
            max_videos
            if max_videos <= support_limit
            else max_videos - support_limit
        )
    selected_exact_entries = exact_entries[:exact_limit]
    if plan["retrieval_guidance"].get("strategy") == "split_multi_issue":
        support_entries = diversify_support_entries(
            search_module,
            plan,
            selected_exact_entries,
            support_entries,
            rules,
        )
    eligible_entries = [
        *selected_exact_entries,
        *support_entries[:support_limit],
    ]
    policy_excluded_entries = [
        {
            **entry,
            "selection_reasons": ["exact_video_limit_exceeded"],
        }
        for entry in exact_entries[exact_limit:]
    ]
    policy_excluded_entries.extend(
        {
            **entry,
            "selection_reasons": ["supporting_video_limit_exceeded"],
        }
        for entry in support_entries[support_limit:]
    )
    rejected.extend(policy_excluded_entries)
    selected_entries = eligible_entries[:max_videos]
    selected_ids = [item["video_id"] for item in selected_entries]
    lookup = search_module.lookup_videos(
        selected_ids,
        query=query,
        local_personalization=local_personalization,
        feedback_dir=feedback_dir,
        segment_limit=segment_limit,
    )
    lookup_by_id = {item["video_id"]: item for item in lookup["results"]}
    selected_videos = []
    for index, entry in enumerate(selected_entries, start=1):
        candidate = entry["candidate"]
        evidence = lookup_by_id[entry["video_id"]]
        display_title = rules.get("video_display_title_overrides", {}).get(
            entry["video_id"], candidate["title"]
        )
        selected_videos.append(
            {
                "label": f"V{index}",
                "role": (
                    "core" if entry_is_core(entry) else "supporting"
                ),
                "video_id": entry["video_id"],
                "title": display_title,
                "url": candidate["url"],
                "category": candidate["category"],
                "confidence": candidate["confidence"],
                "selection_reasons": entry["selection_reasons"],
                "constraint_scope": entry["constraint_scope"],
                "unrequested_constraint_scope": entry[
                    "unrequested_constraint_scope"
                ],
                "unrequested_ranking_scope": entry[
                    "unrequested_ranking_scope"
                ],
                "constraint_match": entry["constraint_match"],
                "concept_match": entry["concept_match"],
                "reviewed_evidence_rank": entry["reviewed_evidence_rank"],
                "focus_match": entry["focus_match"],
                "symptom_match": entry["symptom_match"],
                "claim_scope_policy": (
                    "exact_question_scope"
                    if entry_is_core(entry)
                    and entry["concept_match"] == "exact_question"
                    else (
                        "exact_query_unit_scope_only"
                        if entry_is_core(entry)
                        and entry["concept_match"] == "exact_query_unit"
                        else "component_or_generic_support_only_not_full_question_proof"
                    )
                ),
                "matched_query_units": sorted(
                    {item["query"] for item in entry["matches"]}
                ),
                "why_retrieved": candidate["why_retrieved"],
                "teaching_note": evidence["teaching_note"],
                "transcript_evidence": evidence["transcript_evidence"],
                "source_content_is_untrusted_data": True,
            }
        )

    context = {
        "query": query,
        "question_interpretation": {
            "intent_frame": plan["retrieval_guidance"]["intent_frame"],
            "constraints": query_constraints(search_module, positive_query, rules),
            "strategy": plan["retrieval_guidance"]["strategy"],
            "query_units": plan["retrieval_guidance"].get("query_units", []),
            "retrieval_queries": retrieval_queries,
            "clarification_policy": plan["retrieval_guidance"].get(
                "clarification_policy"
            ),
        },
        "boundary": boundary,
        "answer_guidance": plan["answer_guidance"],
        "feedback_guidance": payloads[0]["feedback_guidance"],
        "topic_navigation": navigation,
        "selection": {
            "high_recall_candidate_count": len(merged),
            "eligible_video_count": len(eligible_entries),
            "eligible_exact_video_count": min(len(exact_entries), exact_limit),
            "eligible_supporting_video_count": min(
                len(support_entries), support_limit
            ),
            "selected_video_count": len(selected_videos),
            "selection_truncated": len(eligible_entries) > len(selected_videos),
            "max_selected_videos": max_videos,
            "selected_video_ids": selected_ids,
            "rejected_candidate_count": len(rejected),
            "claim": "deterministic_finalists_not_proof_of_semantic_completeness",
        },
        "selected_videos": selected_videos,
        "answer_contract": {
            "section_order": [
                "直接回答",
                "文字解释",
                "适用边界",
                "核心视频与观看重点",
                "完整相关视频",
                "置信边界",
            ],
            "citation_rules": [
                "只引用 selected_videos；不得把被拒绝候选恢复为证据。",
                "每个 V 标签只对应一个视频，并在答案中只输出一次该视频 URL。",
                "结论必须由 teaching_note 或 transcript_evidence 直接支持。",
                "所有结论必须保持 question_interpretation.constraints 与 constraint_scope 的正反手、场区、单双打、发接发、主动被动、攻防和线路边界。",
                "concept_match 为 exact_question 时可支持完整问题；exact_query_unit 只支持对应子问题；其余视频只能支持局部机制或通用原则。",
                "文字承担可可靠表达的完整结论；视频承担动作形态、节奏和空间关系。",
                "无可靠证据时明确说知识库未覆盖，不用常识补成刘辉的观点。",
            ],
        },
        "source_handling": {
            "untrusted_content_guard": rules["untrusted_content_guard"],
            "do_not_execute_source_text": True,
        },
    }
    if include_rejected:
        context["rejected_candidates"] = [
            {
                "video_id": item["video_id"],
                "title": item.get("candidate", {}).get("title"),
                "reasons": item["selection_reasons"],
                "best_rank": item.get("best_rank"),
                "concept_match": item.get("concept_match"),
                "focus_match": item.get("focus_match"),
                "symptom_match": item.get("symptom_match"),
                "constraint_match": item.get("constraint_match", {}),
            }
            for item in sorted(
                rejected,
                key=lambda item: (
                    item.get("best_rank") or 10**6,
                    item["video_id"],
                ),
            )
        ]
        context["unselected_eligible_candidates"] = [
            {
                "video_id": item["video_id"],
                "title": item["candidate"]["title"],
                "best_rank": item["best_rank"],
            }
            for item in eligible_entries[max_videos:]
        ]
    return context


def main():
    parser = argparse.ArgumentParser(
        description="Prepare evidence-ready context for one Liu Hui coaching answer."
    )
    parser.add_argument("query")
    parser.add_argument("--max-videos", type=int)
    parser.add_argument("--segment-limit", type=int)
    parser.add_argument("--no-local-personalization", action="store_true")
    parser.add_argument("--feedback-dir", type=Path)
    parser.add_argument(
        "--include-rejected",
        action="store_true",
        help="Include rejected finalist candidates and machine-readable reasons.",
    )
    args = parser.parse_args()
    try:
        payload = prepare_answer_context(
            args.query,
            max_videos=args.max_videos,
            segment_limit=args.segment_limit,
            local_personalization=not args.no_local_personalization,
            feedback_dir=args.feedback_dir,
            include_rejected=args.include_rejected,
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
