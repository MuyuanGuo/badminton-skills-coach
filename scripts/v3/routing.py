"""Build the private, globally deduplicated M3 pilot review queue."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable

from v3 import SCHEMA_VERSION
from v3.canonical import atomic_write_json, content_id, sha256_json
from v3.inventory import ANSWER_ELIGIBILITY, source_identity


QUEUE_KIND = "v3-private-pilot-review-queue"
QUEUE_AUTHORITY = "candidate_routing_only"
ELIGIBILITY_RANK = {"supplemental": 1, "primary": 2}
TRANSCRIPT_RANK = {
    "input_missing": 0,
    "embedded_legacy_candidate": 1,
    "local_candidate_present": 2,
}


class _UnionFind:
    def __init__(self, values: Iterable[str]):
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        first, second = sorted((left_root, right_root))
        self.parent[second] = first


def _iter_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _iter_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_strings(child)


def _priority_case_counts(
    payloads: Iterable[Any], known_legacy_ids: set[str]
) -> Counter[str]:
    counts: Counter[str] = Counter()
    for payload in payloads:
        if isinstance(payload, dict) and isinstance(payload.get("cases"), list):
            cases = payload["cases"]
        elif isinstance(payload, list):
            cases = payload
        else:
            cases = [payload]
        for case in cases:
            referenced = set(_iter_strings(case)) & known_legacy_ids
            counts.update(referenced)
    return counts


def _legacy_keys(video: dict[str, Any]) -> set[str]:
    values = {
        str(video.get("video_id") or "").strip(),
        str(video.get("source_video_id") or "").strip(),
        str(video.get("evidence_id") or "").strip(),
    }
    source_video_id = str(video.get("source_video_id") or "").strip()
    if source_video_id:
        values.add(f"bilibili:{source_video_id}")
    return {value for value in values if value}


def _explicit_mirror_targets(video: dict[str, Any]) -> set[str]:
    targets = set()
    parent = str(video.get("parent_source_id") or "").strip()
    if parent:
        targets.add(parent)
    evidence = video.get("possible_duplicate_evidence") or []
    if not isinstance(evidence, list):
        raise ValueError("possible_duplicate_evidence must be a list")
    for item in evidence:
        if not isinstance(item, dict):
            raise ValueError("duplicate evidence entry must be an object")
        target = str(item.get("evidence_id") or "").strip()
        if not target:
            raise ValueError("duplicate evidence entry is missing evidence_id")
        targets.add(target)
    return targets


def _validate_config(
    routing_config: dict[str, Any], quality_gates: dict[str, Any]
) -> tuple[list[dict[str, Any]], int]:
    if routing_config.get("authority") != QUEUE_AUTHORITY:
        raise ValueError("pilot routing config must remain candidate-only")
    rules = routing_config.get("topic_rules")
    if not isinstance(rules, list) or not rules:
        raise ValueError("pilot routing topic rules are missing")
    rule_ids = [str(rule.get("id") or "") for rule in rules]
    if any(not topic_id for topic_id in rule_ids) or len(rule_ids) != len(set(rule_ids)):
        raise ValueError("pilot routing topic ids must be non-empty and unique")
    gate_topics = quality_gates.get("pilot_topics")
    if not isinstance(gate_topics, list):
        raise ValueError("quality-gate pilot topics are missing")
    gate_ids = {str(topic.get("id") or "") for topic in gate_topics}
    if set(rule_ids) != gate_ids:
        raise ValueError("routing topics do not match quality-gate pilot topics")
    budget = routing_config.get("review_budget_per_topic")
    if not isinstance(budget, int) or isinstance(budget, bool) or budget < 1:
        raise ValueError("review_budget_per_topic must be a positive integer")
    normalized = []
    for rule in rules:
        normalized_rule = dict(rule)
        for field in (
            "exact_categories",
            "exact_tags",
            "required_term_groups",
            "excluded_title_terms",
            "generic_categories",
        ):
            if not isinstance(normalized_rule.get(field), list):
                raise ValueError(f"pilot routing rule {rule['id']} has invalid {field}")
        normalized.append(normalized_rule)
    return sorted(normalized, key=lambda item: item["id"]), budget


def _topic_signal(video: dict[str, Any], rule: dict[str, Any]) -> dict[str, Any] | None:
    category = str(video.get("category") or "").strip()
    tags = [str(tag).strip() for tag in (video.get("tags") or []) if str(tag).strip()]
    title = str(video.get("title") or "").strip()
    excluded_title_terms = sorted(
        {term for term in rule["excluded_title_terms"] if term and term in title}
    )
    if excluded_title_terms:
        return None
    metadata_text = " ".join((category, *tags, title))
    exact_category = category in set(rule["exact_categories"])
    exact_tags = sorted(set(tags) & set(rule["exact_tags"]))
    matched_groups = []
    matched_title_groups = []
    for group in rule["required_term_groups"]:
        if not isinstance(group, list) or not group:
            raise ValueError(f"pilot routing rule {rule['id']} has an empty term group")
        matches = sorted({str(term) for term in group if str(term) in metadata_text})
        if not matches:
            matched_groups = []
            break
        matched_groups.append(matches)
        title_matches = sorted({str(term) for term in group if str(term) in title})
        if title_matches:
            matched_title_groups.append(title_matches)
    term_match = bool(rule["required_term_groups"] and matched_groups)
    title_term_match = bool(
        rule["required_term_groups"]
        and len(matched_title_groups) == len(rule["required_term_groups"])
    )
    generic_category = category in set(rule["generic_categories"])
    if title_term_match and (exact_category or exact_tags):
        specificity = 4
        confidence = "high"
    elif title_term_match:
        specificity = 3
        confidence = "medium"
    elif exact_category or exact_tags or term_match:
        specificity = 2
        confidence = "medium"
    elif generic_category:
        specificity = 1
        confidence = "low"
    else:
        return None
    return {
        "topic_id": rule["id"],
        "confidence": confidence,
        "specificity": specificity,
        "candidate_basis": {
            "exact_category": category if exact_category else "",
            "exact_tags": exact_tags,
            "matched_term_groups": matched_groups if term_match else [],
            "matched_title_term_groups": (
                matched_title_groups if title_term_match else []
            ),
            "generic_category": category if generic_category else "",
        },
    }


def _member_priority(
    source: dict[str, Any],
    video: dict[str, Any],
    historical_case_count: int,
) -> dict[str, int]:
    transcript_rank = TRANSCRIPT_RANK.get(source["candidate_transcript_status"], 0)
    review_ready = int(
        transcript_rank == TRANSCRIPT_RANK["local_candidate_present"]
        and source["candidate_media_status"] == "local_candidate_present_unhashed"
    )
    automatic = (video.get("quality") or {}).get("automatic_evidence") or {}
    return {
        "review_ready": review_ready,
        "historical_case_count": historical_case_count,
        "answer_eligibility_rank": ELIGIBILITY_RANK[video["answer_eligibility"]],
        "candidate_transcript_rank": transcript_rank,
        "evidence_role_count": len(set(video.get("evidence_roles") or [])),
        "automatic_key_evidence_count": int(automatic.get("key_evidence_count") or 0),
    }


def _canonical_member_key(member: dict[str, Any]) -> tuple[Any, ...]:
    priority = member["priority"]
    return (
        -int(member["already_published"]),
        -priority["answer_eligibility_rank"],
        -priority["review_ready"],
        -priority["candidate_transcript_rank"],
        member["source_id"],
    )


def _candidate_key(route: dict[str, Any], topic_id: str) -> tuple[Any, ...]:
    priority = route["priority"]
    signal = next(
        item for item in route["candidate_topics"] if item["topic_id"] == topic_id
    )
    return (
        -priority["review_ready"],
        -priority["historical_case_count"],
        -priority["answer_eligibility_rank"],
        -signal["specificity"],
        -priority["candidate_transcript_rank"],
        len(route["candidate_topics"]),
        -priority["evidence_role_count"],
        -priority["automatic_key_evidence_count"],
        route["source_group_id"],
    )


def build_pilot_review_queue(
    *,
    knowledge: dict[str, Any],
    source_config: dict[str, Any],
    inventory: dict[str, Any],
    publication: dict[str, Any],
    routing_config: dict[str, Any],
    quality_gates: dict[str, Any],
    priority_payloads: Iterable[Any] = (),
) -> dict[str, Any]:
    """Route every eligible source before selecting any per-topic review queue."""

    priority_payloads = list(priority_payloads)
    rules, budget = _validate_config(routing_config, quality_gates)
    profile_id = str(source_config.get("profile_id") or "").strip()
    if not profile_id:
        raise ValueError("Douyin source profile identity is missing")
    videos = knowledge.get("videos")
    if not isinstance(videos, list):
        raise ValueError("knowledge base videos are missing")
    inventory_sources = inventory.get("sources")
    if not isinstance(inventory_sources, list):
        raise ValueError("source inventory sources are missing")
    inventory_by_id = {source["source_id"]: source for source in inventory_sources}
    if len(inventory_by_id) != len(inventory_sources):
        raise ValueError("source inventory identities are not unique")
    published_ids = {
        str(source.get("source_id") or "")
        for source in (publication.get("sources") or [])
        if str(source.get("source_id") or "")
    }

    records: dict[str, dict[str, Any]] = {}
    legacy_to_source: dict[str, str] = {}
    for video in videos:
        source_id, platform, native_video_id = source_identity(video, profile_id)
        if source_id in records:
            raise ValueError(f"knowledge source identity is duplicated: {source_id}")
        records[source_id] = {
            "video": video,
            "platform": platform,
            "native_video_id": native_video_id,
        }
        for key in _legacy_keys(video):
            existing = legacy_to_source.get(key)
            if existing is not None and existing != source_id:
                raise ValueError(f"legacy source key is ambiguous: {key}")
            legacy_to_source[key] = source_id

    union = _UnionFind(records)
    for source_id, record in records.items():
        for target in _explicit_mirror_targets(record["video"]):
            target_source = legacy_to_source.get(target)
            if target_source is None:
                raise ValueError(f"explicit mirror target is missing: {target}")
            union.union(source_id, target_source)

    known_legacy_ids = {
        str(source.get("legacy_evidence_id") or "") for source in inventory_sources
    }
    historical_counts = _priority_case_counts(priority_payloads, known_legacy_ids)
    component_ids: dict[str, list[str]] = defaultdict(list)
    for source_id in sorted(records):
        component_ids[union.find(source_id)].append(source_id)

    grouped_routes: list[dict[str, Any]] = []
    eligible_coverage: set[str] = set()
    for member_source_ids in component_ids.values():
        eligible_members = []
        all_urls = []
        for source_id in member_source_ids:
            record = records[source_id]
            video = record["video"]
            url = str(video.get("canonical_url") or video.get("url") or "")
            if url:
                all_urls.append(url)
            if video.get("answer_eligibility") not in ANSWER_ELIGIBILITY:
                continue
            inventory_source = inventory_by_id.get(source_id)
            if inventory_source is None:
                raise ValueError(f"eligible source is missing from inventory: {source_id}")
            legacy_id = str(inventory_source.get("legacy_evidence_id") or "")
            member = {
                "source_id": source_id,
                "platform": record["platform"],
                "native_video_id": record["native_video_id"],
                "knowledge_video_id": str(video.get("video_id") or ""),
                "video": video,
                "inventory": inventory_source,
                "already_published": source_id in published_ids,
                "priority": _member_priority(
                    inventory_source, video, historical_counts[legacy_id]
                ),
            }
            eligible_members.append(member)
            eligible_coverage.add(source_id)
        if not eligible_members:
            continue
        eligible_members.sort(key=_canonical_member_key)
        canonical = eligible_members[0]
        video = canonical["video"]
        inventory_source = canonical["inventory"]
        signals = [
            signal
            for rule in rules
            if (signal := _topic_signal(video, rule)) is not None
        ]
        canonical_url = str(video.get("canonical_url") or video.get("url") or "")
        if not canonical_url.startswith("https://"):
            raise ValueError(f"source canonical URL is invalid: {canonical['source_id']}")
        eligible_source_ids = sorted(member["source_id"] for member in eligible_members)
        group_id = content_id("source_group", eligible_source_ids)
        priority = dict(canonical["priority"])
        priority["routing_specificity_max"] = max(
            (signal["specificity"] for signal in signals), default=0
        )
        grouped_routes.append(
            {
                "source_group_id": group_id,
                "source_id": canonical["source_id"],
                "eligible_source_ids": eligible_source_ids,
                "platform": canonical["platform"],
                "native_video_id": canonical["native_video_id"],
                "knowledge_video_id": canonical["knowledge_video_id"],
                "canonical_url": canonical_url,
                "alternate_urls": sorted(set(all_urls) - {canonical_url}),
                "title": str(video.get("title") or ""),
                "answer_eligibility": video["answer_eligibility"],
                "candidate_transcript_status": inventory_source[
                    "candidate_transcript_status"
                ],
                "candidate_media_status": inventory_source["candidate_media_status"],
                "candidate_transcript_file": str(video.get("transcript_file") or ""),
                "mirror_resolution_status": (
                    "resolved_explicit" if len(member_source_ids) > 1 else "unique"
                ),
                "candidate_topics": sorted(signals, key=lambda item: item["topic_id"]),
                "priority": priority,
                "evidence_status": (
                    "published" if any(member["already_published"] for member in eligible_members)
                    else "candidate_only"
                ),
                "topic_assignment_status": "candidate_needs_human_confirmation",
                "route_status": "pending",
                "assigned_topic": "",
                "queue_rank": None,
            }
        )

    inventory_ids = set(inventory_by_id)
    if eligible_coverage != inventory_ids:
        missing = sorted(inventory_ids - eligible_coverage)[:5]
        unexpected = sorted(eligible_coverage - inventory_ids)[:5]
        raise ValueError(
            "pilot routing inventory coverage mismatch: "
            f"missing={missing}, unexpected={unexpected}"
        )

    grouped_routes.sort(key=lambda route: route["source_group_id"])
    route_by_group = {route["source_group_id"]: route for route in grouped_routes}
    unassigned = {
        route["source_group_id"]
        for route in grouped_routes
        if route["evidence_status"] == "candidate_only" and route["candidate_topics"]
    }
    topic_ids = sorted(rule["id"] for rule in rules)
    assignments: dict[str, list[str]] = {topic_id: [] for topic_id in topic_ids}
    while True:
        available: dict[str, list[dict[str, Any]]] = {}
        for topic_id in topic_ids:
            if len(assignments[topic_id]) >= budget:
                continue
            candidates = [
                route_by_group[group_id]
                for group_id in unassigned
                if any(
                    signal["topic_id"] == topic_id
                    for signal in route_by_group[group_id]["candidate_topics"]
                )
            ]
            if candidates:
                available[topic_id] = candidates
        if not available:
            break
        topic_id = min(
            available,
            key=lambda item: (
                Fraction(
                    len(available[item]),
                    budget - len(assignments[item]),
                ),
                len(available[item]),
                item,
            ),
        )
        selected = min(available[topic_id], key=lambda route: _candidate_key(route, topic_id))
        assignments[topic_id].append(selected["source_group_id"])
        unassigned.remove(selected["source_group_id"])

    topics = []
    for rule in rules:
        topic_id = rule["id"]
        selected_routes = [route_by_group[group_id] for group_id in assignments[topic_id]]
        selected_routes.sort(key=lambda route: _candidate_key(route, topic_id))
        entries = []
        for rank, route in enumerate(selected_routes, start=1):
            route["route_status"] = "queued"
            route["assigned_topic"] = topic_id
            route["queue_rank"] = rank
            entries.append(
                {
                    "queue_rank": rank,
                    "source_group_id": route["source_group_id"],
                    "source_id": route["source_id"],
                    "knowledge_video_id": route["knowledge_video_id"],
                    "platform": route["platform"],
                    "title": route["title"],
                    "candidate_transcript_status": route["candidate_transcript_status"],
                    "candidate_media_status": route["candidate_media_status"],
                    "priority": route["priority"],
                }
            )
        topics.append(
            {
                "topic_id": topic_id,
                "name_zh": rule["name_zh"],
                "review_budget": budget,
                "entries": entries,
            }
        )

    for route in grouped_routes:
        if route["evidence_status"] == "published":
            route["route_status"] = "already_published"
        elif not route["candidate_topics"]:
            route["route_status"] = "out_of_pilot"
        elif route["route_status"] == "pending":
            route["route_status"] = "candidate_not_selected"

    status_counts = Counter(route["route_status"] for route in grouped_routes)
    platform_counts = Counter(
        route["platform"] for route in grouped_routes if route["route_status"] == "queued"
    )
    by_topic = {}
    for topic in topics:
        topic_id = topic["topic_id"]
        candidates = [
            route
            for route in grouped_routes
            if any(signal["topic_id"] == topic_id for signal in route["candidate_topics"])
        ]
        by_topic[topic_id] = {
            "candidate_source_groups": len(candidates),
            "queued_source_groups": len(topic["entries"]),
            "queued_review_ready": sum(
                entry["priority"]["review_ready"] for entry in topic["entries"]
            ),
        }
    body = {
        "schema_version": SCHEMA_VERSION,
        "kind": QUEUE_KIND,
        "authority": QUEUE_AUTHORITY,
        "routing_config_version": routing_config["version"],
        "routing_policy": {
            "all_sources_routed_before_topic_queues": True,
            "explicit_mirrors_count_once": True,
            "platform_weighting": "none",
            "review_budget_is_quality_gate": False,
            "candidate_metadata_is_answer_evidence": False,
            "machine_topic_assignment_is_formal": False,
        },
        "input_fingerprints": {
            "knowledge": sha256_json(knowledge),
            "source_inventory": str(inventory.get("inventory_fingerprint") or sha256_json(inventory)),
            "publication": str(publication.get("publication_fingerprint") or sha256_json(publication)),
            "routing_config": sha256_json(routing_config),
            "quality_gates": sha256_json(quality_gates),
            "priority_signals": sha256_json(list(priority_payloads)),
        },
        "summary": {
            "answer_eligible_sources_considered": len(inventory_sources),
            "answer_eligible_source_groups": len(grouped_routes),
            "explicit_mirror_groups": sum(
                route["mirror_resolution_status"] == "resolved_explicit"
                for route in grouped_routes
            ),
            "by_route_status": dict(sorted(status_counts.items())),
            "by_queued_platform": dict(sorted(platform_counts.items())),
            "by_topic": by_topic,
        },
        "topics": topics,
        "routes": grouped_routes,
    }
    result = dict(body)
    result["routing_fingerprint"] = sha256_json(body)
    validate_pilot_review_queue(result)
    return result


def validate_pilot_review_queue(queue: dict[str, Any]) -> dict[str, int]:
    if queue.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("pilot review queue schema mismatch")
    if queue.get("kind") != QUEUE_KIND or queue.get("authority") != QUEUE_AUTHORITY:
        raise ValueError("pilot review queue authority mismatch")
    body = {key: value for key, value in queue.items() if key != "routing_fingerprint"}
    if queue.get("routing_fingerprint") != sha256_json(body):
        raise ValueError("pilot review queue fingerprint mismatch")
    routes = queue.get("routes")
    topics = queue.get("topics")
    if not isinstance(routes, list) or not isinstance(topics, list):
        raise ValueError("pilot review queue routes and topics must be lists")
    eligible_ids = [source_id for route in routes for source_id in route["eligible_source_ids"]]
    if len(eligible_ids) != len(set(eligible_ids)):
        raise ValueError("an answer-eligible source appears in more than one route")
    queued_groups = [
        entry["source_group_id"] for topic in topics for entry in topic["entries"]
    ]
    if len(queued_groups) != len(set(queued_groups)):
        raise ValueError("a source group appears in more than one topic queue")
    route_by_group = {route["source_group_id"]: route for route in routes}
    if len(route_by_group) != len(routes):
        raise ValueError("pilot review queue group ids are not unique")
    for topic in topics:
        for entry in topic["entries"]:
            route = route_by_group.get(entry["source_group_id"])
            if route is None or route["assigned_topic"] != topic["topic_id"]:
                raise ValueError("topic queue entry does not match its global route")
            if route["evidence_status"] != "candidate_only":
                raise ValueError("published evidence cannot consume a review queue slot")
    summary = queue.get("summary") or {}
    if summary.get("answer_eligible_sources_considered") != len(eligible_ids):
        raise ValueError("pilot review queue source count mismatch")
    if summary.get("answer_eligible_source_groups") != len(routes):
        raise ValueError("pilot review queue group count mismatch")
    serialized = json.dumps(queue, ensure_ascii=False, sort_keys=True)
    for forbidden in ("transcript_segments", "raw_text", "corrected_text", "reviewer_id"):
        if forbidden in serialized:
            raise ValueError(f"pilot review queue leaks forbidden field: {forbidden}")
    return {"sources": len(eligible_ids), "groups": len(routes), "queued": len(queued_groups)}


def write_pilot_review_queue(
    *,
    root: Path,
    output_path: Path,
    knowledge_path: Path | None = None,
    source_config_path: Path | None = None,
    inventory_path: Path | None = None,
    publication_path: Path | None = None,
    routing_config_path: Path | None = None,
    quality_gates_path: Path | None = None,
) -> dict[str, Any]:
    routing_path = routing_config_path or root / "config/v3/pilot-routing.json"
    routing_config = json.loads(routing_path.read_text(encoding="utf-8"))
    priority_payloads = []
    for value in routing_config.get("priority_signal_files") or []:
        relative = Path(str(value))
        resolved = (root / relative).resolve()
        if relative.is_absolute() or not resolved.is_relative_to(root.resolve()):
            raise ValueError("priority signal paths must stay inside the repository")
        priority_payloads.append(json.loads(resolved.read_text(encoding="utf-8")))
    queue = build_pilot_review_queue(
        knowledge=json.loads(
            (knowledge_path or root / "data/knowledge/douyin_knowledge_base.json").read_text(
                encoding="utf-8"
            )
        ),
        source_config=json.loads(
            (source_config_path or root / "config/douyin_source.json").read_text(
                encoding="utf-8"
            )
        ),
        inventory=json.loads(
            (inventory_path or root / "data/v3/source-inventory.json").read_text(
                encoding="utf-8"
            )
        ),
        publication=json.loads(
            (publication_path or root / "data/v3/publication.json").read_text(
                encoding="utf-8"
            )
        ),
        routing_config=routing_config,
        quality_gates=json.loads(
            (quality_gates_path or root / "config/v3/quality-gates.json").read_text(
                encoding="utf-8"
            )
        ),
        priority_payloads=priority_payloads,
    )
    atomic_write_json(output_path, queue, indent=2)
    return queue
