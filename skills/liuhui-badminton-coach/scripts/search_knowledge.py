#!/usr/bin/env python3
import argparse
import bisect
import hashlib
import importlib.util
import json
import os
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
KNOWLEDGE_PATH = ROOT / "references" / "knowledge-base.json"
RETRIEVAL_INDEX_PATH = ROOT / "references" / "retrieval-index.json"
RUNTIME_STORE_PATH = ROOT / "references" / "runtime-store.sqlite3"
RULES_PATH = ROOT / "references" / "retrieval-rules.json"
ANSWER_RULES_PATH = ROOT / "references" / "answer-modality-rules.json"
FEEDBACK_RULES_PATH = ROOT / "references" / "feedback-rules.json"
FEEDBACK_SIGNALS_PATH = ROOT / "references" / "feedback-signals.json"
SELECTION_SCRIPT_PATH = ROOT / "scripts" / "answer_selection_policy.py"

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
_JSON_SNAPSHOT_CACHE = {}
_PREPARED_RETRIEVAL_CACHE = {}
_LOCAL_FEEDBACK_CACHE = {}
_FEEDBACK_SIGNATURE_CACHE = {}
_COMPONENT_MODULES = {}


def load_component(name, filename):
    if filename in _COMPONENT_MODULES:
        return _COMPONENT_MODULES[filename]
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _COMPONENT_MODULES[filename] = module
    return module


def flatten(value):
    if isinstance(value, dict):
        return " ".join(flatten(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(flatten(item) for item in value)
    return str(value or "")


CHINESE_VARIANTS = str.maketrans(
    {
        "後": "后",
        "場": "场",
        "動": "动",
        "發": "发",
        "無": "无",
        "願": "愿",
        "這": "这",
        "個": "个",
        "來": "来",
        "麼": "么",
        "們": "们",
        "線": "线",
        "轉": "转",
        "頂": "顶",
        "軸": "轴",
        "裡": "里",
        "擊": "击",
        "盤": "盘",
        "隨": "随",
        "隱": "隐",
        "繼": "继",
        "續": "续",
        "變": "变",
        "順": "顺",
        "實": "实",
        "話": "话",
        "學": "学",
        "習": "习",
        "會": "会",
        "處": "处",
        "標": "标",
        "準": "准",
        "運": "运",
        "員": "员",
        "對": "对",
        "還": "还",
        "從": "从",
        "種": "种",
        "進": "进",
        "階": "阶",
        "單": "单",
        "雙": "双",
        "網": "网",
        "體": "体",
        "術": "术",
        "區": "区",
        "應": "应",
        "讓": "让",
        "過": "过",
        "遠": "远",
        "邊": "边",
        "壓": "压",
    }
)


@lru_cache(maxsize=16384)
def normalize(text):
    normalized = str(text).lower().translate(CHINESE_VARIANTS)
    return "".join(re.findall(r"[\u4e00-\u9fff]+|[a-z0-9]+", normalized))


def load_json_snapshot(path):
    path = Path(path)
    stat = path.stat()
    key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    if key not in _JSON_SNAPSHOT_CACHE:
        for cached_key in list(_JSON_SNAPSHOT_CACHE):
            if cached_key[0] == key[0]:
                del _JSON_SNAPSHOT_CACHE[cached_key]
        _JSON_SNAPSHOT_CACHE[key] = json.loads(path.read_text(encoding="utf-8"))
    return _JSON_SNAPSHOT_CACHE[key]


def evidence_descriptor(record):
    """Return a source-neutral identity for a video or future teaching clip."""
    legacy_video_id = str(record.get("video_id", ""))
    evidence_id = str(record.get("evidence_id") or legacy_video_id)
    canonical_url = record.get("canonical_url") or record.get("url") or ""
    source_type = record.get("source_type")
    if not source_type:
        source_type = (
            "douyin_video"
            if "douyin.com/video/" in canonical_url
            else "external_video"
        )
    return {
        "evidence_id": evidence_id,
        "source_type": source_type,
        "canonical_url": canonical_url,
        "parent_source_id": record.get("parent_source_id"),
        "clip_start_seconds": record.get("clip_start_seconds"),
        "clip_end_seconds": record.get("clip_end_seconds"),
        "legacy_video_id": legacy_video_id or None,
    }


def load_answer_rules():
    return load_json_snapshot(ANSWER_RULES_PATH)


def load_selection_module():
    global _SELECTION_MODULE
    if _SELECTION_MODULE is None:
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
        rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
        if RUNTIME_STORE_PATH.exists():
            runtime_store = load_component(
                "liuhui_runtime_store", "runtime_store.py"
            ).RuntimeStore(RUNTIME_STORE_PATH)
            _RESOURCE_CACHE = (
                runtime_store.knowledge,
                runtime_store.retrieval_index,
                rules,
            )
        else:
            _RESOURCE_CACHE = (
                json.loads(KNOWLEDGE_PATH.read_text(encoding="utf-8")),
                json.loads(RETRIEVAL_INDEX_PATH.read_text(encoding="utf-8")),
                rules,
            )
    return _RESOURCE_CACHE


def knowledge_video_map(knowledge, video_ids=None, *, full=True):
    runtime_store = load_component(
        "liuhui_runtime_store", "runtime_store.py"
    )
    return runtime_store.video_map(knowledge, video_ids, full=full)


def iter_search_videos(knowledge):
    return knowledge.get("search_videos", knowledge["videos"])


def decode_video_ngram_postings(encoded):
    """Decode one compact top-level posting list, while accepting legacy lists."""

    if not isinstance(encoded, str):
        return encoded
    if not encoded:
        return ()
    return tuple(
        (int(record_index), int(channel_mask))
        for item in encoded.split(";")
        for record_index, channel_mask in [item.split(",", 1)]
    )


def decode_chunk_ngram_postings(encoded):
    """Decode one compact chunk posting list, while accepting legacy lists."""

    if not isinstance(encoded, str):
        return encoded
    if not encoded:
        return ()
    return tuple(int(index) for index in encoded.split(","))


def video_transcript_segments(video):
    """Return timestamped segments, lazily expanding bundled Bilibili payloads."""

    segments = video.get("transcript_segments")
    if segments is not None:
        return segments
    encoded = video.get("transcript_segments_json")
    if not encoded:
        return []
    segments = json.loads(encoded)
    if not isinstance(segments, list):
        raise ValueError("compact transcript segments must decode to a list")
    return segments


def prepared_retrieval_index(retrieval_index):
    cache_key = id(retrieval_index)
    cached = _PREPARED_RETRIEVAL_CACHE.get(cache_key)
    if cached is not None and cached[0] is retrieval_index:
        return cached[1]
    records = retrieval_index["videos"]
    prepared = {
        "records": {item["video_id"]: item for item in records},
        "video_ids": [item["video_id"] for item in records],
    }
    chunk_index = retrieval_index.get("chunk_index") or {}
    chunk_config = chunk_index.get("config") or {}
    chunk_allowed_sources = set(
        chunk_config.get("source_allowlist") or ["bilibili_video"]
    )
    chunk_cluster_sources = set(
        chunk_config.get("cluster_source_allowlist")
        or chunk_allowed_sources
    )
    chunks = chunk_index.get("chunks") or []
    cluster_chunk_indexes = frozenset(
        index
        for index, chunk in enumerate(chunks)
        if isinstance(chunk.get("video_index"), int)
        and 0 <= chunk["video_index"] < len(records)
        and records[chunk["video_index"]].get("source_type")
        in chunk_cluster_sources
    )
    scoring_chunk_indexes = frozenset(
        index
        for index in cluster_chunk_indexes
        if records[chunks[index]["video_index"]].get("source_type")
        in chunk_allowed_sources
    )
    prepared["chunk"] = {
        "cluster_indexes": cluster_chunk_indexes,
        "scoring_indexes": scoring_chunk_indexes,
        "clustered_video_ids": {
            records[chunks[index]["video_index"]]["video_id"]
            for index in cluster_chunk_indexes
        },
        "indexed_video_ids": {
            records[chunks[index]["video_index"]]["video_id"]
            for index in scoring_chunk_indexes
        },
    }
    if "ngram_vocabulary" not in retrieval_index:
        prepared["forward_gram_sets"] = {
            item["video_id"]: {
                "title": set(item.get("title_ngrams", [])),
                "teaching_note": set(item.get("teaching_note_ngrams", [])),
                "transcript": set(item.get("transcript_ngrams", [])),
            }
            for item in records
        }
    _PREPARED_RETRIEVAL_CACHE.clear()
    _PREPARED_RETRIEVAL_CACHE[cache_key] = (
        retrieval_index,
        prepared,
    )
    return prepared


def inverted_ngram_matches(retrieval_index, grams):
    """Return document frequencies and per-video channel matches for query grams."""
    prepared = prepared_retrieval_index(retrieval_index)
    posting_lookup = getattr(retrieval_index, "lookup_ngram_postings", None)
    if posting_lookup is not None:
        document_frequency = Counter()
        matches = {}
        video_ids = prepared["video_ids"]
        for gram, encoded in posting_lookup(grams).items():
            gram_postings = decode_video_ngram_postings(encoded)
            document_frequency[gram] = len(gram_postings)
            for record_index, channel_mask in gram_postings:
                video_id = video_ids[record_index]
                channels = matches.setdefault(
                    video_id,
                    {"title": set(), "teaching_note": set(), "transcript": set()},
                )
                if channel_mask & 1:
                    channels["title"].add(gram)
                if channel_mask & 2:
                    channels["teaching_note"].add(gram)
                if channel_mask & 4:
                    channels["transcript"].add(gram)
        return document_frequency, matches

    vocabulary = retrieval_index.get("ngram_vocabulary")
    postings = retrieval_index.get("ngram_postings")
    if vocabulary is None or postings is None:
        forward = prepared["forward_gram_sets"]
        document_frequency = Counter(
            gram
            for gram in grams
            for channel_sets in forward.values()
            if any(gram in values for values in channel_sets.values())
        )
        matches = {
            video_id: {
                channel: grams & values
                for channel, values in channel_sets.items()
            }
            for video_id, channel_sets in forward.items()
        }
        return document_frequency, matches

    document_frequency = Counter()
    matches = {}
    video_ids = prepared["video_ids"]
    for gram in grams:
        position = bisect.bisect_left(vocabulary, gram)
        if position >= len(vocabulary) or vocabulary[position] != gram:
            continue
        gram_postings = decode_video_ngram_postings(postings[position])
        document_frequency[gram] = len(gram_postings)
        for record_index, channel_mask in gram_postings:
            video_id = video_ids[record_index]
            channels = matches.setdefault(
                video_id,
                {
                    "title": set(),
                    "teaching_note": set(),
                    "transcript": set(),
                },
            )
            if channel_mask & 1:
                channels["title"].add(gram)
            if channel_mask & 2:
                channels["teaching_note"].add(gram)
            if channel_mask & 4:
                channels["transcript"].add(gram)
    return document_frequency, matches


def inverted_candidate_ids(retrieval_index, expansion, query_grams):
    if "ngram_vocabulary" not in retrieval_index:
        return None
    minimum_ngram_size = min(retrieval_index["transcript_ngram_sizes"])
    if any(
        0 < len(normalize(term)) < minimum_ngram_size
        for term in expansion["term_weights"]
    ):
        return None
    concept_terms = {
        term
        for group in expansion["matched_synonym_groups"]
        for term in group
    }
    candidate_grams = set(query_grams)
    for term in {*expansion["term_weights"], *concept_terms}:
        candidate_grams.update(
            hashed_ngrams(term, retrieval_index["transcript_ngram_sizes"])
        )
    _, gram_matches = inverted_ngram_matches(retrieval_index, candidate_grams)
    indexes = set()
    for term in {*expansion["term_weights"], *concept_terms}:
        indexes.update(retrieval_index.get("term_postings", {}).get(term, []))
    for topic in expansion["matched_topics"]:
        indexes.update(
            retrieval_index.get("topic_postings", {}).get(topic["topic_id"], [])
        )
    video_ids = prepared_retrieval_index(retrieval_index)["video_ids"]
    candidates = set(gram_matches)
    candidates.update(
        video_ids[index] for index in indexes if 0 <= index < len(video_ids)
    )
    if candidates:
        return candidates
    return None


_query_planning = load_component(
    "liuhui_query_planning", "query_planning.py"
)
_query_planning.normalize = normalize
_query_planning.load_answer_rules = load_answer_rules
build_lexicon = _query_planning.build_lexicon
fallback_shards = _query_planning.fallback_shards
longest_non_overlapping_terms = _query_planning.longest_non_overlapping_terms
extract_negative_scopes = _query_planning.extract_negative_scopes
requested_output = _query_planning.requested_output
build_intent_frame = _query_planning.build_intent_frame
expand_query = _query_planning.expand_query
split_query_units = _query_planning.split_query_units
build_query_plan = _query_planning.build_query_plan


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
    return load_json_snapshot(FEEDBACK_RULES_PATH)


def default_feedback_dir():
    override = os.environ.get("LIUHUI_FEEDBACK_DIR")
    if override:
        return Path(override).expanduser()
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    return codex_home / "feedback" / "liuhui-badminton-coach"












def load_global_feedback_records():
    if not FEEDBACK_SIGNALS_PATH.exists():
        return [], {"signal_count": 0, "updated_at": None}
    payload = load_json_snapshot(FEEDBACK_SIGNALS_PATH)
    return payload["signals"], {
        "signal_count": len(payload["signals"]),
        "updated_at": payload.get("updated_at"),
    }


def load_local_feedback_records(feedback_dir=None):
    queue_dir = Path(feedback_dir or default_feedback_dir()) / "queue"
    paths = sorted(queue_dir.glob("*.json"))
    signature = tuple(
        (str(path.resolve()), path.stat().st_mtime_ns, path.stat().st_size)
        for path in paths
    )
    cache_key = str(queue_dir.resolve())
    cached = _LOCAL_FEEDBACK_CACHE.get(cache_key)
    if cached is not None and cached["signature"] == signature:
        return cached["records"], dict(cached["stats"])
    records = []
    stats = {
        "queue_file_count": 0,
        "accepted_record_count": 0,
        "usable_record_count": 0,
        "skipped_record_count": 0,
    }
    for path in paths:
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
    _LOCAL_FEEDBACK_CACHE[cache_key] = {
        "signature": signature,
        "records": records,
        "stats": dict(stats),
    }
    return records, stats














_retrieval_ranking = load_component(
    "liuhui_retrieval_ranking", "retrieval_ranking.py"
)
_retrieval_ranking.normalize = normalize
_retrieval_ranking.flatten = flatten
_retrieval_ranking.expand_query = expand_query
_retrieval_ranking.hashed_ngrams = hashed_ngrams
_retrieval_ranking.inverted_candidate_ids = inverted_candidate_ids
_retrieval_ranking.inverted_ngram_matches = inverted_ngram_matches
_retrieval_ranking.prepared_retrieval_index = prepared_retrieval_index
_retrieval_ranking.decode_chunk_ngram_postings = decode_chunk_ngram_postings
_retrieval_ranking.knowledge_video_map = knowledge_video_map
_retrieval_ranking.iter_search_videos = iter_search_videos
_retrieval_ranking.load_selection_policy = load_selection_policy
_retrieval_ranking.TIER_ORDER = TIER_ORDER
_retrieval_ranking._VIDEO_CONSTRAINT_SCOPE_CACHE = _VIDEO_CONSTRAINT_SCOPE_CACHE
searchable_teaching_note = _retrieval_ranking.searchable_teaching_note
field_values = _retrieval_ranking.field_values
match_fields = _retrieval_ranking.match_fields
dynamic_term_statistics = _retrieval_ranking.dynamic_term_statistics
bm25_record_fields = _retrieval_ranking.bm25_record_fields
choose_tier = _retrieval_ranking.choose_tier
candidate_sort_key = _retrieval_ranking.candidate_sort_key
refresh_score_breakdown = _retrieval_ranking.refresh_score_breakdown
assign_review_budget = _retrieval_ranking.assign_review_budget
apply_structured_query_expansion = _retrieval_ranking.apply_structured_query_expansion
rank_candidates = _retrieval_ranking.rank_candidates
apply_retrieval_policy = _retrieval_ranking.apply_retrieval_policy


_feedback_ranking = load_component(
    "liuhui_feedback_ranking", "feedback_ranking.py"
)
_feedback_ranking.normalize = normalize
_feedback_ranking.expand_query = expand_query
_feedback_ranking.load_feedback_rules = load_feedback_rules
_feedback_ranking.load_global_feedback_records = load_global_feedback_records
_feedback_ranking.load_local_feedback_records = load_local_feedback_records
_feedback_ranking.assign_review_budget = assign_review_budget
_feedback_ranking.candidate_sort_key = candidate_sort_key
_feedback_ranking.refresh_score_breakdown = refresh_score_breakdown
_feedback_ranking.knowledge_video_map = knowledge_video_map
_feedback_ranking.TIER_ORDER = TIER_ORDER
character_grams = _feedback_ranking.character_grams
jaccard = _feedback_ranking.jaccard
feedback_signature = _feedback_ranking.feedback_signature
feedback_query_match = _feedback_ranking.feedback_query_match
feedback_query_similarity = _feedback_ranking.feedback_query_similarity
feedback_record_values = _feedback_ranking.feedback_record_values
build_feedback_adjustments = _feedback_ranking.build_feedback_adjustments
matched_feedback_corrections = _feedback_ranking.matched_feedback_corrections
local_answer_preferences = _feedback_ranking.local_answer_preferences
feedback_only_candidate = _feedback_ranking.feedback_only_candidate


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
    return _feedback_ranking.apply_feedback_layers(
        query,
        ranked,
        expansion,
        knowledge,
        retrieval_index,
        retrieval_rules,
        local_personalization=local_personalization,
        feedback_dir=feedback_dir,
        global_feedback_loader=load_global_feedback_records,
        local_feedback_loader=load_local_feedback_records,
    )

_retrieval_projection = load_component(
    "liuhui_retrieval_projection", "retrieval_projection.py"
)
_retrieval_projection.normalize = normalize
_retrieval_projection.character_grams = character_grams
ranked_result = _retrieval_projection.ranked_result
compact_candidate = _retrieval_projection.compact_candidate
compact_quality = _retrieval_projection.compact_quality
compact_teaching_note = _retrieval_projection.compact_teaching_note
rank_transcript_evidence = _retrieval_projection.rank_transcript_evidence
rank_bounded_note_evidence = (
    _retrieval_projection.rank_bounded_note_evidence
)
compact_lookup_feedback = _retrieval_projection.compact_lookup_feedback


def primary_content_cluster_id(candidate):
    cluster_ids = query_content_cluster_ids(candidate)
    return str(cluster_ids[0]) if cluster_ids else None


def query_content_cluster_ids(candidate):
    retrieval = candidate.get("transcript_retrieval") or {}
    return list(
        dict.fromkeys(
            str(cluster_id)
            for cluster_id in retrieval.get("matched_cluster_ids", [])
            if str(cluster_id)
        )
    )


def cap_content_clusters(
    items,
    *,
    limit=None,
    candidate_getter=None,
):
    """Keep the highest-ranked item per query-relevant content cluster."""

    candidate_getter = candidate_getter or (lambda item: item)
    if limit is not None and limit <= 0:
        return [], []
    kept = []
    suppressed = []
    representatives = {}
    covered_cluster_ids = set()
    for item in items:
        candidate = candidate_getter(item)
        cluster_ids = set(query_content_cluster_ids(candidate))
        if cluster_ids and cluster_ids.issubset(covered_cluster_ids):
            cluster_id = primary_content_cluster_id(candidate)
            suppressed.append(
                {
                    "item": item,
                    "cluster_id": cluster_id,
                    "cluster_ids": sorted(cluster_ids),
                    "representative": representatives[cluster_id],
                }
            )
            continue
        kept.append(item)
        for cluster_id in cluster_ids:
            representatives.setdefault(cluster_id, item)
        covered_cluster_ids.update(cluster_ids)
        if limit is not None and len(kept) >= limit:
            break
    return kept, suppressed


def cap_retrieval_cohort(items, rules):
    """Bound one unreviewed release cohort without hiding it from the manifest."""

    limit = rules["retrieval"].get("automatic_expansion_surface_limit")
    if limit is None:
        return list(items), []
    kept = []
    suppressed = []
    automatic_count = 0
    for item in items:
        if item.get("retrieval_cohort") == "automatic_expansion":
            automatic_count += 1
            if automatic_count > limit:
                suppressed.append(item)
                continue
        kept.append(item)
    return kept, suppressed


def search(
    query,
    limit=12,
    mode="hybrid",
    recall_mode="exhaustive",
    manifest_offset=0,
    manifest_limit=DEFAULT_MANIFEST_LIMIT,
    local_personalization=True,
    feedback_dir=None,
    enforce_retrieval_policy=True,
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
    if enforce_retrieval_policy:
        ranked, retrieval_policy = apply_retrieval_policy(
            query,
            ranked,
            expansion,
            knowledge,
            retrieval_guidance,
            rules,
        )
    else:
        for candidate in ranked:
            candidate["retrieval_policy_eligible"] = True
            candidate["retrieval_policy_reasons"] = []
        retrieval_policy = {
            "deferred_to_answer_context_selection": True,
            "eligible_candidate_count": len(ranked),
            "rejected_candidate_count": 0,
            "exhaustive_candidates_preserved": True,
        }
    eligible_ranked = [
        item for item in ranked if item["retrieval_policy_eligible"]
    ]
    cluster_capped_ranked, cluster_suppressed_results = cap_content_clusters(
        eligible_ranked,
    )
    cohort_capped_ranked, cohort_suppressed_results = cap_retrieval_cohort(
        cluster_capped_ranked,
        rules,
    )
    if limit is None:
        surfaced_ranked = cohort_capped_ranked
    elif limit > 0:
        surfaced_ranked = cohort_capped_ranked[:limit]
    else:
        surfaced_ranked = []
    surfaced_video_ids = [
        item["video_id"]
        for item in (surfaced_ranked if manifest_offset == 0 else [])
    ]
    videos = knowledge_video_map(knowledge, surfaced_video_ids)
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
            "cohort_suppressed_result_count": len(
                cohort_suppressed_results
            ),
            "content_cluster_suppressed_result_count": len(
                cluster_suppressed_results
            ),
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
                item["review_priority"]
                in {"deferred_review", "deferred_cohort_review"}
                for item in ranked
            ),
            "cohort_deferred_review_candidate_count": sum(
                item["review_priority"] == "deferred_cohort_review"
                for item in ranked
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
            for item in (surfaced_ranked if manifest_offset == 0 else [])
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
    include_query_match=True,
    chunk_hints_by_video=None,
):
    knowledge, retrieval_index, rules = load_resources()
    videos = knowledge_video_map(knowledge, video_ids)
    records = {item["video_id"]: item for item in retrieval_index["videos"]}
    candidates = {}
    expansion = None
    feedback_guidance = None
    if query:
        expansion = expand_query(query, retrieval_index, rules)
        if include_query_match:
            ranked, expansion = rank_candidates(
                query, knowledge, retrieval_index, rules
            )
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
        transcript_segments = video_transcript_segments(video)
        evidence_video = (
            video
            if video.get("transcript_segments") is not None
            else {**video, "transcript_segments": transcript_segments}
        )
        result = {
            "video_id": video_id,
            "evidence": evidence_descriptor(video),
            "title": video["title"],
            "category": video["category"],
            "confidence": video["confidence"],
            "processing_status": video["processing_status"],
            "answer_eligibility": video.get(
                "answer_eligibility", "primary"
            ),
            "evidence_roles": video.get("evidence_roles", ["context"]),
            "metadata_title_trust": video.get(
                "metadata_title_trust", "not_applicable"
            ),
            "runtime_evidence_mode": video.get(
                "runtime_evidence_mode", "full_transcript"
            ),
            "url": video["url"],
            "duration_seconds": video["duration_seconds"],
            "quality": compact_quality(video.get("quality")),
            "teaching_note": compact_teaching_note(video["teaching_note"]),
            "transcript_evidence": rank_transcript_evidence(
                evidence_video,
                query,
                expansion,
                limit=segment_limit,
                chunk_hints=(chunk_hints_by_video or {}).get(video_id),
            ),
            "retrieval_summary": {
                "topic_ids": record.get("topic_ids", []),
                "lexicon_terms": record.get("lexicon_terms", []),
                "transcript_ngram_count": (
                    record.get("ngram_counts", {}).get("transcript")
                    if "ngram_counts" in record
                    else len(record.get("transcript_ngrams", []))
                ),
                "bundled_transcript_segment_count": len(
                    transcript_segments
                ),
            },
        }
        if result["runtime_evidence_mode"] == "bounded_note_windows":
            result["bounded_note_evidence"] = rank_bounded_note_evidence(
                result["teaching_note"]["evidence"],
                query,
                expansion,
                limit=segment_limit,
            )
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
