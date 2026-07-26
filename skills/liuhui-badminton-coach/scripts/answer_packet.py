#!/usr/bin/env python3
"""Closed answer planning and compact packet projection."""

import hashlib
import json


ANSWER_PACKET_SCHEMA_VERSION = 1
ANSWER_PLAN_SCHEMA_VERSION = 1
FALLBACK_WINDOW_LIMIT = 4


def canonical_json_digest(payload):
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
    return {
        key: interpretation[key]
        for key in (
            "intent_frame",
            "constraints",
            "actor_context",
            "ambiguities",
            "terminology_corrections",
            "technique_definitions",
            "query_units",
            "retrieval_query_budget",
            "clarification_policy",
        )
        if key in interpretation
    }


def compact_answer_guidance(guidance):
    return {
        key: guidance[key]
        for key in (
            "mode",
            "label",
            "text_obligations",
            "video_obligations",
            "global_obligations",
        )
        if key in guidance
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
                windows.append(window)
                seen.add(key)
    if include_fallback_windows:
        source_windows = list(
            video.get("teaching_note", {}).get("evidence", [])
        ) + list(video.get("transcript_evidence", []))
        role_priority = {
            "principles": 0,
            "action_cues": 1,
            "key_evidence": 2,
            "error_evidence": 3,
            "coverage_evidence": 4,
        }
        source_windows.sort(
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
    return compact | {"evidence_windows": windows}


def build_answer_packet(context, audit_context_reference=None):
    digest = canonical_json_digest(context)
    plan = context["answer_plan"]
    turn = context["answer_turn_contract"]
    return {
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
        "diagnostic_model": context["diagnostic_model"],
        "clarification_decision": context["clarification_decision"],
        "answer_turn": {
            "resolved_clarifications": turn["resolved_clarifications"],
            "pending_clarifications": turn["pending_clarifications"],
            "resolved_question_ids_must_not_be_reasked": turn[
                "resolved_question_ids_must_not_be_reasked"
            ],
        },
        "claim_evidence_map": context["claim_evidence_map"],
        "completeness_contract": context["completeness_contract"],
        "answer_plan": plan,
        "answer_guidance": compact_answer_guidance(context["answer_guidance"]),
        "selected_videos": [
            compact_video(video, plan["selected_evidence_atoms"], False)
            if plan["mode"] == "reviewed_atoms_closed"
            else compact_video(video, [], True)
            for video in context["selected_videos"]
            if video["label"] in set(context["answer_visible_video_labels"])
        ],
        "feedback_prompt": context["answer_contract"]["feedback_prompt"],
    }


def validate_answer_packet(packet, context):
    if packet.get("schema_version") != ANSWER_PACKET_SCHEMA_VERSION:
        raise ValueError("unsupported answer_packet schema_version")
    if packet.get("packet_type") != "liuhui_badminton_answer_packet":
        raise ValueError("invalid answer_packet type")
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
