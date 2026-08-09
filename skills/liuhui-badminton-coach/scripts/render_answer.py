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
    "practice.session",
    "practice.three_day",
    "practice.two_week",
    "practice.success_criteria",
    "practice.common_errors",
    "practice.stop_signals",
    "tactics.direction_branch",
    "tactics.condition_axes",
    "evidence.sources",
    "evidence.boundary",
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
                window_id = next(
                    (
                        candidate
                        for candidate in evidence.get("window_ids", [])
                        if candidate in windows
                    ),
                    None,
                )
                if window_id is None:
                    window_id = next(
                        (
                            candidate
                            for candidate in videos.get(label, {}).get(
                                "window_ids", []
                            )
                            if candidate in windows
                        ),
                        None,
                    )
                if window_id:
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
    if any(item.get("kind", "").startswith("practice.") for item in items):
        practice = packet.get("practice_plan")
        if not isinstance(practice, dict):
            raise ValueError("practice delivery requires a practice plan")
        total = practice.get("session_minutes")
        allocation = practice.get("minute_allocation")
        if (
            not isinstance(total, int)
            or not isinstance(allocation, dict)
            or sum(allocation.values()) != total
        ):
            raise ValueError("practice minute allocation is invalid")
        for item in items:
            if item.get("kind") != "practice.session":
                continue
            parameters = item.get("parameters", {})
            if parameters.get("session_minutes") != total:
                raise ValueError(
                    "practice session delivery does not match practice plan"
                )
    return items


def status_label(status):
    return {
        "supported": "有证据支持",
        "conditional": "有条件支持",
        "unverified": "未确认",
        "unsupported": "没有直接证据",
    }.get(status, "未确认")


def numbered_records(records, text_key="instruction"):
    return "；".join(
        f"{item.get('label', f'第{index}项')}：{item.get(text_key, '')}"
        for index, item in enumerate(records, start=1)
    )


def render_delivery_blocks(packet, videos):
    items = validate_delivery_contract(packet)
    if not items:
        return []
    practice = packet.get("practice_plan") or {}
    lines = ["", "## 结构化交付", ""]
    segment_names = practice.get("segment_labels", {})
    segment_instructions = practice.get("segment_instructions", {})
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
        elif kind == "practice.session":
            total = practice["session_minutes"]
            allocation = practice["minute_allocation"]
            segments = []
            for key in (
                "warm_up",
                "isolated_cue",
                "pressure_or_decision",
                "self_check",
            ):
                segments.append(
                    f"{segment_names.get(key, key)} {allocation[key]} 分钟"
                    f"（{segment_instructions.get(key, '')}）"
                )
            adaptations = []
            if practice.get("setup_adaptation"):
                adaptations.append(
                    f"陪练方式：{practice['setup_adaptation']}"
                )
            if practice.get("discipline_boundary"):
                adaptations.append(
                    f"双打边界：{practice['discipline_boundary']}"
                )
            adaptation_text = (
                "；" + "；".join(adaptations) if adaptations else ""
            )
            lines.append(
                f"{marker}单次训练总计 {total} 分钟："
                + "；".join(segments)
                + adaptation_text
                + "。"
            )
        elif kind == "practice.three_day":
            progression = practice.get("three_day_progression", [])
            if len(progression) != 3:
                raise ValueError("three-day delivery requires exactly three days")
            lines.append(
                f"{marker}三天纠正：{numbered_records(progression)}。"
            )
        elif kind == "practice.two_week":
            progression = practice.get("two_week_consolidation", [])
            if len(progression) != 2:
                raise ValueError("two-week delivery requires exactly two weeks")
            lines.append(
                f"{marker}两周巩固：{numbered_records(progression)}。"
            )
        elif kind == "practice.success_criteria":
            criteria = practice.get("success_criteria", [])
            if len(criteria) < 2:
                raise ValueError("practice delivery requires observable success criteria")
            lines.append(
                f"{marker}成功标准："
                + "；".join(
                    f"{index}）{criterion}"
                    for index, criterion in enumerate(criteria, start=1)
                )
                + "。"
            )
        elif kind == "practice.common_errors":
            errors = practice.get("common_errors", [])
            if len(errors) < 2:
                raise ValueError("practice delivery requires common errors")
            lines.append(
                f"{marker}常见错误："
                + "；".join(
                    f"{index}）{error}"
                    for index, error in enumerate(errors, start=1)
                )
                + "。"
            )
        elif kind == "practice.stop_signals":
            signals = practice.get("quality_stop_rules", [])
            if len(signals) < 2:
                raise ValueError("practice delivery requires stop signals")
            boundary = practice.get("bounded_synthesis_statement")
            lines.append(
                f"{marker}停止与复核信号："
                + "；".join(signals)
                + (f"。训练边界：{boundary}" if boundary else "。")
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
                "仅凭文字或缺少连续动作视频时，不能确认个人动作的唯一原因。"
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
    lines.extend(render_delivery_blocks(packet, videos))
    pending = packet.get("answer_turn", {}).get("pending_clarifications", [])
    if pending:
        lines.extend(["", "## 仍需确认", ""])
        lines.extend(f"- {item['question']}" for item in pending)
    core_labels = packet.get("core_videos", [])
    if core_labels:
        lines.extend(["", "## 核心视频与观看重点", ""])
        for label in core_labels:
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
                f"{video['evidence_id']}｜{canonical_video_url(video)}"
            )
    complete_labels = packet.get("complete_related_videos", [])
    remaining_labels = [
        label for label in complete_labels if label not in set(core_labels)
    ]
    if remaining_labels:
        lines.extend(["", "## 完整相关视频", ""])
        for label in remaining_labels:
            video = videos[label]
            lines.append(
                f"- {label}｜{video['title']}｜证据ID："
                f"{video['evidence_id']}｜{canonical_video_url(video)}"
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
