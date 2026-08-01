#!/usr/bin/env python3
"""Diagnostic hypotheses, mechanisms, evidence maps, and confidence contracts."""

import re

def extract_user_hypotheses(query, diagnostic_rules):
    """Return causes proposed by the user without treating them as facts."""
    hypotheses = []
    seen = set()
    for rule in diagnostic_rules.get("hypothesis_patterns", []):
        for match in re.finditer(rule["pattern"], query):
            group_names = (
                ["hypothesis"]
                if rule["type"] == "single_cause_question"
                else ["left", "right"]
            )
            for group_name in group_names:
                raw_text = match.group(group_name).strip(" ，,。？?！!")
                parts = re.split(r"[、]", raw_text)
                for text in parts:
                    text = re.sub(
                        r"(?:造成|导致|引起|带来)?的?(?:问题|原因)?$",
                        "",
                        text,
                    ).strip()
                    if not text or text in seen:
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
        return "incompatible"
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
    return any(
        video.get("constraint_match", {}).get(axis) in supported_matches
        for axis in requested_axes
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


def query_window_support(video):
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
    ]
    for window in source_windows:
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
        candidate = {
            "rank": rank,
            "score": float(window.get("score") or 0),
            "matched_term_count": matched_count,
            "query_ngram_coverage": coverage,
            "exact_query_match": exact,
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
        and video.get("reviewed_evidence_rank", 2) <= 1
    ):
        best = {
            **best,
            "rank": 2,
            "reviewed_evidence_fallback": True,
        }
    if (
        best["rank"] < 2
        and video.get("source_type") != "bilibili_video"
        and video.get("teaching_note", {}).get("evidence")
    ):
        best = {
            **best,
            "rank": 2,
            "legacy_source_fallback": True,
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


def query_unit_evidence(video, strategy, query_constraints, diagnostic_rules):
    if not has_requested_action_scope_support(
        video, query_constraints, diagnostic_rules
    ):
        return None
    scope_directness = claim_scope_directness(video, diagnostic_rules)
    if scope_directness == "incompatible":
        return None
    concept = video.get("concept_match")
    symptom = video.get("symptom_match")
    if concept == "none" and symptom in {"none", "not_required"}:
        return None
    window_support = query_window_support(video)
    if window_support["rank"] < 2:
        return None
    if (
        scope_directness == "exact"
        and concept in {"exact_question", "exact_query_unit"}
        and video.get("claim_scope_policy")
        in {"exact_question_scope", "exact_query_unit_scope_only"}
    ):
        directness = "direct"
    elif concept in {"exact_question", "exact_query_unit"}:
        directness = "scoped"
    else:
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
    evidence["window_support"] = {
        **window_support,
        "primary_query_score": float(video.get("primary_query_score") or 0),
        "best_retrieval_rank": video.get("best_retrieval_rank"),
    }
    return evidence


def mechanism_evidence(
    search_module,
    mechanism,
    selected_videos,
    query_constraints,
    diagnostic_rules,
):
    matched = []
    for video in selected_videos:
        if not has_requested_action_scope_support(
            video, query_constraints, diagnostic_rules
        ):
            continue
        evidence_text = selected_video_evidence_text(search_module, video)
        terms = [
            term
            for term in mechanism.get("evidence_terms", [])
            if search_module.normalize(term) in evidence_text
        ]
        if not terms:
            continue
        scope_directness = claim_scope_directness(video, diagnostic_rules)
        if scope_directness == "incompatible":
            continue
        directness = "direct" if scope_directness == "exact" else "scoped"
        if video.get("concept_match") in {
            "component_support",
            "reviewed_support",
            "expanded_support",
        }:
            directness = "component" if directness == "scoped" else "scoped"
        matched.append(
            claim_evidence_entry(
                video,
                directness,
                f'direct evidence text matches {mechanism["label"]}: {terms[0]}',
            )
        )
    rank = {"direct": 0, "scoped": 1, "component": 2}
    matched.sort(key=lambda item: (rank[item["directness"]], item["label"]))
    return matched[: diagnostic_rules.get("max_evidence_per_claim", 3)]


def material_diagnostic_branches(
    query, query_constraints, selected_videos, diagnostic_rules
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
    resolved_question_ids=None,
    resolved_answers=None,
):
    resolved_question_ids = set(resolved_question_ids or [])
    resolved_answers = list(resolved_answers or [])
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
    query_units = question_interpretation.get("query_units") or [query]
    for unit in query_units:
        evidence_entries = [
            evidence
            for video in selected_videos
            if (
                evidence := query_unit_evidence(
                    video,
                    question_interpretation["strategy"],
                    question_interpretation["constraints"],
                    diagnostic_rules,
                )
            )
            and (
                unit in video.get("matched_query_units", [])
                or len(query_units) == 1
            )
        ]
        directness_rank = {"direct": 0, "scoped": 1, "component": 2}
        evidence_entries.sort(
            key=lambda item: (
                -int(
                    bool(
                        item["window_support"].get(
                            "reviewed_evidence_fallback"
                        )
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
            : diagnostic_rules.get("max_evidence_per_claim", 3)
        ]
        claim_map.append(
            {
                "claim_id": f"Q{len(claim_map) + 1}",
                "kind": "question_unit",
                "text": unit,
                "status": "supported" if evidence_entries else "unsupported",
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
        evidence_entries = (
            mechanism_evidence(
                search_module,
                mechanism,
                selected_videos,
                question_interpretation["constraints"],
                diagnostic_rules,
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

    normalized_query = search_module.normalize(query)
    supported_mechanisms = []
    for mechanism in diagnostic_rules.get("mechanisms", []):
        if mechanism["id"] in hypothesis_mechanism_ids:
            continue
        if not any(
            search_module.normalize(term) in normalized_query
            for term in mechanism.get("query_terms", [])
        ):
            continue
        evidence_entries = mechanism_evidence(
            search_module,
            mechanism,
            selected_videos,
            question_interpretation["constraints"],
            diagnostic_rules,
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

    branches = material_diagnostic_branches(
        query,
        question_interpretation["constraints"],
        selected_videos,
        diagnostic_rules,
    )
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
                evidence_entries.append(
                    claim_evidence_entry(
                        video,
                        "direct" if directness == "exact" else "scoped",
                        (
                            f'directly supports the {branch["label"]} '
                            f'{branch_value["label"]} branch'
                        ),
                    )
                )
            evidence_entries = evidence_entries[
                : diagnostic_rules.get("max_evidence_per_claim", 3)
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
    diagnostic_question = bool(
        observed_symptoms
        or user_hypotheses
        or question_interpretation["strategy"] == "literal_symptom_first"
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
    if diagnostic_question:
        material_unknowns.append(
            {
                "id": "unknown.user_movement_observation",
                "type": "user_movement_observation",
                "description": "the user's actual contact, racket, body, and movement sequence has not been observed",
                "required_for_unique_diagnosis": True,
            }
        )

    clarification_requests = []
    for branch in branches:
        question_id = f'clarify.branch.{branch["axis"]}'
        if question_id in resolved_question_ids:
            continue
        clarification_requests.append(
            {
                "question_id": question_id,
                "unknown_type": f'branch_axis:{branch["axis"]}',
                "question": branch["question"],
                "query_label": branch["query_label"],
                "purpose": f'{branch["label"]}会改变适用的诊断分支和视频证据。',
                "materially_affects": ["diagnosis", "evidence_selection"],
                "answer_format": "free_text_with_one_branch_value",
                "answer_cues": [
                    item["label"].removesuffix("分支")
                    for item in branch["branches"]
                ],
            }
        )
    for mechanism_record in supported_mechanisms:
        mechanism = mechanism_by_id[mechanism_record["mechanism_id"]]
        question = mechanism.get("observation_question")
        question_id = f'clarify.mechanism.{mechanism["id"]}'
        if (
            question
            and question_id not in resolved_question_ids
            and question not in {
                item["question"] for item in clarification_requests
            }
        ):
            clarification_requests.append(
                {
                    "question_id": question_id,
                    "unknown_type": "user_movement_observation",
                    "question": question,
                    "query_label": mechanism["label"],
                    "purpose": mechanism.get(
                        "observation_purpose",
                        "用于缩小证据支持的排查范围；不能单凭文字观察确认唯一原因。",
                    ),
                    "materially_affects": ["diagnosis", "evidence_selection"],
                    "answer_format": "focused_free_text_observation",
                    "answer_cues": mechanism.get("answer_cues", []),
                }
            )
    if diagnostic_question and not clarification_requests and not resolved_question_ids:
        clarification_requests.append(
            {
                "question_id": "clarify.user_movement_video",
                "unknown_type": "user_movement_observation",
                "question": "若要确认具体原因，请提供包含准备、击球和下一步回动的连续动作视频；仅凭文字症状只能给排查分支。",
                "query_label": "用户连续动作视频观察",
                "purpose": "用于观察完整动作链并确认用户自己的实际动作；没有连续视频时只能给出条件性排查。",
                "materially_affects": ["unique_cause_confirmation"],
                "answer_format": "continuous_user_video",
                "answer_cues": [],
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
            if material_unknowns or branches
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
                {
                    "question_id": item["question_id"],
                    "question": item["question"],
                    "text": item["answer"],
                    "source": "user_clarification_text",
                    "verification_status": "reported_not_video_verified",
                }
                for item in resolved_answers
                if item["unknown_type"] == "user_movement_observation"
            ],
            "user_hypotheses": user_hypotheses,
            "supported_mechanisms": supported_mechanisms,
            "material_branches": branches,
            "do_not_claim_unique_cause": diagnostic_question,
            "unique_cause_confirmation_requires_user_video": diagnostic_question,
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
