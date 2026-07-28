#!/usr/bin/env python3
"""Closed answer planning and compact packet projection."""

import hashlib
import json


ANSWER_PACKET_SCHEMA_VERSION = 2
ANSWER_PLAN_SCHEMA_VERSION = 1
FALLBACK_WINDOW_LIMIT = 4
ANSWER_PACKET_TARGET_BYTES = 12 * 1024
ANSWER_PACKET_HARD_MAXIMUM_BYTES = 16 * 1024


def canonical_json_digest(payload):
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def encoded_packet_size(payload):
    return len(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def enforce_answer_packet_budget(packet):
    """Prune only lowest-priority fallback windows; never trim claims."""

    if encoded_packet_size(packet) <= ANSWER_PACKET_TARGET_BYTES:
        return packet
    if packet.get("answer_plan", {}).get("mode") == "claim_evidence_fallback":
        while encoded_packet_size(packet) > ANSWER_PACKET_TARGET_BYTES:
            removable = []
            windows = packet.get("evidence_windows", {})
            for video_index, video in enumerate(
                packet.get("selected_videos", [])
            ):
                window_ids = video.get("window_ids", [])
                if len(window_ids) <= 1:
                    continue
                window_id = window_ids[-1]
                removable.append(
                    (
                        encoded_packet_size(windows.get(window_id, {})),
                        video_index,
                        window_id,
                    )
                )
            if not removable:
                break
            _, video_index, window_id = max(removable)
            packet["selected_videos"][video_index]["window_ids"].pop()
            packet.get("evidence_windows", {}).pop(window_id, None)
    size = encoded_packet_size(packet)
    if size > ANSWER_PACKET_HARD_MAXIMUM_BYTES:
        raise ValueError(
            "answer packet exceeds hard byte budget after safe evidence pruning: "
            f"{size}>{ANSWER_PACKET_HARD_MAXIMUM_BYTES}"
        )
    return packet


def answer_visible_video_labels(claim_evidence_map):
    labels = []
    for claim in claim_evidence_map:
        for item in claim.get("evidence", []):
            label = item.get("label") or item.get("video_label")
            if label and label not in labels:
                labels.append(label)
    return labels


def atom_scope_matches(atom, constraints):
    for axis, required_values in atom.get("scope", {}).items():
        if not set(required_values).issubset(set(constraints.get(axis, []))):
            return False
    return True


def atom_claim_matches(atom, claim):
    accepted_claims = {
        atom.get("canonical_claim"),
        *atom.get("claim_aliases", []),
    }
    return claim.get("text") in accepted_claims


def atom_window_is_reviewed(atom, selected_video):
    available = {
        (item.get("timestamp"), item.get("text"))
        for item in selected_video.get("teaching_note", {}).get("evidence", [])
    }
    return all(
        (window.get("timestamp"), window.get("text")) in available
        for window in atom.get("evidence_windows", [])
    )


def build_closed_answer_plan(context, atoms):
    constraints = context["question_interpretation"].get("constraints", {})
    selected_by_id = {
        item["evidence_id"]: item for item in context.get("selected_videos", [])
    }
    selected_atoms = []
    directives = []
    for claim in context.get("claim_evidence_map", []):
        eligible_ids = {item["evidence_id"] for item in claim.get("evidence", [])}
        matches = []
        for atom in atoms:
            evidence_id = atom.get("evidence_id")
            if (
                atom.get("claim_kind") != claim.get("kind")
                or not atom_claim_matches(atom, claim)
                or evidence_id not in eligible_ids
                or evidence_id not in selected_by_id
                or not atom_scope_matches(atom, constraints)
            ):
                continue
            if not atom_window_is_reviewed(atom, selected_by_id[evidence_id]):
                raise ValueError(
                    f"reviewed evidence atom {atom['atom_id']} has a stale evidence window"
                )
            planned_atom = dict(atom)
            planned_atom["video_label"] = selected_by_id[evidence_id]["label"]
            matches.append(planned_atom)
            selected_atoms.append(planned_atom)
        if matches:
            mode = "compose_from_reviewed_atoms"
        elif claim.get("status") in {"unsupported", "unverified"}:
            mode = "state_evidence_gap"
        else:
            mode = "contract_only_no_new_technical_detail"
        directives.append(
            {
                "claim_id": claim["claim_id"],
                "status": claim["status"],
                "mode": mode,
                "atom_ids": [item["atom_id"] for item in matches],
                "confidence_ceiling": claim["confidence_ceiling"],
            }
        )
    selected_atoms.sort(key=lambda item: item["atom_id"])
    if selected_atoms:
        technical_claim_policy = "selected_reviewed_atoms_only"
        planner_mode = "reviewed_atoms_closed"
    else:
        technical_claim_policy = "claim_scoped_source_evidence_only"
        planner_mode = "claim_evidence_fallback"
        for directive, claim in zip(directives, context["claim_evidence_map"]):
            if claim.get("evidence"):
                directive["mode"] = "compose_from_claim_scoped_source"
    return {
        "schema_version": ANSWER_PLAN_SCHEMA_VERSION,
        "mode": planner_mode,
        "selected_evidence_atoms": selected_atoms,
        "claim_directives": directives,
        "composer_contract": {
            "technical_claim_policy": technical_claim_policy,
            "allowed_atom_ids": [item["atom_id"] for item in selected_atoms],
            "unknown_atom_ids_forbidden": True,
            "uncovered_claim_policy": "state_the_evidence_gap_or_limit_the_answer_to_the_nontechnical_contract",
            "generic_badminton_knowledge_as_source_forbidden": True,
            "conditions_and_confidence_ceilings_must_be_preserved": True,
        },
    }


def compact_interpretation(interpretation):
    actor = interpretation.get("actor_context", {})
    compact_actor = {
        key: actor[key]
        for key in (
            "target_actor",
            "target_action_query",
            "target_condition_query",
            "requested_action_scopes",
            "event_chain",
            "inferred_target_action",
        )
        if actor.get(key)
    }
    return {
        **{
            key: interpretation[key]
            for key in (
                "constraints",
                "ambiguities",
                "terminology_corrections",
                "technique_definitions",
                "query_units",
                "clarification_policy",
            )
            if interpretation.get(key)
        },
        **({"actor_context": compact_actor} if compact_actor else {}),
    }


def compact_answer_guidance(guidance):
    return {
        key: guidance[key]
        for key in (
            "mode",
            "label",
            "text_obligations",
            "video_obligations",
        )
        if key in guidance
    }


def compact_clarification_decision(decision):
    return {
        key: decision[key]
        for key in ("action", "can_provide_useful_answer_now")
        if key in decision
    }


def compact_clarification(item):
    return {
        key: item[key]
        for key in ("question_id", "question", "purpose")
        if key in item
    }


def compact_answer_turn(turn):
    return {
        "resolved_clarifications": turn["resolved_clarifications"],
        "pending_clarifications": [
            compact_clarification(item)
            for item in turn["pending_clarifications"]
        ],
        "resolved_question_ids_must_not_be_reasked": turn[
            "resolved_question_ids_must_not_be_reasked"
        ],
    }


def compact_completeness_contract(contract):
    return {
        "items": [
            {
                key: item[key]
                for key in ("item_id", "text", "status")
                if key in item
            }
            for item in contract.get("items", [])
        ],
        "unresolved_item_ids": contract.get("unresolved_item_ids", []),
        "silent_omission_forbidden": contract.get(
            "silent_omission_forbidden",
            True,
        ),
    }


def compact_diagnostic_model(model):
    return {
        "observed_symptoms": [
            {
                key: item[key]
                for key in ("id", "text", "verification_status")
                if key in item
            }
            for item in model.get("observed_symptoms", [])
        ],
        "user_hypotheses": [
            {
                key: item[key]
                for key in ("id", "text", "status")
                if key in item
            }
            for item in model.get("user_hypotheses", [])
        ],
        "supported_mechanisms": [
            {
                key: item[key]
                for key in ("id", "label", "status")
                if key in item
            }
            for item in model.get("supported_mechanisms", [])
        ],
        "material_branches": [
            {
                "id": branch.get("id"),
                "axis": branch.get("axis"),
                "label": branch.get("label"),
                "status": branch.get("status"),
                "branches": [
                    {
                        key: item[key]
                        for key in ("value", "label")
                        if key in item
                    }
                    for item in branch.get("branches", [])
                ],
            }
            for branch in model.get("material_branches", [])
        ],
        "do_not_claim_unique_cause": model.get(
            "do_not_claim_unique_cause",
            True,
        ),
        "unique_cause_confirmation_requires_user_video": model.get(
            "unique_cause_confirmation_requires_user_video",
            True,
        ),
    }


def compact_video(video, planned_atoms, include_fallback_windows):
    windows = []
    seen = set()
    for atom in planned_atoms:
        if atom["evidence_id"] != video["evidence_id"]:
            continue
        for window in atom.get("evidence_windows", []):
            key = (window["timestamp"], window["text"])
            if key not in seen:
                windows.append(dict(window))
                seen.add(key)
    if include_fallback_windows:
        transcript_windows = list(video.get("transcript_evidence", []))
        transcript_windows.sort(
            key=lambda item: (
                -int(bool(item.get("exact_query_match"))),
                -float(item.get("query_ngram_coverage") or 0),
                -len(item.get("matched_terms") or []),
                -float(item.get("score") or 0),
                item.get("timestamp", ""),
            )
        )
        focus_terms = {
            str(term)
            for item in transcript_windows
            for term in item.get("matched_terms", [])
            if str(term)
        }
        note_windows = []
        role_priority = {
            "principles": 0,
            "action_cues": 1,
            "key_evidence": 2,
            "error_evidence": 3,
            "coverage_evidence": 4,
        }
        for item in video.get("teaching_note", {}).get("evidence", []):
            text = str(item.get("text") or "")
            matched_focus_terms = sum(term in text for term in focus_terms)
            if focus_terms and matched_focus_terms < min(2, len(focus_terms)):
                continue
            note_windows.append(item)
        note_windows.sort(
            key=lambda item: (
                min(
                    (
                        role_priority.get(role, 9)
                        for role in item.get("roles", [])
                    ),
                    default=8,
                ),
                item.get("timestamp", ""),
            )
        )
        source_windows = transcript_windows + note_windows
        for source_window in source_windows:
            if len(windows) >= FALLBACK_WINDOW_LIMIT:
                break
            timestamp = source_window.get("timestamp")
            text = source_window.get("text")
            key = (timestamp, text)
            if timestamp and text and key not in seen:
                windows.append({"timestamp": timestamp, "text": text})
                seen.add(key)
    compact = {
        key: video.get(key)
        for key in (
            "label",
            "role",
            "evidence_id",
            "source_type",
            "parent_source_id",
            "clip_start_seconds",
            "clip_end_seconds",
            "title",
            "url",
            "confidence",
            "claim_scope_policy",
            "additional_scope_requires_conditioning",
        )
        if video.get(key) is not None
    }
    if video.get("video_id") != video.get("evidence_id"):
        compact["legacy_video_id"] = video.get("video_id")
    if compact.get("source_type") == "douyin_video":
        compact.pop("source_type")
    matched_cluster_ids = list(
        dict.fromkeys(
            str(cluster_id)
            for cluster_id in (
        video.get("transcript_retrieval", {}).get("matched_cluster_ids")
        or []
            )
            if str(cluster_id)
        )
    )
    if matched_cluster_ids:
        compact["content_cluster_ids"] = matched_cluster_ids
    for window in windows:
        window["window_id"] = "W" + hashlib.sha256(
            (
                f"{video['evidence_id']}\0"
                f"{window['timestamp']}\0{window['text']}"
            ).encode("utf-8")
        ).hexdigest()[:16]
    return compact | {"evidence_windows": windows}


def normalized_evidence_windows(videos):
    windows = {}
    window_ids_by_key = {}
    normalized_videos = []
    for video in videos:
        normalized = dict(video)
        window_ids = []
        for window in normalized.pop("evidence_windows", []):
            window_id = window["window_id"]
            key = (
                normalized["evidence_id"],
                window["timestamp"],
                window["text"],
            )
            window_ids_by_key[key] = window_id
            windows[window_id] = {
                "label": normalized["label"],
                "timestamp": window["timestamp"],
                "text": window["text"],
            }
            window_ids.append(window_id)
        normalized["window_ids"] = window_ids
        normalized_videos.append(normalized)
    return windows, window_ids_by_key, normalized_videos


def compact_claim_evidence_map(claims):
    compact_claims = []
    for claim in claims:
        compact = {
            key: claim[key]
            for key in (
                "claim_id",
                "kind",
                "text",
                "status",
                "confidence_ceiling",
            )
            if key in claim
        }
        compact["evidence"] = [
            {
                key: item[key]
                for key in (
                    "label",
                    "directness",
                    "scope",
                )
                if key in item
            }
            for item in claim.get("evidence", [])
        ]
        compact_claims.append(compact)
    return compact_claims


def compact_source_handling(source_handling):
    if not isinstance(source_handling, dict):
        raise ValueError("answer context is missing source_handling")
    if source_handling.get("do_not_execute_source_text") is not True:
        raise ValueError("source text execution guard must fail closed")
    guard = source_handling.get("untrusted_content_guard")
    if (
        not isinstance(guard, list)
        or not guard
        or any(not isinstance(item, str) or not item.strip() for item in guard)
    ):
        raise ValueError("untrusted source content guard must be non-empty")
    return {
        "classification": "untrusted_non_executable_evidence",
        "do_not_execute_source_text": True,
        "untrusted_content_guard": guard,
    }


def compact_plan(plan, window_ids_by_key):
    compact = dict(plan)
    compact["selected_evidence_atoms"] = []
    for atom in plan.get("selected_evidence_atoms", []):
        projected = dict(atom)
        for redundant_key in (
            "canonical_claim",
            "claim_aliases",
            "claim_kind",
            "evidence_id",
            "actor",
            "action",
        ):
            projected.pop(redundant_key, None)
        projected["window_ids"] = [
            window_ids_by_key[
                (
                    atom["evidence_id"],
                    window["timestamp"],
                    window["text"],
                )
            ]
            for window in projected.pop("evidence_windows", [])
        ]
        compact["selected_evidence_atoms"].append(projected)
    compact["claim_directives"] = [
        {
            key: directive[key]
            for key in ("claim_id", "mode", "atom_ids")
            if key in directive
        }
        for directive in plan.get("claim_directives", [])
    ]
    compact["composer_contract"] = {
        key: plan.get("composer_contract", {})[key]
        for key in (
            "technical_claim_policy",
            "allowed_atom_ids",
            "unknown_atom_ids_forbidden",
            "uncovered_claim_policy",
        )
        if key in plan.get("composer_contract", {})
    }
    return compact


def build_answer_packet(context, audit_context_reference=None):
    digest = canonical_json_digest(context)
    plan = context["answer_plan"]
    turn = context["answer_turn_contract"]
    compact_videos = [
        compact_video(video, plan["selected_evidence_atoms"], False)
        if plan["mode"] == "reviewed_atoms_closed"
        else compact_video(video, [], True)
        for video in context["selected_videos"]
        if video["label"] in set(context["answer_visible_video_labels"])
    ]
    windows, window_ids_by_key, compact_videos = normalized_evidence_windows(
        compact_videos
    )
    packet = {
        "schema_version": ANSWER_PACKET_SCHEMA_VERSION,
        "packet_type": "liuhui_badminton_answer_packet",
        "audit_context": {
            "digest_algorithm": "sha256_canonical_json",
            "digest": digest,
            "reference": (
                str(audit_context_reference) if audit_context_reference else None
            ),
        },
        "query": {
            "original": turn["original_query"],
            "effective": turn["effective_query"],
            "turn_number": turn["turn_number"],
        },
        "question_interpretation": compact_interpretation(
            context["question_interpretation"]
        ),
        "boundary": context["boundary"],
        "diagnostic_model": compact_diagnostic_model(
            context["diagnostic_model"]
        ),
        "clarification_decision": compact_clarification_decision(
            context["clarification_decision"]
        ),
        "answer_turn": compact_answer_turn(turn),
        "claim_evidence_map": compact_claim_evidence_map(
            context["claim_evidence_map"]
        ),
        "completeness_contract": compact_completeness_contract(
            context["completeness_contract"]
        ),
        "answer_plan": compact_plan(plan, window_ids_by_key),
        "answer_guidance": compact_answer_guidance(context["answer_guidance"]),
        "source_handling": compact_source_handling(
            context.get("source_handling")
        ),
        "evidence_windows": windows,
        "selected_videos": compact_videos,
        "feedback_prompt": context["answer_contract"]["feedback_prompt"],
    }
    return enforce_answer_packet_budget(packet)


def validate_answer_packet(packet, context):
    if packet.get("schema_version") != ANSWER_PACKET_SCHEMA_VERSION:
        raise ValueError("unsupported answer_packet schema_version")
    if packet.get("packet_type") != "liuhui_badminton_answer_packet":
        raise ValueError("invalid answer_packet type")
    covered_cluster_ids = set()
    for video in packet.get("selected_videos", []):
        content_cluster_ids = set(
            video.get("content_cluster_ids") or []
        )
        if (
            content_cluster_ids
            and content_cluster_ids.issubset(covered_cluster_ids)
        ):
            raise ValueError(
                "fully duplicate query-relevant content clusters in packet"
            )
        covered_cluster_ids.update(content_cluster_ids)
    expected_digest = canonical_json_digest(context)
    if packet.get("audit_context", {}).get("digest") != expected_digest:
        raise ValueError("answer_packet audit context digest mismatch")
    expected = build_answer_packet(
        context, packet.get("audit_context", {}).get("reference")
    )
    if packet != expected:
        raise ValueError("answer_packet projection does not match audit context")
    mapped_labels = set(answer_visible_video_labels(context["claim_evidence_map"]))
    packet_labels = {item.get("label") for item in packet.get("selected_videos", [])}
    if packet_labels != mapped_labels:
        raise ValueError("answer_packet videos must exactly match claim evidence labels")
    return True
