#!/usr/bin/env python3
"""Build a deterministic, evidence-ready context before answer generation."""

import argparse
import importlib.util
import json
import re
from itertools import chain
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
SELECTION_RULES_PATH = ROOT / "references" / "answer-selection-rules.json"
RETRIEVAL_RULES_PATH = ROOT / "references" / "retrieval-rules.json"
REVIEWED_EVIDENCE_PATH = ROOT / "references" / "reviewed-evidence-signals.json"
DIAGNOSTIC_RULES_PATH = ROOT / "references" / "diagnostic-answer-rules.json"
EVIDENCE_ATOMS_PATH = ROOT / "references" / "reviewed-evidence-atoms.json"
CLARIFICATION_STATE_SCHEMA_VERSION = 1
ANSWER_TURN_CONTRACT_SCHEMA_VERSION = 1
ANSWER_PACKET_SCHEMA_VERSION = 4
ANSWER_PLAN_SCHEMA_VERSION = 1
_SIBLING_MODULES = {}
_STATIC_RESOURCE_CACHE = {}


def load_sibling(name, filename):
    if filename in _SIBLING_MODULES:
        return _SIBLING_MODULES[filename]
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _SIBLING_MODULES[filename] = module
    return module


def load_search_module():
    return load_sibling("liuhui_answer_search", "search_knowledge.py")


def load_navigation_module():
    return load_sibling("liuhui_answer_navigation", "navigate_topics.py")


def load_feedback_module():
    return load_sibling("liuhui_answer_feedback", "feedback.py")


def canonicalize_retrieval_query(query, rules):
    """Normalize accepted spelling errors before retrieval planning."""

    canonical = query
    for rule in rules.get("canonical_terminology", []):
        for term in sorted(
            rule.get("accepted_input_errors", []),
            key=len,
            reverse=True,
        ):
            canonical = re.sub(
                re.escape(term),
                rule["canonical_term"],
                canonical,
                flags=re.IGNORECASE,
            )
    return canonical


_selection_policy = load_sibling(
    "liuhui_answer_selection_policy", "answer_selection_policy.py"
)
load_selection_rules = _selection_policy.load_selection_rules
classify_boundary = _selection_policy.classify_boundary


def load_reviewed_evidence_signals():
    if "reviewed_evidence_signals" in _STATIC_RESOURCE_CACHE:
        return _STATIC_RESOURCE_CACHE["reviewed_evidence_signals"]
    if not REVIEWED_EVIDENCE_PATH.exists():
        return []
    payload = json.loads(REVIEWED_EVIDENCE_PATH.read_text(encoding="utf-8"))
    if (
        payload.get("registry_type")
        != "operational_feedback_runtime_prior"
        or payload.get("evaluation_case_ids_forbidden") is not True
    ):
        return []
    signals = payload.get("signals", [])
    _STATIC_RESOURCE_CACHE["reviewed_evidence_signals"] = signals
    return signals


def load_diagnostic_rules():
    if "diagnostic_rules" not in _STATIC_RESOURCE_CACHE:
        _STATIC_RESOURCE_CACHE["diagnostic_rules"] = json.loads(
            DIAGNOSTIC_RULES_PATH.read_text(encoding="utf-8")
        )
    return _STATIC_RESOURCE_CACHE["diagnostic_rules"]


def load_reviewed_evidence_atoms():
    if "reviewed_evidence_atoms" in _STATIC_RESOURCE_CACHE:
        return _STATIC_RESOURCE_CACHE["reviewed_evidence_atoms"]
    payload = json.loads(EVIDENCE_ATOMS_PATH.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported reviewed evidence atom schema_version")
    atoms = payload.get("atoms")
    if not isinstance(atoms, list):
        raise ValueError("reviewed evidence atoms must be a list")
    atom_ids = [atom.get("atom_id") for atom in atoms]
    if any(not atom_id for atom_id in atom_ids) or len(atom_ids) != len(
        set(atom_ids)
    ):
        raise ValueError("reviewed evidence atom IDs must be present and unique")
    _STATIC_RESOURCE_CACHE["reviewed_evidence_atoms"] = atoms
    return atoms


_answer_continuation = load_sibling(
    "liuhui_answer_continuation", "answer_continuation.py"
)
canonical_json_digest = _answer_continuation.canonical_json_digest
clarification_state_digest = _answer_continuation.clarification_state_digest
validate_clarification_state = _answer_continuation.validate_clarification_state
normalize_clarification_answers = _answer_continuation.normalize_clarification_answers
answer_resolves_request = _answer_continuation.answer_resolves_request
resolve_continuation = _answer_continuation.resolve_continuation
build_clarification_state = _answer_continuation.build_clarification_state
build_answer_turn_contract = _answer_continuation.build_answer_turn_contract


_answer_retrieval_plan = load_sibling(
    "liuhui_answer_retrieval_plan", "answer_retrieval_plan.py"
)
reviewed_evidence_priorities = _answer_retrieval_plan.reviewed_evidence_priorities
planned_queries = _answer_retrieval_plan.planned_queries
budget_retrieval_queries = _answer_retrieval_plan.budget_retrieval_queries
continuation_query_plan = _answer_retrieval_plan.continuation_query_plan
topic_navigation = _answer_retrieval_plan.topic_navigation
merge_candidates = _answer_retrieval_plan.merge_candidates


_delivery_contract = load_sibling(
    "liuhui_answer_delivery_contract", "delivery_contract.py"
)
analyze_query_units = _delivery_contract.analyze_query_units
inherit_actor_context = _delivery_contract.inherit_actor_context
should_inherit_root_context = (
    _delivery_contract.should_inherit_root_context
)
build_delivery_contract = _delivery_contract.build_delivery_contract
delivery_completeness_items = _delivery_contract.completeness_items


_answer_constraints = load_sibling(
    "liuhui_answer_constraints", "answer_constraints.py"
)
structured_video_text = _answer_constraints.structured_video_text
structured_constraint_text = _answer_constraints.structured_constraint_text
axis_values = _answer_constraints.axis_values
query_axis_values = _answer_constraints.query_axis_values
source_axis_values = _answer_constraints.source_axis_values
_query_actor_marker_suppressed = _answer_constraints._query_actor_marker_suppressed
_query_actor_parser_parts = _answer_constraints._query_actor_parser_parts
_query_actor_segments = _answer_constraints._query_actor_segments
query_actor_text = _answer_constraints.query_actor_text
_segment_requests_answer = _answer_constraints._segment_requests_answer
query_target_actor = _answer_constraints.query_target_actor
_query_constraints_from_text = _answer_constraints._query_constraints_from_text
_action_sequence_implication = _answer_constraints._action_sequence_implication
_reception_symptom_implication = _answer_constraints._reception_symptom_implication
_query_target_action_context = _answer_constraints._query_target_action_context
query_actor_context = _answer_constraints.query_actor_context
query_constraints = _answer_constraints.query_constraints
query_ambiguities = _answer_constraints.query_ambiguities
query_terminology_corrections = _answer_constraints.query_terminology_corrections
requested_technique_definitions = _answer_constraints.requested_technique_definitions
explicit_constraint_terms = _answer_constraints.explicit_constraint_terms
primary_video_constraint_text = _answer_constraints.primary_video_constraint_text
video_constraint_scope = _answer_constraints.video_constraint_scope
constraint_decision = _answer_constraints.constraint_decision
required_constraint_support_failures = _answer_constraints.required_constraint_support_failures
named_technique_comparison_focus_failures = _answer_constraints.named_technique_comparison_focus_failures
unrequested_specific_scope = _answer_constraints.unrequested_specific_scope
unrequested_ranking_scope = _answer_constraints.unrequested_ranking_scope
non_target_actor_condition_failures = _answer_constraints.non_target_actor_condition_failures
partner_context_rank = _answer_constraints.partner_context_rank
derived_player_constraint_failures = _answer_constraints.derived_player_constraint_failures
requested_action_scope_failures = _answer_constraints.requested_action_scope_failures
is_direct_question_match = _answer_constraints.is_direct_question_match
term_matches_concept = _answer_constraints.term_matches_concept
substantive_instruction_text = _answer_constraints.substantive_instruction_text
has_instructional_evidence = _answer_constraints.has_instructional_evidence
match_has_substantive_concept_evidence = _answer_constraints.match_has_substantive_concept_evidence
required_relationship_group = _answer_constraints.required_relationship_group
video_supports_relationship = _answer_constraints.video_supports_relationship
required_focus_groups = _answer_constraints.required_focus_groups
text_supports_focus_group = _answer_constraints.text_supports_focus_group
video_supports_required_focus = _answer_constraints.video_supports_required_focus
primary_reviewed_focus_text = _answer_constraints.primary_reviewed_focus_text
entry_focus_requirements = _answer_constraints.entry_focus_requirements
entry_focus_match = _answer_constraints.entry_focus_match
symptom_decision = _answer_constraints.symptom_decision
match_has_full_concept_coverage = _answer_constraints.match_has_full_concept_coverage
match_passes_direct_threshold = _answer_constraints.match_passes_direct_threshold
match_passes_expansion_threshold = _answer_constraints.match_passes_expansion_threshold
match_passes_component_threshold = _answer_constraints.match_passes_component_threshold
concept_decision = _answer_constraints.concept_decision
selection_decision = _answer_constraints.selection_decision
selected_sort_key = _answer_constraints.selected_sort_key
entry_is_core = _answer_constraints.entry_is_core
entry_claim_scope_policy = _answer_constraints.entry_claim_scope_policy
question_concept_anchors = _answer_constraints.question_concept_anchors
entry_question_concept_coverage = (
    _answer_constraints.entry_question_concept_coverage
)
diversify_support_entries = _answer_constraints.diversify_support_entries


def apply_supplemental_evidence_policy(
    accepted,
    plan,
    boundary,
    rules,
):
    """Use supplemental evidence only for bounded coverage or corroboration."""

    primary_entries = [
        entry
        for entry in accepted
        if entry["candidate"].get("answer_eligibility", "primary")
        == "primary"
    ]
    covered_concepts = {
        concept
        for entry in primary_entries
        for concept in entry["candidate"].get(
            "matched_query_concepts", []
        )
    }
    covered_roles = {
        role
        for entry in primary_entries
        for role in entry["candidate"].get("evidence_roles", [])
    }
    requested_output = plan["retrieval_guidance"]["intent_frame"].get(
        "requested_output", "coaching_answer"
    )
    required_roles = set(
        rules.get("supplemental_role_requirements", {}).get(
            requested_output, []
        )
    )
    if boundary.get("type") == "purchase_advice":
        required_roles.add("equipment")
    allowed_tiers = set(
        rules.get(
            "supplemental_allowed_relevance_tiers",
            ["direct", "strong_related"],
        )
    )
    limit = int(rules.get("supplemental_selection_limit", 2))
    kept = []
    rejected = []
    supplemental_count = 0
    corroboration_count = 0
    for entry in accepted:
        candidate = entry["candidate"]
        if candidate.get("answer_eligibility", "primary") != "supplemental":
            kept.append(entry)
            continue
        if supplemental_count >= limit:
            rejected.append(
                {
                    **entry,
                    "selection_reasons": [
                        "supplemental_synthesis_limit_exceeded"
                    ],
                }
            )
            continue
        tier = candidate.get("relevance_tier")
        candidate_concepts = set(
            candidate.get("matched_query_concepts", [])
        )
        adds_concepts = candidate_concepts - covered_concepts
        roles = set(candidate.get("evidence_roles", []))
        bounded_note_term_count = len(
            candidate.get("matched_fields", {}).get("teaching_note", [])
        )
        has_direct_match = (
            bounded_note_term_count >= 2
            if candidate.get("runtime_evidence_mode")
            == "bounded_note_windows"
            else bool(
                candidate.get("matched_original_terms")
                or candidate.get("matched_equivalent_terms")
                or entry_is_core(entry)
            )
        )
        bounded_note_direct_match = bool(
            candidate.get("runtime_evidence_mode")
            == "bounded_note_windows"
            and bounded_note_term_count >= 3
            and (
                candidate.get("matched_original_terms")
                or candidate.get("matched_equivalent_terms")
            )
        )
        runtime_evidence_channels = {
            "teaching_note_lexicon",
            "teaching_note_ngram",
            "full_transcript_lexicon",
            "full_transcript_ngram",
            "chunk_transcript_lexicon",
            "chunk_transcript_ngram",
        }
        limited_metadata_transcript_match = bool(
            candidate.get("metadata_title_trust") == "limited"
            and set(candidate.get("retrieval_channels", []))
            & runtime_evidence_channels
            and entry.get("concept_match") == "exact_question"
        )
        reason = None
        if tier in allowed_tiers and has_direct_match:
            if not primary_entries:
                reason = "supplemental_only_direct_evidence_available"
            elif adds_concepts and (
                candidate.get("runtime_evidence_mode")
                != "bounded_note_windows"
                or bounded_note_term_count >= 3
            ):
                reason = "supplemental_fills_uncovered_query_concept"
            elif roles & (required_roles - covered_roles):
                reason = "supplemental_fills_requested_evidence_role"
            elif (
                (
                    tier == "direct"
                    or bounded_note_direct_match
                    or limited_metadata_transcript_match
                )
                and entry_is_core(entry)
                and corroboration_count < 1
            ):
                reason = "supplemental_direct_corroboration"
                corroboration_count += 1
        if reason is None:
            rejected.append(
                {
                    **entry,
                    "selection_reasons": [
                        "supplemental_not_needed_for_synthesis"
                    ],
                }
            )
            continue
        entry["selection_reasons"].append(reason)
        kept.append(entry)
        supplemental_count += 1
        covered_concepts.update(candidate_concepts)
        covered_roles.update(roles)
    return kept, rejected














_diagnostic_contract = load_sibling(
    "liuhui_diagnostic_contract", "diagnostic_contract.py"
)
extract_user_hypotheses = _diagnostic_contract.extract_user_hypotheses
diagnostic_mechanism_for_text = _diagnostic_contract.diagnostic_mechanism_for_text
diagnostic_observed_symptoms = _diagnostic_contract.diagnostic_observed_symptoms
selected_video_evidence_text = _diagnostic_contract.selected_video_evidence_text
claim_scope_directness = _diagnostic_contract.claim_scope_directness
has_requested_action_scope_support = _diagnostic_contract.has_requested_action_scope_support
claim_evidence_entry = _diagnostic_contract.claim_evidence_entry
confidence_ceiling = _diagnostic_contract.confidence_ceiling
query_unit_evidence = _diagnostic_contract.query_unit_evidence
mechanism_evidence = _diagnostic_contract.mechanism_evidence
material_diagnostic_branches = _diagnostic_contract.material_diagnostic_branches
build_diagnostic_contract = _diagnostic_contract.build_diagnostic_contract


def answer_visible_video_labels(claim_evidence_map):
    labels = []
    seen = set()
    for claim in claim_evidence_map:
        for evidence in claim.get("evidence", []):
            label = evidence.get("label")
            if label and label not in seen:
                labels.append(label)
                seen.add(label)
    return labels


def _remap_contract_video_labels(value, label_map):
    """Remap only structured video-label fields in a diagnostic contract."""

    if isinstance(value, dict):
        for labels_key in ("eligible_video_labels", "evidence_labels"):
            labels = value.get(labels_key)
            if isinstance(labels, list):
                value[labels_key] = [
                    label_map.get(label, label) for label in labels
                ]
        if value.get("evidence_id") and value.get("label") in label_map:
            value["label"] = label_map[value["label"]]
        if value.get("video_label") in label_map:
            value["video_label"] = label_map[value["video_label"]]
        for child in value.values():
            _remap_contract_video_labels(child, label_map)
    elif isinstance(value, list):
        for child in value:
            _remap_contract_video_labels(child, label_map)


def relabel_answer_videos(
    selected_videos,
    diagnostic_contract,
    visible_labels=None,
):
    """Put answer-visible videos first and assign a contiguous usefulness order."""

    selected_by_label = {
        video["label"]: video for video in selected_videos
    }
    if len(selected_by_label) != len(selected_videos):
        raise ValueError("selected video labels must be unique")
    if visible_labels is None:
        visible_labels = answer_visible_video_labels(
            diagnostic_contract["claim_evidence_map"]
        )
    unknown_labels = [
        label for label in visible_labels if label not in selected_by_label
    ]
    if unknown_labels:
        raise ValueError(
            "claim evidence references unknown selected video labels: "
            + ", ".join(unknown_labels)
        )
    visible_set = set(visible_labels)
    ordered_old_labels = [
        *visible_labels,
        *[
            video["label"]
            for video in selected_videos
            if video["label"] not in visible_set
        ],
    ]
    label_map = {
        old_label: f"V{index}"
        for index, old_label in enumerate(ordered_old_labels, start=1)
    }
    for video in selected_videos:
        video["label"] = label_map[video["label"]]
    _remap_contract_video_labels(diagnostic_contract, label_map)
    return (
        selected_videos,
        [f"V{index}" for index in range(1, len(visible_labels) + 1)],
        label_map,
    )


def automatic_expansion_variant_failure(
    search_module,
    video,
    entry,
    requested_constraints,
    constraint_match,
    rules,
):
    """Fail closed when a named variant is absent from retrieved B chunks."""

    if video.get("retrieval_cohort") != "automatic_expansion":
        return None
    requested_variants = requested_constraints.get(
        "technique_variant", []
    )
    if not requested_variants:
        return None
    if constraint_match.get("technique_variant") not in {
        "exact",
        "mixed_support",
    }:
        return "automatic_expansion_named_variant_not_exact"
    variant_axis = next(
        (
            axis
            for axis in rules.get("constraint_axes", [])
            if axis.get("name") == "technique_variant"
        ),
        None,
    )
    if not variant_axis:
        return "automatic_expansion_named_variant_rules_missing"
    variant_terms = [
        term
        for variant in requested_variants
        for term in variant_axis.get("values", {}).get(variant, [])
    ]
    hints = (
        entry.get("candidate", {})
        .get("transcript_retrieval", {})
        .get("chunk_hints", [])
    )
    segments = search_module.video_transcript_segments(video)
    if hints:
        segment_indexes = {
            index
            for hint in hints
            for index in range(
                max(0, int(hint.get("start_segment", 0))),
                min(
                    len(segments),
                    int(hint.get("end_segment", len(segments))),
                ),
            )
        }
        evidence_text = "".join(
            str(segments[index].get("text") or "")
            for index in sorted(segment_indexes)
        )
    else:
        evidence_text = "".join(
            str(segment.get("text") or "") for segment in segments
        )
    normalized_evidence = search_module.normalize(evidence_text)
    if not any(
        search_module.normalize(term) in normalized_evidence
        for term in variant_terms
        if search_module.normalize(term)
    ):
        return "automatic_expansion_named_variant_missing_from_query_chunks"
    return None


def evaluate_candidate_for_query_unit(
    search_module,
    query,
    plan,
    boundary,
    entry,
    video,
    rules,
    actor_context,
    constraint_scope,
):
    """Evaluate one candidate against one independently planned query unit."""

    requested_constraints = actor_context["target_constraints"]
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
    actor_failures = non_target_actor_condition_failures(
        search_module,
        actor_context,
        constraint_scope,
        video,
        rules,
    )
    if actor_failures:
        keep = False
        reasons = actor_failures
    derived_failures = derived_player_constraint_failures(
        actor_context["derived_player_constraints"],
        constraint_scope,
        rules,
    )
    if derived_failures:
        keep = False
        reasons = derived_failures
    action_failures = requested_action_scope_failures(
        search_module,
        actor_context,
        video,
        rules,
    )
    action_reason_may_replace = keep or set(reasons).issubset(
        {
            "recall_safeguard_only",
            "no_direct_or_supporting_question_evidence",
        }
    )
    if (
        action_failures
        and not actor_failures
        and not derived_failures
        and action_reason_may_replace
    ):
        keep = False
        reasons = action_failures
    action_fallback_scope_supported = all(
        constraint_result[4].get(axis_name)
        in {"exact", "mixed_support", "incidental_support"}
        and constraint_scope.get(axis_name, {}).get("source")
        in {
            "primary_metadata",
            "reviewed_context",
            "primary_and_reviewed",
            "reviewed_override",
            "category",
        }
        for axis_name in requested_constraints
    )
    if (
        actor_context.get("requested_action_scopes")
        and not action_failures
        and not actor_failures
        and not derived_failures
        and not keep
        and set(reasons).issubset(
            {
                "recall_safeguard_only",
                "no_direct_or_supporting_question_evidence",
                "literal_symptom_or_mechanism_not_supported",
            }
        )
        and constraint_result[0]
        and action_fallback_scope_supported
        and (
            concept_decision(search_module, plan, entry, video, rules)
            != "none"
            or set(actor_context.get("requested_action_scopes", []))
            == {"positioning"}
        )
        and has_instructional_evidence(video)
    ):
        keep = True
        reasons = [
            (
                "matched_inferred_target_action_scope"
                if actor_context.get("inferred_target_action")
                else "matched_requested_action_scope_support_only"
            )
        ]
    variant_failure = automatic_expansion_variant_failure(
        search_module,
        video,
        entry,
        requested_constraints,
        constraint_result[4],
        rules,
    )
    if variant_failure:
        keep = False
        reasons = [variant_failure]
    unrequested_scope = unrequested_specific_scope(
        constraint_result[2], constraint_scope, rules
    )
    ranking_scope = unrequested_ranking_scope(
        constraint_result[2], constraint_scope, rules
    )
    concept_match = concept_decision(
        search_module, plan, entry, video, rules
    )
    focus_match = entry_focus_match(
        search_module, plan, entry, video, rules
    )
    symptom_match = symptom_decision(search_module, plan, video, rules)
    scope_supported_axes = [
        axis_name
        for axis_name in requested_constraints
        if constraint_result[4].get(axis_name)
        in {"exact", "mixed_support", "incidental_support"}
    ]
    best_match_rank = min(
        (match.get("rank", 10**6) for match in entry.get("matches", [])),
        default=10**6,
    )
    reviewed_scope_support = any(
        constraint_scope.get(axis_name, {}).get("source")
        in {
            "reviewed_context",
            "reviewed_override",
            "primary_and_reviewed",
        }
        for axis_name in scope_supported_axes
    )
    scoped_instructional_rescue = bool(
        not actor_failures
        and not derived_failures
        and not action_failures
        and not variant_failure
        and constraint_result[0]
        and scope_supported_axes
        and has_instructional_evidence(video)
        and set(reasons).issubset(
            {
                "no_direct_or_supporting_question_evidence",
                "literal_symptom_or_mechanism_not_supported",
            }
        )
        and (
            (
                concept_match != "none"
                and best_match_rank <= 3
                and (
                    reviewed_scope_support
                    or len(scope_supported_axes) >= 2
                )
            )
            or (
                concept_match == "none"
                and reviewed_scope_support
                and best_match_rank
                <= rules.get("direct_review_rank_acceptance", 24)
            )
        )
    )
    if scoped_instructional_rescue:
        keep = True
        reasons = ["matched_constraint_scoped_instructional_evidence"]
        if concept_match == "none":
            concept_match = "constraint_scoped_support"
    weak_requested_action_axes = {
        axis_name
        for axis_name in {
            "shot_family",
            "technique_variant",
        }
        if requested_constraints.get(axis_name)
        and constraint_result[4].get(axis_name)
        in {"unspecified_support", "incidental_support"}
    }
    if (
        keep
        and weak_requested_action_axes
        and set(ranking_scope) & {"shot_family", "technique_variant"}
        and not any(
            constraint_result[4].get(axis_name) == "exact"
            for axis_name in requested_constraints
        )
        and concept_match
        in {
            "component_support",
            "constraint_scoped_support",
            "expanded_support",
            "reviewed_support",
        }
    ):
        keep = False
        reasons = [
            "unrequested_specific_scope_cannot_fill_weak_action_scope"
        ]
    if (
        symptom_match == "none"
        and entry.get("reviewed_evidence_rank", 2) <= 1
        and concept_match != "none"
    ):
        symptom_match = "reviewed_mechanism"
    return {
        "keep": keep,
        "reasons": list(reasons),
        "constraint_result": constraint_result,
        "unrequested_scope": unrequested_scope,
        "ranking_scope": ranking_scope,
        "action_failures": action_failures,
        "concept_match": concept_match,
        "focus_match": focus_match,
        "symptom_match": symptom_match,
        "actor_context_rank": partner_context_rank(
            search_module, actor_context, video, rules
        ),
        "inferred_target_action_match": bool(
            actor_context.get("inferred_target_action")
            and not action_failures
        ),
    }


def prepare_answer_context(
    query,
    max_videos=None,
    segment_limit=None,
    local_personalization=True,
    feedback_dir=None,
    include_rejected=False,
    continue_from=None,
    clarification_answers=None,
):
    if not query.strip():
        raise ValueError("query cannot be empty")
    search_module = load_search_module()
    navigation_module = load_navigation_module()
    feedback_module = load_feedback_module()
    rules = load_selection_rules()
    diagnostic_rules = load_diagnostic_rules()
    continuation = None
    if continue_from is not None:
        query, continuation = resolve_continuation(
            search_module,
            query,
            continue_from,
            clarification_answers,
            diagnostic_rules,
        )
    elif clarification_answers is not None:
        raise ValueError("clarification_answers requires continue_from")
    user_query = query
    query = canonicalize_retrieval_query(query, rules)
    max_videos = max_videos or rules["default_max_selected_videos"]
    segment_limit = segment_limit or rules["default_segment_limit"]
    if not 1 <= max_videos <= 120:
        raise ValueError("max_videos must be between 1 and 120")
    if not 1 <= segment_limit <= 12:
        raise ValueError("segment_limit must be between 1 and 12")

    plan, retrieval_base_query = continuation_query_plan(
        search_module, query, continuation
    )
    intent_frame = plan["retrieval_guidance"]["intent_frame"]
    positive_query = intent_frame.get("positive_query", query)
    actor_query = intent_frame.get("actor_query", positive_query)
    boundary = classify_boundary(positive_query, rules)
    knowledge, retrieval_index, retrieval_rules = search_module.load_resources()
    reviewed_priorities = reviewed_evidence_priorities(
        search_module,
        retrieval_base_query,
        plan,
        retrieval_index,
        retrieval_rules,
        rules,
        load_reviewed_evidence_signals(),
    )
    normalized_positive_query = search_module.normalize(positive_query)
    for atom in load_reviewed_evidence_atoms():
        aliases = {
            atom.get("canonical_claim", ""),
            *atom.get("claim_aliases", []),
        }
        if any(
            search_module.normalize(alias) in normalized_positive_query
            for alias in aliases
            if alias
        ):
            evidence_id = atom.get("evidence_id")
            if evidence_id:
                reviewed_priorities[evidence_id] = 0
    navigation = None
    source_query_units = plan["retrieval_guidance"].get(
        "query_units"
    ) or [query]
    query_unit_records = analyze_query_units(source_query_units)
    evidence_query_units = [
        item["evidence_query"]
        for item in query_unit_records
        if item["evidence_query"]
    ] or [query]
    retrieval_plan = {
        **plan,
        "retrieval_guidance": {
            **plan["retrieval_guidance"],
            "query_units": evidence_query_units,
        },
    }
    retrieval_queries = planned_queries(
        search_module, retrieval_plan, retrieval_base_query, rules
    )
    use_topic_navigation = plan["retrieval_guidance"].get(
        "use_topic_navigation"
    )
    needs_practice_context = (
        plan["retrieval_guidance"]["intent_frame"].get("requested_output")
        == "practice"
        and boundary["type"]
        not in {
            "pain_or_injury",
            "endorsement_or_authorship",
            "purchase_advice",
        }
    )
    if use_topic_navigation or needs_practice_context:
        navigation = topic_navigation(navigation_module, retrieval_base_query)
    if use_topic_navigation:
        retrieval_queries.extend(navigation["suggested_search_queries"][:3])
        retrieval_queries = list(dict.fromkeys(retrieval_queries))
    retrieval_queries, retrieval_query_budget = budget_retrieval_queries(
        search_module,
        retrieval_queries,
        retrieval_plan,
        retrieval_base_query,
        rules,
    )

    payload_iterator = (
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
    )
    primary_payload = next(payload_iterator)
    merged = merge_candidates(
        chain([primary_payload], payload_iterator), retrieval_queries
    )
    videos = search_module.knowledge_video_map(knowledge, merged)
    actor_context = query_actor_context(search_module, actor_query, rules)
    requested_constraints = actor_context["target_constraints"]
    boundary = classify_boundary(
        positive_query,
        rules,
        requested_constraints=requested_constraints,
    )
    query_units = evidence_query_units
    coherent_actor_sequence = bool(
        actor_context.get("inferred_target_action")
        and actor_context.get("event_chain")
        and "同时" not in retrieval_base_query
    )
    diagnostic_query_units = (
        [actor_context["target_action_query"]]
        if coherent_actor_sequence and len(query_units) > 1
        else query_units
    )
    split_multi_issue = (
        plan["retrieval_guidance"].get("strategy") == "split_multi_issue"
        and len(query_units) > 1
        and not coherent_actor_sequence
    )
    unit_evaluation_specs = []
    if split_multi_issue:
        for unit in query_units:
            unit_plan = search_module.plan_query(unit)
            unit_plan["retrieval_guidance"]["strategy"] = "split_multi_issue"
            unit_plan["retrieval_guidance"]["query_units"] = [unit]
            unit_intent = unit_plan["retrieval_guidance"]["intent_frame"]
            unit_actor_query = unit_intent.get(
                "actor_query", unit_intent.get("positive_query", unit)
            )
            unit_evaluation_specs.append(
                {
                    "unit": unit,
                    "plan": unit_plan,
                    "actor_context": query_actor_context(
                        search_module, unit_actor_query, rules
                    ),
                    "boundary": classify_boundary(unit, rules),
                }
            )
    else:
        unit_evaluation_specs = [
            {
                "unit": (
                    retrieval_base_query
                    if coherent_actor_sequence
                    else query_units[0]
                ),
                "plan": plan,
                "actor_context": actor_context,
                "boundary": boundary,
            }
        ]
    local_unit_actor_contexts = {
        spec["unit"]: spec["actor_context"] for spec in unit_evaluation_specs
    }
    root_actor_context = next(
        (
            spec["actor_context"]
            for spec in unit_evaluation_specs
            if spec["actor_context"].get("target_constraints")
        ),
        actor_context,
    )
    unit_roles = {
        item["evidence_query"]: item["role"]
        for item in query_unit_records
        if item["evidence_query"]
    }
    for spec in unit_evaluation_specs:
        local_constraints = spec["actor_context"].get(
            "target_constraints", {}
        )
        parent_context = (
            root_actor_context
            if should_inherit_root_context(
                local_constraints,
                unit_roles.get(spec["unit"], "evidence_question"),
            )
            else {}
        )
        spec["actor_context"] = inherit_actor_context(
            parent_context,
            spec["actor_context"],
        )
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
        constraint_scope = search_module._VIDEO_CONSTRAINT_SCOPE_CACHE.get(video_id)
        if constraint_scope is None:
            constraint_scope = video_constraint_scope(search_module, video, rules)
        evaluations = [
            {
                **spec,
                "evaluation": evaluate_candidate_for_query_unit(
                    search_module,
                    spec["unit"],
                    spec["plan"],
                    spec["boundary"],
                    entry,
                    video,
                    rules,
                    spec["actor_context"],
                    constraint_scope,
                ),
            }
            for spec in unit_evaluation_specs
        ]
        kept_evaluations = [
            item for item in evaluations if item["evaluation"]["keep"]
        ]
        chosen = (kept_evaluations or evaluations)[0]
        evaluation = chosen["evaluation"]
        keep = bool(kept_evaluations)
        supported_units = [item["unit"] for item in kept_evaluations]
        failed_focus_units = [
            item["unit"]
            for item in evaluations
            if item["unit"] not in supported_units
            and (
                focus_groups := required_focus_groups(
                    search_module, item["unit"], rules
                )
            )
            and video_supports_required_focus(
                search_module, video, focus_groups, rules
            )
        ]
        if (
            keep
            and failed_focus_units
            and all(
                item["evaluation"]["concept_match"]
                in {"expanded_support", "reviewed_support"}
                for item in kept_evaluations
            )
        ):
            keep = False
        else:
            failed_focus_units = []
        reasons = list(evaluation["reasons"])
        if failed_focus_units:
            reasons = ["cross_unit_focus_evidence_failed_its_own_unit"]
        elif not keep and len(evaluations) > 1:
            reasons = list(
                dict.fromkeys(
                    reason
                    for item in evaluations
                    for reason in item["evaluation"]["reasons"]
                )
            )
        constraint_result = evaluation["constraint_result"]
        if not keep:
            supported_units = []
        query_unit_constraint_matches = {
            item["unit"]: item["evaluation"]["constraint_result"][4]
            for item in evaluations
        }
        record = {
            **entry,
            "video_id": video_id,
            "selection_reasons": list(reasons),
            "constraint_scope": constraint_scope,
            "unrequested_constraint_scope": evaluation[
                "unrequested_scope"
            ],
            "unrequested_ranking_scope": evaluation["ranking_scope"],
            "inferred_target_action_match": evaluation[
                "inferred_target_action_match"
            ],
            "supported_query_units": supported_units,
            "query_unit_constraint_matches": query_unit_constraint_matches,
        }
        record["constraint_match"] = constraint_result[4]
        record["actor_context_rank"] = evaluation["actor_context_rank"]
        if keep and evaluation["unrequested_scope"]:
            record["selection_reasons"].append(
                "unrequested_specific_scenario_support_only"
            )
        if keep and evaluation["ranking_scope"]:
            record["selection_reasons"].append(
                "unrequested_additional_scope_requires_conditioning"
            )
        if (
            keep
            and record["inferred_target_action_match"]
            and "matched_inferred_target_action_scope"
            not in record["selection_reasons"]
        ):
            record["selection_reasons"].append(
                "matched_inferred_target_action_scope"
            )
        record["concept_match"] = evaluation["concept_match"]
        record["focus_match"] = evaluation["focus_match"]
        record["symptom_match"] = evaluation["symptom_match"]
        record["matched_query_units"] = sorted(
            set(supported_units)
            or {item["query"] for item in entry["matches"]}
        )
        (accepted if keep else rejected).append(record)

    accepted.sort(key=lambda entry: selected_sort_key(entry, rules))
    semantic_answerable_entries = list(accepted)
    deferred = []
    accepted, cluster_duplicates = search_module.cap_content_clusters(
        accepted,
        candidate_getter=lambda entry: entry["candidate"],
    )
    deferred.extend(
        {
            **duplicate["item"],
            "selection_reasons": [
                "content_cluster_duplicate_deferred_from_synthesis"
            ],
            "duplicate_of_video_id": duplicate["representative"]["video_id"],
            "duplicate_content_cluster_id": duplicate["cluster_id"],
        }
        for duplicate in cluster_duplicates
    )
    automatic_limit = rules.get(
        "automatic_expansion_selection_limit", 3
    )
    cohort_kept = []
    cohort_suppressed = []
    automatic_count = 0
    for entry in accepted:
        if (
            entry["candidate"].get("retrieval_cohort")
            == "automatic_expansion"
        ):
            automatic_count += 1
            if automatic_count > automatic_limit:
                cohort_suppressed.append(entry)
                continue
        cohort_kept.append(entry)
    accepted = cohort_kept
    deferred.extend(
        {
            **entry,
            "selection_reasons": [
                "automatic_expansion_synthesis_limit_exceeded"
            ],
        }
        for entry in cohort_suppressed
    )
    accepted, supplemental_deferred = apply_supplemental_evidence_policy(
        accepted,
        plan,
        boundary,
        rules,
    )
    deferred.extend(supplemental_deferred)
    exact_entries = [
        entry
        for entry in accepted
        if entry_is_core(entry)
    ]
    support_entries = [entry for entry in accepted if entry not in exact_entries]
    if (
        split_multi_issue
        or len(question_concept_anchors(search_module, plan)) > 1
    ):
        support_entries = diversify_support_entries(
            search_module,
            plan,
            exact_entries,
            support_entries,
            rules,
        )
    synthesis_candidate_entries = [*exact_entries, *support_entries]
    selected_entries = semantic_answerable_entries[:max_videos]
    semantic_budget_deferred = [
        {
            **entry,
            "selection_reasons": ["semantic_answerable_video_limit_exceeded"],
        }
        for entry in semantic_answerable_entries[max_videos:]
    ]
    deferred.extend(semantic_budget_deferred)
    selected_ids = [item["video_id"] for item in selected_entries]
    lookup = (
        search_module.lookup_videos(
            selected_ids,
            query=query,
            local_personalization=local_personalization,
            feedback_dir=feedback_dir,
            segment_limit=segment_limit,
            include_query_match=False,
            chunk_hints_by_video={
                entry["video_id"]: entry["candidate"].get(
                    "transcript_retrieval", {}
                ).get("chunk_hints", [])
                for entry in selected_entries
                if entry["candidate"].get("transcript_retrieval", {}).get(
                    "chunk_hints"
                )
            },
        )
        if selected_ids
        else {"results": []}
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
                "answer_eligibility": candidate.get(
                    "answer_eligibility", "primary"
                ),
                "evidence_roles": candidate.get(
                    "evidence_roles", ["context"]
                ),
                "confidence_ceiling": (
                    "conditional_medium"
                    if candidate.get("answer_eligibility")
                    == "supplemental"
                    else "source_default"
                ),
                "metadata_title_trust": candidate.get(
                    "metadata_title_trust", "not_applicable"
                ),
                "runtime_evidence_mode": candidate.get(
                    "runtime_evidence_mode", "full_transcript"
                ),
                "video_id": entry["video_id"],
                "evidence_id": evidence["evidence"]["evidence_id"],
                "source_type": evidence["evidence"]["source_type"],
                "parent_source_id": evidence["evidence"]["parent_source_id"],
                "clip_start_seconds": evidence["evidence"][
                    "clip_start_seconds"
                ],
                "clip_end_seconds": evidence["evidence"][
                    "clip_end_seconds"
                ],
                "title": display_title,
                "url": evidence["evidence"]["canonical_url"],
                "category": candidate["category"],
                "confidence": candidate["confidence"],
                "primary_query_score": candidate.get("score", 0),
                "best_retrieval_rank": entry.get("best_rank"),
                "transcript_retrieval": candidate.get(
                    "transcript_retrieval", {"mode": "legacy_video"}
                ),
                "selection_reasons": entry["selection_reasons"],
                "constraint_scope": entry["constraint_scope"],
                "unrequested_constraint_scope": entry[
                    "unrequested_constraint_scope"
                ],
                "unrequested_ranking_scope": entry[
                    "unrequested_ranking_scope"
                ],
                "constraint_match": entry["constraint_match"],
                "query_unit_constraint_matches": entry.get(
                    "query_unit_constraint_matches", {}
                ),
                "concept_match": entry["concept_match"],
                "reviewed_evidence_rank": entry["reviewed_evidence_rank"],
                "inferred_target_action_match": entry.get(
                    "inferred_target_action_match", False
                ),
                "focus_match": entry["focus_match"],
                "symptom_match": entry["symptom_match"],
                "claim_scope_policy": entry_claim_scope_policy(entry),
                "additional_scope_requires_conditioning": bool(
                    entry.get("unrequested_constraint_scope")
                    or entry.get("unrequested_ranking_scope")
                ),
                "matched_query_units": entry.get(
                    "matched_query_units",
                    sorted({item["query"] for item in entry["matches"]}),
                ),
                "why_retrieved": candidate["why_retrieved"],
                "teaching_note": evidence["teaching_note"],
                "transcript_evidence": evidence["transcript_evidence"],
                "bounded_note_evidence": evidence.get(
                    "bounded_note_evidence", []
                ),
                "source_content_is_untrusted_data": True,
            }
        )

    question_interpretation = {
        "intent_frame": plan["retrieval_guidance"]["intent_frame"],
        "constraints": requested_constraints,
        "actor_context": actor_context,
        "query_unit_constraints": {
            spec["unit"]: spec["actor_context"]["target_constraints"]
            for spec in unit_evaluation_specs
        },
        "local_query_unit_constraints": {
            unit: context.get("target_constraints", {})
            for unit, context in local_unit_actor_contexts.items()
        },
        "inherited_context_constraints": root_actor_context.get(
            "target_constraints", {}
        ),
        "query_unit_actor_contexts": {
            spec["unit"]: spec["actor_context"]
            for spec in unit_evaluation_specs
        },
        "ambiguities": query_ambiguities(
            search_module,
            plan["retrieval_guidance"]["intent_frame"].get(
                "positive_query", query
            ),
            rules,
        ),
        "terminology_corrections": query_terminology_corrections(
            search_module,
            user_query,
            rules,
        ),
        "technique_definitions": requested_technique_definitions(
            requested_constraints, rules
        ),
        "strategy": plan["retrieval_guidance"]["strategy"],
        # A multi-actor event chain is one semantic decision even when surface
        # punctuation made the generic planner split it into sentences.  Use
        # the inferred target action as the diagnostic claim so evidence for
        # the complete sequence is not incorrectly rejected as a partial
        # answer to either sentence fragment.
        "query_units": diagnostic_query_units,
        "source_query_units": source_query_units,
        "query_unit_records": query_unit_records,
        "retrieval_queries": retrieval_queries,
        "retrieval_query_budget": retrieval_query_budget,
        "clarification_policy": plan["retrieval_guidance"].get(
            "clarification_policy"
        ),
    }
    diagnostic_contract = build_diagnostic_contract(
        search_module,
        query,
        plan,
        question_interpretation,
        boundary,
        selected_videos,
        diagnostic_rules,
        resolved_question_ids={
            item["question_id"]
            for item in (continuation or {}).get("resolved_answers", [])
        },
        resolved_answers=(continuation or {}).get("resolved_answers", []),
    )
    delivery_contract = build_delivery_contract(
        user_query,
        question_interpretation,
        diagnostic_contract["diagnostic_model"],
        navigation,
    )
    diagnostic_contract["completeness_contract"]["items"].extend(
        delivery_completeness_items(delivery_contract)
    )
    selected_videos, visible_labels, _ = relabel_answer_videos(
        selected_videos, diagnostic_contract
    )
    selected_ids = [video["video_id"] for video in selected_videos]
    if retrieval_query_budget["missing_required_units"]:
        diagnostic_contract["completeness_contract"]["items"].append(
            {
                "item_id": "retrieval.required_units_over_hard_limit",
                "text": "问题包含超过检索硬上限的独立必答单元",
                "status": "unresolved",
                "required_treatment": (
                    "明确说明本轮无法可靠覆盖的子问题，并请用户拆分后续问题"
                ),
            }
        )
        diagnostic_contract["completeness_contract"][
            "unresolved_item_ids"
        ].append("retrieval.required_units_over_hard_limit")
    visible_label_set = set(visible_labels)
    answer_visible_videos = [
        video for video in selected_videos if video["label"] in visible_label_set
    ]
    answer_visible_videos.sort(key=lambda video: int(video["label"][1:]))
    context = {
        "query": user_query,
        "question_interpretation": question_interpretation,
        "boundary": boundary,
        "answer_guidance": plan["answer_guidance"],
        "feedback_guidance": primary_payload["feedback_guidance"],
        "topic_navigation": navigation,
        "delivery_contract": delivery_contract,
        "evidence_layer_contract": {
            "semantic_answerable_definition": (
                "passes_ready_relevance_scope_constraint_concept_and_"
                "symptom_evidence_checks"
            ),
            "synthesis_candidate_definition": (
                "semantically_answerable_after_content_cluster_automatic_"
                "expansion_and_supplemental_synthesis_policy"
            ),
            "max_synthesis_evidence_per_claim": diagnostic_rules.get(
                "max_synthesis_evidence_per_claim", 3
            ),
            "max_related_evidence_per_claim": diagnostic_rules.get(
                "max_related_evidence_per_claim", 8
            ),
            "core_video_limit": 5,
        },
        **diagnostic_contract,
        "selection": {
            "high_recall_candidate_count": len(merged),
            "semantic_answerable_video_count": len(
                semantic_answerable_entries
            ),
            "semantic_answerable_video_ids": [
                item["video_id"] for item in semantic_answerable_entries
            ],
            "synthesis_candidate_video_count": len(
                synthesis_candidate_entries
            ),
            "synthesis_candidate_video_ids": [
                item["video_id"] for item in synthesis_candidate_entries
            ],
            "eligible_video_count": len(semantic_answerable_entries),
            "eligible_exact_video_count": sum(
                entry_is_core(item) for item in semantic_answerable_entries
            ),
            "eligible_supporting_video_count": sum(
                not entry_is_core(item)
                for item in semantic_answerable_entries
            ),
            "selected_video_count": len(selected_videos),
            "selection_truncated": len(semantic_answerable_entries)
            > len(selected_videos),
            "max_selected_videos": max_videos,
            "selected_video_ids": selected_ids,
            "deferred_candidate_count": len(deferred),
            "rejected_candidate_count": len(rejected),
            "claim": (
                "layered_semantic_answerability_and_synthesis_selection_"
                "not_proof_of_unrestricted_semantic_completeness"
            ),
        },
        "selected_videos": selected_videos,
        "answer_visible_video_labels": visible_labels,
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
                "技术结论只引用 answer_synthesis_video_labels；完整相关视频清单使用 answer_complete_related_video_labels；selected_videos 中未映射到 claim 的 finalist 仅供审计。",
                "每个 V 标签只对应一个 evidence_id，并在答案中只输出一次 canonical URL。当前抖音条目的 evidence_id 等于 video_id；直播切片等新来源使用自己的稳定 evidence_id。",
                "结论必须由 teaching_note 或 transcript_evidence 直接支持。",
                "所有结论必须保持 question_interpretation.constraints 与 constraint_scope 的正反手、场区、单双打、发接发、主动被动、攻防和线路边界。",
                "question_interpretation.ambiguities 非空时，先逐条说明 required_statement；不得把有多种场区含义的术语静默收窄成一种技术。",
                "question_interpretation.terminology_corrections 非空时，先说明 required_statement，并在回答正文、视频标题改写和观看重点中只使用 canonical_term；错误输入词只可在纠正句中出现一次。",
                "question_interpretation.technique_definitions 是维护者确认的规范术语、父类、起跳边界和线路分类；用于解释技术归属，但不能让父类视频替代所问细分技术的直接动作证据。",
                "actor_context 已解析他/她的最近明确指代以及陪练、发球机等来球方；target_actor 指明建议对象。event_chain 非空时必须按顺序保留每个主体的先前动作、对手响应与目标动作，不得因中间插入另一主体而丢失命名序列。target_action_query 是实际请求动作，target_condition_query 是同一主体的既有状态或症状，不得把条件动作当成所问动作；inferred_target_action 非空时，先说明从症状推导出的目标动作，并把 incoming_shot_constraints 仅视为来球条件。target_action_backreferences_condition 为真时，怎么改等泛化请求只从 target_action_scope_query 继承已配置的动作范围。requested_action_scopes 要求来源直接支持所问动作，并排除只讨论其他场景或其他主体的来源。opponent_constraints、partner_constraints 与其他非目标主体约束只描述条件，不得当成目标球员执行动作。硬证据范围只使用 question_interpretation.constraints，其中 derived_target_constraints 可能是补位、轮转或站位所隐含的双打场景。",
                "concept_match 只说明概念覆盖；只有 claim_scope_policy 为 exact_question_scope 时才可支持无额外条件的完整问题。",
                "claim_scope_policy 为 additional_specific_scope_only_not_unrestricted_full_question_proof 时，必须明确说明 unrequested_constraint_scope 或 unrequested_ranking_scope 中的额外条件，不得把专项来源概括为泛问通则。",
                "exact_query_unit_scope_only 只支持对应子问题；component_or_generic_support_only_not_full_question_proof 只能支持局部机制或通用原则。",
                "文字承担可可靠表达的完整结论；视频承担动作形态、节奏和空间关系。",
                "无可靠证据时明确说知识库未覆盖，不用常识补成刘辉的观点。",
                "先执行 diagnostic_model 与 clarification_decision：用户提出的原因不是事实；除非用户动作已被观察，否则不得声称找到唯一原因。",
                "逐项执行 answer_turn_contract：正文承认每条 resolved_clarifications，不得重复询问 resolved_question_ids_must_not_be_reasked，并逐条提出 pending_clarifications；本轮引用只能来自契约绑定的最新 evidence_state。",
                "每个重要结论只能使用 answer_plan 为该结论选定、且同时位于 claim_evidence_map 的 V 标签，并服从 confidence_ceiling；完整相关视频不得被借用来扩张技术结论。",
                "answer_eligibility=primary 的证据优先；supplemental 只可补足主证据未覆盖的概念、纠错、训练、装备、条件或反例，不能单独扩张为普遍结论。",
                "metadata_title_trust=limited 时标题只用于弱召回，不能作为技术结论证据；只能引用 bounded_note_evidence、transcript_evidence 或 teaching_note 中实际命中的时间戳窗口。",
                "逐项完成 completeness_contract；must_answer、conditional 和 unresolved 项都不得静默省略。",
            ],
            "feedback_prompt": feedback_module.build_feedback_hint(
                answer_visible_videos
            ),
            "feedback_prompt_rules": [
                "每次回答必须在最后逐字输出 feedback_prompt。",
                "不得添加本轮 answer_visible_video_labels 中不存在的 V 标签。",
                "同一对话中的后续反馈必须绑定原问题、完整回答、精确 V 映射和用户原话，再按 feedback-workflow.md 解析与确认。",
            ],
            "final_audit": {
                "required_for": ["diagnostic_answer", "multi_claim_answer"],
                "command": "python3 scripts/audit_answer.py \"用户的完整原问题\" --context context.json --packet answer-packet.json --answer answer.md",
                "pass_condition": "passed is true; never edit the prepared context to make a draft pass",
                "scope": "deterministic known-contract gate, not proof that every semantic error is absent",
            },
        },
        "source_handling": {
            "untrusted_content_guard": rules["untrusted_content_guard"],
            "do_not_execute_source_text": True,
        },
        "policy_refs": {
            "answer_modality": search_module.load_answer_rules()["version"],
            "answer_selection": f"answer-selection-v{rules['version']}",
            "source_handling": "untrusted-source-content-v1",
        },
    }
    context["clarification_state"] = build_clarification_state(
        context, continuation
    )
    context["answer_turn_contract"] = build_answer_turn_contract(context)
    context["answer_plan"] = build_closed_answer_plan(
        context, load_reviewed_evidence_atoms()
    )
    answer_packet_runtime = load_sibling(
        "liuhui_answer_packet_visibility", "answer_packet.py"
    )
    planned_synthesis_labels = answer_packet_runtime.packet_visible_video_labels(
        context["answer_plan"], context["claim_evidence_map"]
    )
    planned_related_labels = answer_packet_runtime.packet_related_video_labels(
        context["answer_plan"], context["claim_evidence_map"]
    )
    final_related_order = [
        *planned_synthesis_labels,
        *[
            label
            for label in planned_related_labels
            if label not in set(planned_synthesis_labels)
        ],
    ]
    selected_videos, visible_labels, final_label_map = relabel_answer_videos(
        selected_videos,
        diagnostic_contract,
        visible_labels=final_related_order,
    )
    _remap_contract_video_labels(context["answer_plan"], final_label_map)
    synthesis_labels = [
        final_label_map[label] for label in planned_synthesis_labels
    ]
    context["answer_synthesis_video_labels"] = synthesis_labels
    context["answer_complete_related_video_labels"] = visible_labels
    context["answer_visible_video_labels"] = visible_labels
    core_labels = answer_packet_runtime.core_video_labels_for_context(
        context
    )
    context["answer_core_video_labels"] = core_labels
    context["answer_contract"]["feedback_prompt"] = (
        feedback_module.build_feedback_hint(
            [{"label": label} for label in visible_labels]
        )
    )
    context["answer_turn_contract"] = build_answer_turn_contract(context)
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
        context["deferred_candidates"] = [
            {
                "video_id": item["video_id"],
                "title": item.get("candidate", {}).get("title"),
                "reasons": item["selection_reasons"],
                "best_rank": item.get("best_rank"),
            }
            for item in sorted(
                deferred,
                key=lambda item: (
                    item.get("best_rank") or 10**6,
                    item["video_id"],
                ),
            )
        ]
        selected_id_set = set(selected_ids)
        deferred_by_id = {
            item["video_id"]: item["selection_reasons"]
            for item in deferred
        }
        context["unselected_semantically_answerable_candidates"] = [
            {
                "video_id": item["video_id"],
                "title": item["candidate"]["title"],
                "best_rank": item["best_rank"],
                "reasons": deferred_by_id.get(
                    item["video_id"],
                    ["not_selected_for_synthesis"],
                ),
            }
            for item in semantic_answerable_entries
            if item["video_id"] not in selected_id_set
        ]
        context["unselected_eligible_candidates"] = list(
            context["unselected_semantically_answerable_candidates"]
        )
    return context


def build_closed_answer_plan(context, atoms):
    return load_sibling(
        "liuhui_answer_packet", "answer_packet.py"
    ).build_closed_answer_plan(context, atoms)


def build_answer_packet(context, audit_context_reference=None):
    return load_sibling(
        "liuhui_answer_packet", "answer_packet.py"
    ).build_answer_packet(context, audit_context_reference)


def validate_answer_packet(packet, context):
    return load_sibling(
        "liuhui_answer_packet", "answer_packet.py"
    ).validate_answer_packet(packet, context)


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
        "--continue-from",
        type=Path,
        help="Prior context JSON whose clarification state should be continued.",
    )
    parser.add_argument(
        "--clarification-answers",
        type=Path,
        help="JSON object or list binding pending question IDs to answers.",
    )
    parser.add_argument(
        "--include-rejected",
        action="store_true",
        help="Include rejected finalist candidates and machine-readable reasons.",
    )
    parser.add_argument(
        "--answer-packet",
        action="store_true",
        help="Print the compact answer-facing packet instead of the audit context.",
    )
    parser.add_argument(
        "--audit-context",
        type=Path,
        help="Write the complete authoritative context to this path.",
    )
    args = parser.parse_args()
    if args.answer_packet and not args.audit_context:
        parser.error("--answer-packet requires --audit-context")
    try:
        previous_context = (
            json.loads(args.continue_from.read_text(encoding="utf-8"))
            if args.continue_from
            else None
        )
        clarification_answers = (
            json.loads(args.clarification_answers.read_text(encoding="utf-8"))
            if args.clarification_answers
            else None
        )
        payload = prepare_answer_context(
            args.query,
            max_videos=args.max_videos,
            segment_limit=args.segment_limit,
            local_personalization=not args.no_local_personalization,
            feedback_dir=args.feedback_dir,
            include_rejected=args.include_rejected,
            continue_from=previous_context,
            clarification_answers=clarification_answers,
        )
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise SystemExit(str(error)) from error
    if args.audit_context:
        args.audit_context.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    output = (
        build_answer_packet(payload, args.audit_context)
        if args.answer_packet
        else payload
    )
    print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
