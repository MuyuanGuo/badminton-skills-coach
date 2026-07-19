#!/usr/bin/env python3
import argparse
import hashlib
import json
import math
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_PATH = ROOT / "references" / "knowledge-base.json"
RETRIEVAL_INDEX_PATH = ROOT / "references" / "retrieval-index.json"
RULES_PATH = ROOT / "references" / "retrieval-rules.json"
ANSWER_RULES_PATH = ROOT / "references" / "answer-modality-rules.json"
FEEDBACK_RULES_PATH = ROOT / "references" / "feedback-rules.json"
FEEDBACK_SIGNALS_PATH = ROOT / "references" / "feedback-signals.json"
SELECTION_SCRIPT_PATH = ROOT / "scripts" / "prepare_answer_context.py"

TIER_ORDER = {
    "direct": 0,
    "strong_related": 1,
    "topic_related": 2,
    "semantic_lead": 3,
}

DEFAULT_MANIFEST_LIMIT = object()
_SELECTION_MODULE = None
_SELECTION_RULES = None
_RESOURCE_CACHE = None
_VIDEO_CONSTRAINT_SCOPE_CACHE = {}


def flatten(value):
    if isinstance(value, dict):
        return " ".join(flatten(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(flatten(item) for item in value)
    return str(value or "")


def normalize(text):
    return "".join(re.findall(r"[\u4e00-\u9fff]+|[a-z0-9]+", text.lower()))


def load_answer_rules():
    return json.loads(ANSWER_RULES_PATH.read_text(encoding="utf-8"))


def load_selection_module():
    global _SELECTION_MODULE
    if _SELECTION_MODULE is None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "liuhui_retrieval_selection_policy", SELECTION_SCRIPT_PATH
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _SELECTION_MODULE = module
    return _SELECTION_MODULE


def load_selection_policy():
    global _SELECTION_RULES
    module = load_selection_module()
    if _SELECTION_RULES is None:
        _SELECTION_RULES = module.load_selection_rules()
    return module, _SELECTION_RULES


def classify_answer_mode(query, rules=None):
    rules = rules or load_answer_rules()
    query_normalized = normalize(query)
    scores = {}
    matched_signals = {}
    for mode, config in rules["modes"].items():
        matched = []
        score = 0.0
        for term, weight in config["signals"].items():
            if normalize(term) in query_normalized:
                matched.append(term)
                score += weight
        scores[mode] = score
        matched_signals[mode] = matched

    decisive_text = [
        term
        for term in rules["decision"]["decisive_text_terms"]
        if normalize(term) in query_normalized
    ]
    decisive_video = [
        term
        for term in rules["decision"]["decisive_video_terms"]
        if normalize(term) in query_normalized
    ]
    decisive_balanced = [
        term
        for term in rules["decision"].get("decisive_balanced_terms", [])
        if normalize(term) in query_normalized
    ]
    decisive_text_boundary = [
        term
        for term in rules["decision"].get("decisive_text_boundary_terms", [])
        if normalize(term) in query_normalized
    ]
    if decisive_text_boundary:
        mode = "text_primary"
        reason = "query_requires_a_safety_or_source_boundary_answer"
    elif decisive_balanced:
        mode = "balanced"
        reason = "query_requires_textual_explanation_and_visual_evidence_boundary"
    elif decisive_text and decisive_video:
        mode = "balanced"
        reason = "query_contains_both_textual_decision_and_visual_form_signals"
    elif decisive_video:
        mode = "video_primary"
        reason = "query_contains_visual_form_signal"
    elif decisive_text:
        mode = "text_primary"
        reason = "query_contains_textual_decision_signal"
    else:
        ranked_modes = sorted(scores, key=lambda item: (-scores[item], item))
        top_mode = ranked_modes[0]
        second_score = scores[ranked_modes[1]]
        if scores[top_mode] <= 0:
            mode = rules["default_mode"]
            reason = "no_mode_signal_defaulted_to_balanced"
        elif top_mode == "balanced":
            mode = "balanced"
            reason = "execution_and_demonstration_signals_dominate"
        elif scores[top_mode] - second_score >= rules["decision"]["minimum_score_margin"]:
            mode = top_mode
            reason = "one_mode_has_clear_score_margin"
        else:
            mode = "balanced"
            reason = "mixed_signals_without_clear_margin"

    config = rules["modes"][mode]
    return {
        "mode": mode,
        "label": config["label"],
        "reason": reason,
        "scores": scores,
        "matched_signals": matched_signals,
        "decisive_text_terms": decisive_text,
        "decisive_video_terms": decisive_video,
        "decisive_balanced_terms": decisive_balanced,
        "decisive_text_boundary_terms": decisive_text_boundary,
        "text_obligations": config["text_obligations"],
        "video_obligations": config["video_obligations"],
        "global_obligations": rules["global_obligations"],
    }


def ngram_hash(value):
    return hashlib.blake2b(value.encode("utf-8"), digest_size=6).hexdigest()


def hashed_ngrams(text, sizes):
    normalized = normalize(text)
    grams = set()
    for size in sizes:
        for index in range(len(normalized) - size + 1):
            grams.add(ngram_hash(normalized[index : index + size]))
    return grams


def load_resources():
    global _RESOURCE_CACHE
    if _RESOURCE_CACHE is None:
        _RESOURCE_CACHE = (
            json.loads(KNOWLEDGE_PATH.read_text(encoding="utf-8")),
            json.loads(RETRIEVAL_INDEX_PATH.read_text(encoding="utf-8")),
            json.loads(RULES_PATH.read_text(encoding="utf-8")),
        )
    return _RESOURCE_CACHE


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
    scopes = []
    spans = []
    for match in pattern.finditer(query):
        scope = match.group("scope").strip()
        if not scope:
            continue
        scopes.append({"marker": match.group("marker"), "text": scope})
        spans.append(match.span())
    actor_query = query
    for start, end in reversed(spans):
        actor_query = actor_query[:start] + " " + actor_query[end:]
    actor_query = re.sub(r"\s+", " ", actor_query).strip()
    positive_query = actor_query
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
        if any(
            normalize(term) in normalized_query
            for term in intent_rules.get(key, [])
        ):
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


def plan_query(query):
    _, retrieval_index, retrieval_rules = load_resources()
    answer_rules = load_answer_rules()
    expansion = expand_query(query, retrieval_index, retrieval_rules)
    return {
        "query": query,
        "answer_guidance": classify_answer_mode(query, answer_rules),
        "retrieval_guidance": build_query_plan(query, expansion, answer_rules),
        "query_expansion": {
            key: value for key, value in expansion.items() if key != "term_weights"
        },
    }


def load_feedback_rules():
    return json.loads(FEEDBACK_RULES_PATH.read_text(encoding="utf-8"))


def default_feedback_dir():
    override = os.environ.get("LIUHUI_FEEDBACK_DIR")
    if override:
        return Path(override).expanduser()
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    return codex_home / "feedback" / "liuhui-badminton-coach"


def character_grams(text, size=2):
    normalized = normalize(text)
    if len(normalized) <= size:
        return {normalized} if normalized else set()
    return {
        normalized[index : index + size]
        for index in range(len(normalized) - size + 1)
    }


def jaccard(left, right):
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def feedback_signature(query, expansion):
    terms = {
        normalize(term)
        for key in ["original_terms", "query_shards", "synonym_terms", "topic_terms"]
        for term in expansion[key]
        if normalize(term)
    }
    topics = {topic["topic_id"] for topic in expansion["matched_topics"]}
    frame = expansion["intent_frame"]
    primary_equivalents = set()
    for primary in expansion.get("primary_terms", []):
        normalized_primary = normalize(primary)
        primary_equivalents.add(normalized_primary)
    primary_equivalents.update(
        normalize(term) for term in expansion.get("synonym_terms", [])
    )
    return {
        "normalized": normalize(query),
        "terms": terms,
        "topics": topics,
        "character_grams": character_grams(query),
        "primary_terms": {
            term for term in primary_equivalents if term
        },
        "concepts": {
            normalize(group[0])
            for group in expansion.get("matched_synonym_groups", [])
            if group
        },
        "literal_symptoms": {
            normalize(term) for term in frame.get("literal_symptoms", [])
        },
        "scenarios": {
            normalize(term) for term in frame.get("scenarios", [])
        },
        "levels": {normalize(term) for term in frame.get("levels", [])},
        "excluded_terms": {
            normalize(term) for term in frame.get("excluded_terms", [])
        },
        "requested_output": frame.get("requested_output"),
    }


def feedback_query_match(
    current_signature,
    feedback_query,
    retrieval_index,
    retrieval_rules,
    feedback_rules=None,
):
    feedback_rules = feedback_rules or load_feedback_rules()
    feedback_expansion = expand_query(feedback_query, retrieval_index, retrieval_rules)
    feedback_signature_value = feedback_signature(feedback_query, feedback_expansion)
    if (
        current_signature["normalized"]
        and current_signature["normalized"] == feedback_signature_value["normalized"]
    ):
        return {
            "semantic_similarity": 1.0,
            "positive_similarity": 1.0,
            "strict_similarity": 1.0,
            "positive_compatible": True,
            "strict_compatible": True,
            "incompatibility_reasons": [],
        }
    term_score = jaccard(current_signature["terms"], feedback_signature_value["terms"])
    topic_score = jaccard(current_signature["topics"], feedback_signature_value["topics"])
    character_score = jaccard(
        current_signature["character_grams"],
        feedback_signature_value["character_grams"],
    )
    semantic_score = min(
        1.0, term_score * 0.55 + topic_score * 0.25 + character_score * 0.20
    )
    primary_score = jaccard(
        current_signature["primary_terms"],
        feedback_signature_value["primary_terms"],
    )
    concept_score = jaccard(
        current_signature["concepts"], feedback_signature_value["concepts"]
    )
    reasons = []
    for left, right in feedback_rules["personalization"].get(
        "scenario_conflicts", []
    ):
        normalized_left = normalize(left)
        normalized_right = normalize(right)
        if (
            normalized_left in current_signature["scenarios"]
            and normalized_right in feedback_signature_value["scenarios"]
        ) or (
            normalized_right in current_signature["scenarios"]
            and normalized_left in feedback_signature_value["scenarios"]
        ):
            reasons.append(f"scenario_conflict:{left}:{right}")
    if current_signature["excluded_terms"] & feedback_signature_value["terms"]:
        reasons.append("current_exclusion_conflicts_with_feedback_positive_intent")
    if feedback_signature_value["excluded_terms"] & current_signature["terms"]:
        reasons.append("feedback_exclusion_conflicts_with_current_positive_intent")

    primary_conflict = bool(
        current_signature["primary_terms"]
        and feedback_signature_value["primary_terms"]
        and primary_score == 0
    )
    if primary_conflict:
        reasons.append("primary_action_mismatch")
    positive_compatible = not reasons

    current_symptoms = current_signature["literal_symptoms"]
    feedback_symptoms = feedback_signature_value["literal_symptoms"]
    symptom_compatible = current_symptoms == feedback_symptoms
    if not symptom_compatible:
        reasons.append("literal_symptom_mismatch")
    scenario_compatible = (
        current_signature["scenarios"] == feedback_signature_value["scenarios"]
    )
    if not scenario_compatible:
        reasons.append("scenario_scope_mismatch")
    output_compatible = (
        current_signature["requested_output"]
        == feedback_signature_value["requested_output"]
    )
    if not output_compatible:
        reasons.append("requested_output_mismatch")
    exclusions_compatible = (
        current_signature["excluded_terms"]
        == feedback_signature_value["excluded_terms"]
    )
    if not exclusions_compatible:
        reasons.append("exclusion_scope_mismatch")
    strict_compatible = (
        positive_compatible
        and symptom_compatible
        and scenario_compatible
        and output_compatible
        and exclusions_compatible
        and (primary_score > 0 or concept_score > 0)
    )
    strict_score = (
        semantic_score * 0.55
        + primary_score * 0.25
        + concept_score * 0.10
        + (0.10 if symptom_compatible else 0.0)
    )
    return {
        "semantic_similarity": round(semantic_score, 4),
        "positive_similarity": round(
            semantic_score if positive_compatible else 0.0, 4
        ),
        "strict_similarity": round(
            strict_score if strict_compatible else 0.0, 4
        ),
        "positive_compatible": positive_compatible,
        "strict_compatible": strict_compatible,
        "incompatibility_reasons": sorted(set(reasons)),
    }


def feedback_query_similarity(
    current_signature,
    feedback_query,
    retrieval_index,
    retrieval_rules,
):
    """Backward-compatible positive similarity used by older integrations."""

    return feedback_query_match(
        current_signature,
        feedback_query,
        retrieval_index,
        retrieval_rules,
    )["positive_similarity"]


def load_global_feedback_records():
    if not FEEDBACK_SIGNALS_PATH.exists():
        return [], {"signal_count": 0, "updated_at": None}
    payload = json.loads(FEEDBACK_SIGNALS_PATH.read_text(encoding="utf-8"))
    return payload["signals"], {
        "signal_count": len(payload["signals"]),
        "updated_at": payload.get("updated_at"),
    }


def load_local_feedback_records(feedback_dir=None):
    queue_dir = Path(feedback_dir or default_feedback_dir()) / "queue"
    records = []
    stats = {
        "queue_file_count": 0,
        "accepted_record_count": 0,
        "usable_record_count": 0,
        "skipped_record_count": 0,
    }
    for path in sorted(queue_dir.glob("*.json")):
        stats["queue_file_count"] += 1
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            stats["skipped_record_count"] += 1
            continue
        if record.get("status") != "accepted":
            continue
        if record.get("source", {}).get("type") != "local":
            continue
        stats["accepted_record_count"] += 1
        if record.get("parser_warnings") or not record.get("question"):
            stats["skipped_record_count"] += 1
            continue
        records.append(record)
    stats["usable_record_count"] = len(records)
    return records, stats


def feedback_record_values(record, layer):
    if layer == "global":
        return {
            "record_id": record["signal_id"],
            "query": record["public_query"],
            "helpful_video_ids": record.get("helpful_video_ids", []),
            "irrelevant_video_ids": record.get("irrelevant_video_ids", []),
            "missing_video_ids": record.get("missing_video_ids", []),
            "text_issue_types": record.get("answer_issue_types", []),
            "intended_query": record.get("intended_query"),
            "source_issue_video_ids": record.get("source_issue_video_ids", []),
            "outcome": None,
        }
    signals = record.get("signals", {})
    return {
        "record_id": record["feedback_id"],
        "query": record["question"],
        "helpful_video_ids": signals.get("helpful_video_ids", []),
        "irrelevant_video_ids": signals.get("irrelevant_video_ids", []),
        "missing_video_ids": signals.get("missing_video_ids", []),
        "text_issue_types": signals.get("text_issue_types", []),
        "intended_query": signals.get("intended_query"),
        "source_issue_video_ids": signals.get("source_issue_video_ids", []),
        "outcome": signals.get("outcome"),
    }


def build_feedback_adjustments(
    layer,
    records,
    current_signature,
    retrieval_index,
    retrieval_rules,
    feedback_rules,
):
    config = feedback_rules["personalization"]
    weights = config["weights"]
    positive_threshold = config["query_similarity_threshold"]
    strict_threshold = config["strict_intent_similarity_threshold"]
    strict_issue_types = set(config.get("strict_signal_types", [])) - {
        "irrelevant_video"
    }
    adjustments = defaultdict(
        lambda: {
            "delta": 0.0,
            "positive_strength": 0.0,
            "negative_strength": 0.0,
            "max_positive_similarity": 0.0,
            "max_negative_similarity": 0.0,
            "record_ids": set(),
            "reasons": set(),
        }
    )
    matched_ids = []
    strict_matched_ids = []
    reminders = set()
    for record in records:
        values = feedback_record_values(record, layer)
        query_match = feedback_query_match(
            current_signature,
            values["query"],
            retrieval_index,
            retrieval_rules,
            feedback_rules,
        )
        positive_similarity = query_match["positive_similarity"]
        strict_similarity = query_match["strict_similarity"]
        positive_match = positive_similarity >= positive_threshold
        strict_match = strict_similarity >= strict_threshold
        broad_issue_types = set(values["text_issue_types"]) - strict_issue_types
        has_positive_signals = bool(
            values["helpful_video_ids"]
            or values["missing_video_ids"]
            or broad_issue_types
            or values["outcome"] in {"unresolved"}
        )
        has_strict_signals = bool(
            values["irrelevant_video_ids"]
            or set(values["text_issue_types"]) & strict_issue_types
            or values["intended_query"]
            or values["source_issue_video_ids"]
            or values["outcome"] == "misunderstood"
        )
        record_matched = (
            positive_match and has_positive_signals
        ) or (strict_match and has_strict_signals)
        if not record_matched:
            continue
        matched_ids.append(values["record_id"])
        if strict_match:
            strict_matched_ids.append(values["record_id"])
        if positive_match:
            reminders.update(broad_issue_types)
        if strict_match:
            reminders.update(set(values["text_issue_types"]) & strict_issue_types)
        if positive_match and values["outcome"] == "unresolved":
            reminders.add("hard_to_apply")
        elif strict_match and values["outcome"] == "misunderstood":
            reminders.add("question_misunderstood")

        helpful_ids = set(values["helpful_video_ids"])
        missing_ids = set(values["missing_video_ids"]) - helpful_ids
        signal_groups = [
            (
                helpful_ids if positive_match else set(),
                weights[f"{layer}_helpful"],
                "helpful",
                positive_similarity,
            ),
            (
                missing_ids if positive_match else set(),
                weights[f"{layer}_missing"],
                "missing",
                positive_similarity,
            ),
            (
                set(values["irrelevant_video_ids"]) if strict_match else set(),
                weights[f"{layer}_irrelevant"],
                "irrelevant",
                strict_similarity,
            ),
        ]
        for video_ids, weight, reason, similarity in signal_groups:
            for video_id in video_ids:
                adjustment = adjustments[video_id]
                weighted_delta = similarity * weight
                adjustment["delta"] += weighted_delta
                adjustment["record_ids"].add(values["record_id"])
                adjustment["reasons"].add(reason)
                if weight > 0:
                    adjustment["positive_strength"] += abs(weighted_delta)
                    adjustment["max_positive_similarity"] = max(
                        adjustment["max_positive_similarity"], similarity
                    )
                else:
                    adjustment["negative_strength"] += abs(weighted_delta)
                    adjustment["max_negative_similarity"] = max(
                        adjustment["max_negative_similarity"], similarity
                    )

    max_delta = config["max_abs_delta_per_layer"]
    for adjustment in adjustments.values():
        adjustment["delta"] = max(-max_delta, min(max_delta, adjustment["delta"]))
        adjustment["record_ids"] = sorted(adjustment["record_ids"])
        adjustment["reasons"] = sorted(adjustment["reasons"])
    return (
        dict(adjustments),
        sorted(matched_ids),
        sorted(strict_matched_ids),
        sorted(reminders),
    )


def matched_feedback_corrections(records, layer, matched_record_ids):
    matched = set(matched_record_ids)
    corrections = []
    for record in records:
        values = feedback_record_values(record, layer)
        if values["record_id"] not in matched:
            continue
        if values["intended_query"] or values["source_issue_video_ids"]:
            corrections.append(
                {
                    "record_id": values["record_id"],
                    "intended_query": values["intended_query"],
                    "source_issue_video_ids": values["source_issue_video_ids"],
                }
            )
    return corrections


def local_answer_preferences(
    records,
    matched_reminders,
    public_reminders,
    feedback_rules,
    matched_corrections=None,
):
    issue_counts = Counter(
        issue_type
        for record in records
        for issue_type in record.get("signals", {}).get("text_issue_types", [])
    )
    outcome_counts = Counter(
        record.get("signals", {}).get("outcome")
        for record in records
        if record.get("signals", {}).get("outcome")
    )
    minimum = feedback_rules["personalization"]["local_preference_min_count"]
    concise_count = issue_counts["too_verbose"]
    detailed_count = sum(
        issue_counts[issue_type]
        for issue_type in ["missing_content", "too_vague", "hard_to_apply"]
    )
    if concise_count >= minimum and concise_count > detailed_count:
        verbosity = "concise"
    elif detailed_count >= minimum and detailed_count > concise_count:
        verbosity = "detailed"
    else:
        verbosity = "default"
    reminders = sorted(set(matched_reminders) | set(public_reminders))
    matched_corrections = matched_corrections or []
    query_replan_hints = list(
        dict.fromkeys(
            item["intended_query"]
            for item in matched_corrections
            if item.get("intended_query")
        )
    )
    source_recheck_video_ids = list(
        dict.fromkeys(
            video_id
            for item in matched_corrections
            for video_id in item.get("source_issue_video_ids", [])
        )
    )
    source_issue_types = {
        "transcript_error",
        "video_misinterpreted",
        "citation_mismatch",
    }
    return {
        "preferred_verbosity": verbosity,
        "query_reminders": reminders,
        "needs_query_replan": "question_misunderstood" in reminders,
        "query_replan_hints": query_replan_hints,
        "needs_source_recheck": bool(source_issue_types.intersection(reminders)),
        "source_recheck_video_ids": source_recheck_video_ids,
        "needs_more_boundaries": (
            "scenario_mismatch" in reminders
            or "question_misunderstood" in reminders
            or issue_counts["scenario_mismatch"] >= minimum
            or outcome_counts["misunderstood"] >= minimum
        ),
        "needs_more_action_steps": (
            "hard_to_apply" in reminders
            or issue_counts["hard_to_apply"] >= minimum
            or outcome_counts["unresolved"] >= minimum
        ),
        "preference_evidence_counts": {
            "too_verbose": concise_count,
            "detail_needed": detailed_count,
            "scenario_mismatch": issue_counts["scenario_mismatch"],
            "question_misunderstood": issue_counts["question_misunderstood"],
            "unresolved": outcome_counts["unresolved"],
        },
    }


def feedback_only_candidate(video):
    return {
        "score": 0.0,
        "relevance_tier": "strong_related",
        "intrinsic_relevance_tier": "strong_related",
        "retrieval_channels": [],
        "matched_query_concepts": [],
        "matched_structured_query_concepts": [],
        "matched_original_terms": [],
        "matched_equivalent_terms": [],
        "matched_terms": [],
        "matched_fields": {},
        "matched_topics": [],
        "matched_topic_details": [],
        "matched_required_intents": [],
        "required_intent_miss_count": 0,
        "matched_excluded_terms": [],
        "matched_excluded_seed_terms": [],
        "excluded_query_penalty": 0.0,
        "transcript_ngram_coverage": 0.0,
        "ngram_match": False,
        "ngram_coverage_by_field": {},
        "score_breakdown": {
            "structured_field_score": 0.0,
            "topic_score": 0.0,
            "ngram_score": 0.0,
            "exact_focus_score": 0.0,
            "matched_concept_score": 0.0,
            "evidence_quality_bonus": 0.0,
            "base_score_before_feedback": 0.0,
        },
        "video_id": video["video_id"],
        "title": video["title"],
        "category": video["category"],
        "confidence": video["confidence"],
        "processing_status": video["processing_status"],
        "url": video["url"],
    }


def apply_feedback_layers(
    query,
    ranked,
    expansion,
    knowledge,
    retrieval_index,
    retrieval_rules,
    local_personalization=True,
    feedback_dir=None,
):
    feedback_rules = load_feedback_rules()
    current_signature = feedback_signature(query, expansion)
    global_records, global_stats = load_global_feedback_records()
    (
        global_adjustments,
        global_matches,
        global_strict_matches,
        public_reminders,
    ) = build_feedback_adjustments(
        "global",
        global_records,
        current_signature,
        retrieval_index,
        retrieval_rules,
        feedback_rules,
    )
    global_corrections = matched_feedback_corrections(
        global_records, "global", global_strict_matches
    )
    if local_personalization:
        local_records, local_stats = load_local_feedback_records(feedback_dir)
        (
            local_adjustments,
            local_matches,
            local_strict_matches,
            local_reminders,
        ) = build_feedback_adjustments(
            "local",
            local_records,
            current_signature,
            retrieval_index,
            retrieval_rules,
            feedback_rules,
        )
        local_corrections = matched_feedback_corrections(
            local_records, "local", local_strict_matches
        )
    else:
        local_records = []
        local_adjustments = {}
        local_matches = []
        local_strict_matches = []
        local_reminders = []
        local_corrections = []
        local_stats = {
            "queue_file_count": 0,
            "accepted_record_count": 0,
            "usable_record_count": 0,
            "skipped_record_count": 0,
        }

    videos = {
        video["video_id"]: video
        for video in knowledge["videos"]
        if video["processing_status"] == "ready"
    }
    candidates = {item["video_id"]: dict(item) for item in ranked}
    adjusted_video_ids = set(global_adjustments) | set(local_adjustments)
    exact_threshold = feedback_rules["personalization"]["exact_query_threshold"]
    applied = []
    for video_id in adjusted_video_ids:
        global_value = global_adjustments.get(video_id)
        local_value = local_adjustments.get(video_id)
        global_delta = global_value["delta"] if global_value else 0.0
        local_delta = local_value["delta"] if local_value else 0.0
        total_delta = global_delta + local_delta
        candidate = candidates.get(video_id)
        if candidate is None:
            if total_delta <= 0 or video_id not in videos:
                continue
            candidate = feedback_only_candidate(videos[video_id])
            candidates[video_id] = candidate

        original_tier = candidate["relevance_tier"]
        original_score = candidate["score"]
        tier_decided = False
        for value in [local_value, global_value]:
            if not value:
                continue
            if (
                value["negative_strength"] > value["positive_strength"]
                and value["max_negative_similarity"] >= exact_threshold
            ):
                candidate["relevance_tier"] = "semantic_lead"
                tier_decided = True
                break
            if (
                value["positive_strength"] > value["negative_strength"]
                and value["max_positive_similarity"] >= exact_threshold
            ):
                candidate["relevance_tier"] = "direct"
                tier_decided = True
                break
        if (
            not tier_decided
            and total_delta > 0
            and TIER_ORDER[candidate["relevance_tier"]] > TIER_ORDER["strong_related"]
        ):
            candidate["relevance_tier"] = "strong_related"

        sources = []
        signal_ids = []
        reasons = []
        if global_value:
            sources.append("global_promoted_feedback")
            signal_ids.extend(global_value["record_ids"])
            reasons.extend(f"global_{reason}" for reason in global_value["reasons"])
            candidate["retrieval_channels"] = sorted(
                set(candidate["retrieval_channels"]) | {"global_promoted_feedback"}
            )
        if local_value:
            sources.append("local_accepted_feedback")
            signal_ids.extend(local_value["record_ids"])
            reasons.extend(f"local_{reason}" for reason in local_value["reasons"])
            candidate["retrieval_channels"] = sorted(
                set(candidate["retrieval_channels"]) | {"local_accepted_feedback"}
            )
        candidate["score"] = round(original_score + total_delta, 4)
        candidate["feedback_adjustment"] = {
            "score_delta": round(total_delta, 4),
            "global_delta": round(global_delta, 4),
            "local_delta": round(local_delta, 4),
            "sources": sources,
            "signal_ids": sorted(set(signal_ids)),
            "reasons": sorted(set(reasons)),
            "original_tier": original_tier,
            "adjusted_tier": candidate["relevance_tier"],
        }
        refresh_score_breakdown(candidate, retrieval_rules)
        applied.append(
            {
                "video_id": video_id,
                **candidate["feedback_adjustment"],
            }
        )

    reranked = list(candidates.values())
    reranked.sort(key=lambda item: candidate_sort_key(item, retrieval_rules))
    assign_review_budget(
        reranked,
        len(expansion["matched_synonym_groups"]),
        retrieval_rules,
    )
    answer_preferences = local_answer_preferences(
        local_records,
        local_reminders,
        public_reminders,
        feedback_rules,
        matched_corrections=global_corrections + local_corrections,
    )
    guidance = {
        "global": {
            **global_stats,
            "matched_signal_count": len(global_matches),
            "matched_signal_ids": global_matches,
            "strict_intent_match_count": len(global_strict_matches),
        },
        "local": {
            "enabled": bool(local_personalization),
            **local_stats,
            "matched_feedback_count": len(local_matches),
            "matched_feedback_ids": local_matches,
            "strict_intent_match_count": len(local_strict_matches),
        },
        "applied_video_adjustments": sorted(
            applied,
            key=lambda item: (-abs(item["score_delta"]), item["video_id"]),
        ),
        "answer_preferences": answer_preferences,
        "guardrails": [
            "feedback_changes_ranking_and_answer_presentation_only",
            "feedback_never_overrides_source_evidence",
            "negative_feedback_remains_in_exhaustive_manifest",
            "only_accepted_local_and_promoted_global_feedback_is_used",
        ],
    }
    return reranked, guidance


def field_values(video):
    return {
        "title": video.get("retrieval_title") or video["title"],
        "teaching_note": flatten(video["teaching_note"]),
    }


def match_fields(video, term_weights, field_weights):
    matched_fields = {}
    matched_terms = set()
    score = 0.0
    for field, value in field_values(video).items():
        normalized_value = normalize(value)
        field_terms = []
        for term, weight in term_weights.items():
            normalized_term = normalize(term)
            if normalized_term and normalized_term in normalized_value:
                occurrences = min(normalized_value.count(normalized_term), 3)
                score += weight * field_weights[field] * occurrences
                matched_terms.add(term)
                field_terms.append(term)
        if field_terms:
            matched_fields[field] = sorted(set(field_terms))
    return score, sorted(matched_terms), matched_fields


def dynamic_term_statistics(knowledge, terms):
    terms = {term for term in terms if normalize(term)}
    document_frequency = Counter()
    by_video = {}
    if not terms:
        return document_frequency, by_video
    for video in knowledge["videos"]:
        if video.get("processing_status") != "ready":
            continue
        field_text = {
            "title": normalize(video.get("retrieval_title") or video["title"]),
            "teaching_note": normalize(flatten(video["teaching_note"])),
            "transcript": normalize(
                "".join(
                    segment.get("text", "")
                    for segment in video.get("transcript_segments", [])
                )
            ),
        }
        video_frequencies = {}
        video_terms = set()
        for field, text_value in field_text.items():
            frequencies = {
                term: text_value.count(normalize(term))
                for term in terms
                if normalize(term) in text_value
            }
            if frequencies:
                video_frequencies[field] = frequencies
                video_terms.update(frequencies)
        if video_frequencies:
            by_video[video["video_id"]] = video_frequencies
            document_frequency.update(video_terms)
    return document_frequency, by_video


def bm25_record_fields(
    record,
    term_weights,
    retrieval_index,
    rules,
    dynamic_document_frequency=None,
    dynamic_field_frequencies=None,
):
    document_count = max(1, retrieval_index["indexable_video_count"])
    document_frequency = dict(retrieval_index.get("term_document_frequency", {}))
    document_frequency.update(dynamic_document_frequency or {})
    average_lengths = retrieval_index.get("average_field_lengths", {})
    k1 = rules["retrieval"].get("bm25_k1", 1.2)
    b = rules["retrieval"].get("bm25_b", 0.75)
    matched_fields = {}
    matched_terms = set()
    score = 0.0
    for field, field_weight in rules["field_weights"].items():
        frequencies = record.get("field_term_frequencies", {}).get(field, {})
        frequencies = {
            **frequencies,
            **(dynamic_field_frequencies or {}).get(field, {}),
        }
        document_length = record.get("field_lengths", {}).get(field, 0)
        average_length = max(1.0, average_lengths.get(field, 1.0))
        field_matches = []
        for term, query_weight in term_weights.items():
            frequency = frequencies.get(term, 0)
            if frequency <= 0:
                continue
            frequency = min(frequency, 8)
            frequency_normalized = (
                frequency * (k1 + 1)
                / (
                    frequency
                    + k1 * (1 - b + b * document_length / average_length)
                )
            )
            df = document_frequency.get(term, 0)
            inverse_frequency = math.log(
                1 + (document_count - df + 0.5) / (df + 0.5)
            )
            score += (
                query_weight
                * field_weight
                * inverse_frequency
                * frequency_normalized
            )
            matched_terms.add(term)
            field_matches.append(term)
        if field_matches:
            matched_fields[field] = sorted(field_matches)
    return score, sorted(matched_terms), matched_fields


def choose_tier(
    original_matches,
    matched_concepts,
    query_concept_count,
    expanded_matches,
    matched_topics,
    ngram_match,
    title_concept_count,
    title_matches,
    required_intent_count,
    matched_required_intent_count,
):
    if required_intent_count > matched_required_intent_count:
        return "semantic_lead" if ngram_match else "topic_related"

    required_concepts = min(2, query_concept_count) if query_concept_count else 0
    if query_concept_count and title_concept_count >= required_concepts:
        return "direct"
    if not query_concept_count and set(title_matches) & set(original_matches):
        return "direct"
    if query_concept_count and len(matched_concepts) >= required_concepts:
        return "strong_related"
    if title_matches:
        return "strong_related"
    if len(original_matches) >= max(1, required_concepts):
        return "strong_related"
    if expanded_matches and matched_topics:
        return "topic_related"
    if expanded_matches:
        return "topic_related"
    if matched_topics:
        return "topic_related"
    if ngram_match:
        return "semantic_lead"
    return None


def candidate_sort_key(candidate, rules):
    tier_bonus = rules["retrieval"]["tier_score_bonus"]
    intent_penalty = (
        candidate.get("required_intent_miss_count", 0)
        * rules["retrieval"]["required_intent_miss_penalty"]
    )
    ranking_score = (
        candidate["score"]
        + tier_bonus[candidate["relevance_tier"]]
        - intent_penalty
        - candidate.get("excluded_query_penalty", 0)
    )
    return (-ranking_score, TIER_ORDER[candidate["relevance_tier"]], candidate["title"])


def refresh_score_breakdown(candidate, rules):
    """Keep the displayed score explanation aligned with the actual sort key."""

    breakdown = dict(candidate.get("score_breakdown") or {})
    feedback_delta = (candidate.get("feedback_adjustment") or {}).get(
        "score_delta", 0.0
    )
    tier_bonus = rules["retrieval"]["tier_score_bonus"][
        candidate["relevance_tier"]
    ]
    required_intent_penalty = (
        candidate.get("required_intent_miss_count", 0)
        * rules["retrieval"]["required_intent_miss_penalty"]
    )
    excluded_query_penalty = candidate.get("excluded_query_penalty", 0.0)
    breakdown.update(
        {
            "feedback_adjustment": round(feedback_delta, 4),
            "score_after_feedback": round(candidate["score"], 4),
            "tier_bonus": round(tier_bonus, 4),
            "required_intent_penalty": round(required_intent_penalty, 4),
            "excluded_query_penalty": round(excluded_query_penalty, 4),
            "effective_ranking_score": round(
                candidate["score"]
                + tier_bonus
                - required_intent_penalty
                - excluded_query_penalty,
                4,
            ),
        }
    )
    candidate["score_breakdown"] = breakdown


def assign_review_budget(ranked, query_concept_count, rules):
    retrieval = rules["retrieval"]
    limit = (
        retrieval["single_concept_review_limit"]
        if query_concept_count <= 1
        else retrieval["multi_concept_review_limit"]
    )
    review_rank = 0
    for candidate in ranked:
        candidate.setdefault(
            "intrinsic_relevance_tier", candidate["relevance_tier"]
        )
        if candidate.get("retrieval_policy_eligible") is False:
            candidate["review_rank"] = None
            candidate["within_review_budget"] = False
            candidate["review_priority"] = "policy_rejected"
            continue
        if candidate["relevance_tier"] not in {"direct", "strong_related"}:
            candidate["review_rank"] = None
            candidate["within_review_budget"] = False
            candidate["review_priority"] = "recall_safeguard"
            continue
        review_rank += 1
        candidate["review_rank"] = review_rank
        candidate["within_review_budget"] = review_rank <= limit
        candidate["review_priority"] = (
            "priority_review" if review_rank <= limit else "deferred_review"
        )


def rank_candidates(query, knowledge, retrieval_index, rules, mode="hybrid"):
    expansion = expand_query(query, retrieval_index, rules)
    selection_module, selection_rules = load_selection_policy()
    boundary = selection_module.classify_boundary(
        expansion["positive_query"], selection_rules
    )
    if boundary["type"] != "none":
        # Boundary language is an answer constraint, not a technical focus signal.
        expansion["focus_shards"] = []
    records = {item["video_id"]: item for item in retrieval_index["videos"]}
    topic_ids = {item["topic_id"] for item in expansion["matched_topics"]}
    original_terms = set(expansion["original_terms"])
    equivalent_terms = set(expansion["synonym_terms"])
    expanded_terms = set(expansion["term_weights"])
    matched_groups = expansion["matched_synonym_groups"]
    required_intents = expansion["matched_required_intents"]
    topic_details_by_id = {
        item["topic_id"]: {
            "topic_id": item["topic_id"],
            "category": item["category"],
            "subtopic": item["subtopic"],
            "query_match_reasons": item["reasons"],
        }
        for item in expansion["matched_topics"]
    }

    cleaned_query = expansion["positive_query"]
    for phrase in rules["stop_phrases"]:
        cleaned_query = cleaned_query.replace(phrase, " ")
    query_grams = hashed_ngrams(
        cleaned_query,
        retrieval_index["transcript_ngram_sizes"],
    )
    min_shared = rules["retrieval"]["transcript_ngram_min_shared"]
    min_coverage = rules["retrieval"]["transcript_ngram_min_query_coverage"]
    record_gram_sets = {
        video_id: {
            "title": set(record.get("title_ngrams", [])),
            "teaching_note": set(record.get("teaching_note_ngrams", [])),
            "transcript": set(record["transcript_ngrams"]),
        }
        for video_id, record in records.items()
    }
    query_gram_document_frequency = Counter(
        gram
        for gram in query_grams
        for channel_sets in record_gram_sets.values()
        if any(gram in values for values in channel_sets.values())
    )
    query_gram_weights = {
        gram: math.log(
            1
            + (retrieval_index["indexable_video_count"] + 1)
            / (query_gram_document_frequency.get(gram, 0) + 1)
        )
        for gram in query_grams
    }
    total_query_gram_weight = sum(query_gram_weights.values())
    dynamic_terms = set(expansion["term_weights"]) - set(
        retrieval_index.get("term_document_frequency", {})
    )
    dynamic_document_frequency, dynamic_frequencies_by_video = (
        dynamic_term_statistics(knowledge, dynamic_terms)
    )

    ranked = []
    for video in knowledge["videos"]:
        if video["processing_status"] in {"not_teaching", "low_value"}:
            continue
        record = records.get(video["video_id"])
        if not record:
            continue
        field_score, field_terms, matched_fields = bm25_record_fields(
            record,
            expansion["term_weights"],
            retrieval_index,
            rules,
            dynamic_document_frequency=dynamic_document_frequency,
            dynamic_field_frequencies=dynamic_frequencies_by_video.get(
                video["video_id"], {}
            ),
        )
        transcript_terms = set(record["lexicon_terms"]) & expanded_terms
        matched_topic_ids = sorted(set(record["topic_ids"]) & topic_ids)
        topic_score = len(matched_topic_ids) * 2.0
        title_focus_length = max(
            [
                len(normalize(term))
                for term in matched_fields.get("title", [])
                if term in expansion["focus_shards"]
            ]
            or [0]
        )
        note_focus_length = max(
            [
                len(normalize(term))
                for term in matched_fields.get("teaching_note", [])
                if term in expansion["focus_shards"]
            ]
            or [0]
        )
        focus_score = (
            min(title_focus_length, 3)
            * rules["retrieval"].get(
                "exact_focus_title_bonus_per_character", 0
            )
            + min(note_focus_length, 3)
            * rules["retrieval"].get("exact_focus_note_bonus_per_character", 0)
        )

        channel_shared_grams = {
            channel: query_grams & values
            for channel, values in record_gram_sets[video["video_id"]].items()
        }
        channel_ngram_coverage = {
            channel: (
                sum(query_gram_weights[gram] for gram in shared)
                / max(1.0, total_query_gram_weight)
            )
            for channel, shared in channel_shared_grams.items()
        }
        shared_grams = set().union(*channel_shared_grams.values())
        ngram_coverage = max(channel_ngram_coverage.values(), default=0.0)
        required_shared = 1 if len(query_grams) <= 2 else min_shared
        ngram_match = (
            len(shared_grams) >= required_shared and ngram_coverage >= min_coverage
        )
        ngram_score = (
            channel_ngram_coverage["title"] * 24
            + channel_ngram_coverage["teaching_note"] * 14
            + channel_ngram_coverage["transcript"] * 8
            if ngram_match
            else 0.0
        )

        if mode == "keyword":
            ngram_match = False
            ngram_score = 0.0
        elif mode == "semantic":
            field_score = 0.0
            topic_score = 0.0
            matched_fields = {}
            field_terms = []
            transcript_terms = set()
            matched_topic_ids = []

        original_matches = sorted(
            (set(field_terms) | transcript_terms) & original_terms
        )
        equivalent_matches = sorted(
            ((set(field_terms) | transcript_terms) & equivalent_terms)
            - set(original_matches)
        )
        direct_matches = sorted(set(original_matches) | set(equivalent_matches))
        expanded_matches = sorted(set(field_terms) | transcript_terms)
        candidate_lexicon_terms = set(record["lexicon_terms"]) | set(field_terms)
        matched_concepts = sorted(
            {
                group[0]
                for group in matched_groups
                if any(term in candidate_lexicon_terms for term in group)
            }
        )
        structured_terms = set(matched_fields.get("title", [])) | set(
            matched_fields.get("teaching_note", [])
        )
        matched_structured_concepts = sorted(
            {
                group[0]
                for group in matched_groups
                if any(term in structured_terms for term in group)
            }
        )
        title_terms = set(matched_fields.get("title", []))
        strong_title_related = {
            term
            for term in title_terms
            if any(
                item["term"] == term and item["weight"] >= 0.45
                for item in expansion["related_terms"]
            )
        }
        title_concepts = {
            group[0]
            for group in matched_groups
            if any(term in title_terms for term in group)
        }
        matched_required_intents = sorted(
            intent["name"]
            for intent in required_intents
            if any(term in expanded_matches for term in intent["terms"])
        )
        candidate_searchable = normalize(
            flatten(
                {
                    "title": video["title"],
                    "teaching_note": video["teaching_note"],
                }
            )
        )
        excluded_matches = sorted(
            term
            for term in expansion["intent_frame"]["excluded_terms"]
            if normalize(term)
            and (
                normalize(term) in candidate_searchable
                or term in set(record["lexicon_terms"])
            )
        )
        excluded_seed_matches = sorted(
            term
            for term in expansion["intent_frame"]["excluded_seed_terms"]
            if normalize(term)
            and (
                normalize(term) in candidate_searchable
                or term in set(record["lexicon_terms"])
            )
        )
        expanded_only_matches = set(excluded_matches) - set(excluded_seed_matches)
        excluded_query_penalty = (
            min(3, len(excluded_seed_matches))
            * rules["retrieval"].get("excluded_query_term_penalty", 0)
            + min(3, len(expanded_only_matches))
            * rules["retrieval"].get("excluded_related_term_penalty", 0)
        )
        if (
            topic_ids
            and not matched_topic_ids
            and len(matched_concepts) < 2
            and len(original_matches) < 2
            and not equivalent_matches
            and not strong_title_related
            and not ngram_match
        ):
            continue
        tier = choose_tier(
            direct_matches,
            matched_concepts,
            len(matched_groups),
            expanded_matches,
            matched_topic_ids,
            ngram_match,
            len(title_concepts),
            sorted(title_terms),
            len(required_intents),
            len(matched_required_intents),
        )
        if not tier:
            continue

        channels = []
        if matched_fields:
            channels.append("structured_fields")
        if transcript_terms:
            channels.append("full_transcript_lexicon")
        if matched_topic_ids:
            channels.append("full_topic_membership")
        if channel_shared_grams["title"]:
            channels.append("title_ngram")
        if channel_shared_grams["teaching_note"]:
            channels.append("teaching_note_ngram")
        if channel_shared_grams["transcript"]:
            channels.append("full_transcript_ngram")

        score = (
            field_score
            + topic_score
            + ngram_score
            + focus_score
            + len(matched_concepts) * 4.0
        )
        evidence_quality_bonus = rules["retrieval"].get(
            "evidence_quality_bonus", {}
        ).get(
            video["confidence"], 0.0
        )
        score += evidence_quality_bonus
        candidate = {
                "score": round(score, 4),
                "relevance_tier": tier,
                "intrinsic_relevance_tier": tier,
                "retrieval_channels": channels,
                "matched_query_concepts": matched_concepts,
                "matched_structured_query_concepts": (
                    matched_structured_concepts
                ),
                "matched_original_terms": original_matches,
                "matched_equivalent_terms": equivalent_matches,
                "matched_terms": expanded_matches,
                "matched_fields": matched_fields,
                "matched_topics": matched_topic_ids,
                "matched_topic_details": [
                    topic_details_by_id[topic_id]
                    for topic_id in matched_topic_ids
                    if topic_id in topic_details_by_id
                ],
                "matched_required_intents": matched_required_intents,
                "required_intent_miss_count": (
                    len(required_intents) - len(matched_required_intents)
                ),
                "matched_excluded_terms": excluded_matches,
                "matched_excluded_seed_terms": excluded_seed_matches,
                "excluded_query_penalty": excluded_query_penalty,
                "transcript_ngram_coverage": round(ngram_coverage, 4),
                "ngram_match": ngram_match,
                "ngram_coverage_by_field": {
                    field: round(value, 4)
                    for field, value in channel_ngram_coverage.items()
                },
                "score_breakdown": {
                    "structured_field_score": round(field_score, 4),
                    "topic_score": round(topic_score, 4),
                    "ngram_score": round(ngram_score, 4),
                    "exact_focus_score": round(focus_score, 4),
                    "matched_concept_score": round(
                        len(matched_concepts) * 4.0, 4
                    ),
                    "evidence_quality_bonus": round(evidence_quality_bonus, 4),
                    "base_score_before_feedback": round(score, 4),
                },
                "video_id": video["video_id"],
                "title": video["title"],
                "category": video["category"],
                "confidence": video["confidence"],
                "processing_status": video["processing_status"],
                "url": video["url"],
            }
        refresh_score_breakdown(candidate, rules)
        ranked.append(candidate)

    ranked.sort(key=lambda item: candidate_sort_key(item, rules))
    assign_review_budget(ranked, len(matched_groups), rules)
    return ranked, expansion


def apply_retrieval_policy(
    query,
    ranked,
    expansion,
    knowledge,
    retrieval_guidance,
    retrieval_rules,
):
    """Partition surfaced evidence from exhaustive recall without deleting it."""

    selection_module, selection_rules = load_selection_policy()
    boundary = selection_module.classify_boundary(
        expansion["positive_query"], selection_rules
    )
    plan = {
        "query": query,
        "query_expansion": {
            key: value for key, value in expansion.items() if key != "term_weights"
        },
        "retrieval_guidance": retrieval_guidance,
    }
    policy_api = SimpleNamespace(normalize=normalize, flatten=flatten)
    videos = {video["video_id"]: video for video in knowledge["videos"]}
    rejected_counts = Counter()
    requested_constraints = selection_module.query_constraints(
        policy_api, expansion["positive_query"], selection_rules
    )

    for candidate in ranked:
        video = videos[candidate["video_id"]]
        reasons = []
        if boundary["type"] == "pain_or_injury":
            reasons.append("medical_boundary_has_no_direct_safety_evidence")
        elif boundary["type"] == "endorsement_or_authorship":
            reasons.append("identity_boundary_does_not_need_teaching_video")
        elif (
            boundary["type"] == "insufficient_observation"
            and "唯一原因" in boundary.get("matched_terms", [])
        ):
            reasons.append("unique_cause_cannot_be_established_without_observation")
        elif (
            boundary["type"] == "purchase_advice"
            and video.get("category")
            not in selection_rules["purchase_allowed_categories"]
        ):
            reasons.append("purchase_query_requires_equipment_evidence")

        if not reasons:
            constraint_scope = _VIDEO_CONSTRAINT_SCOPE_CACHE.get(
                candidate["video_id"]
            )
            if constraint_scope is None:
                constraint_scope = selection_module.video_constraint_scope(
                    policy_api, video, selection_rules
                )
                _VIDEO_CONSTRAINT_SCOPE_CACHE[candidate["video_id"]] = (
                    constraint_scope
                )
            (
                allowed,
                failures,
                policy_requested_constraints,
                _,
                constraint_matches,
            ) = selection_module.constraint_decision(
                policy_api,
                query,
                plan,
                video,
                selection_rules,
                requested=requested_constraints,
                scope=constraint_scope,
            )
            if not allowed:
                reasons.extend(failures)
            else:
                reasons.extend(
                    selection_module.required_constraint_support_failures(
                        policy_requested_constraints,
                        constraint_matches,
                        selection_rules,
                    )
                )

        title_normalized = normalize(video.get("title", ""))
        if not reasons and any(
            normalize(term) in title_normalized
            for term in selection_rules["incomplete_fragment_terms"]
        ):
            reasons.append("incomplete_series_fragment")

        structured = selection_module.structured_video_text(policy_api, video)
        positive_query = expansion["positive_query"]
        if (
            not reasons
            and expansion["intent_frame"].get("requested_output") == "comparison"
            and "被动" in positive_query
            and normalize("被动") not in structured
        ):
            reasons.append("comparison_missing_passive_scenario")
        if (
            not reasons
            and "姿势" in positive_query
            and "被动" not in positive_query
            and normalize("被动") in title_normalized
        ):
            reasons.append("basic_form_query_conflicts_with_passive_variant")

        eligible = not reasons
        candidate["retrieval_policy_eligible"] = eligible
        candidate["retrieval_policy_reasons"] = reasons
        rejected_counts.update(reasons)

    ranked.sort(
        key=lambda item: (
            0 if item["retrieval_policy_eligible"] else 1,
            candidate_sort_key(item, retrieval_rules),
        )
    )
    assign_review_budget(
        ranked,
        len(expansion["matched_synonym_groups"]),
        retrieval_rules,
    )
    return ranked, {
        "boundary_type": boundary["type"],
        "eligible_candidate_count": sum(
            item["retrieval_policy_eligible"] for item in ranked
        ),
        "rejected_candidate_count": sum(
            not item["retrieval_policy_eligible"] for item in ranked
        ),
        "rejection_reason_counts": dict(sorted(rejected_counts.items())),
        "exhaustive_candidates_preserved": True,
    }


def ranked_result(candidate, video):
    return {
        **compact_candidate(candidate),
        "category": video["category"],
        "confidence": video["confidence"],
        "processing_status": video["processing_status"],
        "duration_seconds": video["duration_seconds"],
        "matched_topics": candidate["matched_topics"],
        "retrieval_channels": candidate["retrieval_channels"],
    }


def compact_candidate(candidate):
    why_retrieved = []
    if candidate.get("matched_original_terms"):
        why_retrieved.append(
            "直接命中提问词：" + "、".join(candidate["matched_original_terms"])
        )
    if candidate.get("matched_equivalent_terms"):
        why_retrieved.append(
            "命中同义表达：" + "、".join(candidate["matched_equivalent_terms"])
        )
    if candidate.get("matched_fields"):
        fields = "；".join(
            f"{field}={','.join(terms)}"
            for field, terms in sorted(candidate["matched_fields"].items())
        )
        why_retrieved.append("结构化字段命中：" + fields)
    if candidate.get("matched_topic_details"):
        why_retrieved.append(
            "主题命中："
            + "、".join(
                item["subtopic"] for item in candidate["matched_topic_details"]
            )
        )
    active_ngram_fields = [
        field
        for field, coverage in candidate.get("ngram_coverage_by_field", {}).items()
        if coverage > 0
    ]
    if candidate.get("ngram_match") and active_ngram_fields:
        why_retrieved.append("字符片段命中：" + "、".join(active_ngram_fields))
    if candidate.get("feedback_adjustment"):
        why_retrieved.append("用户反馈参与排序")
    if candidate.get("matched_excluded_terms"):
        why_retrieved.append(
            "同时命中排除词，已降权："
            + "、".join(candidate["matched_excluded_terms"])
        )
    if candidate.get("retrieval_policy_eligible") is False:
        why_retrieved.append(
            "仅保留在穷举召回清单，不能作为当前问题证据："
            + "、".join(candidate.get("retrieval_policy_reasons", []))
        )
    result = {
        "video_id": candidate["video_id"],
        "title": candidate["title"],
        "url": candidate["url"],
        "score": candidate["score"],
        "relevance_tier": candidate["relevance_tier"],
        "intrinsic_relevance_tier": candidate["intrinsic_relevance_tier"],
        "review_priority": candidate["review_priority"],
        "within_review_budget": candidate["within_review_budget"],
        "category": candidate["category"],
        "confidence": candidate["confidence"],
        "processing_status": candidate["processing_status"],
        "retrieval_channels": candidate.get("retrieval_channels", []),
        "matched_query_concepts": candidate["matched_query_concepts"],
        "matched_structured_query_concepts": candidate.get(
            "matched_structured_query_concepts", []
        ),
        "matched_original_terms": candidate["matched_original_terms"],
        "matched_equivalent_terms": candidate.get(
            "matched_equivalent_terms", []
        ),
        "matched_terms": candidate.get("matched_terms", []),
        "matched_fields": candidate.get("matched_fields", {}),
        "matched_topics": candidate.get("matched_topics", []),
        "matched_topic_details": candidate.get("matched_topic_details", []),
        "matched_required_intents": candidate.get("matched_required_intents", []),
        "matched_excluded_terms": candidate.get("matched_excluded_terms", []),
        "matched_excluded_seed_terms": candidate.get(
            "matched_excluded_seed_terms", []
        ),
        "ngram_match": candidate.get("ngram_match", False),
        "ngram_coverage_by_field": candidate.get(
            "ngram_coverage_by_field", {}
        ),
        "score_breakdown": candidate.get("score_breakdown", {}),
        "retrieval_policy_eligible": candidate.get(
            "retrieval_policy_eligible", True
        ),
        "retrieval_policy_reasons": candidate.get(
            "retrieval_policy_reasons", []
        ),
        "why_retrieved": why_retrieved,
    }
    if candidate.get("feedback_adjustment"):
        result["feedback_adjustment"] = candidate["feedback_adjustment"]
    return result


def compact_quality(quality):
    if not quality:
        return None
    transcript = quality.get("transcript", {})
    automatic = quality.get("automatic_evidence", {})
    return {
        "transcript": {
            "passed": transcript.get("passed"),
            "issues": transcript.get("issues", []),
            "language_probability": transcript.get("language_probability"),
            "segment_count": transcript.get("segment_count"),
            "text_characters": transcript.get("text_characters"),
        },
        "automatic_evidence": {
            "passed": automatic.get("passed"),
            "issues": automatic.get("issues", []),
            "key_evidence_count": automatic.get("key_evidence_count"),
            "teaching_term_matches": automatic.get("teaching_term_matches"),
        },
    }


def compact_teaching_note(note):
    evidence_fields = {
        "key_evidence",
        "error_evidence",
        "action_cues",
        "principles",
        "visual_review_evidence",
    }
    summary = {key: value for key, value in note.items() if key not in evidence_fields}
    evidence_by_content = {}
    for role in evidence_fields:
        values = note.get(role)
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, dict) or not value.get("text"):
                continue
            marker = (str(value.get("timestamp") or ""), str(value["text"]))
            if marker not in evidence_by_content:
                evidence_by_content[marker] = {
                    "timestamp": marker[0],
                    "text": marker[1],
                    "roles": [],
                }
            evidence_by_content[marker]["roles"].append(role)
    evidence = sorted(
        evidence_by_content.values(),
        key=lambda item: (item["timestamp"], item["text"]),
    )
    for item in evidence:
        item["roles"].sort()
    return {"summary": summary, "evidence": evidence}


def rank_transcript_evidence(video, query, expansion, limit=6, context_radius=2):
    """Return query-matched timestamped transcript windows from one finalist video."""

    segments = video.get("transcript_segments") or []
    if not query.strip() or not segments or limit <= 0:
        return []
    query_normalized = normalize(query)
    query_grams = character_grams(query)
    term_weights = expansion.get("term_weights", {}) if expansion else {}
    scored = []
    for index in range(len(segments)):
        start_index = max(0, index - context_radius)
        end_index = min(len(segments), index + context_radius + 1)
        window = segments[start_index:end_index]
        text_value = "".join(str(item.get("text") or "") for item in window)
        normalized_value = normalize(text_value)
        if not normalized_value:
            continue
        matched_terms = sorted(
            term
            for term in term_weights
            if normalize(term) and normalize(term) in normalized_value
        )
        shared_grams = query_grams & character_grams(text_value)
        gram_coverage = len(shared_grams) / max(1, len(query_grams))
        exact_match = bool(query_normalized and query_normalized in normalized_value)
        score = (
            (100.0 if exact_match else 0.0)
            + sum(term_weights[term] for term in matched_terms)
            + gram_coverage * 25.0
        )
        if not exact_match and not matched_terms and len(shared_grams) < 2:
            continue
        scored.append(
            {
                "score": round(score, 4),
                "start_index": start_index,
                "end_index": end_index,
                "timestamp": (
                    f"{window[0]['timestamp'].split('-', 1)[0]}-"
                    f"{window[-1]['timestamp'].rsplit('-', 1)[-1]}"
                ),
                "text": text_value,
                "matched_terms": matched_terms,
                "query_ngram_coverage": round(gram_coverage, 4),
                "exact_query_match": exact_match,
            }
        )
    scored.sort(
        key=lambda item: (
            -item["score"],
            item["start_index"],
            item["text"],
        )
    )
    selected = []
    for item in scored:
        overlaps = any(
            item["start_index"] < current["end_index"]
            and current["start_index"] < item["end_index"]
            for current in selected
        )
        if overlaps:
            continue
        selected.append(item)
        if len(selected) == limit:
            break
    for item in selected:
        item.pop("start_index", None)
        item.pop("end_index", None)
    return selected


def compact_lookup_feedback(feedback_guidance, video_ids):
    if not feedback_guidance:
        return None
    requested = set(video_ids)
    return {
        "matched_global_signal_count": feedback_guidance["global"][
            "matched_signal_count"
        ],
        "matched_local_feedback_count": feedback_guidance["local"][
            "matched_feedback_count"
        ],
        "applied_video_adjustments": [
            adjustment
            for adjustment in feedback_guidance["applied_video_adjustments"]
            if adjustment["video_id"] in requested
        ],
        "answer_preferences": feedback_guidance["answer_preferences"],
    }


def search(
    query,
    limit=12,
    mode="hybrid",
    recall_mode="exhaustive",
    manifest_offset=0,
    manifest_limit=DEFAULT_MANIFEST_LIMIT,
    local_personalization=True,
    feedback_dir=None,
):
    if recall_mode not in {"exhaustive", "balanced"}:
        raise ValueError(f"Unsupported recall mode: {recall_mode}")
    if manifest_offset < 0:
        raise ValueError("manifest_offset must be non-negative")
    if (
        manifest_limit is not DEFAULT_MANIFEST_LIMIT
        and manifest_limit is not None
        and manifest_limit <= 0
    ):
        raise ValueError("manifest_limit must be positive")
    knowledge, retrieval_index, rules = load_resources()
    answer_rules = load_answer_rules()
    answer_guidance = classify_answer_mode(query, answer_rules)
    ranked, expansion = rank_candidates(
        query,
        knowledge,
        retrieval_index,
        rules,
        mode=mode,
    )
    retrieval_guidance = build_query_plan(query, expansion, answer_rules)
    ranked, feedback_guidance = apply_feedback_layers(
        query,
        ranked,
        expansion,
        knowledge,
        retrieval_index,
        rules,
        local_personalization=local_personalization,
        feedback_dir=feedback_dir,
    )
    ranked, retrieval_policy = apply_retrieval_policy(
        query,
        ranked,
        expansion,
        knowledge,
        retrieval_guidance,
        rules,
    )
    videos = {video["video_id"]: video for video in knowledge["videos"]}
    eligible_ranked = [
        item for item in ranked if item["retrieval_policy_eligible"]
    ]
    accessible_candidate_count = (
        len(ranked)
        if recall_mode == "exhaustive"
        else min(
            len(ranked),
            max(limit, rules["retrieval"]["balanced_manifest_limit"]),
        )
    )
    default_manifest_limit_applied = manifest_limit is DEFAULT_MANIFEST_LIMIT
    if default_manifest_limit_applied:
        manifest_limit = min(
            accessible_candidate_count,
            rules["retrieval"]["balanced_manifest_limit"],
        )
    elif manifest_limit is None:
        manifest_limit = accessible_candidate_count
    manifest_end = min(
        accessible_candidate_count,
        manifest_offset + manifest_limit,
    )
    manifest = ranked[manifest_offset:manifest_end]
    next_manifest_offset = (
        manifest_end if manifest_end < accessible_candidate_count else None
    )
    tier_counts = Counter(item["relevance_tier"] for item in ranked)
    intrinsic_tier_counts = Counter(
        item["intrinsic_relevance_tier"] for item in ranked
    )
    channel_counts = Counter(
        channel for item in ranked for channel in item["retrieval_channels"]
    )
    return {
        "query": query,
        "mode": mode,
        "recall_mode": recall_mode,
        "answer_guidance": (
            answer_guidance
            if manifest_offset == 0
            else {
                "pagination": True,
                "mode": answer_guidance["mode"],
                "see_manifest_offset": 0,
            }
        ),
        "retrieval_guidance": (
            retrieval_guidance
            if manifest_offset == 0
            else {
                "pagination": True,
                "strategy": retrieval_guidance["strategy"],
                "see_manifest_offset": 0,
            }
        ),
        "feedback_guidance": (
            feedback_guidance
            if manifest_offset == 0
            else {
                "pagination": True,
                "local_personalization_enabled": bool(local_personalization),
                "see_manifest_offset": 0,
            }
        ),
        "retrieval_policy": (
            retrieval_policy
            if manifest_offset == 0
            else {"pagination": True, "see_manifest_offset": 0}
        ),
        "query_expansion": (
            {
                key: value
                for key, value in expansion.items()
                if key != "term_weights"
            }
            if manifest_offset == 0
            else {"pagination": True, "see_manifest_offset": 0}
        ),
        "coverage": {
            "indexable_videos": retrieval_index["indexable_video_count"],
            "candidate_count": len(ranked),
            "eligible_candidate_count": len(eligible_ranked),
            "policy_rejected_candidate_count": len(ranked) - len(eligible_ranked),
            "accessible_candidate_count": accessible_candidate_count,
            "candidate_manifest_count": len(manifest),
            "default_manifest_limit_applied": default_manifest_limit_applied,
            "manifest_offset": manifest_offset,
            "manifest_truncated": (
                manifest_offset > 0
                or manifest_end < accessible_candidate_count
                or accessible_candidate_count < len(ranked)
            ),
            "selection_truncated": accessible_candidate_count < len(ranked),
            "next_manifest_offset": next_manifest_offset,
            "tier_counts": dict(tier_counts),
            "intrinsic_tier_counts": dict(intrinsic_tier_counts),
            "intrinsic_review_candidate_count": sum(
                intrinsic_tier_counts[tier]
                for tier in ["direct", "strong_related"]
            ),
            "policy_rejected_review_candidate_count": sum(
                item["retrieval_policy_eligible"] is False
                and item["relevance_tier"] in {"direct", "strong_related"}
                for item in ranked
            ),
            "review_candidate_count": sum(
                item["within_review_budget"] for item in ranked
            ),
            "deferred_review_candidate_count": sum(
                item["review_priority"] == "deferred_review" for item in ranked
            ),
            "channel_counts": dict(channel_counts),
            "coverage_claim": (
                "high_recall_candidate_set_not_proof_of_semantic_completeness"
                if recall_mode == "exhaustive"
                else "bounded_top_candidate_set_intentionally_not_exhaustive"
            ),
        },
        "results": [
            ranked_result(item, videos[item["video_id"]])
            for item in (eligible_ranked[:limit] if manifest_offset == 0 else [])
        ],
        "candidate_manifest": [compact_candidate(item) for item in manifest],
    }


def lookup_videos(
    video_ids,
    query="",
    local_personalization=True,
    feedback_dir=None,
    debug=False,
    segment_limit=6,
):
    knowledge, retrieval_index, rules = load_resources()
    videos = {video["video_id"]: video for video in knowledge["videos"]}
    records = {item["video_id"]: item for item in retrieval_index["videos"]}
    candidates = {}
    expansion = None
    feedback_guidance = None
    if query:
        ranked, expansion = rank_candidates(query, knowledge, retrieval_index, rules)
        ranked, feedback_guidance = apply_feedback_layers(
            query,
            ranked,
            expansion,
            knowledge,
            retrieval_index,
            rules,
            local_personalization=local_personalization,
            feedback_dir=feedback_dir,
        )
        candidates = {item["video_id"]: item for item in ranked}
    results = []
    missing = []
    rejected = []
    for video_id in video_ids:
        video = videos.get(video_id)
        if not video:
            missing.append(video_id)
            continue
        if video.get("processing_status") != "ready":
            rejected.append(
                {
                    "video_id": video_id,
                    "title": video.get("title"),
                    "processing_status": video.get("processing_status"),
                    "reason": "processing_status_not_ready",
                }
            )
            continue
        record = records.get(video_id) or {}
        result = {
            "video_id": video_id,
            "title": video["title"],
            "category": video["category"],
            "confidence": video["confidence"],
            "processing_status": video["processing_status"],
            "url": video["url"],
            "duration_seconds": video["duration_seconds"],
            "quality": compact_quality(video.get("quality")),
            "teaching_note": compact_teaching_note(video["teaching_note"]),
            "transcript_evidence": rank_transcript_evidence(
                video,
                query,
                expansion,
                limit=segment_limit,
            ),
            "retrieval_summary": {
                "topic_ids": record.get("topic_ids", []),
                "lexicon_terms": record.get("lexicon_terms", []),
                "transcript_ngram_count": len(record.get("transcript_ngrams", [])),
                "bundled_transcript_segment_count": len(
                    video.get("transcript_segments") or []
                ),
            },
        }
        if video_id in candidates:
            candidate = candidates[video_id]
            result["query_match"] = {
                "score": candidate["score"],
                "relevance_tier": candidate["relevance_tier"],
                "retrieval_channels": candidate["retrieval_channels"],
                "matched_query_concepts": candidate["matched_query_concepts"],
                "matched_original_terms": candidate["matched_original_terms"],
                "matched_terms": candidate["matched_terms"],
                "matched_fields": candidate["matched_fields"],
                "matched_topics": candidate["matched_topics"],
                "matched_required_intents": candidate.get(
                    "matched_required_intents", []
                ),
            }
            if candidate.get("feedback_adjustment"):
                result["query_match"]["feedback_adjustment"] = candidate[
                    "feedback_adjustment"
                ]
        if debug:
            result["debug_stored_teaching_note"] = video["teaching_note"]
            result["debug_retrieval_index"] = record
            result["debug_ranked_candidate"] = candidates.get(video_id)
        results.append(result)
    return {
        "query": query,
        "answer_guidance": classify_answer_mode(query) if query else None,
        "feedback_guidance": compact_lookup_feedback(feedback_guidance, video_ids),
        "results": results,
        "missing_video_ids": missing,
        "rejected_video_ids": rejected,
    }


def main():
    parser = argparse.ArgumentParser(
        description="High-recall retrieval over the Liu Hui badminton knowledge base."
    )
    parser.add_argument("query", nargs="?", default="")
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument(
        "--mode", choices=["hybrid", "keyword", "semantic"], default="hybrid"
    )
    parser.add_argument(
        "--recall-mode",
        choices=["exhaustive", "balanced"],
        default="exhaustive",
    )
    parser.add_argument(
        "--video-id",
        action="append",
        default=[],
        help="Return compact stored evidence for a candidate video ID; repeat as needed.",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Return answer allocation and retrieval workflow without ranking videos.",
    )
    parser.add_argument(
        "--lookup-debug",
        action="store_true",
        help="Include full retrieval hashes and ranking internals with --video-id; output can be very large.",
    )
    parser.add_argument(
        "--segment-limit",
        type=int,
        default=6,
        help="Maximum query-matched transcript windows returned per --video-id.",
    )
    parser.add_argument("--manifest-offset", type=int, default=0)
    parser.add_argument("--manifest-limit", type=int, default=20)
    parser.add_argument(
        "--no-local-personalization",
        action="store_true",
        help="Ignore accepted feedback in the current user's local feedback queue.",
    )
    parser.add_argument(
        "--feedback-dir",
        type=Path,
        help="Override the local feedback directory for this search.",
    )
    args = parser.parse_args()
    if args.limit <= 0:
        parser.error("--limit must be positive")
    if args.manifest_offset < 0:
        parser.error("--manifest-offset must be non-negative")
    if args.manifest_limit <= 0:
        parser.error("--manifest-limit must be positive")
    if args.segment_limit <= 0:
        parser.error("--segment-limit must be positive")
    if args.lookup_debug and not args.video_id:
        parser.error("--lookup-debug requires at least one --video-id")
    if args.plan_only:
        if args.video_id:
            parser.error("--plan-only cannot be combined with --video-id")
        if not args.query.strip():
            parser.error("query is required with --plan-only")
        print(json.dumps(plan_query(args.query), ensure_ascii=False, indent=2))
        return
    if args.video_id:
        payload = lookup_videos(
            args.video_id,
            query=args.query,
            local_personalization=not args.no_local_personalization,
            feedback_dir=args.feedback_dir,
            debug=args.lookup_debug,
            segment_limit=args.segment_limit,
        )
    else:
        if not args.query.strip():
            parser.error("query is required unless --video-id is provided")
        payload = search(
            args.query,
            limit=args.limit,
            mode=args.mode,
            recall_mode=args.recall_mode,
            manifest_offset=args.manifest_offset,
            manifest_limit=args.manifest_limit,
            local_personalization=not args.no_local_personalization,
            feedback_dir=args.feedback_dir,
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
