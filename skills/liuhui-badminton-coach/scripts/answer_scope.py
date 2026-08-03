#!/usr/bin/env python3
"""Actor parsing, query/source constraints, and applicability scope checks."""

import re

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
        window_end = min(len(query), match.end() + len(phrase) - 1)
        phrase_start = query.find(phrase, window_start, window_end)
        while phrase_start >= 0:
            if (
                phrase_start <= match.start()
                and match.end() <= phrase_start + len(phrase)
            ):
                return True
            phrase_start = query.find(
                phrase,
                phrase_start + 1,
                window_end,
            )
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
    previous_explicit_referent = None
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
            actor_before_marker = current_actor
            restore_actor_after_pronoun = None
            if token in pronouns and last_explicit_referent in referent_actors:
                prefix = re.sub(r"\s+", "", query[cursor : match.start()])
                object_pronoun = any(
                    prefix.endswith(term)
                    for term in rules.get(
                        "query_actor_object_pronoun_prefixes", []
                    )
                )
                partner_object_pronoun = any(
                    prefix.endswith(term)
                    for term in rules.get(
                        "query_actor_partner_object_pronoun_prefixes", []
                    )
                )
                if partner_object_pronoun and "partner" in {
                    last_explicit_referent,
                    previous_explicit_referent,
                }:
                    current_actor = "partner"
                elif (
                    object_pronoun
                    and current_actor == last_explicit_referent
                    and previous_explicit_referent in referent_actors
                ):
                    current_actor = previous_explicit_referent
                else:
                    current_actor = last_explicit_referent
                if any(
                    prefix.endswith(term)
                    for term in rules.get(
                        "query_actor_object_pronoun_restore_prefixes", []
                    )
                ):
                    restore_actor_after_pronoun = actor_before_marker
            else:
                current_actor = configured_actor
            append_text(token)
            if restore_actor_after_pronoun:
                current_actor = restore_actor_after_pronoun
            if token not in pronouns and configured_actor in referent_actors:
                if configured_actor != last_explicit_referent:
                    previous_explicit_referent = last_explicit_referent
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
    for implication in rules.get("query_constraint_implications", []):
        if any(
            axis_name in constraints
            for axis_name in implication.get("only_if_axes_missing", [])
        ):
            continue
        if not all(
            search_module.normalize(term) in normalized_query
            for term in implication.get("all_terms", [])
        ):
            continue
        any_terms = implication.get("any_terms", [])
        if any_terms and not any(
            search_module.normalize(term) in normalized_query
            for term in any_terms
        ):
            continue
        for axis_name, values in implication.get(
            "derived_constraints", {}
        ).items():
            if axis_name not in constraints:
                constraints[axis_name] = sorted(set(values))
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
    actor_text = query_actor_text(query, rules)
    normalized_player = search_module.normalize(actor_text.get("player", ""))
    normalized_opponent = search_module.normalize(actor_text.get("opponent", ""))

    def matching_terms(normalized_text, terms):
        return [
            term
            for term in terms
            if search_module.normalize(term) in normalized_text
        ]

    normalized_actor_text = {
        actor: search_module.normalize(text)
        for actor, text in actor_text.items()
    }
    for implication in rules.get("multi_actor_sequence_implications", []):
        event_chain = []
        for event in implication.get("events", []):
            matches = matching_terms(
                normalized_actor_text.get(event["actor"], ""),
                event.get("terms", []),
            )
            if not matches:
                event_chain = []
                break
            event_chain.append(
                {
                    "actor": event["actor"],
                    "role": event["role"],
                    "term": matches[0],
                }
            )
        if event_chain:
            result = dict(implication)
            event_chain[-1]["term"] = implication["canonical_action_query"]
            result["matched_context"] = {
                "match_type": "multi_actor_sequence",
                "event_chain": event_chain,
                "explicit_after_term": event_chain[-1]["term"],
            }
            return result

    def matched_implication(
        implication,
        match_type,
        before_term="",
        after_term="",
        opponent_response_term="",
    ):
        result = dict(implication)
        event_chain = []
        if before_term:
            event_chain.append(
                {
                    "actor": "player",
                    "role": "prior_action",
                    "term": before_term,
                }
            )
        if opponent_response_term:
            event_chain.append(
                {
                    "actor": "opponent",
                    "role": "response",
                    "term": opponent_response_term,
                }
            )
        event_chain.append(
            {
                "actor": "player",
                "role": "target_action",
                "term": implication["canonical_action_query"],
            }
        )
        result["matched_context"] = {
            "match_type": match_type,
            "event_chain": event_chain,
            "explicit_after_term": after_term,
        }
        return result

    for implication in rules.get("action_sequence_implications", []):
        canonical_matches = matching_terms(
            normalized_player, implication.get("canonical_terms", [])
        )
        if canonical_matches:
            return matched_implication(
                implication,
                "canonical_term",
                after_term=canonical_matches[0],
            )
        before_matches = [
            (normalized_player.find(search_module.normalize(term)), term)
            for term in implication.get("before_terms", [])
            if search_module.normalize(term) in normalized_player
        ]
        after_matches = [
            (normalized_player.find(search_module.normalize(term)), term)
            for term in implication.get("after_terms", [])
            if search_module.normalize(term) in normalized_player
        ]
        opponent_response_matches = [
            term
            for group in implication.get("opponent_response_groups", [])
            for term in matching_terms(
                normalized_opponent, group.get("response_terms", [])
            )
        ]
        max_gap = implication.get("max_gap_characters", 12)
        for before_index, before_term in before_matches:
            before_end = before_index + len(search_module.normalize(before_term))
            for after_index, after_term in after_matches:
                if (
                    after_index >= before_end
                    and after_index - before_end <= max_gap
                ):
                    return matched_implication(
                        implication,
                        (
                            "opponent_response_with_explicit_target"
                            if opponent_response_matches
                            else "same_actor_explicit_sequence"
                        ),
                        before_term=before_term,
                        after_term=after_term,
                        opponent_response_term=(
                            opponent_response_matches[0]
                            if opponent_response_matches
                            else ""
                        ),
                    )

        if not before_matches or not normalized_opponent:
            continue
        for response_group in implication.get("opponent_response_groups", []):
            response_matches = matching_terms(
                normalized_opponent,
                response_group.get("response_terms", []),
            )
            symptom_matches = matching_terms(
                normalized_player,
                response_group.get("required_player_symptom_terms", []),
            )
            if response_matches and symptom_matches:
                return matched_implication(
                    implication,
                    "opponent_response_interruption",
                    before_term=before_matches[0][1],
                    opponent_response_term=response_matches[0],
                )
    return None


def _reception_symptom_implication(search_module, query, rules):
    actor_text = query_actor_text(query, rules)
    normalized_player = search_module.normalize(actor_text.get("player", ""))
    normalized_opponent = search_module.normalize(actor_text.get("opponent", ""))

    def matching_terms(normalized_text, terms):
        return [
            term
            for term in terms
            if search_module.normalize(term) in normalized_text
        ]

    def term_is_prior_player_action(term, implication):
        normalized_term = search_module.normalize(term)
        prefix_terms = implication.get(
            "player_action_prefixes_by_incoming_term", {}
        ).get(term, [])
        start = 0
        found = False
        while True:
            index = normalized_player.find(normalized_term, start)
            if index < 0:
                return found
            found = True
            prefix = normalized_player[:index]
            prefixed_as_action = any(
                prefix.endswith(search_module.normalize(item))
                for item in prefix_terms
            )
            suffix = normalized_player[index + len(normalized_term):]
            suffixed_as_action = any(
                suffix.startswith(search_module.normalize(item))
                for item in implication.get("prior_action_suffixes", [])
            )
            if not prefixed_as_action and not suffixed_as_action:
                return False
            start = index + 1

    for implication in rules.get("reception_symptom_implications", []):
        symptoms = matching_terms(
            normalized_player, implication.get("symptom_terms", [])
        )
        opponent_incoming = matching_terms(
            normalized_opponent, implication.get("incoming_terms", [])
        )
        player_incoming = [
            term
            for term in matching_terms(
                normalized_player, implication.get("incoming_terms", [])
            )
            if not term_is_prior_player_action(term, implication)
        ]
        incoming = opponent_incoming or player_incoming
        responses = matching_terms(
            normalized_player, implication.get("response_terms", [])
        )
        implicit_terms = {
            search_module.normalize(term)
            for term in implication.get("implicit_response_incoming_terms", [])
        }
        implicit_response = any(
            search_module.normalize(term) in implicit_terms for term in incoming
        )
        if symptoms and incoming and (responses or implicit_response):
            result = dict(implication)
            result["matched_context"] = {
                "match_type": (
                    "explicit_opponent_incoming"
                    if opponent_incoming
                    else "unmarked_incoming_condition"
                ),
                "incoming_term": incoming[0],
                "symptom_term": symptoms[0],
                "response_term": responses[0] if responses else "",
            }
            return result
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
        search_module, query, rules
    )
    if sequence_implication and target_actor == "player":
        action_query = sequence_implication["canonical_action_query"]
        normalized_target_query = search_module.normalize(target_query)
        has_symptom = any(
            search_module.normalize(term) in normalized_target_query
            for term in sequence_implication.get("symptom_terms", [])
        )
        matched_context = sequence_implication.get("matched_context", {})
        has_opponent_response = any(
            item.get("actor") == "opponent"
            for item in matched_context.get("event_chain", [])
        )
        action_constraints = _query_constraints_from_text(
            search_module, action_query, rules
        )
        for axis_name, values in sequence_implication.get(
            "derived_constraints", {}
        ).items():
            action_constraints[axis_name] = sorted(
                set(action_constraints.get(axis_name, [])) | set(values)
            )
        return {
            "target_action_query": action_query,
            "target_condition_query": (
                query if has_symptom or has_opponent_response else ""
            ),
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
            "event_chain": matched_context.get("event_chain", []),
            "condition_constraints_are_incoming": False,
            "retain_prior_player_constraints": sequence_implication.get(
                "retain_prior_player_constraints", True
            ),
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
            "event_chain": [
                {
                    "actor": "opponent_or_feed",
                    "role": "incoming_condition",
                    "term": reception_implication.get(
                        "matched_context", {}
                    ).get("incoming_term", ""),
                },
                {
                    "actor": "player",
                    "role": "target_action",
                    "term": action_query,
                },
            ],
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
            else (
                "partner_query_value_additions"
                if target_actor == "partner"
                else None
            )
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
    if "team_coverage_rotation" in requested_action_scopes:
        requested_action_scopes = [
            scope_name
            for scope_name in requested_action_scopes
            if scope_name != "positioning"
        ]
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
        "event_chain": [],
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
                else (
                    "partner_query_value_additions"
                    if actor == "partner"
                    else None
                )
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
    scope_by_name = {
        item["name"]: item
        for item in rules.get("target_action_scopes", [])
    }
    target_action_context["scope_boundary_statements"] = list(
        dict.fromkeys(
            statement
            for scope_name in target_action_context.get(
                "requested_action_scopes", []
            )
            for statement in [
                scope_by_name.get(scope_name, {}).get(
                    "answer_boundary_statement"
                )
            ]
            if statement
        )
    )
    if target_action_context.get("inferred_target_action"):
        if not target_action_context.get("retain_prior_player_constraints", True):
            actor_constraints[target_actor] = {}
            if target_actor == "player":
                player_constraints = actor_constraints[target_actor]
        target_actor_constraints = actor_constraints.setdefault(
            target_actor, {}
        )
        for axis_name, values in target_action_context.get(
            "target_action_constraints", {}
        ).items():
            target_actor_constraints[axis_name] = sorted(
                set(target_actor_constraints.get(axis_name, []))
                | set(values)
            )
        if target_actor == "player":
            player_constraints = target_actor_constraints
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
        and not target_action_context.get("condition_constraints_are_incoming")
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
    for axis_name, failure_reason in rules.get(
        "required_multi_value_constraint_support_axes", {}
    ).items():
        if (
            len(requested.get(axis_name, [])) > 1
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


def named_technique_comparison_focus_failures(
    search_module,
    query,
    requested,
    video,
    rules,
):
    if len(requested.get("technique_variant", [])) <= 1:
        return []
    normalized_query = search_module.normalize(query)
    support_text = search_module.normalize(
        " ".join(
            [
                primary_video_constraint_text(search_module, video),
                substantive_instruction_text(search_module, video, rules),
            ]
        )
    )
    requested_groups = [
        group
        for group in rules.get(
            "named_technique_comparison_focus_groups", []
        )
        if any(
            search_module.normalize(term) in normalized_query
            for term in group.get("query_terms", [])
        )
    ]
    if not requested_groups:
        return []
    if all(
        any(
            search_module.normalize(term) in support_text
            for term in group.get("source_terms", [])
        )
        for group in requested_groups
    ):
        return []
    return ["named_technique_comparison_focus_not_supported"]


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
