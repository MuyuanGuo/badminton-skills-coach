#!/usr/bin/env python3
"""Deterministic mechanical canaries for Bilibili retrieval and answer wiring.

These cases prove that transcript-backed evidence can travel through retrieval,
claim mapping, and packet projection. They are deliberately not semantic gold.
"""

import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence


SCHEMA_VERSION = 2
MEASUREMENT_TYPE = "mechanical_wiring_canary_not_semantic_gold"
DEFAULT_THRESHOLDS = {
    "retrieval_top_k": 5,
    "maximum_packet_bytes": 16384,
    "maximum_top_k_results_per_cluster": 1,
    "maximum_packet_videos_per_cluster": 1,
}


def stable_payload_default(value):
    """Materialize portable lazy containers for canonical JSON hashing."""

    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return list(value)
    raise TypeError(
        f"Object of type {value.__class__.__name__} is not JSON serializable"
    )


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
            default=stable_payload_default,
        ).encode("utf-8")
    ).hexdigest()


def runtime_transcript_segments(video):
    """Return transcript segments from canonical or compact Skill records."""

    segments = video.get("transcript_segments")
    if isinstance(segments, list):
        return segments
    encoded = video.get("transcript_segments_json")
    if not isinstance(encoded, str) or not encoded.strip():
        return []
    try:
        decoded = json.loads(encoded)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return decoded if isinstance(decoded, list) else []


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
                "answer_eligibility": video.get("answer_eligibility"),
                "runtime_evidence_mode": video.get("runtime_evidence_mode"),
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
                    runtime_transcript_segments(video)
                ),
                "bounded_note_sha256": stable_payload_hash(
                    bounded_note_evidence(video)
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


BOUNDED_NOTE_FIELDS = ("key_evidence", "error_evidence", "action_cues")


def bounded_note_evidence(video):
    """Return a stable, role-preserving view of committed note windows."""

    note = video.get("teaching_note") or {}
    merged = defaultdict(set)
    for role in BOUNDED_NOTE_FIELDS:
        for item in note.get(role, []) or []:
            if not isinstance(item, dict):
                continue
            timestamp = str(item.get("timestamp") or "").strip()
            text = str(item.get("text") or "").strip()
            if timestamp and text:
                merged[(timestamp, text)].add(role)
    return [
        {
            "timestamp": timestamp,
            "text": text,
            "roles": sorted(roles),
        }
        for (timestamp, text), roles in sorted(merged.items())
    ]


def bounded_note_anchor(video):
    """Choose one deterministic direct window for a mechanical probe."""

    evidence = bounded_note_evidence(video)
    if not evidence:
        return None
    role_priority = {
        "key_evidence": 0,
        "action_cues": 1,
        "error_evidence": 2,
    }
    selected = min(
        evidence,
        key=lambda item: (
            min(role_priority.get(role, 9) for role in item["roles"]),
            -len(normalize(item["text"])),
            item["timestamp"],
            item["text"],
        ),
    )
    return {
        "timestamp": selected["timestamp"],
        "roles": selected["roles"],
        "text_sha256": hashlib.sha256(
            selected["text"].encode("utf-8")
        ).hexdigest(),
    }


def current_bounded_note_anchor_hash(video, anchor):
    for item in bounded_note_evidence(video):
        if (
            item["timestamp"] == anchor.get("timestamp")
            and item["roles"] == anchor.get("roles")
        ):
            return hashlib.sha256(item["text"].encode("utf-8")).hexdigest()
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
            for segment in runtime_transcript_segments(video)
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
    segments = runtime_transcript_segments(video)
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
        runtime_evidence_mode = video.get(
            "runtime_evidence_mode", "full_transcript"
        )
        if runtime_evidence_mode == "bounded_note_windows":
            anchor = bounded_note_anchor(video)
            evidence = bounded_note_evidence(video)
            if anchor is None:
                exclusions.append(
                    {
                        "evidence_id": evidence_id,
                        "reason": "missing_bounded_note_evidence",
                        "blocking": True,
                    }
                )
                continue
            probe = next(
                item["text"]
                for item in evidence
                if item["timestamp"] == anchor["timestamp"]
                and item["roles"] == anchor["roles"]
            )
            case = {
                "case_id": "bili-mechanical-" + evidence_id.split(":", 1)[-1],
                "measurement_type": MEASUREMENT_TYPE,
                "semantic_gold": False,
                "admission_state": state,
                "evidence_mode": "bounded_note_windows",
                "query": probe,
                "query_derivation": "committed_bounded_note_window",
                "expected_evidence_id": evidence_id,
                "bounded_note_probe": probe,
                "bounded_note_sha256": stable_payload_hash(evidence),
                "bounded_note_anchor": anchor,
            }
            case["case_sha256"] = stable_payload_hash(case)
            cases.append(case)
            continue
        segments = runtime_transcript_segments(video)
        if not segments:
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
        ) or stable_payload_hash(segments)
        anchor_probe = "".join(
            str(segment.get("text") or "")
            for segment in segments[
                anchor["start_segment"]:anchor["end_segment"]
            ]
        ).strip()
        case = {
            "case_id": "bili-mechanical-" + evidence_id.split(":", 1)[-1],
            "measurement_type": MEASUREMENT_TYPE,
            "semantic_gold": False,
            "admission_state": state,
            "evidence_mode": "full_transcript",
            "query": retrieval_title,
            "query_derivation": (
                "cleaned_retrieval_title_with_separate_transcript_anchor_probe"
            ),
            "expected_evidence_id": evidence_id,
            "supported_title_terms": supported_terms,
            "transcript_probe": anchor_probe,
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
            "full-transcript and bounded-note retrieval/packet plumbing, not "
            "coaching semantics."
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
            "evidence_mode",
            "query",
            "expected_evidence_id",
            "case_sha256",
        }
        if not required.issubset(case):
            raise ValueError("Mechanical canary case is incomplete")
        if not case["query"].strip():
            raise ValueError("Mechanical canary case has an empty wiring contract")
        if case["evidence_mode"] == "full_transcript":
            transcript_required = {
                "supported_title_terms",
                "transcript_probe",
                "transcript_sha256",
                "transcript_anchor",
                "expected_chunk_ids",
                "expected_cluster_ids",
            }
            if not transcript_required.issubset(case):
                raise ValueError("Full-transcript mechanical case is incomplete")
            if (
                not case["supported_title_terms"]
                or not case["transcript_probe"].strip()
                or not case["expected_chunk_ids"]
                or not case["expected_cluster_ids"]
            ):
                raise ValueError("Full-transcript canary has an empty contract")
            if not re.fullmatch(r"[0-9a-f]{64}", str(case["transcript_sha256"])):
                raise ValueError("Mechanical canary transcript hash is invalid")
        elif case["evidence_mode"] == "bounded_note_windows":
            note_required = {
                "bounded_note_probe",
                "bounded_note_sha256",
                "bounded_note_anchor",
            }
            if not note_required.issubset(case):
                raise ValueError("Bounded-note mechanical case is incomplete")
            if not case["bounded_note_probe"].strip():
                raise ValueError("Bounded-note canary has an empty probe")
            if not re.fullmatch(
                r"[0-9a-f]{64}", str(case["bounded_note_sha256"])
            ):
                raise ValueError("Mechanical canary bounded-note hash is invalid")
        else:
            raise ValueError("Mechanical canary evidence_mode is invalid")
        expected_hash = stable_payload_hash(
            {key: value for key, value in case.items() if key != "case_sha256"}
        )
        if case["case_sha256"] != expected_hash:
            raise ValueError(f"Mechanical canary case hash is stale: {case['case_id']}")
        case_ids.append(case["case_id"])
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("Mechanical canary case IDs are not unique")
    return registry


def shard_registry(registry, shard_index, shard_count):
    """Return one deterministic modulo shard of a validated registry."""

    validate_registry(registry)
    if shard_count < 1:
        raise ValueError("Mechanical canary shard count must be positive")
    if not 0 <= shard_index < shard_count:
        raise ValueError(
            "Mechanical canary shard index must be within the shard count"
        )
    cases = registry["cases"][shard_index::shard_count]
    if not cases:
        raise ValueError("Mechanical canary shard must contain at least one case")
    return {
        **registry,
        "case_count": len(cases),
        "cases": cases,
    }


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
    segments = runtime_transcript_segments(video)
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
        evidence_mode = case["evidence_mode"]
        retrieval = search_module.search(
            query,
            limit=int(thresholds["retrieval_top_k"]),
            manifest_limit=None,
            local_personalization=False,
        )
        top_results = retrieval.get("results", [])
        top_ids = [item["video_id"] for item in top_results]
        target = next(
            (item for item in top_results if item["video_id"] == expected),
            None,
        )
        manifest_target = next(
            (
                item
                for item in retrieval.get("candidate_manifest", [])
                if item.get("video_id") == expected
            ),
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
            (target or manifest_target or {}).get("transcript_retrieval") or {}
        )
        matched_chunks = set(target_retrieval.get("matched_chunk_ids") or [])
        matched_clusters = set(target_retrieval.get("matched_cluster_ids") or [])
        top_clusters = {
            cluster_id
            for item in top_results
            for cluster_id in (
                (item.get("transcript_retrieval") or {}).get(
                    "matched_cluster_ids",
                    [],
                )
            )
        }
        target_clusters = set(
            target_retrieval.get("matched_cluster_ids") or []
        )
        evidence_probe = (
            case["transcript_probe"]
            if evidence_mode == "full_transcript"
            else case["bounded_note_probe"]
        )
        chunk_hints = (
            {
                expected: [
                    {
                        "start_segment": case["transcript_anchor"][
                            "start_segment"
                        ],
                        "end_segment": case["transcript_anchor"][
                            "end_segment"
                        ],
                    }
                ]
            }
            if evidence_mode == "full_transcript"
            else {}
        )
        anchor_lookup = search_module.lookup_videos(
            [expected],
            query=evidence_probe,
            local_personalization=False,
            include_query_match=False,
            chunk_hints_by_video=chunk_hints,
        )
        anchor_lookup_video = next(
            (
                item
                for item in anchor_lookup.get("results", [])
                if item.get("video_id") == expected
            ),
            None,
        )
        normalized_probe = normalize(evidence_probe)
        lookup_evidence_field = (
            "transcript_evidence"
            if evidence_mode == "full_transcript"
            else "bounded_note_evidence"
        )
        anchor_probe_lookup_hit = bool(
            normalized_probe
            and anchor_lookup_video
            and any(
                normalized_probe in normalize(item.get("text"))
                for item in anchor_lookup_video.get(lookup_evidence_field, [])
            )
        )
        case_failures = []
        video = videos.get(expected)
        if video is None:
            case_failures.append("expected_evidence_missing_from_knowledge")
        elif evidence_mode == "full_transcript":
            current_transcript_hash = (
                (video.get("quality") or {})
                .get("transcript", {})
                .get("integrity", {})
                .get("transcript_sha256")
            ) or stable_payload_hash(runtime_transcript_segments(video))
            if current_transcript_hash != case["transcript_sha256"]:
                case_failures.append("transcript_content_hash_mismatch")
            if (
                current_anchor_hash(video, case["transcript_anchor"])
                != case["transcript_anchor"]["text_sha256"]
            ):
                case_failures.append("transcript_anchor_hash_mismatch")
        else:
            if stable_payload_hash(bounded_note_evidence(video)) != case[
                "bounded_note_sha256"
            ]:
                case_failures.append("bounded_note_content_hash_mismatch")
            if (
                current_bounded_note_anchor_hash(
                    video, case["bounded_note_anchor"]
                )
                != case["bounded_note_anchor"]["text_sha256"]
            ):
                case_failures.append("bounded_note_anchor_hash_mismatch")
        surface_disposition = "surfaced_top_k"
        if expected not in top_ids:
            policy_guarded = bool(
                manifest_target
                and manifest_target.get("retrieval_policy_eligible") is False
                and manifest_target.get("retrieval_policy_reasons")
            )
            cohort_deferred = bool(
                manifest_target
                and manifest_target.get("review_priority")
                == "deferred_cohort_review"
            )
            content_cluster_deferred = bool(
                manifest_target
                and target_clusters
                and target_clusters.issubset(top_clusters)
            )
            if policy_guarded:
                surface_disposition = "policy_guarded_manifest"
            elif cohort_deferred:
                surface_disposition = "cohort_deferred_manifest"
            elif content_cluster_deferred:
                surface_disposition = "content_cluster_deferred_manifest"
            elif evidence_mode == "bounded_note_windows" and anchor_probe_lookup_hit:
                # Supplemental records are not guaranteed a top-k slot when
                # stronger primary evidence already covers an artificial
                # per-window probe.  Their portable direct-lookup contract is
                # still checked above, while realistic admission into answers
                # is covered by the positive supplemental policy canary.
                surface_disposition = "bounded_note_lookup_only"
            else:
                surface_disposition = "unexpectedly_missing_top_k"
        if surface_disposition == "unexpectedly_missing_top_k":
            case_failures.append("expected_evidence_not_in_top_k")
        if not (target or manifest_target) and not (
            evidence_mode == "bounded_note_windows" and anchor_probe_lookup_hit
        ):
            case_failures.append("expected_evidence_missing_from_search_manifest")
        if not anchor_probe_lookup_hit:
            case_failures.append(
                "transcript_anchor_probe_lookup_failed"
                if evidence_mode == "full_transcript"
                else "bounded_note_probe_lookup_failed"
            )
        if evidence_mode == "bounded_note_windows" and bool(mapped) != bool(
            packet_window_ids
        ):
            # Supplemental evidence is intentionally not forced into every
            # answer: primary evidence may already cover the question.  But
            # claim mapping and packet projection must agree whenever policy
            # does select it.  A separate positive policy canary proves that
            # bounded notes can enter answers when they add useful coverage.
            case_failures.append("bounded_note_mapping_packet_mismatch")
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
            "evidence_mode": evidence_mode,
            "retrieval_top_ids": top_ids,
            "retrieval_surface_disposition": surface_disposition,
            "candidate_manifest_found": manifest_target is not None,
            "transcript_chunk_hit": bool(matched_chunks),
            "transcript_anchor_probe_lookup_hit": anchor_probe_lookup_hit,
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
