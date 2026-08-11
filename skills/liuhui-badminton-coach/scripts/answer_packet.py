#!/usr/bin/env python3
"""Closed answer planning and compact packet projection."""

import hashlib
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from token_budget import estimate_json_tokens as estimate_packet_tokens
from feedback import build_feedback_hint


ANSWER_PACKET_SCHEMA_VERSION = 7
ANSWER_PLAN_SCHEMA_VERSION = 1
FALLBACK_WINDOW_LIMIT = 6
CORE_VIDEO_LIMIT = 5
COMPLETE_RELATED_TITLE_LIMIT = 48
COMPLETE_RELATED_CATALOG_FIELDS = (
    "label",
    "evidence_id",
    "title",
    "legacy_video_id",
    "url",
    "citation_reason",
    "viewing_value",
    "watch_focus",
)
ANSWER_PACKET_TARGET_BYTES = 24 * 1024
ANSWER_PACKET_HARD_MAXIMUM_BYTES = 32 * 1024
ANSWER_PACKET_TARGET_TOKENS = 10_000
ANSWER_PACKET_HARD_MAXIMUM_TOKENS = 12_000


def compact_display_text(value, limit=96):
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


TECHNICAL_FOCUS_TERMS = (
    "击球",
    "击球点",
    "击球位置",
    "框架",
    "拍面",
    "握拍",
    "架拍",
    "引拍",
    "发力",
    "挥拍",
    "重心",
    "步法",
    "回动",
    "启动",
    "身体",
    "手腕",
    "手指",
    "肩",
    "肘",
    "线路",
    "落点",
    "主动",
    "被动",
)


def technical_focus_score(item):
    text = str(item.get("text") or "")
    return sum(term in text for term in TECHNICAL_FOCUS_TERMS)


def video_display_guidance(video, claim_evidence_map):
    """Explain why every displayed source belongs and what to inspect."""

    matches = []
    for claim in claim_evidence_map:
        for evidence in claim.get("evidence", []):
            label = evidence.get("label") or evidence.get("video_label")
            if label == video.get("label"):
                matches.append((claim, evidence))
    directness_rank = {"direct": 3, "scoped": 2, "component": 1}
    matches.sort(
        key=lambda item: (
            -directness_rank.get(item[1].get("directness"), 0),
            -int(item[1].get("window_support", {}).get("rank") or 0),
            -float(item[1].get("window_support", {}).get("score") or 0),
            item[0].get("claim_id", ""),
        )
    )
    claim, evidence = matches[0] if matches else ({}, {})
    claim_text = compact_display_text(claim.get("text") or "本题", 54)
    roles = set(evidence.get("evidence_roles") or video.get("evidence_roles") or [])
    if {"correction", "mechanism"}.issubset(roles):
        viewing_value = (
            f"它同时包含问题表现、原因解释和纠正线索，适合用来区分"
            f"“{claim_text}”中的不同可能原因。"
        )
    elif "correction" in roles:
        viewing_value = f"可直观看到与“{claim_text}”有关的错误表现和纠正差别。"
    elif "mechanism" in roles or "principle" in roles:
        viewing_value = f"用于理解“{claim_text}”背后难以只用文字表达的动作机制。"
    elif "action" in roles:
        viewing_value = f"用于观察“{claim_text}”对应的动作顺序、空间位置和连续变化。"
    elif "tactics" in roles:
        viewing_value = f"用于观察“{claim_text}”成立时的来球、站位和回球条件。"
    elif "context" in roles:
        viewing_value = f"仅补充“{claim_text}”的场景和动作外观，不单独证明机制。"
    else:
        viewing_value = f"用于核对来源中的具体示范是否真正对应“{claim_text}”。"

    candidate_windows = [
        *video.get("evidence_windows", []),
        *video.get("transcript_evidence", []),
        *video.get("bounded_note_evidence", []),
    ]
    candidate_windows.sort(
        key=lambda item: (
            -technical_focus_score(item),
            -int(bool(item.get("exact_query_match"))),
            -float(item.get("query_ngram_coverage") or 0),
            -len(item.get("matched_terms") or []),
            -float(item.get("score") or 0),
            item.get("timestamp", ""),
        )
    )
    if not candidate_windows:
        candidate_windows = [
            item
            for item in video.get("teaching_note", {}).get("evidence", [])
            if item.get("timestamp") and item.get("text")
        ]
        candidate_windows.sort(
            key=lambda item: (
                -technical_focus_score(item),
                -len(str(item.get("text") or "")),
                item.get("timestamp", ""),
            )
        )
    focus = candidate_windows[0] if candidate_windows else None
    focus_summary = compact_display_text(
        focus.get("text") if focus else video.get("title"), 72
    )
    directness = evidence.get("directness")
    if directness == "direct":
        citation_reason = (
            f"直接支持“{claim_text}”中的主要结论；关键依据是“{focus_summary}”。"
        )
    elif directness == "scoped":
        citation_reason = (
            f"在该视频的具体场景下支持“{claim_text}”；关键依据是"
            f"“{focus_summary}”，不能脱离场景泛化。"
        )
    else:
        citation_reason = (
            f"补充“{claim_text}”中的局部动作或机制；重点依据是“{focus_summary}”。"
        )
    if candidate_windows:
        if focus.get("timestamp") == "visual_review_no_timestamp":
            watch_focus = (
                "全片（无精确时间点）："
                f"{compact_display_text(focus.get('text'), 88)}"
            )
        else:
            watch_focus = (
                f"{focus.get('timestamp')}："
                f"{compact_display_text(focus.get('text'), 88)}"
            )
    elif video.get("runtime_evidence_mode") == "visual_reviewed":
        watch_focus = (
            "全片（无精确时间点）：只观察动作连续性、击球位置和出球结果，"
            "不从画面额外推导未说明的机制。"
        )
    else:
        watch_focus = (
            "全片：围绕标题所示主题核对动作或解释；当前来源没有可靠的精确时间点。"
        )
    return {
        "citation_reason": citation_reason,
        "viewing_value": viewing_value,
        "watch_focus": watch_focus,
    }


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

    if (
        encoded_packet_size(packet) <= ANSWER_PACKET_TARGET_BYTES
        and estimate_packet_tokens(packet) <= ANSWER_PACKET_TARGET_TOKENS
    ):
        return packet
    if packet.get("answer_plan", {}).get("mode") in {
        "claim_evidence_fallback",
        "hybrid_reviewed_atoms_and_claim_evidence",
    }:
        while (
            encoded_packet_size(packet) > ANSWER_PACKET_TARGET_BYTES
            or estimate_packet_tokens(packet) > ANSWER_PACKET_TARGET_TOKENS
        ):
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
    tokens = estimate_packet_tokens(packet)
    if (
        size > ANSWER_PACKET_HARD_MAXIMUM_BYTES
        or tokens > ANSWER_PACKET_HARD_MAXIMUM_TOKENS
    ):
        raise ValueError(
            "answer packet exceeds a hard size budget after safe evidence pruning: "
            f"bytes={size}/{ANSWER_PACKET_HARD_MAXIMUM_BYTES}, "
            f"estimated_tokens={tokens}/{ANSWER_PACKET_HARD_MAXIMUM_TOKENS}"
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


def packet_visible_video_labels(plan, claim_evidence_map):
    """Return evidence labels selected for technical answer synthesis."""

    atoms_by_id = {
        atom["atom_id"]: atom
        for atom in plan.get("selected_evidence_atoms", [])
    }
    labels = []
    for directive in plan.get("claim_directives", []):
        if directive.get("mode") == "compose_from_reviewed_atoms":
            candidates = [
                atoms_by_id[atom_id].get("video_label")
                for atom_id in directive.get("atom_ids", [])
                if atom_id in atoms_by_id
            ]
        elif directive.get("mode") == "compose_from_claim_scoped_source":
            candidates = directive.get("evidence_labels", [])
        else:
            candidates = []
        for label in candidates:
            if label and label not in labels:
                labels.append(label)
    return labels


def packet_related_video_labels(plan, claim_evidence_map):
    """Return every claim-authorized video, including non-core sources."""

    active_claim_ids = {
        directive.get("claim_id")
        for directive in plan.get("claim_directives", [])
        if directive.get("mode")
        in {"compose_from_reviewed_atoms", "compose_from_claim_scoped_source"}
    }
    labels = []
    for claim in claim_evidence_map:
        if claim.get("claim_id") not in active_claim_ids:
            continue
        for item in claim.get("evidence", []):
            label = item.get("label") or item.get("video_label")
            if label and label not in labels:
                labels.append(label)
    return labels


def fallback_video_labels(plan, claim_evidence_map):
    return {
        label
        for directive in plan.get("claim_directives", [])
        if directive.get("mode") == "compose_from_claim_scoped_source"
        for label in directive.get("evidence_labels", [])
        if label
    }


def atom_scope_matches(atom, constraints):
    for axis, required_values in atom.get("scope", {}).items():
        if not set(required_values).issubset(set(constraints.get(axis, []))):
            return False
    return True


def atom_claim_matches(atom, claim, inferred_target_claim=None):
    accepted_claims = {
        atom.get("canonical_claim"),
        *atom.get("claim_aliases", []),
    }
    return claim.get("text") in accepted_claims or (
        claim.get("kind") == "question_unit"
        and inferred_target_claim in accepted_claims
    )


def atom_window_is_reviewed(atom, selected_video):
    available = {
        (item.get("timestamp"), item.get("text"))
        for item in [
            *selected_video.get("teaching_note", {}).get("evidence", []),
            *selected_video.get("transcript_evidence", []),
            *selected_video.get("bounded_note_evidence", []),
        ]
    }
    return all(
        (window.get("timestamp"), window.get("text")) in available
        for window in atom.get("evidence_windows", [])
    )


def build_closed_answer_plan(context, atoms):
    constraints = context["question_interpretation"].get("constraints", {})
    actor_context = context["question_interpretation"].get(
        "actor_context", {}
    )
    inferred_target_claim = (
        actor_context.get("target_action_query")
        if actor_context.get("inferred_target_action")
        else None
    )
    selected_by_id = {
        item["evidence_id"]: item for item in context.get("selected_videos", [])
    }
    selected_atoms = []
    directives = []
    source_limit = context.get("evidence_layer_contract", {}).get(
        "max_synthesis_evidence_per_claim", 3
    )
    for claim in context.get("claim_evidence_map", []):
        eligible_ids = {item["evidence_id"] for item in claim.get("evidence", [])}
        matches = []
        for atom in atoms:
            evidence_id = atom.get("evidence_id")
            if (
                atom.get("claim_kind") != claim.get("kind")
                or not atom_claim_matches(
                    atom, claim, inferred_target_claim
                )
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
        if matches:
            selected_evidence_ids = []
            for item in matches:
                if item["evidence_id"] not in selected_evidence_ids:
                    selected_evidence_ids.append(item["evidence_id"])
            selected_evidence_ids = selected_evidence_ids[:source_limit]
            matches = [
                item
                for item in matches
                if item["evidence_id"] in selected_evidence_ids
            ]
            selected_atoms.extend(matches)
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
                "evidence_labels": [],
                "confidence_ceiling": claim["confidence_ceiling"],
            }
        )
    selected_atoms.sort(key=lambda item: item["atom_id"])
    fallback_directives = [
        directive
        for directive, claim in zip(directives, context["claim_evidence_map"])
        if not directive["atom_ids"]
        and claim.get("evidence")
        and claim.get("status") not in {"unsupported", "unverified"}
    ]
    for directive in fallback_directives:
        directive["mode"] = "compose_from_claim_scoped_source"
    if selected_atoms and fallback_directives:
        technical_claim_policy = (
            "selected_reviewed_atoms_else_claim_scoped_source_evidence"
        )
        planner_mode = "hybrid_reviewed_atoms_and_claim_evidence"
    elif selected_atoms:
        technical_claim_policy = "selected_reviewed_atoms_only"
        planner_mode = "reviewed_atoms_closed"
    else:
        technical_claim_policy = "claim_scoped_source_evidence_only"
        planner_mode = "claim_evidence_fallback"
        for directive, claim in zip(directives, context["claim_evidence_map"]):
            if claim.get("evidence"):
                directive["mode"] = "compose_from_claim_scoped_source"
    claims_by_id = {
        claim["claim_id"]: claim for claim in context["claim_evidence_map"]
    }
    for directive in directives:
        if directive["mode"] != "compose_from_claim_scoped_source":
            continue
        directive["evidence_labels"] = [
            item.get("label") or item.get("video_label")
            for item in claims_by_id[directive["claim_id"]].get("evidence", [])
            if item.get("label") or item.get("video_label")
        ][:source_limit]
    return {
        "schema_version": ANSWER_PLAN_SCHEMA_VERSION,
        "mode": planner_mode,
        "selected_evidence_atoms": selected_atoms,
        "claim_directives": directives,
        "composer_contract": {
            "technical_claim_policy": technical_claim_policy,
            "allowed_atom_ids": [item["atom_id"] for item in selected_atoms],
            "max_synthesis_evidence_per_claim": source_limit,
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
            "scope_boundary_statements",
            "event_chain",
            "inferred_target_action",
        )
        if actor.get(key)
    }
    result = {
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
    query_unit_constraints = interpretation.get("query_unit_constraints")
    if query_unit_constraints:
        result["query_unit_constraints"] = query_unit_constraints
    return result


def compact_answer_guidance(guidance):
    return {
        key: guidance[key]
        for key in (
            "mode",
            "label",
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
                for key in ("item_id", "kind", "text", "status")
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
        "additional_information_can_improve_answer": model.get(
            "additional_information_can_improve_answer",
            False,
        ),
    }


def compact_video(
    video,
    planned_atoms,
    include_fallback_windows,
    claim_windows=(),
):
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
    if not include_fallback_windows:
        for window in claim_windows:
            key = (window["timestamp"], window["text"])
            if key not in seen:
                windows.append(dict(window))
                seen.add(key)
    if include_fallback_windows:
        transcript_windows = [
            *video.get("transcript_evidence", []),
            *video.get("bounded_note_evidence", []),
        ]
        transcript_windows.sort(
            key=lambda item: (
                -int(bool(item.get("exact_query_match"))),
                -float(item.get("query_ngram_coverage") or 0),
                -len(item.get("matched_terms") or []),
                -float(item.get("score") or 0),
                item.get("timestamp", ""),
            )
        )
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
            if item.get("timestamp") and text:
                note_windows.append(item)
        note_windows.sort(
            key=lambda item: (
                -technical_focus_score(item),
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
        for source_window in note_windows[:2]:
            if len(windows) >= FALLBACK_WINDOW_LIMIT:
                break
            timestamp = source_window.get("timestamp")
            text = source_window.get("text")
            key = (timestamp, text)
            if timestamp and text and key not in seen:
                windows.append({"timestamp": timestamp, "text": text})
                seen.add(key)
        for source_window in claim_windows:
            if len(windows) >= FALLBACK_WINDOW_LIMIT:
                break
            timestamp = source_window.get("timestamp")
            text = source_window.get("text")
            key = (timestamp, text)
            if timestamp and text and key not in seen:
                windows.append({"timestamp": timestamp, "text": text})
                seen.add(key)
        for source_window in transcript_windows:
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
            "answer_eligibility",
            "evidence_roles",
            "confidence_ceiling",
            "metadata_title_trust",
            "runtime_evidence_mode",
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
    windows: dict[str, dict[str, object]] = {}
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


def compact_claim_evidence_map(claims, plan, window_ids_by_key=None):
    directives_by_claim = {
        directive["claim_id"]: directive
        for directive in plan.get("claim_directives", [])
    }
    atoms_by_id = {
        atom["atom_id"]: atom
        for atom in plan.get("selected_evidence_atoms", [])
    }
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
        directive = directives_by_claim.get(claim.get("claim_id"), {})
        if directive.get("mode") in {
            "compose_from_reviewed_atoms",
            "compose_from_claim_scoped_source",
        }:
            allowed_labels = {
                item.get("label") or item.get("video_label")
                for item in claim.get("evidence", [])
            }
        else:
            allowed_labels = set()
        if directive.get("mode") == "compose_from_reviewed_atoms":
            synthesis_labels = {
                atoms_by_id[atom_id].get("video_label")
                for atom_id in directive.get("atom_ids", [])
                if atom_id in atoms_by_id
            }
        else:
            synthesis_labels = set(directive.get("evidence_labels", []))
        compact_evidence = []
        related_labels = []
        for item in claim.get("evidence", []):
            label = item.get("label") or item.get("video_label")
            if label not in allowed_labels:
                continue
            if label not in synthesis_labels:
                # Complete-related-only sources retain exact claim membership
                # without repeating one JSON object per label. Their source
                # identity lives in complete_related_video_catalog and they
                # cannot authorize prose.
                if label not in related_labels:
                    related_labels.append(label)
                continue
            projected = {
                key: item[key]
                for key in (
                    "label",
                    "directness",
                    "scope",
                    "answer_eligibility",
                    "evidence_roles",
                )
                if key in item
            }
            if window_ids_by_key:
                window_ids = [
                    window_ids_by_key[
                        (
                            item["evidence_id"],
                            window["timestamp"],
                            window["text"],
                        )
                    ]
                    for window in item.get("claim_windows", [])
                    if (
                        item["evidence_id"],
                        window["timestamp"],
                        window["text"],
                    ) in window_ids_by_key
                ]
                if window_ids:
                    projected["window_ids"] = window_ids
            compact_evidence.append(projected)
        compact["evidence"] = compact_evidence
        if related_labels:
            compact["related_labels"] = related_labels
        compact_claims.append(compact)
    return compact_claims


def minimize_complete_list_videos(videos, detail_labels):
    """Keep full metadata only where prose or core guidance can use it."""

    minimal_keys = {
        "label",
        "evidence_id",
        "title",
        "url",
        "legacy_video_id",
        "citation_reason",
        "viewing_value",
        "watch_focus",
    }
    minimized = []
    for video in videos:
        if video["label"] in detail_labels:
            minimized.append(video)
            continue
        compact = {
                key: value
                for key, value in video.items()
                if key in minimal_keys
        }
        evidence_id = str(compact.get("evidence_id", ""))
        derivable_url = (
            f"https://www.bilibili.com/video/{evidence_id.split(':', 1)[1]}/"
            if evidence_id.startswith("bilibili:BV")
            else (
                f"https://www.douyin.com/video/{evidence_id}"
                if evidence_id.isdigit()
                else None
            )
        )
        if compact.get("url") == derivable_url:
            compact.pop("url")
        minimized.append(compact)
    return minimized


def encode_complete_related_video_catalog(videos, detail_labels):
    """Column-encode non-synthesis sources without dropping source identity."""

    rows = []
    for video in videos:
        if video["label"] in detail_labels:
            continue
        title = str(video.get("title") or "")
        if len(title) > COMPLETE_RELATED_TITLE_LIMIT:
            title = title[: COMPLETE_RELATED_TITLE_LIMIT - 1] + "…"
        catalog_video = {**video, "title": title}
        rows.append(
            [
                catalog_video.get(field)
                for field in COMPLETE_RELATED_CATALOG_FIELDS
            ]
        )
    return {
        "fields": list(COMPLETE_RELATED_CATALOG_FIELDS),
        "rows": rows,
    }


def decode_complete_related_video_catalog(packet):
    """Decode and validate the compact complete-related source catalog."""

    catalog = packet.get("complete_related_video_catalog")
    if not isinstance(catalog, dict):
        raise ValueError("answer_packet is missing complete-related video catalog")
    if catalog.get("fields") != list(COMPLETE_RELATED_CATALOG_FIELDS):
        raise ValueError("answer_packet complete-related catalog fields are invalid")
    rows = catalog.get("rows")
    if not isinstance(rows, list):
        raise ValueError("answer_packet complete-related catalog rows are invalid")
    videos = []
    for row in rows:
        if not isinstance(row, list) or len(row) != len(
            COMPLETE_RELATED_CATALOG_FIELDS
        ):
            raise ValueError("answer_packet complete-related catalog row is invalid")
        video = {
            field: value
            for field, value in zip(COMPLETE_RELATED_CATALOG_FIELDS, row)
            if value is not None
        }
        if any(
            not isinstance(video.get(field), str)
            or not video[field].strip()
            for field in (
                "label",
                "evidence_id",
                "title",
                "citation_reason",
                "viewing_value",
                "watch_focus",
            )
        ):
            raise ValueError(
                "answer_packet complete-related catalog source identity is invalid"
            )
        videos.append(video)
    return videos


def packet_video_records(packet):
    """Return detailed and catalog-only videos as one label-addressable set."""

    detailed = packet.get("selected_videos")
    if not isinstance(detailed, list):
        raise ValueError("answer_packet selected_videos must be a list")
    videos = [*detailed, *decode_complete_related_video_catalog(packet)]
    labels = [video.get("label") for video in videos]
    if len(labels) != len(set(labels)):
        raise ValueError("answer_packet video labels must be unique")
    return sorted(videos, key=lambda video: int(video["label"][1:]))


def default_claim_windows_by_evidence_id(claims, plan):
    """Keep windows for every source selected for fallback synthesis."""

    windows: dict[str, list[dict[str, object]]] = {}
    labels_by_claim = {
        directive["claim_id"]: set(directive.get("evidence_labels", []))
        for directive in plan.get("claim_directives", [])
        if directive.get("mode") == "compose_from_claim_scoped_source"
    }
    for claim in claims:
        allowed_labels = labels_by_claim.get(claim.get("claim_id"), set())
        for evidence in claim.get("evidence", []):
            label = evidence.get("label") or evidence.get("video_label")
            if label not in allowed_labels:
                continue
            claim_windows = evidence.get("claim_windows", [])
            if not claim_windows:
                continue
            windows.setdefault(evidence["evidence_id"], []).extend(
                claim_windows
            )
    return windows


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
    return {"policy_id": "untrusted-source-content-v1"}


def default_render_video_labels(plan, claim_evidence_map, videos):
    """Return every video label the renderer's deterministic draft will cite."""

    atoms_by_id = {
        atom["atom_id"]: atom
        for atom in plan.get("selected_evidence_atoms", [])
    }
    videos_by_label = {video["label"]: video for video in videos}
    labels = []
    for directive in plan.get("claim_directives", []):
        if directive.get("mode") == "compose_from_reviewed_atoms":
            candidates = [
                atoms_by_id[atom_id].get("video_label")
                for atom_id in directive.get("atom_ids", [])
                if atom_id in atoms_by_id
            ]
        elif directive.get("mode") == "compose_from_claim_scoped_source":
            candidates = directive.get("evidence_labels", [])
            candidates = [
                label
                for label in candidates
                if videos_by_label.get(label, {}).get(
                    "window_ids",
                    videos_by_label.get(label, {}).get("evidence_windows", []),
                )
            ]
        else:
            candidates = []
        for label in candidates:
            if label and label not in labels:
                labels.append(label)
    return labels


def select_core_videos(
    videos,
    claim_evidence_map,
    limit=CORE_VIDEO_LIMIT,
    preferred_labels=(),
):
    """Choose a bounded core set while preserving the complete related list."""

    video_by_label = {video["label"]: video for video in videos}
    uncovered = {
        claim["claim_id"]
        for claim in claim_evidence_map
        if claim.get("status") in {"supported", "conditional"}
        and claim.get("evidence")
    }
    coverage = {
        label: {
            claim["claim_id"]
            for claim in claim_evidence_map
            if any(item.get("label") == label for item in claim.get("evidence", []))
        }
        for label in video_by_label
    }
    preferred_rank = {
        label: index
        for index, label in enumerate(dict.fromkeys(preferred_labels))
    }
    selected: list[str] = []
    remaining = set(video_by_label) - set(selected)
    while remaining and len(selected) < limit:
        if not uncovered:
            break
        label = min(
            remaining,
            key=lambda candidate: (
                -len(coverage[candidate] & uncovered),
                preferred_rank.get(candidate, 10**6),
                video_by_label[candidate].get("role") != "core",
                video_by_label[candidate].get("answer_eligibility") != "primary",
                int(candidate[1:]),
            ),
        )
        selected.append(label)
        uncovered -= coverage[label]
        remaining.remove(label)
        if not uncovered:
            break
    return selected


def core_video_labels_for_context(context, limit=CORE_VIDEO_LIMIT):
    """Project the bounded core list from sources used in synthesis."""

    plan = context["answer_plan"]
    related_labels = set(
        packet_visible_video_labels(plan, context["claim_evidence_map"])
    )
    fallback_labels = fallback_video_labels(
        plan, context["claim_evidence_map"]
    )
    claim_windows_by_evidence_id = default_claim_windows_by_evidence_id(
        context["claim_evidence_map"], plan
    )
    videos = [
        compact_video(
            video,
            plan["selected_evidence_atoms"],
            video["label"] in fallback_labels,
            claim_windows_by_evidence_id.get(video["evidence_id"], []),
        )
        for video in sorted(
            context["selected_videos"],
            key=lambda item: int(item["label"][1:]),
        )
        if video["label"] in related_labels
    ]
    compact_claims = compact_claim_evidence_map(
        context["claim_evidence_map"], plan
    )
    preferred_labels = default_render_video_labels(plan, compact_claims, videos)
    return select_core_videos(
        videos,
        compact_claims,
        limit=limit,
        preferred_labels=preferred_labels,
    )


def compact_delivery_contract(contract):
    if not isinstance(contract, dict):
        return {"schema_version": 1, "items": [], "required_ids": []}
    return {
        "schema_version": contract.get("schema_version"),
        "items": [
            {
                **{
                    key: item[key]
                    for key in (
                        "delivery_id",
                        "kind",
                        "required",
                    )
                    if key in item
                },
                **(
                    {"parameters": item["parameters"]}
                    if item.get("parameters")
                    else {}
                ),
            }
            for item in contract.get("items", [])
        ],
        "required_ids": contract.get("required_ids", []),
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
            for key in ("claim_id", "mode", "atom_ids", "evidence_labels")
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
            "max_synthesis_evidence_per_claim",
        )
        if key in plan.get("composer_contract", {})
    }
    return compact


def build_answer_packet(context, audit_context_reference=None):
    digest = canonical_json_digest(context)
    plan = context["answer_plan"]
    turn = context["answer_turn_contract"]
    synthesis_labels = set(
        packet_visible_video_labels(plan, context["claim_evidence_map"])
    )
    computed_related_labels = packet_visible_video_labels(
        plan, context["claim_evidence_map"]
    )
    declared_related_labels = context.get(
        "answer_complete_related_video_labels", []
    )
    related_label_order = [
        *[
            label
            for label in declared_related_labels
            if label in set(computed_related_labels)
        ],
        *[
            label
            for label in computed_related_labels
            if label not in set(declared_related_labels)
        ],
    ]
    related_labels = set(related_label_order)
    fallback_labels = fallback_video_labels(
        plan, context["claim_evidence_map"]
    )
    claim_windows_by_evidence_id = default_claim_windows_by_evidence_id(
        context["claim_evidence_map"], plan
    )
    compact_videos = []
    for video in sorted(
        context["selected_videos"],
        key=lambda item: int(item["label"][1:]),
    ):
        if video["label"] not in related_labels:
            continue
        compact = compact_video(
                video,
                plan["selected_evidence_atoms"],
                video["label"] in fallback_labels,
                claim_windows_by_evidence_id.get(video["evidence_id"], []),
        )
        compact_videos.append(
            compact
            | video_display_guidance(
                {**video, "evidence_windows": compact["evidence_windows"]},
                context["claim_evidence_map"],
            )
        )
    windows, window_ids_by_key, compact_videos = normalized_evidence_windows(
        compact_videos
    )
    compact_claims = compact_claim_evidence_map(
        context["claim_evidence_map"], plan, window_ids_by_key
    )
    preferred_labels = default_render_video_labels(
        plan, compact_claims, compact_videos
    )
    core_videos = select_core_videos(
        compact_videos,
        compact_claims,
        preferred_labels=preferred_labels,
    )
    complete_related_videos = [
        label
        for label in related_label_order
        if label in {video["label"] for video in compact_videos}
    ]
    compact_videos = minimize_complete_list_videos(
        compact_videos,
        set(core_videos) | set(synthesis_labels),
    )
    detail_labels = set(core_videos) | set(synthesis_labels)
    complete_related_video_catalog = encode_complete_related_video_catalog(
        compact_videos,
        detail_labels,
    )
    detailed_videos = [
        video for video in compact_videos if video["label"] in detail_labels
    ]
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
        "claim_evidence_map": compact_claims,
        "completeness_contract": compact_completeness_contract(
            context["completeness_contract"]
        ),
        "delivery_contract": compact_delivery_contract(
            context.get("delivery_contract")
        ),
        "answer_plan": compact_plan(plan, window_ids_by_key),
        "answer_guidance": compact_answer_guidance(context["answer_guidance"]),
        "source_handling": compact_source_handling(
            context.get("source_handling")
        ),
        "policy_refs": context["policy_refs"],
        "evidence_windows": windows,
        "selected_videos": detailed_videos,
        "complete_related_video_catalog": complete_related_video_catalog,
        "synthesis_videos": [
            label
            for label in packet_visible_video_labels(
                plan, context["claim_evidence_map"]
            )
            if label in synthesis_labels and label in related_labels
        ],
        "core_videos": core_videos,
        "complete_related_videos": complete_related_videos,
        "feedback_prompt": build_feedback_hint(
            [{"label": label} for label in complete_related_videos]
        ),
    }
    return enforce_answer_packet_budget(packet)


def validate_answer_packet(packet, context):
    if packet.get("schema_version") != ANSWER_PACKET_SCHEMA_VERSION:
        raise ValueError("unsupported answer_packet schema_version")
    if packet.get("packet_type") != "liuhui_badminton_answer_packet":
        raise ValueError("invalid answer_packet type")
    delivery = packet.get("delivery_contract")
    if not isinstance(delivery, dict) or delivery.get("schema_version") != 1:
        raise ValueError("invalid delivery_contract")
    delivery_ids = [
        item.get("delivery_id") for item in delivery.get("items", [])
    ]
    if (
        any(not delivery_id for delivery_id in delivery_ids)
        or len(delivery_ids) != len(set(delivery_ids))
        or delivery.get("required_ids") != delivery_ids
    ):
        raise ValueError("invalid delivery_contract IDs")
    context_delivery = compact_delivery_contract(
        context.get("delivery_contract")
    )
    if delivery != context_delivery:
        raise ValueError("delivery_contract does not match audit context")
    if any(
        item.get("kind", "").startswith("practice.")
        for item in delivery.get("items", [])
    ):
        raise ValueError("synthetic practice delivery kinds are unsupported")
    covered_cluster_ids: set[str] = set()
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
    mapped_labels = set(
        packet_visible_video_labels(
            context["answer_plan"], context["claim_evidence_map"]
        )
    )
    packet_labels = {item.get("label") for item in packet_video_records(packet)}
    for video in packet_video_records(packet):
        if any(
            not isinstance(video.get(field), str) or not video[field].strip()
            for field in ("citation_reason", "viewing_value", "watch_focus")
        ):
            raise ValueError(
                "answer_packet videos require complete viewing guidance"
            )
    if packet_labels != mapped_labels:
        raise ValueError(
            "answer_packet videos must exactly match synthesis evidence labels"
        )
    synthesis_labels = packet.get("synthesis_videos")
    expected_synthesis_labels = packet_visible_video_labels(
        context["answer_plan"], context["claim_evidence_map"]
    )
    if synthesis_labels != expected_synthesis_labels:
        raise ValueError("answer_packet synthesis_videos do not match answer plan")
    complete_labels = packet.get("complete_related_videos")
    if (
        not isinstance(complete_labels, list)
        or len(complete_labels) != len(set(complete_labels))
        or set(complete_labels) != packet_labels
    ):
        raise ValueError(
            "answer_packet complete_related_videos must exactly match synthesis evidence"
        )
    core_labels = packet.get("core_videos")
    detailed_labels = {
        item.get("label") for item in packet.get("selected_videos", [])
    }
    if (
        not isinstance(core_labels, list)
        or len(core_labels) > CORE_VIDEO_LIMIT
        or len(core_labels) != len(set(core_labels))
        or not set(core_labels).issubset(packet_labels)
        or not set(core_labels).issubset(detailed_labels)
    ):
        raise ValueError("answer_packet core_videos must be a bounded evidence subset")
    if not set(synthesis_labels).issubset(detailed_labels):
        raise ValueError(
            "answer_packet synthesis videos must retain detailed source metadata"
        )
    return True
