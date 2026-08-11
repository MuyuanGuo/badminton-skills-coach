#!/usr/bin/env python3
"""Diagnostic hypotheses, mechanisms, evidence maps, and confidence contracts."""

import re

def extract_user_hypotheses(query, diagnostic_rules):
    """Return causes proposed by the user without treating them as facts."""
    hypotheses = []
    seen = set()
    for rule in diagnostic_rules.get("hypothesis_patterns", []):
        for match in re.finditer(rule["pattern"], query):
            if rule["type"] == "single_cause_question":
                group_names = ["hypothesis"]
            elif rule["type"] in {
                "alternative_cause_question",
                "alternative_cause_statement",
                "possible_alternative_statement",
            }:
                group_names = ["left", "right"]
            elif rule["type"] == "enumerated_cause_request":
                group_names = ["hypothesis_list"]
            else:
                continue
            for group_name in group_names:
                raw_text = match.group(group_name).strip(" ，,。？?！!")
                parts = re.split(
                    r"[、，,]|(?:以及|或者|和|与|或)",
                    raw_text,
                )
                for text in parts:
                    text = re.sub(
                        r"(?:造成|导致|引起|带来)?的?(?:问题|原因)?$",
                        "",
                        text,
                    ).strip()
                    text = re.sub(
                        r"^(?:是|也?可能是?|或许是?)",
                        "",
                        text,
                    ).strip()
                    normalized_text = re.sub(r"\s+", "", text)
                    invalid = any(
                        re.fullmatch(pattern, normalized_text)
                        for pattern in diagnostic_rules.get(
                            "invalid_hypothesis_patterns", []
                        )
                    )
                    if not text or invalid or text in seen:
                        continue
                    seen.add(text)
                    hypotheses.append(
                        {
                            "id": f"H{len(hypotheses) + 1}",
                            "text": text,
                            "framing": rule["type"],
                        }
                    )
    return hypotheses


def diagnostic_mechanism_for_text(search_module, text, diagnostic_rules):
    normalized = search_module.normalize(text)
    matches = []
    for mechanism in diagnostic_rules.get("mechanisms", []):
        matched_terms = [
            term
            for term in mechanism.get("query_terms", [])
            if search_module.normalize(term) in normalized
        ]
        if matched_terms:
            matches.append((max(map(len, matched_terms)), mechanism))
    return max(matches, key=lambda item: item[0])[1] if matches else None


def diagnostic_observed_symptoms(
    search_module, query, intent_frame, hypotheses, diagnostic_rules
):
    remaining_query = query
    for hypothesis in hypotheses:
        remaining_query = remaining_query.replace(hypothesis["text"], " ")
    normalized_remaining = search_module.normalize(remaining_query)

    def occurs_without_negation(term):
        normalized_term = search_module.normalize(term)
        start = 0
        while True:
            index = normalized_remaining.find(normalized_term, start)
            if index < 0:
                return False
            prefix = normalized_remaining[max(0, index - 4) : index]
            if not any(
                prefix.endswith(marker)
                for marker in ("不", "没", "没有", "并不", "不会", "从不")
            ):
                return True
            start = index + len(normalized_term)
    configured = diagnostic_rules.get("symptom_terms", [])
    terms = [
        term
        for term in configured
        if occurs_without_negation(term)
    ]
    terms.extend(
        term
        for term in intent_frame.get("literal_symptoms", [])
        if occurs_without_negation(term)
    )
    unique_terms = list(dict.fromkeys(terms))
    terms = [
        term
        for term in unique_terms
        if not any(
            search_module.normalize(term) != search_module.normalize(other)
            and search_module.normalize(term) in search_module.normalize(other)
            for other in unique_terms
        )
    ]
    return [
        {
            "id": f"S{index}",
            "text": term,
            "source": "user_report",
            "verification_status": "reported_not_observed",
        }
        for index, term in enumerate(terms, start=1)
    ]


def selected_video_evidence_text(search_module, video):
    evidence_text = [
        item.get("text", "")
        for item in (video.get("teaching_note") or {}).get("evidence", [])
    ]
    evidence_text.extend(
        item.get("text", "") for item in video.get("transcript_evidence", [])
    )
    evidence_text.extend(
        item.get("text", "")
        for item in video.get("bounded_note_evidence", [])
    )
    return search_module.normalize(" ".join(evidence_text))


def claim_scope_directness(video, diagnostic_rules):
    strong_axes = set(diagnostic_rules.get("strong_scope_axes", []))
    matches = {
        axis: value
        for axis, value in video.get("constraint_match", {}).items()
        if axis in strong_axes
    }
    if not matches:
        return "generic"
    exact_count = sum(value == "exact" for value in matches.values())
    weak = set(diagnostic_rules.get("weak_constraint_matches", []))
    if not exact_count and all(value in weak for value in matches.values()):
        # Explicit conflicts have already failed semantic selection. Weak or
        # incidental scope is therefore generic/component evidence, not an
        # incompatibility; its claim_scope_policy still forces conditioning.
        return "generic"
    if all(value == "exact" for value in matches.values()):
        return "exact"
    return "partial"


def has_requested_action_scope_support(video, query_constraints, diagnostic_rules):
    requested_axes = [
        axis
        for axis in diagnostic_rules.get("claim_action_scope_axes", [])
        if query_constraints.get(axis)
    ]
    if not requested_axes:
        return True
    supported_matches = set(
        diagnostic_rules.get(
            "claim_action_scope_support_matches", ["exact", "partial_support"]
        )
    )
    core_action_axes = {
        "shot_family",
        "technique_variant",
        "stroke_intent",
        "serve_role",
        "serve_trajectory",
    }
    core_requested_axes = [
        axis for axis in requested_axes if axis in core_action_axes
    ]
    axes_to_check = core_requested_axes or requested_axes
    return any(
        video.get("constraint_match", {}).get(axis) in supported_matches
        or (
            axis == "stroke_intent"
            and video.get("constraint_match", {}).get(axis)
            == "incidental_support"
            and video.get("concept_match")
            in {"exact_question", "exact_query_unit"}
            and video.get("focus_match")
            in {"primary", "structured", "not_required"}
        )
        for axis in axes_to_check
    )


def claim_evidence_entry(video, directness, reason):
    return {
        "label": video["label"],
        "evidence_id": video["evidence_id"],
        "directness": directness,
        "scope": video["claim_scope_policy"],
        "reason": reason,
        "answer_eligibility": video.get(
            "answer_eligibility", "primary"
        ),
        "evidence_roles": video.get("evidence_roles", ["context"]),
    }


def requested_scope_window_groups(actor_context, selection_rules):
    requested = set((actor_context or {}).get("requested_action_scopes", []))
    return [
        {
            "name": scope["name"],
            "terms": scope.get("source_terms", []),
            "suppressions": scope.get("source_suppressions", []),
            "overrides": scope.get("source_override_terms", []),
        }
        for scope in (selection_rules or {}).get("target_action_scopes", [])
        if scope.get("name") in requested
    ]


def requested_action_window_groups(actor_context, selection_rules):
    """Bind a named stroke to the evidence window that teaches it."""

    actor_context = actor_context or {}
    constraints = actor_context.get("target_action_constraints") or actor_context.get(
        "target_constraints", {}
    )
    axes = {
        axis.get("name"): axis
        for axis in (selection_rules or {}).get("constraint_axes", [])
    }
    axis_names = (
        ["technique_variant"]
        if constraints.get("technique_variant")
        else ["shot_family"]
    )
    if any(len(constraints.get(axis_name, [])) != 1 for axis_name in axis_names):
        return []
    groups = []
    for axis_name in axis_names:
        axis = axes.get(axis_name, {})
        for value in constraints.get(axis_name, []):
            terms = axis.get("values", {}).get(value, [])
            if terms:
                groups.append(
                    {
                        "name": f"named_action:{axis_name}:{value}",
                        "terms": list(dict.fromkeys(terms)),
                        "suppressions": [],
                        "overrides": [],
                    }
                )
    return groups


def effective_scope_window_groups(video, requested_scope_groups):
    """Apply named-action windows only to genuinely multi-action sources."""

    effective = []
    constraint_scope = video.get("constraint_scope", {})
    for group in requested_scope_groups:
        name = str(group.get("name", ""))
        if not name.startswith("named_action:"):
            effective.append(group)
            continue
        parts = name.split(":", 2)
        axis_name = parts[1] if len(parts) >= 3 else ""
        requested_value = parts[2] if len(parts) >= 3 else ""
        values = constraint_scope.get(axis_name, {}).get("values", [])
        compatible_parent_values = {
            "fake_lift_real_net": {"net_drop"},
            "far_net_umbrella": {
                "far_net_flat_slice",
                "far_net_middle_split",
                "far_net_defense_to_push",
                "far_net_drop",
            },
            "far_net_flat_slice": {"far_net_umbrella"},
            "far_net_middle_split": {"far_net_umbrella"},
            "far_net_defense_to_push": {"far_net_umbrella"},
            "far_net_drop": {"far_net_umbrella"},
        }.get(requested_value, set())
        competing_values = set(values) - {
            requested_value,
            *compatible_parent_values,
        }
        if competing_values:
            effective.append(group)
    return effective


def requested_focus_window_groups(search_module, unit, selection_rules):
    normalized_unit = search_module.normalize(unit)
    return [
        group
        for group in (selection_rules or {}).get(
            "required_focus_equivalent_groups", []
        )
        if any(
            search_module.normalize(term) in normalized_unit
            for term in group
        )
    ]


def incoming_focus_window_groups(actor_context, selection_rules):
    """Require the incoming shot when no player action family was resolved."""

    actor_context = actor_context or {}
    target_constraints = actor_context.get("target_constraints", {})
    if any(
        target_constraints.get(axis)
        for axis in ("shot_family", "technique_variant", "stroke_intent")
    ):
        return []
    incoming = actor_context.get("incoming_shot_constraints", {})
    preferred_axes = (
        ["technique_variant"]
        if incoming.get("technique_variant")
        else ["shot_family"]
    )
    groups = []
    axes_by_name = {
        axis["name"]: axis
        for axis in (selection_rules or {}).get("constraint_axes", [])
    }
    for axis_name in preferred_axes:
        axis = axes_by_name.get(axis_name, {})
        for value in incoming.get(axis_name, []):
            terms = [
                *axis.get("values", {}).get(value, []),
                *axis.get("opponent_query_value_additions", {}).get(value, []),
            ]
            if terms:
                groups.append(list(dict.fromkeys(terms)))
    return groups


def comparison_axis_window_groups(search_module, text, diagnostic_rules):
    """Require direct evidence on every side of an explicit comparison axis."""

    normalized = search_module.normalize(text)
    if not any(
        search_module.normalize(signal) in normalized
        for signal in diagnostic_rules.get("comparison_signals", [])
    ):
        return []
    required = []
    for axis in diagnostic_rules.get("comparison_axis_groups", []):
        matched_values = [
            value_terms
            for value_terms in axis.get("values", [])
            if any(
                search_module.normalize(term) in normalized
                for term in value_terms
            )
        ]
        if len(matched_values) >= 2:
            required.extend(matched_values)
    return required


def window_matches_groups(
    search_module,
    normalized_text,
    requested_scope_groups=(),
    requested_focus_groups=(),
):
    for group in requested_scope_groups:
        has_term = any(
            search_module.normalize(term) in normalized_text
            for term in group.get("terms", [])
        )
        suppressed = any(
            search_module.normalize(term) in normalized_text
            for term in group.get("suppressions", [])
        )
        overridden = any(
            search_module.normalize(term) in normalized_text
            for term in group.get("overrides", [])
        )
        if not has_term or (suppressed and not overridden):
            return False
    normalized_without_particles = normalized_text.replace("的", "")
    return all(
        any(
            search_module.normalize(term).replace("的", "")
            in normalized_without_particles
            for term in group
        )
        for group in requested_focus_groups
    )


def timestamp_bounds(value):
    match = re.fullmatch(r"(\d+):(\d{2})-(\d+):(\d{2})", str(value or ""))
    if not match:
        return None
    start = int(match.group(1)) * 60 + int(match.group(2))
    end = int(match.group(3)) * 60 + int(match.group(4))
    return start, end


def windows_are_near(left, right, maximum_gap_seconds):
    left_bounds = timestamp_bounds(left.get("timestamp"))
    right_bounds = timestamp_bounds(right.get("timestamp"))
    if not left_bounds or not right_bounds:
        return left is right
    gap = max(
        0,
        right_bounds[0] - left_bounds[1],
        left_bounds[0] - right_bounds[1],
    )
    return gap <= maximum_gap_seconds


def query_window_support(
    search_module,
    video,
    requested_scope_groups=(),
    requested_focus_groups=(),
    required_claim_terms=(),
    required_claim_term_groups=(),
):
    """Return claim-level support from query-ranked source windows."""

    best = {
        "rank": 0,
        "score": 0.0,
        "matched_term_count": 0,
        "query_ngram_coverage": 0.0,
        "exact_query_match": False,
    }
    source_windows = [
        *video.get("transcript_evidence", []),
        *video.get("bounded_note_evidence", []),
        *video.get("teaching_note", {}).get("evidence", []),
    ]
    eligible_windows = []
    for window in source_windows:
        normalized_text = search_module.normalize(window.get("text", ""))
        if required_claim_terms and not any(
            search_module.normalize(term) in normalized_text
            for term in required_claim_terms
        ):
            continue
        if required_claim_term_groups and not all(
            any(
                search_module.normalize(term) in normalized_text
                for term in group
            )
            for group in required_claim_term_groups
        ):
            continue
        if not window_matches_groups(
            search_module,
            normalized_text,
            requested_scope_groups,
            requested_focus_groups,
        ):
            continue
        if window.get("text"):
            eligible_windows.append(window)
        matched_count = len(window.get("matched_terms") or [])
        coverage = float(window.get("query_ngram_coverage") or 0)
        exact = bool(window.get("exact_query_match"))
        rank = (
            4
            if exact
            else 3
            if coverage >= 0.25 or (matched_count >= 3 and coverage >= 0.1)
            else 2
            if matched_count >= 2
            else 1
            if matched_count >= 1 and coverage >= 0.15
            else 0
        )
        if rank < 2 and any(
            str(group.get("name", "")).startswith("named_action:")
            for group in requested_scope_groups
        ):
            # The window has already passed the named-action lexical gate.
            # Reviewed/bounded windows do not always carry runtime query-match
            # metadata, so the explicit action occurrence itself is enough
            # for scoped claim authorization.
            rank = 2
        candidate = {
            "rank": rank,
            "score": float(window.get("score") or 0),
            "matched_term_count": matched_count,
            "query_ngram_coverage": coverage,
            "exact_query_match": exact,
            "claim_window": (
                {
                    "timestamp": window.get("timestamp", "visual_review_no_timestamp"),
                    "text": window.get("text", ""),
                }
                if window.get("text")
                else None
            ),
        }
        if (
            candidate["rank"],
            candidate["score"],
            candidate["query_ngram_coverage"],
        ) > (
            best["rank"],
            best["score"],
            best["query_ngram_coverage"],
        ):
            best = candidate
    if (
        best["rank"] < 2
        and video.get("runtime_evidence_mode") == "bounded_note_windows"
    ):
        # Bounded-note sources fail closed: an unmatched note cannot borrow
        # support from a low-trust title.
        return best
    if (
        best["rank"] < 2
        and (
            video.get("reviewed_evidence_rank", 2) <= 1
            or video.get("confidence") == "reviewed_transcript"
        )
        and eligible_windows
    ):
        best = {
            **best,
            "rank": 2,
            "reviewed_evidence_fallback": True,
            "claim_window": {
                "timestamp": eligible_windows[0].get(
                    "timestamp", "visual_review_no_timestamp"
                ),
                "text": eligible_windows[0].get("text", ""),
            },
        }
    if (
        best["rank"] < 2
        and video.get("source_type") != "bilibili_video"
        and video.get("teaching_note", {}).get("evidence")
        and eligible_windows
        and (
            video.get("concept_match") != "none"
            or video.get("focus_match") == "primary"
        )
    ):
        best = {
            **best,
            "rank": 2,
            "legacy_source_fallback": True,
            "claim_window": {
                "timestamp": eligible_windows[0].get(
                    "timestamp", "visual_review_no_timestamp"
                ),
                "text": eligible_windows[0].get("text", ""),
            },
        }
    return best


def confidence_ceiling(evidence_entries, selected_by_label):
    if not evidence_entries:
        return "none"
    if any(item["directness"] == "direct" for item in evidence_entries):
        direct_confidences = {
            selected_by_label[item["label"]].get("confidence")
            for item in evidence_entries
            if item["directness"] == "direct"
        }
        if direct_confidences & {"curated", "reviewed_transcript"}:
            return "high"
        return "moderate"
    if any(item["directness"] == "scoped" for item in evidence_entries):
        return "moderate"
    return "low"


def query_unit_evidence(
    search_module,
    video,
    strategy,
    query_constraints,
    diagnostic_rules,
    requested_scope_groups=(),
    requested_focus_groups=(),
    required_claim_terms=(),
    required_claim_term_groups=(),
):
    del strategy
    requested_scope_groups = effective_scope_window_groups(
        video, requested_scope_groups
    )
    scope_directness = claim_scope_directness(video, diagnostic_rules)
    if scope_directness == "incompatible":
        return None
    concept = video.get("concept_match")
    symptom = video.get("symptom_match")
    if (
        concept == "none"
        and symptom in {"none", "not_required"}
        and not (
            requested_scope_groups
            and video.get("focus_match") in {"primary", "structured"}
        )
    ):
        return None
    action_scope_supported = has_requested_action_scope_support(
        video, query_constraints, diagnostic_rules
    )
    window_support = query_window_support(
        search_module,
        video,
        requested_scope_groups,
        requested_focus_groups,
        required_claim_terms,
        required_claim_term_groups,
    )
    if (
        window_support["rank"] < 2
        and requested_focus_groups
        and concept in {"exact_question", "exact_query_unit"}
        and action_scope_supported
    ):
        # A claim window can express the requested action without repeating
        # the generic focus noun used in the question.  For example, a
        # forecourt pressure passage may say 压球 throughout without repeating
        # 封网.  Exact concept + structured action scope is sufficient to
        # retry the same source windows without that lexical-only focus gate.
        window_support = query_window_support(
            search_module,
            video,
            requested_scope_groups,
            (),
            required_claim_terms,
            required_claim_term_groups,
        )
    if window_support["rank"] < 2:
        return None
    component_only_support = bool(
        video.get("symptom_match") == "not_required"
        and (
            video.get("concept_match")
            in {
                "component_support",
                "constraint_scoped_support",
                "reviewed_support",
                "expanded_support",
            }
            or (
                concept in {"exact_question", "exact_query_unit"}
                and (
                    video.get("focus_match") in {"primary", "structured"}
                    or window_support["rank"] >= 3
                )
            )
        )
    )
    core_action_request = any(
        query_constraints.get(axis)
        for axis in (
            "shot_family",
            "technique_variant",
            "stroke_intent",
            "serve_role",
            "serve_trajectory",
        )
    )
    if core_action_request and not action_scope_supported:
        return None
    if not action_scope_supported and not component_only_support:
        # A symptom word or generic mechanism is not enough to support the
        # whole question when it does not cover any requested action axis.
        # It may still support a separately mapped hypothesis or mechanism.
        return None
    if (
        scope_directness == "exact"
        and concept in {"exact_question", "exact_query_unit"}
        and video.get("claim_scope_policy")
        in {"exact_question_scope", "exact_query_unit_scope_only"}
    ):
        directness = "direct"
    elif (
        concept in {"exact_question", "exact_query_unit"}
        or video.get("inferred_target_action_match")
    ):
        directness = "scoped"
    else:
        directness = "component"
    if video.get("inferred_target_action_match") and directness != "direct":
        # Matching the canonical name of an inferred multi-actor decision is
        # not enough to answer the user's concrete responsibility chain.  A
        # scoped source remains component evidence unless a reviewed atom
        # later binds the actual actors, response and coverage conditions.
        directness = "component"
    reason = (
        "directly covers the requested question scope"
        if directness == "direct"
        else (
            "covers the question under stated source conditions"
            if directness == "scoped"
            else "supports only a component or mechanism of the question"
        )
    )
    evidence = claim_evidence_entry(video, directness, reason)
    claim_window = window_support.pop("claim_window", None)
    if claim_window:
        evidence["claim_windows"] = [claim_window]
    evidence["window_support"] = {
        **window_support,
        "reviewed_evidence_source": (
            video.get("reviewed_evidence_rank", 2) <= 1
        ),
        "primary_query_score": float(video.get("primary_query_score") or 0),
        "best_retrieval_rank": video.get("best_retrieval_rank"),
    }
    return evidence


def scoped_video_for_query_unit(video, unit):
    """Use the constraint match calculated for this unit, if available."""

    unit_matches = video.get("query_unit_constraint_matches", {})
    if unit not in unit_matches:
        return video
    scoped = dict(video)
    scoped["constraint_match"] = unit_matches[unit]
    return scoped


def mechanism_evidence(
    search_module,
    mechanism,
    selected_videos,
    query_constraints,
    diagnostic_rules,
    claim_text=None,
    requested_scope_groups=(),
    requested_focus_groups=(),
):
    matched = []
    for video in selected_videos:
        video_scope_groups = effective_scope_window_groups(
            video, requested_scope_groups
        )
        action_scope_supported = has_requested_action_scope_support(
            video, query_constraints, diagnostic_rules
        )
        core_action_request = any(
            query_constraints.get(axis)
            for axis in (
                "shot_family",
                "technique_variant",
                "stroke_intent",
                "serve_role",
                "serve_trajectory",
            )
        )
        if (
            core_action_request
            and not action_scope_supported
            and not mechanism.get("allow_cross_action_component", False)
        ):
            continue
        if (
            not action_scope_supported
            and not video_scope_groups
            and not (
                (
                    video.get("concept_match")
                    in {"exact_question", "exact_query_unit"}
                    or (
                        video.get("concept_match") == "component_support"
                        and video.get("symptom_match")
                        in {"direct_primary", "direct_structured"}
                    )
                )
                and video.get("focus_match") in {"primary", "structured"}
            )
            and not (
                mechanism.get("allow_cross_action_component", False)
                and video.get("focus_match") in {"primary", "structured"}
            )
        ):
            continue
        configured_terms = mechanism.get("evidence_terms", [])
        if claim_text:
            normalized_claim = search_module.normalize(claim_text)
            matching_groups = [
                group
                for group in mechanism.get(
                    "hypothesis_evidence_term_groups", []
                )
                if any(
                    search_module.normalize(term) in normalized_claim
                    for term in group.get("query_terms", [])
                )
            ]
            if matching_groups:
                configured_terms = list(
                    dict.fromkeys(
                        term
                        for group in matching_groups
                        for term in group.get("evidence_terms", [])
                    )
                )
        source_windows = [
            *video.get("transcript_evidence", []),
            *video.get("bounded_note_evidence", []),
            *video.get("teaching_note", {}).get("evidence", []),
        ]
        matched_windows = []
        for source_index, window in enumerate(source_windows):
            normalized_text = search_module.normalize(window.get("text", ""))
            if claim_text and any(
                re.search(pattern, window.get("text", ""))
                for pattern in diagnostic_rules.get(
                    "hypothesis_evidence_negation_patterns", []
                )
            ):
                # The current model records support and uncertainty, not a
                # polarity-aware contradiction claim.  A passage saying that
                # the proposed factor is *not* the cause must therefore not
                # be counted as support for that hypothesis.
                continue
            if not window_matches_groups(
                search_module,
                normalized_text,
                (),
                requested_focus_groups,
            ):
                continue
            if video_scope_groups and not any(
                windows_are_near(
                    window,
                    scope_window,
                    diagnostic_rules.get(
                        "mechanism_scope_window_max_gap_seconds", 20
                    ),
                )
                and window_matches_groups(
                    search_module,
                    search_module.normalize(scope_window.get("text", "")),
                    video_scope_groups,
                    (),
                )
                for scope_window in source_windows
            ):
                continue
            terms = [
                term
                for term in configured_terms
                if search_module.normalize(term) in normalized_text
            ]
            if terms and window.get("timestamp") and window.get("text"):
                matched_windows.append(
                    (
                        -max(len(search_module.normalize(term)) for term in terms),
                        min(configured_terms.index(term) for term in terms),
                        source_index,
                        window,
                        terms,
                    )
                )
        matched_windows.sort(key=lambda item: item[:3])
        terms = matched_windows[0][4] if matched_windows else []
        if not terms:
            continue
        scope_directness = claim_scope_directness(video, diagnostic_rules)
        if scope_directness == "incompatible":
            continue
        directness = "direct" if scope_directness == "exact" else "scoped"
        if video.get("concept_match") in {
            "component_support",
            "constraint_scoped_support",
            "reviewed_support",
            "expanded_support",
        }:
            directness = "component" if directness == "scoped" else "scoped"
        evidence = claim_evidence_entry(
            video,
            directness,
            f'direct evidence text matches {mechanism["label"]}: {terms[0]}',
        )
        evidence["claim_windows"] = [
            {
                "timestamp": matched_windows[0][3]["timestamp"],
                "text": matched_windows[0][3]["text"],
            }
        ]
        evidence["mechanism_match_specificity"] = max(
            len(search_module.normalize(term)) for term in terms
        )
        matched.append(evidence)
    rank = {"direct": 0, "scoped": 1, "component": 2}
    matched.sort(
        key=lambda item: (
            rank[item["directness"]],
            -item.get("mechanism_match_specificity", 0),
            item["label"],
        )
    )
    return matched[
        : diagnostic_rules.get("max_related_evidence_per_claim", 8)
    ]


def material_diagnostic_branches(
    query,
    query_constraints,
    selected_videos,
    diagnostic_rules,
    eligible_labels=None,
):
    requested_variants = query_constraints.get("technique_variant", [])
    required_axes = {
        axis
        for variant in requested_variants
        for axis in diagnostic_rules.get("required_context_by_technique", {}).get(
            variant, []
        )
    }
    branch_axes = diagnostic_rules.get("material_branch_axes", {})
    branches = []
    for axis_name, axis_rule in branch_axes.items():
        if axis_name in query_constraints:
            continue
        if axis_name not in required_axes and not any(
            term.replace(" ", "").lower() in query.replace(" ", "").lower()
            for term in axis_rule.get("trigger_terms", [])
        ):
            continue
        labels_by_value = {}
        for video in selected_videos:
            if eligible_labels is not None and video["label"] not in eligible_labels:
                continue
            if claim_scope_directness(video, diagnostic_rules) == "incompatible":
                continue
            values = video.get("constraint_scope", {}).get(axis_name, {}).get(
                "values", []
            )
            for value in values:
                if value in axis_rule.get("values", {}):
                    labels_by_value.setdefault(value, []).append(video["label"])
        if axis_name not in required_axes and len(labels_by_value) < 2:
            continue
        branch_values = []
        for value, label in axis_rule.get("values", {}).items():
            branch_values.append(
                {
                    "value": value,
                    "label": label,
                    "eligible_video_labels": labels_by_value.get(value, []),
                }
            )
        branches.append(
            {
                "id": f"B{len(branches) + 1}",
                "axis": axis_name,
                "label": axis_rule["label"],
                "query_label": axis_rule.get("query_label", axis_rule["label"]),
                "status": "conditional",
                "question": axis_rule["question"],
                "branches": branch_values,
            }
        )
    return branches


def build_diagnostic_contract(
    search_module,
    query,
    plan,
    question_interpretation,
    boundary,
    selected_videos,
    diagnostic_rules,
    selection_rules=None,
    resolved_question_ids=None,
    resolved_answers=None,
):
    resolved_question_ids = set(resolved_question_ids or [])
    resolved_answers = list(resolved_answers or [])
    resolved_mechanism_ids = {
        focus["id"]
        for item in resolved_answers
        for focus in [item.get("evidence_focus") or {}]
        if focus.get("kind") == "mechanism" and focus.get("id")
    }
    known_observation_records = [
        item
        for item in question_interpretation.get("query_unit_records", [])
        if item.get("role") == "user_observation"
    ]
    normalized_known_observations = search_module.normalize(
        " ".join(item.get("source_unit", "") for item in known_observation_records)
    )
    non_resolving_cues = {
        search_module.normalize(cue)
        for cue in diagnostic_rules.get("non_resolving_answer_cues", [])
    }

    def explicit_answers_cover_cues(answer_cues):
        normalized_cues = [
            search_module.normalize(cue)
            for cue in answer_cues
            if search_module.normalize(cue)
        ]
        if not normalized_cues:
            return False
        return any(
            cue in search_module.normalize(item.get("answer", ""))
            for item in resolved_answers
            for cue in normalized_cues
        )

    def known_observations_cover_cues(answer_cues):
        normalized_cues = [
            search_module.normalize(cue)
            for cue in answer_cues
            if search_module.normalize(cue)
        ]
        return any(
            cue not in non_resolving_cues
            and cue in normalized_known_observations
            for cue in normalized_cues
        )

    def resolved_answers_cover_cues(answer_cues):
        return explicit_answers_cover_cues(
            answer_cues
        ) or known_observations_cover_cues(answer_cues)
    intent_frame = question_interpretation["intent_frame"]
    user_hypotheses = extract_user_hypotheses(query, diagnostic_rules)
    observed_symptoms = diagnostic_observed_symptoms(
        search_module,
        query,
        intent_frame,
        user_hypotheses,
        diagnostic_rules,
    )
    selected_by_label = {video["label"]: video for video in selected_videos}
    claim_map = []
    query_units = (
        question_interpretation.get("query_units", [query])
        if "query_units" in question_interpretation
        else [query]
    )
    query_unit_constraints = question_interpretation.get(
        "query_unit_constraints", {}
    )
    for unit in query_units:
        alternative_hypotheses = [
            item
            for item in user_hypotheses
            if item.get("framing") == "alternative_cause_question"
            and search_module.normalize(item["text"])
            in search_module.normalize(unit)
        ]
        if len(alternative_hypotheses) >= 2 and "还是" in unit:
            # H1/H2 claims and the typed comparison delivery item already
            # preserve this question.  A duplicate Q claim would incorrectly
            # let evidence for only one alternative mark the comparison as
            # fully supported.
            continue
        unit_constraints = (
            query_unit_constraints.get(unit)
            or question_interpretation["constraints"]
        )
        unit_actor_context = question_interpretation.get(
            "query_unit_actor_contexts", {}
        ).get(unit, question_interpretation.get("actor_context", {}))
        scope_window_groups = [
            *requested_scope_window_groups(
                unit_actor_context, selection_rules
            ),
            *requested_action_window_groups(
                unit_actor_context, selection_rules
            ),
        ]
        focus_window_groups = requested_focus_window_groups(
            search_module, unit, selection_rules
        )
        if scope_window_groups:
            focus_window_groups = []
        diagnostic_anchor_required = (
            (
                intent_frame.get("requested_output")
                in {"diagnosis", "comparison"}
                or any(
                    search_module.normalize(term)
                    in search_module.normalize(query)
                    for term in diagnostic_rules.get(
                        "diagnostic_request_terms", []
                    )
                )
            )
            and not unit_actor_context.get("inferred_target_action")
            and not unit_actor_context.get("requested_action_scopes")
        )
        unit_symptom_terms = [
            item["text"]
            for item in observed_symptoms
            if boundary.get("type") == "none"
            if diagnostic_anchor_required
            if search_module.normalize(item["text"])
            in search_module.normalize(unit)
        ]
        comparison_window_groups = comparison_axis_window_groups(
            search_module,
            query if any(signal in unit for signal in ("一样", "相同", "不同")) else unit,
            diagnostic_rules,
        )
        evidence_entries = [
            evidence
            for video in selected_videos
            if (
                evidence := query_unit_evidence(
                    search_module,
                    scoped_video_for_query_unit(video, unit),
                    question_interpretation["strategy"],
                    unit_constraints,
                    diagnostic_rules,
                    scope_window_groups,
                    focus_window_groups,
                    unit_symptom_terms,
                    comparison_window_groups,
                )
            )
            and (
                any(
                    search_module.normalize(unit)
                    == search_module.normalize(matched_unit)
                    for matched_unit in video.get("matched_query_units", [])
                )
                or (
                    unit_actor_context.get("inferred_target_action")
                    and unit
                    == unit_actor_context.get("target_action_query")
                )
            )
        ]
        if boundary.get("type") == "cross_variant_evidence_transfer":
            evidence_entries = []
        if (
            intent_frame.get("requested_output") == "practice"
            and re.search(
                r"(?:\\d+\\s*分钟|连续.{0,4}(?:天|周)|组数|次数|频率|进阶标准)",
                unit,
            )
        ):
            evidence_entries = []
        directness_rank = {"direct": 0, "scoped": 1, "component": 2}
        evidence_entries.sort(
            key=lambda item: (
                -int(
                    bool(
                        item["window_support"].get("reviewed_evidence_source")
                    )
                ),
                -item["window_support"]["rank"],
                directness_rank[item["directness"]],
                -item["window_support"]["primary_query_score"],
                item["window_support"].get("best_retrieval_rank") or 10**6,
                -item["window_support"]["score"],
                item["label"],
            )
        )
        evidence_entries = evidence_entries[
            : diagnostic_rules.get("max_related_evidence_per_claim", 8)
        ]
        if unit_actor_context.get("explicit_subquestion"):
            # The actor is correctly isolated, but root scenario constraints
            # were intentionally not inherited.  Until a source explicitly
            # binds this named subquestion, keep retrieved material as a
            # component and let the closed answer plan state the gap.
            for item in evidence_entries:
                item["directness"] = "component"
                item["reason"] = (
                    "supports only the isolated actor/action component; "
                    "the root scenario is not directly bound"
                )
        claim_map.append(
            {
                "claim_id": f"Q{len(claim_map) + 1}",
                "kind": "question_unit",
                "text": unit,
                "status": (
                    "supported"
                    if any(
                        item["directness"] == "direct"
                        for item in evidence_entries
                    )
                    else "conditional"
                    if evidence_entries
                    else "unsupported"
                ),
                "evidence": evidence_entries,
                "eligible_video_labels": [
                    item["label"] for item in evidence_entries
                ],
                "confidence_ceiling": confidence_ceiling(
                    evidence_entries, selected_by_label
                ),
            }
        )

    mechanism_by_id = {
        item["id"]: item for item in diagnostic_rules.get("mechanisms", [])
    }
    hypothesis_mechanism_ids = set()
    for hypothesis in user_hypotheses:
        mechanism = diagnostic_mechanism_for_text(
            search_module, hypothesis["text"], diagnostic_rules
        )
        hypothesis_unit = next(
            (
                unit
                for unit in query_units
                if search_module.normalize(hypothesis["text"])
                in search_module.normalize(unit)
            ),
            None,
        )
        hypothesis_constraints = (
            query_unit_constraints.get(hypothesis_unit)
            or question_interpretation["constraints"]
        )
        hypothesis_videos = [
            scoped_video_for_query_unit(video, hypothesis_unit)
            if hypothesis_unit
            else video
            for video in selected_videos
        ]
        evidence_entries = (
            mechanism_evidence(
                search_module,
                mechanism,
                hypothesis_videos,
                hypothesis_constraints,
                diagnostic_rules,
                claim_text=hypothesis["text"],
                requested_scope_groups=[
                    *requested_scope_window_groups(
                        question_interpretation.get(
                            "query_unit_actor_contexts", {}
                        ).get(
                            hypothesis_unit,
                            question_interpretation.get("actor_context", {}),
                        ),
                        selection_rules,
                    ),
                    *requested_action_window_groups(
                        question_interpretation.get(
                            "query_unit_actor_contexts", {}
                        ).get(
                            hypothesis_unit,
                            question_interpretation.get("actor_context", {}),
                        ),
                        selection_rules,
                    ),
                ],
                requested_focus_groups=[
                    *requested_focus_window_groups(
                        search_module,
                        hypothesis["text"],
                        selection_rules,
                    ),
                    *incoming_focus_window_groups(
                        question_interpretation.get(
                            "query_unit_actor_contexts", {}
                        ).get(
                            hypothesis_unit,
                            question_interpretation.get("actor_context", {}),
                        ),
                        selection_rules,
                    ),
                ],
            )
            if mechanism
            else []
        )
        if mechanism:
            hypothesis_mechanism_ids.add(mechanism["id"])
        hypothesis.update(
            {
                "mechanism_id": mechanism["id"] if mechanism else None,
                "status": "conditional" if evidence_entries else "unverified",
                "eligible_video_labels": [
                    item["label"] for item in evidence_entries
                ],
                "reason": (
                    "source evidence supports this as a possible mechanism, but the user's own movement has not been observed"
                    if evidence_entries
                    else "no selected source directly verifies this proposed cause"
                ),
            }
        )
        claim_map.append(
            {
                "claim_id": hypothesis["id"],
                "kind": "user_hypothesis",
                "text": hypothesis["text"],
                "status": hypothesis["status"],
                "evidence": evidence_entries,
                "eligible_video_labels": hypothesis["eligible_video_labels"],
                "confidence_ceiling": confidence_ceiling(
                    evidence_entries, selected_by_label
                ),
            }
        )

    actor_context = question_interpretation.get("actor_context", {})
    mechanism_query = (
        actor_context.get("target_action_query", query)
        if actor_context.get("inferred_target_action")
        else query
    )
    # Terms that describe a partner's prior shot or an opponent's response are
    # conditions of a multi-actor decision, not evidence that the user is
    # asking for a diagnosis of those actions.
    normalized_query = search_module.normalize(mechanism_query)
    supported_mechanisms = []
    for mechanism in diagnostic_rules.get("mechanisms", []):
        if mechanism["id"] in hypothesis_mechanism_ids:
            continue
        if (
            mechanism["id"] not in resolved_mechanism_ids
            and not any(
                search_module.normalize(term) in normalized_query
                for term in mechanism.get("query_terms", [])
            )
        ):
            continue
        mechanism_unit = next(
            (
                unit
                for unit in query_units
                if any(
                    search_module.normalize(term)
                    in search_module.normalize(unit)
                    for term in mechanism.get("query_terms", [])
                )
            ),
            None,
        )
        mechanism_constraints = (
            query_unit_constraints.get(mechanism_unit)
            or question_interpretation["constraints"]
        )
        mechanism_videos = [
            scoped_video_for_query_unit(video, mechanism_unit)
            if mechanism_unit
            else video
            for video in selected_videos
        ]
        evidence_entries = mechanism_evidence(
            search_module,
            mechanism,
            mechanism_videos,
            mechanism_constraints,
            diagnostic_rules,
            requested_scope_groups=[
                *requested_scope_window_groups(
                    actor_context, selection_rules
                ),
                *requested_action_window_groups(
                    actor_context, selection_rules
                ),
            ],
            # Mechanism evidence already has a dedicated, maintainer-curated
            # evidence-term list.  Re-deriving generic focus groups from the
            # mechanism label (for example requiring the literal word 落点)
            # can wrongly reject a direct passage that expresses the same
            # mechanism as “对手出球最快的位置”.
            requested_focus_groups=[
                *incoming_focus_window_groups(
                    actor_context, selection_rules
                ),
                *comparison_axis_window_groups(
                    search_module, query, diagnostic_rules
                ),
            ],
        )
        if not evidence_entries:
            continue
        mechanism_record = {
            "id": f"M{len(supported_mechanisms) + 1}",
            "mechanism_id": mechanism["id"],
            "label": mechanism["label"],
            "status": "conditional",
            "eligible_video_labels": [
                item["label"] for item in evidence_entries
            ],
            "reason": "source-supported diagnostic branch; verify against the user's actual movement before attributing cause",
        }
        supported_mechanisms.append(mechanism_record)
        claim_map.append(
            {
                "claim_id": mechanism_record["id"],
                "kind": "supported_mechanism",
                "text": mechanism["label"],
                "status": "conditional",
                "evidence": evidence_entries,
                "eligible_video_labels": mechanism_record[
                    "eligible_video_labels"
                ],
                "confidence_ceiling": confidence_ceiling(
                    evidence_entries, selected_by_label
                ),
            }
        )

    previously_authorized_labels = {
        evidence["label"]
        for claim in claim_map
        for evidence in claim.get("evidence", [])
    }
    branch_query = (
        question_interpretation.get("actor_context", {}).get("target_query")
        or query
    )
    branches = material_diagnostic_branches(
        branch_query,
        question_interpretation["constraints"],
        selected_videos,
        diagnostic_rules,
        eligible_labels=previously_authorized_labels,
    )
    previous_evidence_by_label = {
        evidence["label"]: evidence
        for claim in claim_map
        for evidence in claim.get("evidence", [])
    }
    for branch in branches:
        for branch_value in branch["branches"]:
            evidence_entries = []
            for label in branch_value["eligible_video_labels"]:
                video = selected_by_label.get(label)
                if video is None:
                    continue
                directness = claim_scope_directness(video, diagnostic_rules)
                if directness == "incompatible":
                    continue
                branch_evidence = claim_evidence_entry(
                    video,
                    "direct" if directness == "exact" else "scoped",
                    (
                        f'directly supports the {branch["label"]} '
                        f'{branch_value["label"]} branch'
                    ),
                )
                prior_evidence = previous_evidence_by_label.get(label, {})
                if prior_evidence.get("claim_windows"):
                    branch_evidence["claim_windows"] = list(
                        prior_evidence["claim_windows"]
                    )
                evidence_entries.append(branch_evidence)
            evidence_entries = evidence_entries[
                : diagnostic_rules.get("max_related_evidence_per_claim", 8)
            ]
            claim_map.append(
                {
                    "claim_id": f'{branch["id"]}.{branch_value["value"]}',
                    "kind": "material_branch",
                    "text": f'{branch["label"]}：{branch_value["label"]}',
                    "status": "conditional" if evidence_entries else "unsupported",
                    "evidence": evidence_entries,
                    "eligible_video_labels": [
                        item["label"] for item in evidence_entries
                    ],
                    "confidence_ceiling": confidence_ceiling(
                        evidence_entries, selected_by_label
                    ),
                }
            )
    if boundary.get("type") == "cross_variant_evidence_transfer":
        for claim in claim_map:
            claim["status"] = (
                "unverified"
                if claim.get("kind") == "user_hypothesis"
                else "unsupported"
            )
            claim["evidence"] = []
            claim["eligible_video_labels"] = []
            claim["confidence_ceiling"] = "none"
        supported_mechanisms = []
        branches = []

    diagnostic_question = bool(
        boundary.get("type")
        not in {
            "pain_or_injury",
            "endorsement_or_authorship",
            "source_evidence_policy",
            "purchase_advice",
        }
        and (
            observed_symptoms
            or user_hypotheses
            or question_interpretation["strategy"] == "literal_symptom_first"
            or intent_frame.get("requested_output") == "diagnosis"
        )
    )
    material_unknowns = []
    for ambiguity in question_interpretation.get("ambiguities", []):
        ambiguity_name = re.sub(r"[^a-z0-9_]+", "_", ambiguity["name"].lower())
        material_unknowns.append(
            {
                "id": f"unknown.ambiguity.{ambiguity_name}",
                "type": "terminology_or_scenario_ambiguity",
                "description": ambiguity.get("required_statement", ambiguity)
                if isinstance(ambiguity, dict)
                else str(ambiguity),
                "required_for_unique_diagnosis": True,
            }
        )
    for branch in branches:
        material_unknowns.append(
            {
                "id": f'unknown.branch.{branch["axis"]}',
                "type": f'branch_axis:{branch["axis"]}',
                "description": branch["label"],
                "required_for_unique_diagnosis": True,
            }
        )
    clarification_requests = []
    for branch in branches:
        question_id = f'clarify.branch.{branch["axis"]}'
        answer_cues = [
            item["label"].removesuffix("分支")
            for item in branch["branches"]
        ]
        if question_id in resolved_question_ids or resolved_answers_cover_cues(
            answer_cues
        ):
            continue
        clarification_requests.append(
            {
                "question_id": question_id,
                "unknown_type": f'branch_axis:{branch["axis"]}',
                "evidence_focus": {
                    "kind": "branch_axis",
                    "id": branch["axis"],
                },
                "question": branch["question"],
                "query_label": branch["query_label"],
                "purpose": f'{branch["label"]}会改变适用的诊断分支和视频证据。',
                "materially_affects": ["diagnosis", "evidence_selection"],
                "answer_format": "free_text_with_one_branch_value",
                "answer_cues": answer_cues,
            }
        )
    clarification_mechanism_ids = list(
        dict.fromkeys(
            [
                *[
                    item["mechanism_id"] for item in supported_mechanisms
                ],
                *[
                    item["mechanism_id"]
                    for item in user_hypotheses
                    if item.get("mechanism_id")
                ],
            ]
        )
    )
    for mechanism_id in clarification_mechanism_ids:
        mechanism = mechanism_by_id[mechanism_id]
        question = mechanism.get("observation_question")
        answer_cues = mechanism.get("answer_cues", [])
        followup = next(
            (
                item
                for item in mechanism.get(
                    "known_observation_followups", []
                )
                if known_observations_cover_cues(
                    item.get("when_cues", [])
                )
            ),
            None,
        )
        if followup:
            question = followup.get("question", question)
            answer_cues = followup.get("answer_cues", answer_cues)
        elif known_observations_cover_cues(answer_cues):
            question = None
        question_id = f'clarify.mechanism.{mechanism["id"]}'
        if (
            question
            and question_id not in resolved_question_ids
            and not explicit_answers_cover_cues(answer_cues)
            and not known_observations_cover_cues(answer_cues)
            and question not in {
                item["question"] for item in clarification_requests
            }
            and not any(
                len(
                    {
                        search_module.normalize(cue)
                        for cue in answer_cues
                    }
                    & {
                        search_module.normalize(cue)
                        for cue in item.get("answer_cues", [])
                    }
                )
                >= 2
                for item in clarification_requests
            )
        ):
            clarification_requests.append(
                {
                    "question_id": question_id,
                    "unknown_type": "user_reported_observation",
                    "evidence_focus": {
                        "kind": "mechanism",
                        "id": mechanism["id"],
                    },
                    "question": question,
                    "query_label": mechanism["label"],
                    "purpose": mechanism.get(
                        "observation_purpose",
                        "用于缩小证据支持的排查范围，并让当前的条件性答案更具体。",
                    ),
                    "materially_affects": ["diagnosis", "evidence_selection"],
                    "answer_format": "focused_free_text_observation",
                    "answer_cues": answer_cues,
                }
            )
    if (
        diagnostic_question
        and not clarification_requests
        and not resolved_question_ids
    ):
        fallback_axes = [
            (
                "问题发生时是主动还是被动",
                ["主动", "被动"],
            ),
            (
                "球最后落在前场、中场还是后场",
                ["前场", "中场", "后场"],
            ),
            (
                "触球点大致在身前、体侧还是身后",
                [
                    "身前",
                    "身体前面",
                    "身体前方",
                    "体侧",
                    "身体侧面",
                    "髋部",
                    "肩部",
                    "身后",
                    "身体后面",
                    "身体后方",
                ],
            ),
        ]
        missing_axes = [
            (label, cues)
            for label, cues in fallback_axes
            if not resolved_answers_cover_cues(cues)
        ]
        if missing_axes:
            clarification_requests.append(
                {
                    "question_id": "clarify.symptom_context",
                    "unknown_type": "user_reported_context",
                    "question": (
                        "若想让答案更完整，可以补充："
                        + "；".join(label for label, _ in missing_axes)
                        + "。"
                    ),
                    "query_label": "问题发生时的具体场景",
                    "purpose": "用于缩小证据支持的排查范围；不影响先回答当前有把握的部分。",
                    "materially_affects": ["diagnosis_detail", "evidence_selection"],
                    "answer_format": "focused_free_text_observation",
                    "answer_cues": [
                        cue for _, cues in missing_axes for cue in cues
                    ],
                }
            )
    if (
        question_interpretation.get("intent_frame", {}).get(
            "requested_output"
        )
        == "practice"
        and not clarification_requests
        and not resolved_question_ids
    ):
        clarification_requests.append(
            {
                "question_id": "clarify.practice_context",
                "unknown_type": "user_reported_context",
                "question": (
                    "若想让答案更具体，可以补充最想解决的来球或动作场景、"
                    "当前失败表现，以及期望的出球或落点。"
                ),
                "query_label": "希望解决的具体技术场景",
                "purpose": (
                    "用于缩小技术解释和来源范围；不会据此生成无来源支持的"
                    "训练时长、组数或周期安排。"
                ),
                "materially_affects": [
                    "technical_detail",
                    "evidence_selection",
                ],
                "answer_format": "focused_free_text_observation",
                "answer_cues": [
                    "来球",
                    "动作",
                    "失败表现",
                    "期望落点",
                ],
            }
        )
    clarification_requests = clarification_requests[
        : diagnostic_rules.get("max_clarification_questions", 3)
    ]
    questions = [item["question"] for item in clarification_requests]
    has_useful_evidence = any(
        claim["evidence"] for claim in claim_map if claim["kind"] != "user_hypothesis"
    )
    ask_first = bool(
        question_interpretation.get("ambiguities")
        and not has_useful_evidence
        and boundary["type"] == "none"
    )
    clarification_action = (
        "ask_first"
        if ask_first
        else (
            "answer_conditionally"
            if material_unknowns or branches or clarification_requests
            else "answer_now"
        )
    )

    completeness_items = []
    for claim in claim_map:
        if claim["kind"] == "question_unit":
            status = "must_answer"
        elif claim["status"] in {"unverified", "unsupported"}:
            status = "unresolved"
        else:
            status = "conditional"
        completeness_items.append(
            {
                "item_id": claim["claim_id"],
                "text": claim["text"],
                "status": status,
                "required_treatment": (
                    "answer with mapped evidence or explicitly state the evidence gap"
                    if status == "must_answer"
                    else (
                        "state that this remains unverified; do not silently accept or omit it"
                        if status == "unresolved"
                        else "explain as a conditional branch, not as the confirmed cause"
                    )
                ),
            }
        )
    for branch in branches:
        completeness_items.append(
            {
                "item_id": branch["id"],
                "text": branch["label"],
                "status": "conditional",
                "required_treatment": "cover every evidenced branch separately until the missing context is supplied",
            }
        )

    return {
        "diagnostic_model": {
            "observed_symptoms": observed_symptoms,
            "clarification_observations": [
                *[
                    {
                        "question_id": None,
                        "question": None,
                        "text": item["source_unit"],
                        "source": "user_initial_question",
                        "verification_status": "user_reported_not_independently_verified",
                    }
                    for item in known_observation_records
                ],
                *[
                    {
                        "question_id": item["question_id"],
                        "question": item["question"],
                        "text": item["answer"],
                        "source": "user_clarification_text",
                        "verification_status": "user_reported_not_independently_verified",
                    }
                    for item in resolved_answers
                    if item["unknown_type"]
                    in {"user_reported_observation", "user_reported_context"}
                ],
            ],
            "user_hypotheses": user_hypotheses,
            "supported_mechanisms": supported_mechanisms,
            "material_branches": branches,
            "do_not_claim_unique_cause": diagnostic_question,
            "additional_information_can_improve_answer": diagnostic_question,
        },
        "clarification_decision": {
            "action": clarification_action,
            "can_provide_useful_answer_now": has_useful_evidence or boundary["type"] != "none",
            "material_unknowns": material_unknowns,
            "questions": questions,
            "clarification_requests": clarification_requests,
            "question_limit": diagnostic_rules.get("max_clarification_questions", 3),
        },
        "claim_evidence_map": claim_map,
        "completeness_contract": {
            "items": completeness_items,
            "unresolved_item_ids": [
                item["item_id"]
                for item in completeness_items
                if item["status"] == "unresolved"
            ],
            "silent_omission_forbidden": True,
            "complete_answer_definition": "cover every must_answer item, preserve every conditional branch, and name every unresolved evidence gap; completeness is not answer length",
        },
    }
