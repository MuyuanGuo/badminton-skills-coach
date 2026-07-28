#!/usr/bin/env python3
"""Candidate evidence matching, thresholds, focus checks, and selection decisions."""

import importlib.util
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent


def _load_scope():
    spec = importlib.util.spec_from_file_location(
        "liuhui_answer_candidate_scope",
        SCRIPT_DIR / "answer_scope.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_scope = _load_scope()
axis_values = _scope.axis_values
constraint_decision = _scope.constraint_decision
named_technique_comparison_focus_failures = (
    _scope.named_technique_comparison_focus_failures
)
primary_video_constraint_text = _scope.primary_video_constraint_text
query_axis_values = _scope.query_axis_values
required_constraint_support_failures = _scope.required_constraint_support_failures
structured_video_text = _scope.structured_video_text
substantive_instruction_text = _scope.substantive_instruction_text

def is_direct_question_match(search_module, plan, match):
    if match.get("query_index") == 0:
        return True
    normalized_match = search_module.normalize(match.get("query", ""))
    if plan["retrieval_guidance"].get("strategy") != "split_multi_issue":
        if len(
            plan.get("query_expansion", {}).get(
                "matched_synonym_groups", []
            )
        ) != 1:
            return False
        return any(
            normalized_match == search_module.normalize(term)
            for term in plan.get("query_expansion", {}).get(
                "original_terms", []
            )
        )
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


def has_instructional_evidence(video):
    note = video.get("teaching_note") or {}
    return bool(note.get("action_cues") or note.get("review_summary"))


def match_has_substantive_concept_evidence(
    search_module, match, video, concept, rules
):
    if not has_instructional_evidence(video):
        return False
    evidence = substantive_instruction_text(search_module, video, rules)
    required_terms = {
        concept,
        *match.get("matched_original_terms", []),
        *match.get("matched_equivalent_terms", []),
    }
    if any(
        search_module.normalize(term) in evidence
        for term in required_terms
        if search_module.normalize(term)
    ):
        return True
    axes = {
        axis["name"]: axis for axis in rules.get("constraint_axes", [])
    }
    for axis_name in rules.get("substantive_concept_equivalence_axes", []):
        axis = axes.get(axis_name)
        if not axis:
            continue
        requested_values = query_axis_values(
            search_module, match.get("query", ""), axis
        )
        evidence_values = axis_values(search_module, evidence, axis)
        if (
            len(requested_values) == 1
            and requested_values == evidence_values
        ):
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
            or match_has_substantive_concept_evidence(
                search_module, match, video, concept, rules
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
    if (
        plan["retrieval_guidance"].get("strategy") != "split_multi_issue"
        and exact_matches
    ) or any(match.get("query_index") == 0 for match in exact_matches):
        return "exact_question"
    if exact_matches:
        return "exact_query_unit"

    component_matches = [
        match
        for match in direct_matches
        if match.get("query_concept_count", 0) >= 1
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
    if video.get("video_id") not in rules.get(
        "incomplete_fragment_exempt_video_ids", []
    ):
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
    support_failures = required_constraint_support_failures(
        requested_constraints, constraint_matches, rules
    )
    if support_failures:
        return False, support_failures
    comparison_focus_failures = named_technique_comparison_focus_failures(
        search_module,
        query,
        requested_constraints,
        video,
        rules,
    )
    if comparison_focus_failures:
        return False, comparison_focus_failures
    if (
        requested_constraints.get("serve_role")
        and requested_constraints.get("technique_variant")
        and constraint_matches.get("serve_role") != "exact"
        and constraint_matches.get("technique_variant") != "exact"
    ):
        return False, ["specific_technique_role_not_supported"]
    serve_scope = constraint_result[3].get("serve_role", {})
    if (
        requested_constraints.get("serve_role")
        and constraint_matches.get("serve_role") == "unspecified_support"
        and serve_scope.get("suppressed_values")
    ):
        return False, ["specific_serve_role_source_suppressed"]

    concept_match = concept_decision(search_module, plan, entry, video, rules)
    if concept_match == "none":
        return False, ["no_direct_or_supporting_question_evidence"]

    positive_query = plan["retrieval_guidance"]["intent_frame"].get(
        "positive_query", query
    )
    query_normalized = search_module.normalize(positive_query)
    symptom_match = symptom_decision(search_module, plan, video, rules)
    reviewed_symptom_support = bool(
        symptom_match == "none"
        and entry.get("reviewed_evidence_rank", 2) <= 1
        and concept_match != "none"
    )
    if symptom_match == "none" and not reviewed_symptom_support:
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
    elif reviewed_symptom_support:
        reasons.append("matched_reviewed_symptom_mechanism")
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
        "reviewed_mechanism": 1,
        "not_required": 5,
        "none": 6,
    }.get(entry.get("symptom_match", "not_required"), 6)
    reviewed_evidence_rank = entry.get("reviewed_evidence_rank", 2)
    retrieval_cohort_rank = (
        1
        if candidate.get("retrieval_cohort") == "automatic_expansion"
        else 0
    )
    direct_terms = {
        search_term
        for search_term in (
            candidate.get("matched_original_terms", [])
            + candidate.get("matched_equivalent_terms", [])
        )
    }
    matched_fields = candidate.get("matched_fields", {})

    value_priority_rules = rules.get(
        "unrequested_ranking_value_priority", {}
    )
    default_value_priority = value_priority_rules.get("default", 1)
    unrequested_value_priorities = [
        value_priority_rules.get(axis_name, {}).get(
            value, default_value_priority
        )
        for axis_name, scope_details in entry.get(
            "unrequested_ranking_scope", {}
        ).items()
        for value in scope_details.get("values", [])
    ]
    unrequested_value_priority = min(
        unrequested_value_priorities,
        default=default_value_priority,
    )

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
        entry.get("actor_context_rank", 2),
        symptom_match_rank,
        reviewed_evidence_rank,
        retrieval_cohort_rank,
        unrequested_value_priority,
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
    inferred_action_match = entry.get("inferred_target_action_match", False)
    return bool(
        not entry.get("unrequested_constraint_scope")
        and (
            inferred_action_match
            or (
                all(
                    match == "exact"
                    for match in entry["constraint_match"].values()
                )
                and entry["concept_match"]
                in {"exact_question", "exact_query_unit"}
            )
        )
    )


def entry_claim_scope_policy(entry):
    if (
        entry.get("unrequested_constraint_scope")
        or entry.get("unrequested_ranking_scope")
    ):
        return "additional_specific_scope_only_not_unrestricted_full_question_proof"
    if entry_is_core(entry) and entry["concept_match"] == "exact_question":
        return "exact_question_scope"
    if entry_is_core(entry) and entry["concept_match"] == "exact_query_unit":
        return "exact_query_unit_scope_only"
    return "component_or_generic_support_only_not_full_question_proof"


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
