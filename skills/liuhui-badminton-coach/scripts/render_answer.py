#!/usr/bin/env python3
"""Render a coaching answer from packet-bound IDs, without free technical prose."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


SCHEMA_VERSION = 1
PACKET_SCHEMA_VERSION = 3
ALLOWED_BLOCK_FIELDS = {
    "claim_atom": {"type", "claim_id", "atom_id"},
    "claim_window": {"type", "claim_id", "window_id"},
    "claim_gap": {"type", "claim_id"},
}


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def normalized_prose(value):
    return re.sub(r"[^0-9A-Za-z\u3400-\u9fff]+", "", str(value)).lower()


def packet_indexes(packet):
    if packet.get("schema_version") != PACKET_SCHEMA_VERSION:
        raise ValueError("unsupported answer packet schema")
    if packet.get("packet_type") != "liuhui_badminton_answer_packet":
        raise ValueError("invalid answer packet type")
    claims = {
        item["claim_id"]: item for item in packet.get("claim_evidence_map", [])
    }
    directives = {
        item["claim_id"]: item
        for item in packet.get("answer_plan", {}).get("claim_directives", [])
    }
    atoms = {
        item["atom_id"]: item
        for item in packet.get("answer_plan", {}).get(
            "selected_evidence_atoms", []
        )
    }
    videos = {
        item["label"]: item for item in packet.get("selected_videos", [])
    }
    windows = packet.get("evidence_windows", {})
    return claims, directives, atoms, videos, windows


def default_draft(packet):
    claims, directives, _atoms, videos, windows = packet_indexes(packet)
    blocks: list[dict[str, object]] = []
    for claim_id, claim in claims.items():
        directive = directives.get(claim_id, {})
        atom_ids = directive.get("atom_ids", [])
        if directive.get("mode") == "compose_from_reviewed_atoms" and atom_ids:
            blocks.extend(
                {"type": "claim_atom", "claim_id": claim_id, "atom_id": atom_id}
                for atom_id in atom_ids
            )
            continue
        if directive.get("mode") == "compose_from_claim_scoped_source":
            allowed_evidence = claim.get("evidence", [])
            window_id = next(
                (
                    candidate
                    for evidence in allowed_evidence
                    for candidate in evidence.get("window_ids", [])
                    if candidate in windows
                ),
                None,
            )
            if window_id is None:
                allowed_labels = [
                    item.get("label") for item in allowed_evidence
                ]
                window_id = next(
                    (
                        candidate
                        for label in allowed_labels
                        for candidate in videos.get(label, {}).get(
                            "window_ids", []
                        )
                        if candidate in windows
                    ),
                    None,
                )
            if window_id:
                blocks.append(
                    {
                        "type": "claim_window",
                        "claim_id": claim_id,
                        "window_id": window_id,
                    }
                )
                continue
        blocks.append({"type": "claim_gap", "claim_id": claim_id})
    return {"schema_version": SCHEMA_VERSION, "blocks": blocks}


def validate_draft(packet, draft):
    claims, directives, atoms, videos, windows = packet_indexes(packet)
    if not isinstance(draft, dict) or set(draft) != {"schema_version", "blocks"}:
        raise ValueError("draft must contain only schema_version and blocks")
    if draft.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported structured draft schema")
    if not isinstance(draft.get("blocks"), list):
        raise ValueError("draft blocks must be a list")
    covered_claims = set()
    for index, block in enumerate(draft["blocks"]):
        if not isinstance(block, dict):
            raise ValueError(f"draft block {index} must be an object")
        block_type = block.get("type")
        if block_type not in ALLOWED_BLOCK_FIELDS:
            raise ValueError(f"draft block {index} has an unsupported type")
        if set(block) != ALLOWED_BLOCK_FIELDS[block_type]:
            raise ValueError(
                f"draft block {index} contains free or missing fields"
            )
        claim_id = block.get("claim_id")
        if claim_id not in claims or claim_id not in directives:
            raise ValueError(f"draft block {index} references an unknown claim")
        directive = directives[claim_id]
        if block_type == "claim_atom":
            atom_id = block["atom_id"]
            if (
                directive.get("mode") != "compose_from_reviewed_atoms"
                or atom_id not in directive.get("atom_ids", [])
                or atom_id not in atoms
            ):
                raise ValueError("atom is not authorized for this claim")
        elif block_type == "claim_window":
            window_id = block["window_id"]
            allowed_labels = {
                item.get("label") for item in claims[claim_id].get("evidence", [])
            }
            if directive.get("mode") != "compose_from_claim_scoped_source":
                raise ValueError("window prose is not authorized for this claim")
            if window_id not in windows or windows[window_id].get("label") not in allowed_labels:
                raise ValueError("window is not authorized for this claim")
            if not any(
                window_id in videos.get(label, {}).get("window_ids", [])
                for label in allowed_labels
            ):
                raise ValueError("window is not bound to an allowed evidence video")
        elif directive.get("mode") not in {
            "state_evidence_gap",
            "contract_only_no_new_technical_detail",
        }:
            raise ValueError("an evidence-backed claim cannot be replaced by a gap")
        covered_claims.add(claim_id)
    missing = set(claims) - covered_claims
    if missing:
        raise ValueError("structured draft omits claims: " + ", ".join(sorted(missing)))
    return True


def render_question_interpretation(packet):
    actor = packet.get("question_interpretation", {}).get(
        "actor_context", {}
    )
    inferred = actor.get("inferred_target_action")
    if not inferred:
        return []
    actor_labels = {
        "player": "你",
        "opponent": "对手",
        "opponent_or_feed": "对手或来球方",
        "partner": "搭档",
    }
    events = [
        f"{actor_labels.get(item.get('actor'), item.get('actor'))}："
        f"{item.get('term')}"
        for item in actor.get("event_chain", [])
        if item.get("actor") and item.get("term")
    ]
    parts = []
    target = actor.get("target_action_query")
    if target:
        parts.append(f"本题按“{target}”处理")
    if events:
        parts.append("事件链为“" + " → ".join(events) + "”")
    reason = inferred.get("reason")
    if reason:
        parts.append(reason.rstrip("。"))
    if not parts:
        return []
    return ["问题解释：" + "；".join(parts) + "。"]


def render_answer(packet, draft=None):
    draft = default_draft(packet) if draft is None else draft
    validate_draft(packet, draft)
    claims, _directives, atoms, videos, windows = packet_indexes(packet)
    lines = ["## 直接回答", ""]
    boundary = packet.get("boundary", {}).get("required_statement")
    if boundary:
        lines.extend([boundary, ""])
    interpretation_lines = render_question_interpretation(packet)
    if interpretation_lines:
        lines.extend(interpretation_lines + [""])
    for statement in packet.get("question_interpretation", {}).get(
        "actor_context", {}
    ).get("scope_boundary_statements", []):
        lines.extend([f"证据边界：{statement}", ""])
    if packet.get("diagnostic_model", {}).get("do_not_claim_unique_cause"):
        lines.extend(["仅凭现有文字与证据，不能确认你个人动作的唯一原因。", ""])
    resolved = packet.get("answer_turn", {}).get(
        "resolved_clarifications", []
    )
    if resolved:
        resolved_text = "；".join(
            f"{item['query_label']}：{item['answer']}" for item in resolved
        )
        lines.extend([f"你已补充：{resolved_text}。", ""])
    rendered_claim_ids = set()
    for block in draft["blocks"]:
        claim = claims[block["claim_id"]]
        marker = f"[{block['claim_id']}]"
        claim_lead = ""
        if block["claim_id"] not in rendered_claim_ids:
            claim_lead = f"关于“{claim['text']}”："
            rendered_claim_ids.add(block["claim_id"])
        if block["type"] == "claim_atom":
            atom = atoms[block["atom_id"]]
            verbalizable_claim = atom["verbalizable_claim"]
            normalized_claim = normalized_prose(verbalizable_claim)
            conditions = "；".join(
                condition
                for condition in atom.get("conditions", [])
                if normalized_prose(condition) not in normalized_claim
            )
            qualifier = f"在{conditions}情况下，" if conditions else ""
            uncertainty = (
                " 这仍不能确认你个人动作的唯一原因。"
                if claim.get("confidence_ceiling") in {"none", "low"}
                else ""
            )
            label = atom.get("video_label")
            lines.append(
                f"{marker}{claim_lead}{qualifier}{verbalizable_claim}"
                + uncertainty
                + (f" [{label}]" if label else "")
            )
        elif block["type"] == "claim_window":
            window = windows[block["window_id"]]
            lines.append(
                f"{marker}{claim['text']}：当前来源直接给出的片段是“"
                f"{window['text']}”（{window['timestamp']}） [{window['label']}]。"
                "这段材料只支持按原片段核对，不能确认你个人动作的唯一原因。"
            )
        else:
            lines.append(
                f"{marker}{claim['text']}：当前证据包没有允许展开的技术结论，"
                "因此保留为未确认项。"
            )
    unresolved_contract = [
        item
        for item in packet.get("completeness_contract", {}).get("items", [])
        if item.get("item_id") not in claims
        and not any(
            claim_id.startswith(f"{item.get('item_id')}.")
            for claim_id in claims
        )
    ]
    for item in unresolved_contract:
        lines.append(
            f"[{item['item_id']}]{item['text']}：现有证据不足以统一处理，"
            "需要按具体场景分别判断。"
        )
    pending = packet.get("answer_turn", {}).get("pending_clarifications", [])
    if pending:
        lines.extend(["", "## 仍需确认", ""])
        lines.extend(f"- {item['question']}" for item in pending)
    display_labels = packet.get("display_videos", [])
    if display_labels:
        lines.extend(["", "## 核心视频与观看重点", ""])
        for label in display_labels:
            video = videos[label]
            observation = next(
                (
                    windows[window_id]
                    for window_id in video.get("window_ids", [])
                    if window_id in windows
                ),
                None,
            )
            if observation and observation["timestamp"] == "visual_review_no_timestamp":
                focus = "；先看视觉复核片段（无精确时间点）"
            elif observation:
                focus = f"；先看 {observation['timestamp']} 的绑定片段"
            else:
                focus = ""
            lines.append(
                f"- {label}｜{video['title']}{focus}｜证据ID："
                f"{video['evidence_id']}｜{video['url']}"
            )
    prompt = packet.get("feedback_prompt")
    if prompt:
        lines.extend(["", prompt])
    return "\n".join(lines).rstrip() + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--draft", type=Path)
    args = parser.parse_args()
    try:
        packet = load_json(args.packet)
        draft = load_json(args.draft) if args.draft else None
        print(render_answer(packet, draft), end="")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
