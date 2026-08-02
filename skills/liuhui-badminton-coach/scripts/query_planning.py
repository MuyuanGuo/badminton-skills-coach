#!/usr/bin/env python3
"""Lexical expansion, intent framing, and retrieval-query planning."""

import re

def build_lexicon(retrieval_index, rules):
    lexicon = {
        term
        for group in rules["synonym_groups"]
        for term in group
        if len(normalize(term)) >= 2
    }
    for group in rules.get("equivalent_groups", []):
        lexicon.update(term for term in group if len(normalize(term)) >= 2)
    for expansion in rules.get("directed_expansions", []):
        lexicon.update(expansion.get("query_terms", []))
        lexicon.update(expansion.get("expanded_terms", {}))
    intent_rules = rules.get("intent", {})
    for key in ["literal_symptom_terms", "scenario_terms", "level_terms"]:
        lexicon.update(intent_rules.get(key, []))
    for topic in retrieval_index["topics"]:
        lexicon.update(topic["keywords"])
        lexicon.add(topic["category"])
        lexicon.add(topic["subtopic"])
    return lexicon

def fallback_shards(query, rules):
    cleaned = query.lower()
    for phrase in rules["stop_phrases"]:
        cleaned = cleaned.replace(phrase.lower(), " ")
    shards = set(re.findall(r"[a-z0-9]{2,}", cleaned))
    for chunk in re.findall(r"[\u4e00-\u9fff]+", cleaned):
        if 2 <= len(chunk) <= 6:
            shards.add(chunk)
        for size in (2, 3, 4):
            for index in range(len(chunk) - size + 1):
                shard = chunk[index : index + size]
                if shard not in rules["stop_phrases"]:
                    shards.add(shard)
    return shards

def longest_non_overlapping_terms(text, terms):
    normalized = normalize(text)
    matches = []
    for term in terms:
        normalized_term = normalize(term)
        if not normalized_term:
            continue
        start = 0
        while True:
            index = normalized.find(normalized_term, start)
            if index < 0:
                break
            matches.append(
                {
                    "term": term,
                    "start": index,
                    "end": index + len(normalized_term),
                    "length": len(normalized_term),
                }
            )
            start = index + 1
    retained = []
    for match in matches:
        if any(
            other["length"] > match["length"]
            and other["start"] <= match["start"]
            and other["end"] >= match["end"]
            for other in matches
        ):
            continue
        retained.append(match)
    return [
        match["term"]
        for match in sorted(retained, key=lambda item: (item["start"], -item["length"]))
    ]

def extract_negative_scopes(query, rules):
    intent_rules = rules.get("intent", {})
    markers = sorted(intent_rules.get("negation_markers", []), key=len, reverse=True)
    contrasts = sorted(intent_rules.get("contrast_markers", []), key=len, reverse=True)
    if not markers:
        return query, []
    marker_patterns = []
    for marker in markers:
        escaped = re.escape(marker)
        if marker.startswith("不") and len(marker) > 1:
            escaped = rf"(?<!{re.escape(marker[1])}){escaped}"
        marker_patterns.append(escaped)
    marker_pattern = "|".join(marker_patterns)
    stop_parts = contrasts + ["，", ",", "。", "；", ";", "！", "!", "？", "?"]
    stop_pattern = "|".join(re.escape(part) for part in stop_parts)
    pattern = re.compile(
        rf"(?P<marker>{marker_pattern})\s*(?P<scope>.+?)(?=(?:{stop_pattern})|$)"
    )
    scope_records = []
    actor_markers = sorted(
        intent_rules.get("negated_scope_actor_markers", []),
        key=len,
        reverse=True,
    )
    postposed_markers = sorted(
        intent_rules.get("postposed_negation_markers", []),
        key=len,
        reverse=True,
    )
    if postposed_markers:
        postposed_pattern = re.compile(
            rf"(?P<scope>[^，,。；;！？!?]+?)\s*"
            rf"(?P<marker>{'|'.join(re.escape(item) for item in postposed_markers)})"
            rf"(?=(?:{stop_pattern})|$)"
        )
        for match in postposed_pattern.finditer(query):
            scope = match.group("scope").strip(" ，,。；;！？!?\t\n")
            if not scope:
                continue
            scope_records.append(
                {
                    "start": match.start(),
                    "end": match.end(),
                    "marker": match.group("marker"),
                    "text": scope,
                    "actor_markers": longest_non_overlapping_terms(
                        scope, actor_markers
                    ),
                }
            )
    for match in pattern.finditer(query):
        if any(
            record["start"] < match.end()
            and match.start() < record["end"]
            for record in scope_records
        ):
            continue
        scope = match.group("scope").strip(" ，,。；;！？!?\t\n")
        if not scope:
            continue
        scope_records.append(
            {
                "start": match.start(),
                "end": match.end(),
                "marker": match.group("marker"),
                "text": scope,
                "actor_markers": longest_non_overlapping_terms(
                    scope, actor_markers
                ),
            }
        )
    scope_records.sort(key=lambda item: item["start"])
    scopes = [
        {"marker": record["marker"], "text": record["text"]}
        for record in scope_records
    ]
    positive_query = query
    actor_query = query
    for record in reversed(scope_records):
        start = record["start"]
        end = record["end"]
        replacement = " ".join(record["actor_markers"])
        positive_query = positive_query[:start] + " " + positive_query[end:]
        actor_query = actor_query[:start] + f" {replacement} " + actor_query[end:]
    actor_query = re.sub(r"\s+", " ", actor_query).strip()
    positive_query = re.sub(r"[，,。；;！？!?]+", " ", positive_query)
    positive_query = re.sub(r"\s+", " ", positive_query).strip()
    return positive_query or query, actor_query or query, scopes

def requested_output(query, rules):
    normalized_query = normalize(query)
    intent_rules = rules.get("intent", {})
    direct_practice_request = any(
        normalize(term) in normalized_query
        for term in intent_rules.get("practice_request_terms", [])
    )
    scheduled_practice_request = (
        any(
            normalize(term) in normalized_query
            for term in intent_rules.get("practice_schedule_terms", [])
        )
        and any(
            normalize(term) in normalized_query
            for term in intent_rules.get("practice_context_terms", [])
        )
    )
    explicit_practice_plan_request = (
        any(
            normalize(term) in normalized_query
            for term in intent_rules.get("practice_plan_nouns", [])
        )
        and any(
            normalize(term) in normalized_query
            for term in intent_rules.get("practice_plan_request_terms", [])
        )
    )
    if (
        direct_practice_request
        or scheduled_practice_request
        or explicit_practice_plan_request
    ):
        return "practice"
    for label, key in [
        ("diagnosis", "diagnosis_request_terms"),
        ("comparison", "comparison_request_terms"),
    ]:
        matching_terms = [
            term
            for term in intent_rules.get(key, [])
            if normalize(term) in normalized_query
        ]
        if label == "comparison":
            suppressions = intent_rules.get(
                "comparison_request_term_suppressions", {}
            )
            matching_terms = [
                term
                for term in matching_terms
                if not any(
                    normalize(phrase) in normalized_query
                    for phrase in suppressions.get(term, [])
                )
            ]
        if matching_terms:
            return label
    return "coaching_answer"

def build_intent_frame(
    query,
    positive_query,
    actor_query,
    negative_scopes,
    lexicon,
    rules,
):
    positive_normalized = normalize(positive_query)
    intent_rules = rules.get("intent", {})
    excluded_seed_terms = set()
    for scope in negative_scopes:
        scope_normalized = normalize(scope["text"])
        excluded_seed_terms.update(
            term for term in lexicon if normalize(term) in scope_normalized
        )
        excluded_seed_terms.update(fallback_shards(scope["text"], rules))
    excluded_terms = set(excluded_seed_terms)
    for group in rules.get("equivalent_groups", []):
        if any(
            normalize(term) in {normalize(seed) for seed in excluded_seed_terms}
            for term in group
        ):
            excluded_terms.update(group)
    literal_symptoms = [
        term
        for term in intent_rules.get("literal_symptom_terms", [])
        if normalize(term) in positive_normalized
    ]
    scenarios = longest_non_overlapping_terms(
        positive_query, intent_rules.get("scenario_terms", [])
    )
    levels = [
        term
        for term in intent_rules.get("level_terms", [])
        if normalize(term) in positive_normalized
    ]
    return {
        "positive_query": positive_query,
        "actor_query": actor_query,
        "negative_scopes": negative_scopes,
        "excluded_seed_terms": sorted(excluded_seed_terms),
        "excluded_terms": sorted(excluded_terms),
        "literal_symptoms": literal_symptoms,
        "scenarios": scenarios,
        "levels": levels,
        "requested_output": requested_output(positive_query, rules),
    }
def expand_query(query, retrieval_index, rules):
    lexicon = build_lexicon(retrieval_index, rules)
    positive_query, actor_query, negative_scopes = extract_negative_scopes(
        query, rules
    )
    intent_frame = build_intent_frame(
        query,
        positive_query,
        actor_query,
        negative_scopes,
        lexicon,
        rules,
    )
    query_normalized = normalize(positive_query)
    original_terms = {
        term for term in lexicon if normalize(term) in query_normalized
    }
    scenario_normalized = {
        normalize(term) for term in intent_frame["scenarios"]
    }
    action_terms = [
        term
        for term in original_terms
        if normalize(term) not in scenario_normalized
    ]
    primary_terms = (
        [
            min(
                action_terms,
                key=lambda term: (
                    query_normalized.find(normalize(term)),
                    -len(normalize(term)),
                    term,
                ),
            )
        ]
        if action_terms
        else []
    )
    residual_query = positive_query
    for phrase in sorted(
        set(original_terms) | set(rules["stop_phrases"]), key=len, reverse=True
    ):
        residual_query = re.sub(re.escape(phrase), " ", residual_query, flags=re.I)
    query_shards = fallback_shards(residual_query, rules)
    query_shards.update(intent_frame["literal_symptoms"])
    excluded_normalized = {
        normalize(term) for term in intent_frame["excluded_terms"]
    }
    query_shards = {
        term for term in query_shards if normalize(term) not in excluded_normalized
    }
    focus_shards = set(intent_frame["literal_symptoms"]) or set(query_shards)

    synonym_terms = set()
    related_term_weights = {}
    matched_groups = []
    for group in rules["synonym_groups"]:
        if any(normalize(term) in query_normalized for term in group):
            matched_groups.append(group)
    for group in rules.get("equivalent_groups", []):
        if any(normalize(term) in query_normalized for term in group):
            synonym_terms.update(group)
    for directed in rules.get("directed_expansions", []):
        if not any(
            normalize(term) in query_normalized
            for term in directed.get("query_terms", [])
        ):
            continue
        if any(
            normalize(term) in query_normalized
            for term in directed.get("suppress_when_terms", [])
        ):
            continue
        for term, weight in directed.get("expanded_terms", {}).items():
            related_term_weights[term] = max(
                related_term_weights.get(term, 0), float(weight)
            )

    topic_matches = []
    seed_terms = original_terms | synonym_terms | set(related_term_weights) | query_shards
    seed_normalized = {normalize(term) for term in seed_terms}
    for topic in retrieval_index["topics"]:
        score = 0
        reasons = []
        if normalize(topic["subtopic"]) in query_normalized:
            score += 10
            reasons.append(topic["subtopic"])
        if normalize(topic["category"]) in query_normalized:
            score += 5
            reasons.append(topic["category"])
        for keyword in topic["keywords"]:
            keyword_normalized = normalize(keyword)
            if keyword_normalized in query_normalized:
                score += 8
                reasons.append(keyword)
            elif keyword_normalized in seed_normalized:
                score += 4
                reasons.append(keyword)
        if score:
            topic_matches.append(
                {
                    "topic_id": topic["topic_id"],
                    "category": topic["category"],
                    "subtopic": topic["subtopic"],
                    "keywords": topic["keywords"],
                    "score": score,
                    "reasons": sorted(set(reasons)),
                    "video_count": topic["video_count"],
                }
            )
    topic_matches.sort(
        key=lambda item: (-item["score"], item["video_count"], item["topic_id"])
    )
    if topic_matches:
        best_topic_score = topic_matches[0]["score"]
        topic_threshold = max(
            rules["retrieval"]["topic_min_score"],
            best_topic_score * rules["retrieval"]["topic_relative_score"],
        )
        topic_matches = [
            item for item in topic_matches if item["score"] >= topic_threshold
        ]
    topic_matches = topic_matches[: rules["retrieval"]["max_topics"]]
    topic_terms = {
        keyword for topic in topic_matches for keyword in topic["keywords"]
    }

    term_weights = {}
    for term in query_shards:
        shard_weight = 3.2 if term in intent_frame["literal_symptoms"] else 1.4
        term_weights[term] = max(term_weights.get(term, 0), shard_weight)
    for term in topic_terms:
        term_weights[term] = max(term_weights.get(term, 0), 0.55)
    for term, weight in related_term_weights.items():
        term_weights[term] = max(term_weights.get(term, 0), weight)
    for term in synonym_terms:
        term_weights[term] = max(term_weights.get(term, 0), 1.8)
    for term in original_terms:
        term_weights[term] = max(term_weights.get(term, 0), 3.5)

    matched_required_intents = []
    for group in rules.get("required_intent_groups", []):
        matched_terms = [
            term for term in group["terms"] if normalize(term) in query_normalized
        ]
        if not matched_terms:
            continue
        matched_required_intents.append(
            {
                "name": group["name"],
                "query_terms": matched_terms,
                "terms": group["terms"],
            }
        )
        for term in group["terms"]:
            term_weights[term] = max(term_weights.get(term, 0), 3.5)

    return {
        "positive_query": positive_query,
        "intent_frame": intent_frame,
        "original_terms": sorted(original_terms),
        "primary_terms": primary_terms,
        "query_shards": sorted(query_shards),
        "focus_shards": sorted(focus_shards),
        "synonym_terms": sorted(synonym_terms),
        "related_terms": [
            {"term": term, "weight": weight}
            for term, weight in sorted(related_term_weights.items())
        ],
        "topic_terms": sorted(topic_terms),
        "term_weights": term_weights,
        "matched_synonym_groups": matched_groups,
        "matched_required_intents": matched_required_intents,
        "matched_topics": topic_matches,
    }

def split_query_units(query, workflow_rules):
    separators = sorted(workflow_rules["multi_issue_separators"], key=len, reverse=True)
    pattern = "|".join(re.escape(separator) for separator in separators)
    units = [
        unit.strip(" ，,？?！!")
        for unit in re.split(pattern, query)
        if unit.strip(" ，,？?！!")
    ]
    if len(units) == 1:
        normalized_query = normalize(query)
        relational = any(
            normalize(signal) in normalized_query
            for signal in workflow_rules["relational_signals"]
        )
        if not relational:
            connectors = sorted(
                workflow_rules["multi_issue_connectors"], key=len, reverse=True
            )
            connector_pattern = "|".join(
                re.escape(connector) for connector in connectors
            )
            connector_units = [
                unit.strip(" ，,？?！!")
                for unit in re.split(connector_pattern, query)
                if unit.strip(" ，,？?！!")
            ]
            if len(connector_units) >= 2:
                units = connector_units
    return units or [query.strip()]

def build_query_plan(query, expansion, answer_rules=None):
    answer_rules = answer_rules or load_answer_rules()
    workflow_rules = answer_rules["workflow"]
    normalized_query = normalize(query)
    systematic_signals = [
        signal
        for signal in workflow_rules["systematic_signals"]
        if normalize(signal) in normalized_query
    ]
    diagnostic_signals = [
        signal
        for signal in workflow_rules["diagnostic_signals"]
        if normalize(signal) in normalized_query
    ]
    boundary_signals = [
        signal
        for signal in workflow_rules["boundary_signals"]
        if normalize(signal) in normalized_query
    ]
    units = split_query_units(query, workflow_rules)
    concept_count = len(expansion["matched_synonym_groups"])
    multi_issue = (
        len(units) >= 2
        and concept_count >= workflow_rules["minimum_multi_issue_concepts"]
    )

    if boundary_signals:
        strategy = "boundary_first"
        use_topic_navigation = False
        query_units = units if multi_issue else [query]
        require_exhaustive = concept_count > 0
        clarification_policy = (
            "state the applicable safety, purchase, attribution, or evidence boundary before coaching evidence; ask for professional help when risk is material"
        )
    elif systematic_signals:
        strategy = "topic_first_systematic"
        use_topic_navigation = True
        query_units = []
        require_exhaustive = True
        clarification_policy = (
            "use topic navigation to create focused module queries; do not send one broad corpus-wide query as the final evidence pass"
        )
    elif multi_issue:
        strategy = "split_multi_issue"
        use_topic_navigation = False
        query_units = units
        require_exhaustive = True
        clarification_policy = (
            "search every query unit independently, then merge and deduplicate videos while preserving conclusions by subproblem"
        )
    elif diagnostic_signals:
        strategy = "literal_symptom_first"
        use_topic_navigation = False
        query_units = [query]
        require_exhaustive = True
        clarification_policy = (
            "start with the user's exact failure wording; ask one scenario question only if competing causes would change the answer"
        )
    elif concept_count:
        strategy = "focused_evidence"
        use_topic_navigation = False
        query_units = [query]
        require_exhaustive = True
        clarification_policy = (
            "retrieve the focused concept directly and clarify only when the playing situation changes the recommendation"
        )
    elif (
        expansion["intent_frame"].get("scenarios")
        and expansion["intent_frame"].get("requested_output")
        in workflow_rules.get("scenario_focused_requested_outputs", [])
    ):
        strategy = "scenario_focused_evidence"
        use_topic_navigation = False
        query_units = [query]
        require_exhaustive = True
        clarification_policy = (
            "treat the stated side, court area, discipline, or tactical phase as a valid evidence scope; retrieve it exhaustively and clarify only which specific technique would materially change the answer"
        )
    else:
        strategy = "evidence_check"
        use_topic_navigation = False
        query_units = [query]
        require_exhaustive = False
        clarification_policy = (
            "run a bounded evidence check and say clearly when the Skill has no grounded answer; do not fill gaps with generic coaching"
        )

    return {
        "intent_frame": expansion["intent_frame"],
        "strategy": strategy,
        "use_topic_navigation": use_topic_navigation,
        "query_units": query_units,
        "first_recall_mode": "exhaustive" if require_exhaustive else "balanced",
        "require_exhaustive_completion": require_exhaustive,
        "must_state_boundary_first": bool(boundary_signals),
        "matched_workflow_signals": {
            "systematic": systematic_signals,
            "diagnostic": diagnostic_signals,
            "boundary": boundary_signals,
        },
        "clarification_policy": clarification_policy,
    }
