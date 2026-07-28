#!/usr/bin/env python3
"""Deterministic mechanical canaries for Bilibili retrieval and answer wiring.

These cases prove that transcript-backed evidence can travel through retrieval,
claim mapping, and packet projection. They are deliberately not semantic gold.
"""

import hashlib
import json
import re
from collections import Counter, defaultdict


SCHEMA_VERSION = 1
MEASUREMENT_TYPE = "mechanical_wiring_canary_not_semantic_gold"
DEFAULT_THRESHOLDS = {
    "retrieval_top_k": 5,
    "maximum_packet_bytes": 16384,
    "maximum_top_k_results_per_cluster": 1,
    "maximum_packet_videos_per_cluster": 1,
}


def normalize(text):
    return "".join(
        re.findall(r"[\u3400-\u9fff]+|[a-z0-9]+", str(text or "").lower())
    )


def stable_payload_hash(payload):
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def mechanical_knowledge_hash(knowledge):
    """Hash only portable Bilibili wiring inputs, not package-only metadata."""

    records = []
    for video in knowledge.get("videos", []):
        if video.get("source_type") != "bilibili_video":
            continue
        records.append(
            {
                "evidence_id": str(
                    video.get("evidence_id") or video.get("video_id") or ""
                ),
                "processing_status": video.get("processing_status"),
                "promotion_state": video.get("promotion_state"),
                "retrieval_cohort": video.get("retrieval_cohort"),
                "retrieval_title": video.get("retrieval_title")
                or video.get("title"),
                "transcript_sha256": (
                    (video.get("quality") or {})
                    .get("transcript", {})
                    .get("integrity", {})
                    .get("transcript_sha256")
                ),
                "runtime_segments_sha256": stable_payload_hash(
                    video.get("transcript_segments") or []
                ),
            }
        )
    records.sort(key=lambda item: item["evidence_id"])
    return stable_payload_hash(records)


def admission_state(video):
    if video.get("processing_status") == "ready":
        return "ready"
    state = str(video.get("promotion_state") or "")
    disposition = str(
        (video.get("automatic_admission") or {}).get("disposition") or ""
    )
    if state == "shadow" or disposition in {
        "shadow",
        "shadow_quality_gate_passed",
    }:
        return "shadow"
    return None


def video_clusters(retrieval_index):
    records = retrieval_index.get("videos", [])
    chunks = (retrieval_index.get("chunk_index") or {}).get("chunks", [])
    clusters = defaultdict(set)
    chunk_clusters = {}
    for chunk in chunks:
        video_index = chunk.get("video_index")
        if not isinstance(video_index, int) or not 0 <= video_index < len(records):
            continue
        video_id = records[video_index]["video_id"]
        cluster_id = str(chunk.get("cluster_id") or "")
        chunk_id = str(chunk.get("chunk_id") or "")
        if cluster_id:
            clusters[video_id].add(cluster_id)
        if chunk_id and cluster_id:
            chunk_clusters[chunk_id] = cluster_id
    return {
        video_id: sorted(values)
        for video_id, values in clusters.items()
    }, chunk_clusters


def chunks_by_video(retrieval_index):
    records = retrieval_index.get("videos", [])
    grouped = defaultdict(list)
    for chunk in (retrieval_index.get("chunk_index") or {}).get("chunks", []):
        video_index = chunk.get("video_index")
        if not isinstance(video_index, int) or not 0 <= video_index < len(records):
            continue
        grouped[records[video_index]["video_id"]].append(chunk)
    for chunks in grouped.values():
        chunks.sort(key=lambda item: item["chunk_id"])
    return grouped


def configured_supported_terms(video, quality_rules):
    consistency = (
        (video.get("quality") or {})
        .get("transcript", {})
        .get("title_content_consistency", {})
    )
    title = normalize(video.get("retrieval_title") or video.get("title"))
    transcript = normalize(
        "".join(
            str(segment.get("text") or "")
            for segment in video.get("transcript_segments") or []
        )
    )
    terms = (
        list(dict.fromkeys(consistency.get("supported_terms", [])))
        if consistency.get("passed") and consistency.get("supported_terms")
        else (
            quality_rules.get("bilibili_unattended", {})
            .get("title_consistency_terms", [])
        )
    )
    supported = [
        term
        for term in terms
        if normalize(term)
        and normalize(term) in title
        and normalize(term) in transcript
    ]
    if supported:
        return supported
    # A locked legacy transcript may contain a stable ASR confusion such as
    # 单打→丹达, leaving the configured title term unsupported even though a
    # longer neutral phrase (for example 核心思路) is shared. Use one
    # deterministic common substring only to construct a mechanical probe;
    # it is not a semantic judgment or a quality-gate override.
    for length in range(min(8, len(title)), 1, -1):
        for start in range(len(title) - length + 1):
            candidate = title[start:start + length]
            if candidate in transcript:
                return [candidate]
    return []


def transcript_anchor(video, supported_terms):
    segments = video.get("transcript_segments") or []
    normalized_terms = {
        term: normalize(term) for term in supported_terms if normalize(term)
    }
    ranked = []
    for center in range(len(segments)):
        start = max(0, center - 1)
        end = min(len(segments), center + 2)
        selected = segments[start:end]
        text = "".join(str(item.get("text") or "") for item in selected)
        normalized_text = normalize(text)
        matched = sorted(
            (
                term
                for term, normalized_term in normalized_terms.items()
                if normalized_term in normalized_text
            ),
            key=lambda term: (-len(normalize(term)), term),
        )
        if not matched:
            continue
        ranked.append(
            (
                -len(matched),
                -sum(len(normalize(term)) for term in matched),
                start,
                end,
                text,
                matched,
            )
        )
    if not ranked:
        return None
    _, _, start, end, text, matched = min(ranked)
    selected = segments[start:end]
    return {
        "start_segment": start,
        "end_segment": end,
        "start_seconds": round(float(selected[0].get("start") or 0), 3),
        "end_seconds": round(
            float(selected[-1].get("end") or selected[-1].get("start") or 0),
            3,
        ),
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "matched_terms": matched,
    }


def anchor_chunks(anchor, chunks):
    matched = [
        chunk
        for chunk in chunks
        if int(chunk.get("start_segment", 0)) < anchor["end_segment"]
        and int(chunk.get("end_segment", 0)) > anchor["start_segment"]
    ]
    return {
        "chunk_ids": sorted(
            str(chunk["chunk_id"]) for chunk in matched if chunk.get("chunk_id")
        ),
        "cluster_ids": sorted(
            {
                str(chunk["cluster_id"])
                for chunk in matched
                if chunk.get("cluster_id")
            }
        ),
    }


def generate_registry(
    knowledge,
    retrieval_index,
    quality_rules,
    *,
    thresholds=None,
):
    thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    grouped_chunks = chunks_by_video(retrieval_index)
    cases = []
    exclusions = []
    for video in sorted(
        knowledge.get("videos", []),
        key=lambda item: str(item.get("evidence_id") or item.get("video_id")),
    ):
        evidence_id = str(video.get("evidence_id") or video.get("video_id") or "")
        if video.get("source_type") != "bilibili_video":
            continue
        state = admission_state(video)
        if state is None:
            continue
        if not video.get("transcript_segments"):
            exclusions.append(
                {
                    "evidence_id": evidence_id,
                    "reason": "missing_runtime_transcript_segments",
                    "blocking": True,
                }
            )
            continue
        retrieval_title = str(
            video.get("retrieval_title") or video.get("title") or ""
        ).strip()
        supported_terms = configured_supported_terms(video, quality_rules)
        anchor = transcript_anchor(video, supported_terms)
        if not retrieval_title or anchor is None:
            exclusions.append(
                {
                    "evidence_id": evidence_id,
                    "reason": (
                        "missing_cleaned_retrieval_title"
                        if not retrieval_title
                        else "no_transcript_supported_title_anchor"
                    ),
                    "blocking": (
                        not retrieval_title
                        or video.get("retrieval_cohort")
                        == "automatic_expansion"
                    ),
                }
            )
            continue
        expected = anchor_chunks(anchor, grouped_chunks.get(evidence_id, []))
        if not expected["chunk_ids"] or not expected["cluster_ids"]:
            exclusions.append(
                {
                    "evidence_id": evidence_id,
                    "reason": "missing_chunk_for_transcript_anchor",
                    "blocking": True,
                }
            )
            continue
        transcript_hash = (
            (video.get("quality") or {})
            .get("transcript", {})
            .get("integrity", {})
            .get("transcript_sha256")
        ) or stable_payload_hash(video.get("transcript_segments") or [])
        case = {
            "case_id": "bili-mechanical-" + evidence_id.split(":", 1)[-1],
            "measurement_type": MEASUREMENT_TYPE,
            "semantic_gold": False,
            "admission_state": state,
            "query": retrieval_title,
            "query_derivation": (
                "cleaned_retrieval_title_with_transcript_supported_terms"
            ),
            "expected_evidence_id": evidence_id,
            "supported_title_terms": supported_terms,
            "transcript_sha256": transcript_hash,
            "transcript_anchor": anchor,
            "expected_chunk_ids": expected["chunk_ids"],
            "expected_cluster_ids": expected["cluster_ids"],
        }
        case["case_sha256"] = stable_payload_hash(case)
        cases.append(case)
    return {
        "schema_version": SCHEMA_VERSION,
        "measurement_type": MEASUREMENT_TYPE,
        "semantic_gold": False,
        "description": (
            "Automatically generated mechanical wiring checks. Passing proves "
            "transcript-backed retrieval and packet plumbing, not coaching semantics."
        ),
        "source": {
            "knowledge_sha256": mechanical_knowledge_hash(knowledge),
            "retrieval_index_sha256": stable_payload_hash(retrieval_index),
        },
        "thresholds": thresholds,
        "case_count": len(cases),
        "excluded_count": len(exclusions),
        "cases": cases,
        "exclusions": exclusions,
    }


def validate_registry(registry):
    if registry.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported Bilibili mechanical canary schema")
    if (
        registry.get("measurement_type") != MEASUREMENT_TYPE
        or registry.get("semantic_gold") is not False
    ):
        raise ValueError("Mechanical canaries cannot claim semantic gold")
    if registry.get("case_count") != len(registry.get("cases", [])):
        raise ValueError("Mechanical canary case_count is stale")
    if registry.get("excluded_count") != len(registry.get("exclusions", [])):
        raise ValueError("Mechanical canary excluded_count is stale")
    required_thresholds = set(DEFAULT_THRESHOLDS)
    if not required_thresholds.issubset(registry.get("thresholds", {})):
        raise ValueError("Mechanical canary thresholds are incomplete")
    case_ids = []
    for case in registry.get("cases", []):
        if (
            case.get("measurement_type") != MEASUREMENT_TYPE
            or case.get("semantic_gold") is not False
        ):
            raise ValueError("A mechanical case claims semantic gold")
        required = {
            "case_id",
            "query",
            "expected_evidence_id",
            "supported_title_terms",
            "transcript_anchor",
            "expected_chunk_ids",
            "expected_cluster_ids",
            "case_sha256",
        }
        if not required.issubset(case):
            raise ValueError("Mechanical canary case is incomplete")
        if (
            not case["query"].strip()
            or not case["supported_title_terms"]
            or not case["expected_chunk_ids"]
            or not case["expected_cluster_ids"]
        ):
            raise ValueError("Mechanical canary case has an empty wiring contract")
        if not re.fullmatch(r"[0-9a-f]{64}", str(case["transcript_sha256"])):
            raise ValueError("Mechanical canary transcript hash is invalid")
        expected_hash = stable_payload_hash(
            {key: value for key, value in case.items() if key != "case_sha256"}
        )
        if case["case_sha256"] != expected_hash:
            raise ValueError(f"Mechanical canary case hash is stale: {case['case_id']}")
        case_ids.append(case["case_id"])
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("Mechanical canary case IDs are not unique")
    return registry


def packet_bytes(packet):
    return len(
        json.dumps(
            packet,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def packet_cluster_violations(packet, cluster_ids_by_video, maximum):
    counts = Counter()
    for video in packet.get("selected_videos", []):
        evidence_id = str(video.get("evidence_id") or video.get("video_id") or "")
        for cluster_id in cluster_ids_by_video.get(evidence_id, []):
            counts[cluster_id] += 1
    return {
        cluster_id: count
        for cluster_id, count in sorted(counts.items())
        if count > maximum
    }


def top_k_cluster_violations(
    results,
    chunk_cluster_by_id,
    maximum,
):
    counts = Counter()
    for result in results:
        retrieval = result.get("transcript_retrieval") or {}
        best_chunk_id = retrieval.get("best_chunk_id")
        cluster_id = chunk_cluster_by_id.get(best_chunk_id)
        if cluster_id is None:
            matched = retrieval.get("matched_cluster_ids") or []
            cluster_id = matched[0] if matched else None
        if cluster_id:
            counts[cluster_id] += 1
    return {
        cluster_id: count
        for cluster_id, count in sorted(counts.items())
        if count > maximum
    }


def current_anchor_hash(video, anchor):
    segments = video.get("transcript_segments") or []
    start = int(anchor["start_segment"])
    end = int(anchor["end_segment"])
    if not 0 <= start < end <= len(segments):
        return None
    text = "".join(
        str(segment.get("text") or "") for segment in segments[start:end]
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def evaluate_registry(
    registry,
    search_module,
    context_runtime,
    *,
    knowledge=None,
    retrieval_index=None,
    validate_source_hashes=True,
):
    validate_registry(registry)
    if knowledge is None or retrieval_index is None:
        loaded_knowledge, loaded_index, _ = search_module.load_resources()
        knowledge = knowledge or loaded_knowledge
        retrieval_index = retrieval_index or loaded_index
    thresholds = registry["thresholds"]
    global_failures = []
    blocking_exclusions = [
        item
        for item in registry.get("exclusions", [])
        if item.get("blocking", True)
    ]
    if blocking_exclusions:
        global_failures.append(
            "blocking_mechanical_case_generation_exclusions_present"
        )
    if validate_source_hashes:
        if (
            registry["source"]["knowledge_sha256"]
            != mechanical_knowledge_hash(knowledge)
        ):
            global_failures.append("knowledge_source_hash_mismatch")
        if (
            registry["source"]["retrieval_index_sha256"]
            != stable_payload_hash(retrieval_index)
        ):
            global_failures.append("retrieval_index_source_hash_mismatch")
    videos = {
        str(video.get("evidence_id") or video.get("video_id")): video
        for video in knowledge.get("videos", [])
    }
    _, chunk_cluster_by_id = video_clusters(retrieval_index)
    results = []
    failures = []
    for case in registry["cases"]:
        query = case["query"]
        expected = case["expected_evidence_id"]
        retrieval = search_module.search(
            query,
            limit=int(thresholds["retrieval_top_k"]),
            local_personalization=False,
        )
        top_results = retrieval.get("results", [])
        top_ids = [item["video_id"] for item in top_results]
        target = next(
            (item for item in top_results if item["video_id"] == expected),
            None,
        )
        context = context_runtime.prepare_answer_context(
            query,
            local_personalization=False,
        )
        mapped = [
            evidence
            for claim in context.get("claim_evidence_map", [])
            for evidence in claim.get("evidence", [])
            if evidence.get("evidence_id") == expected
        ]
        packet = context_runtime.build_answer_packet(context)
        packet_video = next(
            (
                item
                for item in packet.get("selected_videos", [])
                if item.get("evidence_id") == expected
            ),
            None,
        )
        packet_window_ids = (
            packet_video.get("window_ids", []) if packet_video else []
        )
        target_retrieval = (
            target.get("transcript_retrieval", {}) if target else {}
        )
        matched_chunks = set(target_retrieval.get("matched_chunk_ids") or [])
        matched_clusters = set(target_retrieval.get("matched_cluster_ids") or [])
        case_failures = []
        video = videos.get(expected)
        if video is None:
            case_failures.append("expected_evidence_missing_from_knowledge")
        else:
            current_transcript_hash = (
                (video.get("quality") or {})
                .get("transcript", {})
                .get("integrity", {})
                .get("transcript_sha256")
            ) or stable_payload_hash(video.get("transcript_segments") or [])
            if current_transcript_hash != case["transcript_sha256"]:
                case_failures.append("transcript_content_hash_mismatch")
            if (
                current_anchor_hash(video, case["transcript_anchor"])
                != case["transcript_anchor"]["text_sha256"]
            ):
                case_failures.append("transcript_anchor_hash_mismatch")
        if expected not in top_ids:
            case_failures.append("expected_evidence_not_in_top_k")
        if (
            not target
            or target_retrieval.get("mode") != "chunk_first"
            or not matched_chunks
        ):
            case_failures.append("expected_evidence_missing_transcript_chunk_hit")
        if not matched_clusters:
            case_failures.append("expected_evidence_missing_content_cluster_hit")
        size = packet_bytes(packet)
        if size > int(thresholds["maximum_packet_bytes"]):
            case_failures.append("packet_exceeds_absolute_byte_budget")
        top_cluster_violations = top_k_cluster_violations(
            top_results,
            chunk_cluster_by_id,
            int(thresholds["maximum_top_k_results_per_cluster"]),
        )
        query_clusters_by_video = {
            item["video_id"]: (
                item.get("transcript_retrieval", {}).get(
                    "matched_cluster_ids",
                    [],
                )
            )
            for item in top_results
        }
        if top_cluster_violations:
            case_failures.append("top_k_content_cluster_duplicate_limit_exceeded")
        packet_cluster_duplicates = packet_cluster_violations(
            packet,
            query_clusters_by_video,
            int(thresholds["maximum_packet_videos_per_cluster"]),
        )
        if packet_cluster_duplicates:
            case_failures.append("packet_content_cluster_duplicate_limit_exceeded")
        result = {
            "case_id": case["case_id"],
            "measurement_type": MEASUREMENT_TYPE,
            "semantic_gold": False,
            "query": query,
            "expected_evidence_id": expected,
            "retrieval_top_ids": top_ids,
            "transcript_chunk_hit": bool(matched_chunks),
            "matched_chunk_ids": sorted(matched_chunks),
            "matched_cluster_ids": sorted(matched_clusters),
            "claim_mapped": bool(mapped),
            "packet_window_count": len(packet_window_ids),
            "packet_bytes": size,
            "top_k_cluster_violations": top_cluster_violations,
            "packet_cluster_violations": packet_cluster_duplicates,
            "failures": case_failures,
        }
        results.append(result)
        failures.extend(
            {"case_id": case["case_id"], "reason": reason}
            for reason in case_failures
        )
    failures.extend(
        {"case_id": None, "reason": reason} for reason in global_failures
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "measurement_type": MEASUREMENT_TYPE,
        "semantic_gold": False,
        "case_count": len(results),
        "passed": not failures,
        "failure_count": len(failures),
        "global_failures": global_failures,
        "thresholds": thresholds,
        "results": results,
        "failures": failures,
    }
