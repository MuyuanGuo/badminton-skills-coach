#!/usr/bin/env python3
"""Render a coaching answer from packet-bound IDs, without free technical prose."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import answer_packet as answer_packet_runtime

SCHEMA_VERSION = 1
PACKET_SCHEMA_VERSION = answer_packet_runtime.ANSWER_PACKET_SCHEMA_VERSION
ALLOWED_BLOCK_FIELDS = {
    "claim_atom": {"type", "claim_id", "atom_id"},
    "claim_window": {"type", "claim_id", "window_id"},
    "claim_gap": {"type", "claim_id"},
}
SUPPORTED_DELIVERY_KINDS = {
    "diagnosis.hypothesis_comparison",
    "diagnosis.ordered_checklist",
    "tactics.direction_branch",
    "tactics.condition_axes",
    "evidence.sources",
    "evidence.boundary",
    "evidence.training_boundary",
}
FALLBACK_WINDOWS_PER_SOURCE = 2


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
        item["label"]: item
        for item in answer_packet_runtime.packet_video_records(packet)
    }
    windows = packet.get("evidence_windows", {})
    return claims, directives, atoms, videos, windows


def canonical_video_url(video):
    if video.get("url"):
        return video["url"]
    evidence_id = str(video.get("evidence_id", ""))
    if evidence_id.startswith("bilibili:BV"):
        return (
            "https://www.bilibili.com/video/"
            f"{evidence_id.split(':', 1)[1]}/"
        )
    if evidence_id.isdigit():
        return f"https://www.douyin.com/video/{evidence_id}"
    raise ValueError("complete-related video has no canonical URL")


def render_video_item(video):
    required = ("citation_reason", "viewing_value", "watch_focus")
    if any(not str(video.get(field) or "").strip() for field in required):
        raise ValueError(
            f"video {video.get('label', '<unknown>')} has incomplete viewing guidance"
        )
    return [
        f"- {video['label']}｜{video['title']}｜证据ID：{video['evidence_id']}｜"
        f"{canonical_video_url(video)}",
        f"  - 为什么引用：{video['citation_reason']}",
        f"  - 为什么值得看：{video['viewing_value']}",
        f"  - 重点看：{video['watch_focus']}",
    ]


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
            evidence_by_label = {
                item.get("label"): item for item in claim.get("evidence", [])
            }
            fallback_blocks = []
            for label in directive.get("evidence_labels", []):
                evidence = evidence_by_label.get(label, {})
                window_ids = [
                    candidate
                    for candidate in evidence.get("window_ids", [])
                    if candidate in windows
                ]
                if not window_ids:
                    window_ids = [
                        candidate
                        for candidate in videos.get(label, {}).get(
                            "window_ids", []
                        )
                        if candidate in windows
                    ]
                for window_id in window_ids[:FALLBACK_WINDOWS_PER_SOURCE]:
                    fallback_blocks.append(
                        {
                            "type": "claim_window",
                            "claim_id": claim_id,
                            "window_id": window_id,
                        }
                    )
            if fallback_blocks:
                blocks.extend(fallback_blocks)
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


def validate_delivery_contract(packet):
    contract = packet.get("delivery_contract")
    if not isinstance(contract, dict) or contract.get("schema_version") != 1:
        raise ValueError("missing or unsupported delivery contract")
    items = contract.get("items")
    if not isinstance(items, list):
        raise ValueError("delivery contract items must be a list")
    ids = [item.get("delivery_id") for item in items]
    if (
        any(not delivery_id for delivery_id in ids)
        or len(ids) != len(set(ids))
        or contract.get("required_ids") != ids
        or any(item.get("required") is not True for item in items)
    ):
        raise ValueError("delivery contract IDs are invalid")
    unknown = sorted(
        {
            item.get("kind")
            for item in items
            if item.get("kind") not in SUPPORTED_DELIVERY_KINDS
        }
    )
    if unknown:
        raise ValueError(
            "unsupported delivery kinds: " + ", ".join(map(str, unknown))
        )
    return items


def status_label(status):
    return {
        "supported": "有证据支持",
        "conditional": "有条件支持",
        "unverified": "未确认",
        "unsupported": "没有直接证据",
    }.get(status, "未确认")


def render_delivery_blocks(packet, videos):
    items = validate_delivery_contract(packet)
    if not items:
        return []
    lines = ["", "## 结构化交付", ""]
    for item in items:
        marker = f"[{item['delivery_id']}]"
        kind = item["kind"]
        parameters = item.get("parameters", {})
        if kind == "diagnosis.hypothesis_comparison":
            candidates = parameters.get("candidates", [])
            comparison = "；".join(
                f"“{candidate['text']}”={status_label(candidate.get('status'))}"
                for candidate in candidates
            )
            lines.append(
                f"{marker}原因比较：{comparison}。各项必须独立核对，"
                "不能把其中任何一项写成已经确认的唯一原因。"
            )
        elif kind == "diagnosis.ordered_checklist":
            steps = parameters.get("steps", [])
            if steps:
                ordered = "；".join(
                    f"{index}）核对“{step['text']}”"
                    f"（{status_label(step.get('status'))}）"
                    for index, step in enumerate(steps, start=1)
                )
                lines.append(
                    f"{marker}现场检查顺序：{ordered}。每一步只观察一项，"
                    "不能仅凭文字跳到唯一原因。"
                )
            else:
                lines.append(
                    f"{marker}现场检查顺序：当前证据包没有可安全展开的检查项，"
                    "因此明确保留证据缺口。"
                )
        elif kind == "tactics.direction_branch":
            branch = parameters.get("branch", {}).get("label")
            axes = [
                axis.get("label")
                for axis in parameters.get("condition_axes", [])
                if axis.get("label")
            ]
            axis_text = "、".join(axes) or "来球与站位条件"
            lines.append(
                f"{marker}{branch}条件分支：当前答案包没有把“{axis_text}”"
                f"共同绑定到{branch}选择的直接声明，因此不能给固定结论；"
                "先逐轴记录，再与其他方向比较。"
            )
        elif kind == "tactics.condition_axes":
            axes = parameters.get("condition_axes", [])
            descriptions = {
                "incoming_height": "记录触球点相对身体的高、平、低",
                "balance": "记录身体稳定或已经失衡",
                "partner_position": "记录搭档的前后、同侧或对侧位置",
            }
            lines.append(
                f"{marker}条件轴："
                + "；".join(
                    f"{axis['label']}={descriptions.get(axis['axis'], '记录实际状态')}"
                    for axis in axes
                )
                + "。缺少任一轴时不把线路选择说成通用规则。"
            )
        elif kind == "evidence.sources":
            if packet.get("complete_related_videos"):
                lines.append(
                    f"{marker}相关视频：技术结论只使用答案计划选定的合成来源；"
                    "核心列表承担观看优先级，完整列表保留全部 claim 授权来源。"
                )
            else:
                lines.append(
                    f"{marker}相关视频：当前答案包没有可显示来源，明确保留证据缺口。"
                )
        elif kind == "evidence.boundary":
            lines.append(
                f"{marker}证据边界：所有技术结论只限当前答案包映射的场景；"
                "当前信息不足时先给出有证据支持的部分，不把条件性原因写成唯一结论。"
            )
        elif kind == "evidence.training_boundary":
            lines.append(
                f"{marker}训练方案边界：当前知识库主要支持动作、机制、纠错提示和"
                "战术解释，不足以可靠生成训练时长、组数、频次或多日计划。若来源"
                "明确给出练习提示，只复述该提示，不扩写成训练处方。"
            )
    return lines


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
        lines.extend(
            [
                "下面先回答当前证据能够支持的部分，并把仍取决于具体场景的内容"
                "保留为条件分支；仅凭当前描述不能确认某一个因素就是你个人动作的"
                "唯一原因。",
                "",
            ]
        )
    resolved = packet.get("answer_turn", {}).get(
        "resolved_clarifications", []
    )
    if resolved:
        resolved_text = "；".join(
            f"{item['query_label']}：{item['answer']}" for item in resolved
        )
        lines.extend([f"你已补充：{resolved_text}。", ""])
    lines.extend(["## 文字解释", ""])
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
            if claim.get("status") == "conditional":
                uncertainty = "这条依据只支持可能成立的条件性分支，仍需结合具体场景判断。"
            elif claim.get("confidence_ceiling") in {"none", "low"}:
                uncertainty = "这仍只是可能相关的排查方向。"
            else:
                uncertainty = ""
            lines.append(
                f"{marker}{claim_lead}{window['label']} 在 {window['timestamp']} 的"
                f"相关依据是“{window['text']}”。这条依据用于支持当前排查方向，"
                f"适用范围以该来源场景为准。{uncertainty} [{window['label']}]"
            )
        else:
            lines.append(
                f"{marker}{claim['text']}：当前证据包没有允许展开的技术结论，"
                "因此保留为未确认项。"
            )
    unresolved_contract = [
        item
        for item in packet.get("completeness_contract", {}).get("items", [])
        if not item.get("kind")
        and item.get("item_id") not in claims
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
    if packet.get("diagnostic_model", {}).get("do_not_claim_unique_cause"):
        lines.extend(
            [
                "",
                "## 适用边界",
                "",
                "以上内容是依据当前问题描述和来源证据给出的排查范围。信息不足时，"
                "保留多个可能分支；新增场景信息可以改变优先级，但不会否定已经有"
                "直接证据支持的部分。",
            ]
        )
    lines.extend(render_delivery_blocks(packet, videos))
    core_labels = packet.get("core_videos", [])
    if core_labels:
        lines.extend(["", "## 核心视频与观看重点", ""])
        for label in core_labels:
            video = videos[label]
            lines.extend(render_video_item(video))
    complete_labels = packet.get("complete_related_videos", [])
    remaining_labels = [
        label for label in complete_labels if label not in set(core_labels)
    ]
    if remaining_labels:
        lines.extend(["", "## 完整相关视频", ""])
        for label in remaining_labels:
            video = videos[label]
            lines.extend(render_video_item(video))
    pending = packet.get("answer_turn", {}).get("pending_clarifications", [])
    if pending:
        lines.extend(["", "## 为了让答案更完整，你还可以补充", ""])
        lines.extend(f"- {item['question']}" for item in pending)
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
