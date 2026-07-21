#!/usr/bin/env python3
"""Build a deterministic, evidence-ready context before answer generation."""

import argparse
import importlib.util
import json
import re
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
    intent_frame = plan["retrieval_guidance"]["intent_frame"]
    positive_query = intent_frame.get(
        "positive_query", original_query
    )
    actor_query = intent_frame.get("actor_query", positive_query)
    actor_context = query_actor_context(search_module, actor_query, rules)
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
    constrained_queries.extend(actor_context["derived_search_terms"])
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


def structured_constraint_text(search_module, video):
    """Return teaching evidence without repeating metadata or broad taxonomy."""
    note = {
        key: value
        for key, value in (video.get("teaching_note") or {}).items()
        if key
        not in {
            "note",
            "video_id",
            "title",
            "url",
            "topic",
            "review_summary",
            "problem",
        }
    }
    return search_module.normalize(search_module.flatten(note))


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
    normalized = search_module.normalize(query)
    if any(
        search_module.normalize(phrase) in normalized
        for phrase in axis.get("mixed_value_sets", {})
    ):
        return values
    target_prefixes = [
        search_module.normalize(prefix)
        for prefix in axis.get("query_target_prefixes", [])
        if search_module.normalize(prefix)
    ]
    if not values or not target_prefixes:
        return values

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


def _query_actor_marker_suppressed(query, match, rules):
    token = match.group(0)
    for phrase in rules.get("query_actor_marker_suppressions", {}).get(
        token, []
    ):
        window_start = max(0, match.start() - len(phrase) + 1)
        phrase_start = query.find(phrase, window_start, match.start() + 1)
        if (
            phrase_start >= 0
            and phrase_start <= match.start()
            and match.end() <= phrase_start + len(phrase)
        ):
            return True
    return False


def _query_actor_parser_parts(query, rules):
    markers = {
        marker: actor
        for actor, actor_markers in rules.get(
            "query_actor_markers", {}
        ).items()
        for marker in actor_markers
    }
    separators = set(rules.get("query_actor_clause_separators", []))
    tokens = sorted([*markers, *separators], key=len, reverse=True)
    pattern = None
    if tokens:
        pattern = re.compile("|".join(re.escape(token) for token in tokens))
    return markers, separators, pattern


def _query_actor_segments(query, rules):
    markers, separators, pattern = _query_actor_parser_parts(query, rules)
    if pattern is None:
        return [{"actor": "player", "text": query}]
    pronouns = set(rules.get("query_actor_pronoun_markers", []))
    referent_actors = {"opponent", "partner"}
    segments = []
    current_actor = "player"
    last_explicit_referent = None
    cursor = 0

    def append_text(text, force_new=False):
        if not text:
            return
        if (
            not force_new
            and segments
            and segments[-1]["actor"] == current_actor
        ):
            segments[-1]["text"] += text
        else:
            segments.append({"actor": current_actor, "text": text})

    for match in pattern.finditer(query):
        token = match.group(0)
        append_text(query[cursor : match.start()])
        if _query_actor_marker_suppressed(query, match, rules):
            append_text(token)
            cursor = match.end()
            continue
        if token in separators:
            current_actor = "player"
            append_text(" ", force_new=True)
        else:
            configured_actor = markers[token]
            if token in pronouns and last_explicit_referent in referent_actors:
                current_actor = last_explicit_referent
            else:
                current_actor = configured_actor
            append_text(token)
            if token not in pronouns and configured_actor in referent_actors:
                last_explicit_referent = configured_actor
        cursor = match.end()
    append_text(query[cursor:])
    return [
        {"actor": segment["actor"], "text": segment["text"]}
        for segment in segments
        if segment["text"]
    ]


def query_actor_text(query, rules):
    buffers = {
        actor: []
        for actor in rules.get("query_actor_markers", {})
    }
    buffers.setdefault("player", [])
    for segment in _query_actor_segments(query, rules):
        buffers[segment["actor"]].append(segment["text"])
    return {
        actor: re.sub(r"\s+", " ", "".join(parts)).strip()
        for actor, parts in buffers.items()
    }


def _segment_requests_answer(segment, rules):
    normalized = re.sub(r"\s+", "", segment)
    return any(
        re.sub(r"\s+", "", str(term)) in normalized
        for term in rules.get("query_target_actor_terms", [])
        if str(term)
    )


def query_target_actor(query, actor_text, rules):
    target_actor = None

    for segment in _query_actor_segments(query, rules):
        if _segment_requests_answer(segment["text"], rules):
            target_actor = segment["actor"]
    if target_actor in {"player", "partner"}:
        return target_actor
    if actor_text.get("partner") and not actor_text.get("player"):
        return "partner"
    return "player"


def _query_constraints_from_text(
    search_module,
    query,
    rules,
    value_additions_field=None,
):
    constraints = {}
    normalized_query = search_module.normalize(query)
    for axis in rules.get("constraint_axes", []):
        values = query_axis_values(search_module, query, axis)
        if value_additions_field:
            values.update(
                value
                for value, phrases in axis.get(
                    value_additions_field, {}
                ).items()
                if any(
                    search_module.normalize(phrase) in normalized_query
                    for phrase in phrases
                )
            )
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
            for term in [
                "杀球",
                "扣杀",
                "重杀",
                "点杀",
                "跳杀",
                "遁地炮",
                "顿地炮",
                "蹲地炮",
                "dun地炮",
                "压球",
                "杀",
            ]
        )
    ):
        constraints["tactical_phase"] = ["attack"]
    sequence_implication = _action_sequence_implication(
        search_module, query, rules
    )
    if sequence_implication:
        for axis_name, values in sequence_implication.get(
            "derived_constraints", {}
        ).items():
            constraints[axis_name] = sorted(
                set(constraints.get(axis_name, [])) | set(values)
            )
    return constraints


def _action_sequence_implication(search_module, query, rules):
    normalized_query = search_module.normalize(query)
    for implication in rules.get("action_sequence_implications", []):
        if any(
            search_module.normalize(term) in normalized_query
            for term in implication.get("canonical_terms", [])
        ):
            return implication
        before_matches = [
            (normalized_query.find(search_module.normalize(term)), term)
            for term in implication.get("before_terms", [])
            if search_module.normalize(term) in normalized_query
        ]
        after_matches = [
            (normalized_query.find(search_module.normalize(term)), term)
            for term in implication.get("after_terms", [])
            if search_module.normalize(term) in normalized_query
        ]
        max_gap = implication.get("max_gap_characters", 12)
        for before_index, before_term in before_matches:
            before_end = before_index + len(search_module.normalize(before_term))
            if any(
                after_index >= before_end
                and after_index - before_end <= max_gap
                for after_index, _ in after_matches
            ):
                return implication
    return None


def _reception_symptom_implication(search_module, query, rules):
    normalized_query = search_module.normalize(query)
    for implication in rules.get("reception_symptom_implications", []):
        required_groups = [
            implication.get("symptom_terms", []),
            implication.get("incoming_terms", []),
            implication.get("response_terms", []),
        ]
        if all(
            any(
                search_module.normalize(term) in normalized_query
                for term in terms
            )
            for terms in required_groups
        ):
            return implication
    return None


def _query_target_action_context(
    search_module,
    query,
    target_actor,
    target_query,
    target_actor_constraints,
    rules,
):
    sequence_implication = _action_sequence_implication(
        search_module, target_query, rules
    )
    if sequence_implication and target_actor == "player":
        action_query = sequence_implication["canonical_action_query"]
        normalized_target_query = search_module.normalize(target_query)
        has_symptom = any(
            search_module.normalize(term) in normalized_target_query
            for term in sequence_implication.get("symptom_terms", [])
        )
        action_constraints = _query_constraints_from_text(
            search_module, action_query, rules
        )
        return {
            "target_action_query": action_query,
            "target_condition_query": target_query if has_symptom else "",
            "target_action_scope_query": action_query,
            "target_action_backreferences_condition": False,
            "target_action_constraints": action_constraints,
            "target_condition_constraints": {},
            "requested_action_scopes": list(
                sequence_implication["requested_action_scopes"]
            ),
            "inferred_target_action": {
                "rule": sequence_implication["name"],
                "reason": sequence_implication["reason"],
            },
            "inferred_search_terms": list(
                sequence_implication["search_terms"]
            ),
            "condition_constraints_are_incoming": False,
        }

    reception_implication = _reception_symptom_implication(
        search_module, query, rules
    )
    if reception_implication and target_actor == "player":
        action_query = reception_implication["target_action_query"]
        return {
            "target_action_query": action_query,
            "target_condition_query": query,
            "target_action_scope_query": action_query,
            "target_action_backreferences_condition": True,
            "target_action_constraints": _query_constraints_from_text(
                search_module, action_query, rules
            ),
            "target_condition_constraints": _query_constraints_from_text(
                search_module, query, rules
            ),
            "requested_action_scopes": list(
                reception_implication["requested_action_scopes"]
            ),
            "inferred_target_action": {
                "rule": reception_implication["name"],
                "reason": reception_implication["reason"],
            },
            "inferred_search_terms": list(
                reception_implication["search_terms"]
            ),
            "condition_constraints_are_incoming": True,
        }

    target_segments = [
        segment
        for segment in _query_actor_segments(query, rules)
        if segment["actor"] == target_actor and segment["text"].strip()
    ]
    action_segments = [
        segment["text"]
        for segment in target_segments
        if _segment_requests_answer(segment["text"], rules)
    ]
    condition_segments = [
        segment["text"]
        for segment in target_segments
        if not _segment_requests_answer(segment["text"], rules)
    ]
    action_query = re.sub(
        r"\s+", " ", " ".join(action_segments)
    ).strip()
    if not action_query:
        action_query = target_query
        condition_segments = []
    condition_query = re.sub(
        r"\s+", " ", " ".join(condition_segments)
    ).strip()
    action_constraints = _query_constraints_from_text(
        search_module,
        action_query,
        rules,
        value_additions_field=(
            "opponent_query_value_additions"
            if target_actor == "opponent"
            else None
        ),
    )
    condition_constraints = {}
    for axis_name, values in target_actor_constraints.items():
        remaining = set(values) - set(action_constraints.get(axis_name, []))
        if remaining:
            condition_constraints[axis_name] = sorted(remaining)

    normalized_action = search_module.normalize(action_query)
    action_backreferences_condition = bool(
        condition_query
        and any(
            search_module.normalize(term) in normalized_action
            for term in rules.get("target_action_backreference_terms", [])
        )
    )
    action_scope_query = action_query
    if action_backreferences_condition:
        action_scope_query = " ".join([condition_query, action_query]).strip()
    normalized_action_scope = search_module.normalize(action_scope_query)
    normalized_full_query = search_module.normalize(query)
    requested_action_scopes = []
    for scope in rules.get("target_action_scopes", []):
        if not any(
            search_module.normalize(term) in normalized_action_scope
            for term in scope["query_terms"]
        ):
            continue
        context_terms = scope.get("query_context_terms", [])
        if context_terms and not any(
            search_module.normalize(term) in normalized_full_query
            for term in context_terms
        ):
            continue
        requested_action_scopes.append(scope["name"])
    return {
        "target_action_query": action_query,
        "target_condition_query": condition_query,
        "target_action_scope_query": action_scope_query,
        "target_action_backreferences_condition": action_backreferences_condition,
        "target_action_constraints": action_constraints,
        "target_condition_constraints": condition_constraints,
        "requested_action_scopes": requested_action_scopes,
        "inferred_target_action": None,
        "inferred_search_terms": [],
        "condition_constraints_are_incoming": False,
    }


def query_actor_context(search_module, query, rules):
    actor_text = query_actor_text(query, rules)
    actor_constraints = {}
    for actor, text in actor_text.items():
        actor_constraints[actor] = _query_constraints_from_text(
            search_module,
            text,
            rules,
            value_additions_field=(
                "opponent_query_value_additions"
                if actor == "opponent"
                else None
            ),
        )
    player_constraints = actor_constraints.get("player", {})
    opponent_constraints = actor_constraints.get("opponent", {})
    partner_constraints = actor_constraints.get("partner", {})
    target_actor = query_target_actor(query, actor_text, rules)
    target_action_context = _query_target_action_context(
        search_module,
        query,
        target_actor,
        actor_text[target_actor],
        actor_constraints.get(target_actor, {}),
        rules,
    )
    if target_action_context.get("condition_constraints_are_incoming"):
        incoming_constraints = target_action_context[
            "target_condition_constraints"
        ]
        for axis_name, incoming_values in incoming_constraints.items():
            retained = set(player_constraints.get(axis_name, [])) - set(
                incoming_values
            )
            if retained:
                player_constraints[axis_name] = sorted(retained)
            else:
                player_constraints.pop(axis_name, None)
        actor_constraints["player"] = player_constraints
    else:
        incoming_constraints = {}
    normalized_query = search_module.normalize(query)
    derived_player_constraints = {}
    derived_target_constraints = {}
    derived_search_terms = list(
        target_action_context.get("inferred_search_terms", [])
    )
    for implication in (
        rules.get("opponent_response_implications", [])
        if target_actor == "player"
        else []
    ):
        opponent_values = set(
            opponent_constraints.get(implication["opponent_axis"], [])
        )
        if not opponent_values & set(implication["opponent_values"]):
            continue
        if not any(
            search_module.normalize(term) in normalized_query
            for term in implication["response_terms"]
        ):
            continue
        player_axis = implication["player_axis"]
        if player_axis not in player_constraints:
            player_constraints[player_axis] = sorted(
                set(implication["player_values"])
            )
            derived_player_constraints[player_axis] = player_constraints[
                player_axis
            ]
        derived_search_terms.extend(implication.get("search_terms", []))
    if actor_text.get("partner"):
        for implication in rules.get("partner_retrieval_implications", []):
            if any(
                search_module.normalize(term) in normalized_query
                for term in implication["trigger_terms"]
            ):
                derived_search_terms.extend(implication["search_terms"])
                for axis_name, values in implication.get(
                    "derived_constraints", {}
                ).items():
                    derived_target_constraints.setdefault(axis_name, []).extend(
                        values
                    )
    for scope_name in target_action_context["requested_action_scopes"]:
        scope = next(
            item
            for item in rules.get("target_action_scopes", [])
            if item["name"] == scope_name
        )
        derived_search_terms.extend(scope.get("search_terms", []))
    actor_constraints["player"] = player_constraints
    target_constraints = {
        axis_name: list(values)
        for axis_name, values in actor_constraints.get(target_actor, {}).items()
    }
    for axis_name, values in derived_target_constraints.items():
        target_constraints[axis_name] = sorted(
            set(target_constraints.get(axis_name, [])) | set(values)
        )
        derived_target_constraints[axis_name] = sorted(set(values))
    return {
        "player_query": actor_text["player"],
        "opponent_query": actor_text["opponent"],
        "partner_query": actor_text["partner"],
        "player_constraints": player_constraints,
        "opponent_constraints": opponent_constraints,
        "partner_constraints": partner_constraints,
        "actor_constraints": actor_constraints,
        "target_actor": target_actor,
        "target_query": actor_text[target_actor],
        **target_action_context,
        "target_constraints": target_constraints,
        "derived_player_constraints": derived_player_constraints,
        "derived_target_constraints": derived_target_constraints,
        "derived_search_terms": list(dict.fromkeys(derived_search_terms)),
        "incoming_shot_constraints": incoming_constraints,
    }


def query_constraints(search_module, query, rules):
    return query_actor_context(search_module, query, rules)[
        "target_constraints"
    ]


def query_ambiguities(search_module, query, rules):
    normalized = search_module.normalize(query)
    ambiguities = []
    for rule in rules.get("query_ambiguities", []):
        matched_terms = [
            term
            for term in rule.get("query_terms", [])
            if search_module.normalize(term) in normalized
        ]
        if not matched_terms:
            continue
        if any(
            search_module.normalize(term) in normalized
            for term in rule.get("resolved_by_terms", [])
        ):
            continue
        ambiguities.append(
            {
                "name": rule["name"],
                "matched_terms": matched_terms,
                "required_statement": rule["required_statement"],
            }
        )
    return ambiguities


def query_terminology_corrections(search_module, query, rules):
    normalized = search_module.normalize(query)
    corrections = []
    for rule in rules.get("canonical_terminology", []):
        matched_terms = [
            term
            for term in rule.get("accepted_input_errors", [])
            if search_module.normalize(term) in normalized
        ]
        if not matched_terms:
            continue
        corrections.append(
            {
                "name": rule["name"],
                "matched_terms": matched_terms,
                "canonical_term": rule["canonical_term"],
                "required_statement": rule["required_statement"],
            }
        )
    return corrections


def requested_technique_definitions(requested_constraints, rules):
    definitions = rules.get("technique_definitions", {})
    return [
        {"technique_variant": variant, **definitions[variant]}
        for variant in requested_constraints.get("technique_variant", [])
        if variant in definitions
    ]


def explicit_constraint_terms(search_module, query, rules):
    actor_context = query_actor_context(search_module, query, rules)
    normalized = search_module.normalize(actor_context["target_query"])
    requested = actor_context["target_constraints"]
    terms = list(actor_context["derived_search_terms"])
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
    structured_text = structured_constraint_text(search_module, video)
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
        if axis.get("category_evidence_policy") == "ignore":
            category, category_suppressed = set(), set()
        else:
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
    for implication in rules.get("source_constraint_implications", []):
        source_scope = scope.get(implication["source_axis"], {})
        target_scope = scope.get(implication["target_axis"], {})
        if target_scope.get("values"):
            continue
        if any(
            search_module.normalize(term) in structured_text
            for term in implication.get("suppress_when_terms", [])
        ):
            continue
        if not set(implication["source_values"]).issubset(
            source_scope.get("values", [])
        ):
            continue
        scope[implication["target_axis"]] = {
            "values": sorted(set(implication["target_values"])),
            "source": "derived_constraint",
            "suppressed_values": target_scope.get(
                "suppressed_values", []
            ),
            "basis": implication.get("basis", ""),
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
    shot_scope = scope.get("shot_family", {})
    video_shot_families = set(shot_scope.get("values", []))
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
    non_serve_video_shots = video_shot_families - {
        "short_serve",
        "deep_serve",
    }
    if (
        requested_serve_roles
        and not video_serve_roles
        and non_serve_video_shots
        and not requested_shot_families & non_serve_video_shots
    ):
        failures.append(
            "explicit_cross_axis_conflict:serve_role_vs_shot_family"
        )
    return not failures, failures, requested, scope, matches


def required_constraint_support_failures(requested, matches, rules):
    failures = []
    for axis_name, failure_reason in rules.get(
        "required_single_value_constraint_support_axes", {}
    ).items():
        if (
            len(requested.get(axis_name, [])) == 1
            and matches.get(axis_name) == "unspecified_support"
        ):
            failures.append(failure_reason)
    for condition in rules.get(
        "required_constraint_support_conditions", []
    ):
        if not all(
            set(required_values).issubset(requested.get(axis_name, []))
            for axis_name, required_values in condition.get(
                "when_requested", {}
            ).items()
        ):
            continue
        unsupported_matches = set(
            condition.get(
                "unsupported_matches", ["unspecified_support"]
            )
        )
        if matches.get(condition["axis"]) in unsupported_matches:
            failures.append(condition["failure_reason"])
    return list(dict.fromkeys(failures))


def unrequested_specific_scope(requested, scope, rules):
    allowed_sources = set(
        rules.get("unrequested_scope_support_only_sources", [])
    )
    conditional_axes = {
        condition["axis"]
        for condition in rules.get(
            "unrequested_scope_support_only_conditions", []
        )
        if set(scope.get(condition["axis"], {}).get("values", []))
        & set(condition["values"])
        and set(requested.get(condition["requested_axis"], []))
        & set(condition["requested_values"])
    }
    return {
        axis_name: scope[axis_name]
        for axis_name in scope
        if not requested.get(axis_name)
        and scope.get(axis_name, {}).get("values")
        and (
            axis_name
            in rules.get("unrequested_scope_support_only_axes", [])
            or axis_name in conditional_axes
        )
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


def non_target_actor_condition_failures(
    search_module,
    actor_context,
    scope,
    video,
    rules,
):
    requested = actor_context["target_constraints"]
    rejected_sources = set(
        rules.get("opponent_condition_player_action_rejected_sources", [])
    )
    support_text = search_module.normalize(
        " ".join(
            [
                primary_video_constraint_text(search_module, video),
                str(video.get("category", "")),
                str((video.get("teaching_note") or {}).get("review_summary", "")),
                str((video.get("teaching_note") or {}).get("problem", "")),
            ]
        )
    )
    failures = []
    target_actor = actor_context["target_actor"]
    if actor_context.get("partner_query") and not any(
        search_module.normalize(term) in support_text
        for term in rules.get("partner_condition_support_terms", [])
    ):
        failures.append("partner_context_not_supported")
    for actor, actor_constraints in actor_context["actor_constraints"].items():
        if actor == target_actor or not actor_constraints:
            continue
        support_terms_key = (
            "opponent_condition_support_terms"
            if actor == "opponent"
            else "partner_condition_support_terms"
        )
        has_actor_support = any(
            search_module.normalize(term) in support_text
            for term in rules.get(support_terms_key, [])
        )
        if actor == "partner" and not has_actor_support:
            if "partner_context_not_supported" not in failures:
                failures.append("partner_context_not_supported")
            continue
        if has_actor_support:
            continue
        for axis_name, actor_values in actor_constraints.items():
            if requested.get(axis_name):
                continue
            scope_details = scope.get(axis_name, {})
            if scope_details.get("source") not in rejected_sources:
                continue
            if not set(scope_details.get("values", [])) & set(actor_values):
                continue
            if actor == "opponent" and target_actor == "player":
                reason = (
                    "opponent_condition_misread_as_player_action:"
                    f"{axis_name}"
                )
            else:
                reason = (
                    f"{actor}_condition_misread_as_{target_actor}_action:"
                    f"{axis_name}"
                )
            failures.append(reason)
    return failures


def partner_context_rank(search_module, actor_context, video, rules):
    if not actor_context.get("partner_query"):
        return 2
    primary_text = search_module.normalize(
        " ".join(
            [
                primary_video_constraint_text(search_module, video),
                str(video.get("category", "")),
                str((video.get("teaching_note") or {}).get("review_summary", "")),
                str((video.get("teaching_note") or {}).get("problem", "")),
            ]
        )
    )
    if any(
        search_module.normalize(term) in primary_text
        for term in rules.get("query_actor_markers", {}).get("partner", [])
    ):
        return 0
    if any(
        search_module.normalize(term) in primary_text
        for term in rules.get("partner_condition_support_terms", [])
    ):
        return 1
    return 2


def derived_player_constraint_failures(
    derived_player_constraints,
    scope,
    rules,
):
    required_axes = set(
        rules.get("derived_player_constraint_required_match_axes", [])
    )
    failures = []
    for axis_name, requested_values in derived_player_constraints.items():
        if axis_name not in required_axes:
            continue
        source_values = set(scope.get(axis_name, {}).get("values", []))
        if not source_values & set(requested_values):
            failures.append(
                f"derived_player_constraint_not_supported:{axis_name}"
            )
    return failures


def requested_action_scope_failures(
    search_module,
    actor_context,
    video,
    rules,
):
    requested_scopes = set(actor_context.get("requested_action_scopes", []))
    if not requested_scopes:
        return []
    support_text = search_module.normalize(
        " ".join(
            [
                primary_video_constraint_text(search_module, video),
                str(video.get("category", "")),
                substantive_instruction_text(search_module, video, rules),
            ]
        )
    )
    failures = []
    for scope in rules.get("target_action_scopes", []):
        if scope["name"] not in requested_scopes:
            continue
        has_support = any(
            search_module.normalize(term) in support_text
            for term in scope["source_terms"]
        )
        if not has_support:
            failures.append(
                f"requested_action_not_supported:{scope['name']}"
            )
            continue
        suppressed = any(
            search_module.normalize(term) in support_text
            for term in scope.get("source_suppressions", [])
        )
        overridden = any(
            search_module.normalize(term) in support_text
            for term in scope.get("source_override_terms", [])
        )
        if suppressed and not overridden:
            failures.append(
                f"requested_action_wrong_actor:{scope['name']}"
            )
    return failures


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


def substantive_instruction_text(search_module, video, rules):
    note = video.get("teaching_note") or {}
    evidence = {
        key: value
        for key, value in note.items()
        if key
        not in {
            "note",
            "video_id",
            "title",
            "url",
            "topic",
        }
    }
    reviewed_override = rules.get("video_constraint_overrides", {}).get(
        video.get("video_id"), {}
    )
    return search_module.normalize(
        " ".join(
            [
                search_module.flatten(evidence),
                str(reviewed_override.get("basis", "")),
            ]
        )
    )


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
    intent_frame = plan["retrieval_guidance"]["intent_frame"]
    positive_query = intent_frame.get("positive_query", query)
    actor_query = intent_frame.get("actor_query", positive_query)
    boundary = classify_boundary(positive_query, rules)
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
        navigation = topic_navigation(navigation_module, query)
    if use_topic_navigation:
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
        (accepted if keep else rejected).append(record)

    accepted.sort(key=lambda entry: selected_sort_key(entry, rules))
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

    context = {
        "query": query,
        "question_interpretation": {
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
                "question_interpretation.ambiguities 非空时，先逐条说明 required_statement；不得把有多种场区含义的术语静默收窄成一种技术。",
                "question_interpretation.terminology_corrections 非空时，先说明 required_statement，并在回答正文、视频标题改写和观看重点中只使用 canonical_term；错误输入词只可在纠正句中出现一次。",
                "question_interpretation.technique_definitions 是维护者确认的规范术语、父类、起跳边界和线路分类；用于解释技术归属，但不能让父类视频替代所问细分技术的直接动作证据。",
                "actor_context 已解析他/她的最近明确指代以及陪练、发球机等来球方；target_actor 指明建议对象。target_action_query 是实际请求动作，target_condition_query 是同一主体的既有状态或症状，不得把条件动作当成所问动作；inferred_target_action 非空时，先说明从症状推导出的目标动作，并把 incoming_shot_constraints 仅视为来球条件。target_action_backreferences_condition 为真时，怎么改等泛化请求只从 target_action_scope_query 继承已配置的动作范围。requested_action_scopes 要求来源直接支持所问动作，并排除只讨论其他场景或其他主体的来源。opponent_constraints、partner_constraints 与其他非目标主体约束只描述条件，不得当成目标球员执行动作。硬证据范围只使用 question_interpretation.constraints，其中 derived_target_constraints 可能是补位、轮转或站位所隐含的双打场景。",
                "concept_match 只说明概念覆盖；只有 claim_scope_policy 为 exact_question_scope 时才可支持无额外条件的完整问题。",
                "claim_scope_policy 为 additional_specific_scope_only_not_unrestricted_full_question_proof 时，必须明确说明 unrequested_constraint_scope 或 unrequested_ranking_scope 中的额外条件，不得把专项来源概括为泛问通则。",
                "exact_query_unit_scope_only 只支持对应子问题；component_or_generic_support_only_not_full_question_proof 只能支持局部机制或通用原则。",
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
