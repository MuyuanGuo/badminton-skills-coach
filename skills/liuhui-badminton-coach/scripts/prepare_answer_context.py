#!/usr/bin/env python3
"""Build a deterministic, evidence-ready context before answer generation."""

import argparse
import importlib.util
import json
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
ANSWER_PACKET_SCHEMA_VERSION = 1
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
    signals = json.loads(REVIEWED_EVIDENCE_PATH.read_text(encoding="utf-8")).get(
        "signals", []
    )
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
_answer_continuation.CLARIFICATION_STATE_SCHEMA_VERSION = CLARIFICATION_STATE_SCHEMA_VERSION
_answer_continuation.ANSWER_TURN_CONTRACT_SCHEMA_VERSION = ANSWER_TURN_CONTRACT_SCHEMA_VERSION
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
_answer_retrieval_plan.load_reviewed_evidence_signals = load_reviewed_evidence_signals
reviewed_evidence_priorities = _answer_retrieval_plan.reviewed_evidence_priorities
planned_queries = _answer_retrieval_plan.planned_queries
budget_retrieval_queries = _answer_retrieval_plan.budget_retrieval_queries
continuation_query_plan = _answer_retrieval_plan.continuation_query_plan
topic_navigation = _answer_retrieval_plan.topic_navigation
merge_candidates = _answer_retrieval_plan.merge_candidates


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
_answer_retrieval_plan.explicit_constraint_terms = explicit_constraint_terms
_answer_retrieval_plan.query_actor_context = query_actor_context
_answer_retrieval_plan.required_focus_groups = required_focus_groups














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
    segments = video.get("transcript_segments") or []
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
    explicit_max_videos = max_videos is not None
    max_videos = max_videos or rules["default_max_selected_videos"]
    segment_limit = segment_limit or rules["default_segment_limit"]
    if not 1 <= max_videos <= 40:
        raise ValueError("max_videos must be between 1 and 40")
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
    )
    navigation = None
    retrieval_queries = planned_queries(
        search_module, plan, retrieval_base_query, rules
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
    if include_rejected:
        retrieval_query_budget = {
            "configured_budget": rules.get("retrieval_query_budget", 24),
            "hard_limit": rules.get("retrieval_query_hard_limit", 48),
            "generated_query_count": len(retrieval_queries),
            "executed_query_count": len(retrieval_queries),
            "truncated": False,
            "omitted_query_count": 0,
            "missing_required_units": [],
            "diagnostic_override": True,
        }
    else:
        retrieval_queries, retrieval_query_budget = budget_retrieval_queries(
            search_module,
            retrieval_queries,
            plan,
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
    videos = {video["video_id"]: video for video in knowledge["videos"]}
    actor_context = query_actor_context(search_module, actor_query, rules)
    requested_constraints = actor_context["target_constraints"]
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
        action_fallback_axes = set(requested_constraints)
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
            for axis_name in action_fallback_axes
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
        record = {
            **entry,
            "video_id": video_id,
            "selection_reasons": list(reasons),
            "constraint_scope": constraint_scope,
            "unrequested_constraint_scope": unrequested_scope,
            "unrequested_ranking_scope": ranking_scope,
            "inferred_target_action_match": bool(
                actor_context.get("inferred_target_action")
                and not action_failures
            ),
        }
        record["constraint_match"] = constraint_result[4]
        record["actor_context_rank"] = partner_context_rank(
            search_module,
            actor_context,
            video,
            rules,
        )
        if keep and unrequested_scope:
            record["selection_reasons"].append(
                "unrequested_specific_scenario_support_only"
            )
        if keep and ranking_scope:
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
        record["concept_match"] = concept_decision(
            search_module, plan, entry, video, rules
        )
        record["focus_match"] = entry_focus_match(
            search_module, plan, entry, video, rules
        )
        record["symptom_match"] = symptom_decision(
            search_module, plan, video, rules
        )
        if (
            record["symptom_match"] == "none"
            and entry.get("reviewed_evidence_rank", 2) <= 1
            and record["concept_match"] != "none"
        ):
            record["symptom_match"] = "reviewed_mechanism"
        (accepted if keep else rejected).append(record)

    accepted.sort(key=lambda entry: selected_sort_key(entry, rules))
    accepted, cluster_duplicates = search_module.cap_content_clusters(
        accepted,
        candidate_getter=lambda entry: entry["candidate"],
    )
    rejected.extend(
        {
            **duplicate["item"],
            "selection_reasons": ["content_cluster_duplicate"],
            "duplicate_of_video_id": duplicate["representative"]["video_id"],
            "duplicate_content_cluster_id": duplicate["cluster_id"],
        }
        for duplicate in cluster_duplicates
    )
    exact_entries = [
        entry
        for entry in accepted
        if entry_is_core(entry)
    ]
    support_entries = [entry for entry in accepted if entry not in exact_entries]
    support_limit = rules.get("max_supporting_videos", 4)
    requested_variants = requested_constraints.get("technique_variant", [])
    if len(requested_variants) == 1:
        support_limit = rules.get(
            "supporting_video_limits_by_technique_variant", {}
        ).get(requested_variants[0], support_limit)
    support_limit = min(support_limit, max_videos)
    if explicit_max_videos and not exact_entries:
        # An explicit evidence budget should remain usable when the corpus has
        # no exact/core source. Returning only the default supporting cap can
        # hide a valid response-oriented source even though the caller asked
        # for a larger bounded set.
        support_limit = max_videos
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
                "concept_match": entry["concept_match"],
                "reviewed_evidence_rank": entry["reviewed_evidence_rank"],
                "focus_match": entry["focus_match"],
                "symptom_match": entry["symptom_match"],
                "claim_scope_policy": entry_claim_scope_policy(entry),
                "additional_scope_requires_conditioning": bool(
                    entry.get("unrequested_constraint_scope")
                    or entry.get("unrequested_ranking_scope")
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

    question_interpretation = {
        "intent_frame": plan["retrieval_guidance"]["intent_frame"],
        "constraints": requested_constraints,
        "actor_context": actor_context,
        "ambiguities": query_ambiguities(
            search_module,
            plan["retrieval_guidance"]["intent_frame"].get(
                "positive_query", query
            ),
            rules,
        ),
        "terminology_corrections": query_terminology_corrections(
            search_module,
            plan["retrieval_guidance"]["intent_frame"].get(
                "positive_query", query
            ),
            rules,
        ),
        "technique_definitions": requested_technique_definitions(
            requested_constraints, rules
        ),
        "strategy": plan["retrieval_guidance"]["strategy"],
        "query_units": plan["retrieval_guidance"].get("query_units", []),
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
    visible_labels = answer_visible_video_labels(
        diagnostic_contract["claim_evidence_map"]
    )
    visible_label_set = set(visible_labels)
    answer_visible_videos = [
        video for video in selected_videos if video["label"] in visible_label_set
    ]
    context = {
        "query": query,
        "question_interpretation": question_interpretation,
        "boundary": boundary,
        "answer_guidance": plan["answer_guidance"],
        "feedback_guidance": primary_payload["feedback_guidance"],
        "topic_navigation": navigation,
        **diagnostic_contract,
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
                "只引用 answer_visible_video_labels 对应的视频；selected_videos 中未映射到 claim 的检索 finalist 仅供审计，不得出现在回答中。",
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
                "每个重要结论只能使用 claim_evidence_map 为该结论列出的 V 标签，并服从其 confidence_ceiling；answer_visible_video_labels 是回答全局引用白名单。",
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
    }
    context["clarification_state"] = build_clarification_state(
        context, continuation
    )
    context["answer_turn_contract"] = build_answer_turn_contract(context)
    context["answer_plan"] = build_closed_answer_plan(
        context, load_reviewed_evidence_atoms()
    )
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
