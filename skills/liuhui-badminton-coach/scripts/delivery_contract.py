#!/usr/bin/env python3
"""Typed answer-delivery requirements shared by context, render, and audit."""

from __future__ import annotations

import re


DELIVERY_SCHEMA_VERSION = 1

_PLAN_TERMS = (
    "训练方案",
    "训练计划",
    "练习方案",
    "练习计划",
    "分钟计划",
    "三天纠正",
    "三天修正",
    "两周巩固",
    "两周进阶",
    "成功标准",
)
_BOUNDARY_ONLY_PATTERNS = (
    re.compile(r"^(?:没有|无|暂时没有).*(?:视频|录像).*(?:不要|不能).*(?:说死|确认唯一原因)$"),
    re.compile(r"^(?:当前)?信息不足时.*(?:不要|不能).*(?:说死|确认唯一原因)$"),
    re.compile(r"^(?:请)?(?:说明|保留|给出)?(?:证据|适用|置信)边界$"),
)
_DELIVERY_TAIL_STARTS = (
    re.compile(r"(?:，|,)?(?:并|再|然后)?(?:请)?给(?:我|出|一个)?"),
    re.compile(r"(?:。|；|;)?请按"),
)
_DELIVERY_TAIL_TERMS = (
    *_PLAN_TERMS,
    "检查顺序",
    "排查顺序",
    "条件分支",
    "相关视频",
    "证据边界",
)


def _normalized(value):
    return re.sub(r"\s+", "", str(value))


def evidence_query_for_unit(unit):
    """Remove pure delivery instructions while retaining the technical question."""

    text = str(unit).strip()
    normalized = _normalized(text)
    normalized_core = normalized.strip("，,。；;？?！!")
    if any(
        pattern.fullmatch(normalized_core)
        for pattern in _BOUNDARY_ONLY_PATTERNS
    ):
        return ""
    earliest = None
    for pattern in _DELIVERY_TAIL_STARTS:
        for match in pattern.finditer(text):
            tail = text[match.start() :]
            if any(term in _normalized(tail) for term in _DELIVERY_TAIL_TERMS):
                earliest = match.start() if earliest is None else min(earliest, match.start())
                break
    if earliest is not None:
        text = text[:earliest].strip(" ，,。；;？?！!")
    if any(term in _normalized(text) for term in _PLAN_TERMS) and not any(
        marker in _normalized(text)
        for marker in ("区分", "排查", "判断", "检查")
    ):
        return ""
    return text


def analyze_query_units(units):
    records = []
    for source_unit in units:
        evidence_query = evidence_query_for_unit(source_unit)
        if not evidence_query:
            role = "delivery_instruction"
        elif _normalized(evidence_query) != _normalized(source_unit):
            role = "mixed"
        else:
            role = "evidence_question"
        records.append(
            {
                "source_unit": source_unit,
                "evidence_query": evidence_query,
                "role": role,
            }
        )
    return records


def merge_constraints(parent, child):
    """Inherit missing scenario axes while preserving explicit child overrides."""

    result = {
        key: list(values)
        for key, values in (child or {}).items()
        if values
    }
    for key, values in (parent or {}).items():
        if values and key not in result:
            result[key] = list(values)
    return result


def should_inherit_root_context(local_constraints, unit_role):
    """Inherit only for elliptical or delivery-mixed child units."""

    has_local_scope = any((local_constraints or {}).values())
    return not has_local_scope or unit_role in {
        "mixed",
        "delivery_instruction",
    }


def inherit_actor_context(parent, child):
    result = dict(child or {})
    result["local_target_constraints"] = dict(
        (child or {}).get("target_constraints", {})
    )
    for key in (
        "target_constraints",
        "target_action_constraints",
        "player_constraints",
        "derived_target_constraints",
        "derived_player_constraints",
    ):
        result[key] = merge_constraints(
            (parent or {}).get(key, {}),
            (child or {}).get(key, {}),
        )
    result["inherited_root_context"] = bool(
        result["target_constraints"] != result["local_target_constraints"]
    )
    return result


def _append(items, kind, label, parameters=None, source_units=None):
    item = {
        "delivery_id": f"D{len(items) + 1}",
        "kind": kind,
        "label": label,
        "required": True,
        "parameters": parameters or {},
    }
    if source_units:
        item["source_units"] = list(source_units)
    items.append(item)


def _condition_axes(query):
    normalized = _normalized(query)
    axes = []
    for key, label, terms in (
        ("incoming_height", "来球高度", ("来球高度", "球的高度", "高低")),
        ("balance", "身体是否失衡", ("身体是否失衡", "是否失衡", "身体平衡", "重心")),
        ("partner_position", "搭档位置", ("搭档位置", "队友位置", "同伴位置")),
    ):
        if any(term in normalized for term in terms):
            axes.append({"axis": key, "label": label})
    return axes


def _direction_branches(query):
    normalized = _normalized(query)
    branches = []
    for value, label, terms in (
        ("straight", "直线", ("直线",)),
        ("crosscourt", "斜线", ("斜线", "对角")),
        ("middle", "中路", ("中路", "回中")),
    ):
        if any(term in normalized for term in terms):
            branches.append({"value": value, "label": label})
    return branches


def build_delivery_contract(
    query,
    question_interpretation,
    diagnostic_model,
    topic_navigation=None,
):
    """Create atomic, renderer-auditable delivery requirements."""

    items = []
    normalized_query = _normalized(query)
    source_units = question_interpretation.get("source_query_units") or (
        question_interpretation.get("query_units") or [query]
    )
    hypotheses = [
        {
            "id": item.get("id"),
            "text": item.get("text"),
            "status": item.get("status", "unverified"),
        }
        for item in diagnostic_model.get("user_hypotheses", [])
        if item.get("text")
    ]
    mechanisms = [
        {
            "id": item.get("id"),
            "text": item.get("label"),
            "status": item.get("status", "conditional"),
        }
        for item in diagnostic_model.get("supported_mechanisms", [])
        if item.get("label")
    ]
    if len(hypotheses) >= 2 and any(
        term in normalized_query
        for term in (
            "区分",
            "比较",
            "排查",
            "判断",
            "还是",
            "也可能",
            "或者",
            "或",
        )
    ):
        _append(
            items,
            "diagnosis.hypothesis_comparison",
            "逐项区分用户提出的原因",
            {"candidates": hypotheses},
            source_units,
        )
    if any(term in normalized_query for term in ("检查顺序", "排查顺序", "现场检查")):
        steps = []
        seen = set()
        for candidate in [*hypotheses, *mechanisms]:
            text = candidate.get("text")
            if text and text not in seen:
                seen.add(text)
                steps.append(candidate)
        _append(
            items,
            "diagnosis.ordered_checklist",
            "现场检查顺序",
            {"steps": steps},
            source_units,
        )

    requested_output = (
        question_interpretation.get("intent_frame", {}).get("requested_output")
    )
    if requested_output == "practice":
        _append(
            items,
            "evidence.training_boundary",
            "训练方案证据边界",
            source_units=source_units,
        )

    directions = _direction_branches(query)
    decision_requested = directions and any(
        term in normalized_query for term in ("什么时候", "何时", "应该", "条件", "选择")
    )
    if decision_requested:
        axes = _condition_axes(query)
        for branch in directions:
            _append(
                items,
                "tactics.direction_branch",
                f"{branch['label']}条件分支",
                {"branch": branch, "condition_axes": axes},
                source_units,
            )
        if axes:
            _append(
                items,
                "tactics.condition_axes",
                "战术条件轴",
                {"condition_axes": axes},
                source_units,
            )

    if "视频" in normalized_query:
        _append(items, "evidence.sources", "相关视频或明确证据缺口", source_units=source_units)
    if "证据边界" in normalized_query or "不要把原因说死" in normalized_query:
        _append(items, "evidence.boundary", "证据边界", source_units=source_units)

    return {
        "schema_version": DELIVERY_SCHEMA_VERSION,
        "items": items,
        "required_ids": [item["delivery_id"] for item in items],
    }


def completeness_items(delivery_contract):
    return [
        {
            "item_id": item["delivery_id"],
            "kind": item["kind"],
            "text": item["label"],
            "status": "must_answer",
            "required_treatment": "render and semantically validate the typed delivery block",
        }
        for item in delivery_contract.get("items", [])
    ]
