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
    re.compile(r"^(?:没有|无|暂时没有).*(?:视频|录像)(?:时|的情况下)?$"),
    re.compile(r"^(?:当前)?信息不足时.*(?:不要|不能).*(?:说死|确认唯一原因)$"),
    re.compile(r"^(?:请)?(?:说明|保留|给出)?(?:证据|适用|置信)边界$"),
    re.compile(r"^(?:先)?告诉我目前能确定什么.*(?:顺序)?排查$"),
    re.compile(r"^现有信息能支持哪些原因.*(?:还)?不能确定$"),
    re.compile(
        r"^(?:我)?(?:怀疑|猜测|猜|觉得|认为)(?:是)?.*(?:也)?(?:可能|或许)(?:是)?.*$"
    ),
    re.compile(r"^这(?:两|2|二)个结论的证据(?:能不能|是否|可不可以)共用$"),
    re.compile(r"^(?:再)?比较哪些检查项不能互相借证据$"),
    re.compile(r"^(?:请)?分别(?:判断|比较|区分)(?:这)?(?:两|2|二|三|3)种原因$"),
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

_NEGATIVE_ONLY_MARKERS = (
    "不要讲",
    "不讨论",
    "不讲",
    "别讲",
    "别说",
    "别把",
    "不要涉及",
    "不涉及",
    "不考虑",
    "不要",
    "不需要",
    "无需",
    "排除",
)

_OBSERVATION_REQUEST_MARKERS = (
    "为什么",
    "怎么",
    "如何",
    "能否",
    "能不能",
    "是不是",
    "还是",
    "排查",
    "检查",
    "判断",
    "原因",
    "哪些",
    "什么",
    "哪里",
    "哪边",
    "哪块",
    "啥",
    "为何",
    "为啥",
    "咋",
    "还缺",
    "补充",
)

_OBSERVATION_STATE_MARKERS = (
    "总",
    "有时",
    "常",
    "只到",
    "回不到",
    "接不到",
    "够不到",
    "够得到",
    "到不了",
    "来不及",
    "下网",
    "冒高",
    "浮高",
    "过高",
    "失衡",
    "到位",
    "停住",
    "体侧",
    "身前",
    "身后",
    "髋部",
    "肩部",
    "半场",
    "已经",
    "仍",
    "站稳",
    "守住",
    "回中",
    "退守",
    "没有后退",
    "选择",
    "守前场",
    "守后场",
    "被压",
    "先杀",
    "下一拍",
)


def _normalized(value):
    return re.sub(r"\s+", "", str(value))


def _is_exclusion_only(value):
    normalized = _normalized(value).strip("，,。；;？?！!")
    clauses = [
        item
        for item in re.split(
            r"[，,。；;？?！!、]|(?:也|并且|以及|和|与)(?=(?:不要|不讨论|不讲|别讲|别说|别把|不涉及|不考虑|无需|排除))",
            normalized,
        )
        if item
    ]
    return bool(clauses) and all(
        clause.startswith(_NEGATIVE_ONLY_MARKERS) for clause in clauses
    )


def evidence_query_for_unit(unit):
    """Remove pure delivery instructions while retaining the technical question."""

    text = str(unit).strip()
    normalized = _normalized(text)
    normalized_core = normalized.strip("，,。；;？?！!")
    if _is_exclusion_only(normalized_core):
        return ""
    if any(
        pattern.fullmatch(normalized_core)
        for pattern in _BOUNDARY_ONLY_PATTERNS
    ):
        return ""
    if re.fullmatch(
        r"(?:请)?(?:把.*分开解释)?(?:并)?(?:告诉|说明|列出).*(?:视频|证据).*(?:分别支持|支持哪|对应).*",
        normalized_core,
    ):
        return ""
    if (
        "分开解释" in normalized_core
        and "视频" in normalized_core
        and "支持" in normalized_core
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


def _is_user_observation(value):
    """Recognize reported conditions/symptoms that do not need proving.

    These units still inform retrieval and diagnosis, but they must not become
    claims such as “the source proves that the user was already in position”.
    """

    normalized = _normalized(value).strip("，,。；;？?！!")
    if not normalized or any(
        marker in normalized for marker in _OBSERVATION_REQUEST_MARKERS
    ):
        return False
    known_prefix = normalized.startswith(
        ("已知", "只知道", "我只知道", "只有在", "我只有在")
    )
    reports_self_or_condition = any(
        marker in normalized
        for marker in ("我", "自己", "身体", "触球", "击球", "接球", "来球")
    )
    reports_state = any(
        marker in normalized for marker in _OBSERVATION_STATE_MARKERS
    )
    return known_prefix or (reports_self_or_condition and reports_state)


def _is_contextual_followup(value):
    normalized = _normalized(value).strip("，,。；;？?！!")
    return normalized.startswith(("如果", "假如", "若", "换成", "改到")) and any(
        marker in normalized
        for marker in ("一样", "相同", "不同", "会不会", "是否", "吗", "呢")
    )


def _explicit_subquestions(source_unit, all_units):
    """Expand an explicit request to answer named issues separately."""

    normalized = _normalized(source_unit).strip("，,。；;？?！!")
    full = _normalized(" ".join(map(str, all_units)))
    if not any(marker in normalized for marker in ("分开回答", "分别回答")):
        return []

    quoted = re.findall(r"[“\"]([^”\"]+)[”\"]", source_unit)
    if len(quoted) >= 2:
        return [item.strip(" ，,。；;？?！!") for item in quoted if item.strip()]

    # A paired incoming-shot diagnosis names the branches in earlier context
    # and asks for “两种来球” later. Bind each reported outcome to its own
    # branch instead of making the delivery sentence a technical claim.
    if "两种来球" in normalized and "腋下" in full and "膝侧" in full:
        left_outcome = "冒高" if "腋下球冒高" in full else ""
        right_outcome = "下网" if "膝侧球下网" in full else ""
        return [
            f"反手腋下来球{left_outcome}的排查顺序",
            f"反手膝侧来球{right_outcome}的排查顺序",
        ]

    tail = re.split(r"分开回答|分别回答", source_unit, maxsplit=1)[-1]
    tail = re.split(r"(?:，|,)?(?:现有信息|已有信息|以及|并比较|再比较)", tail, maxsplit=1)[0]
    parts = [
        item.strip(" ，,。；;？?！!")
        for item in re.split(r"[、]", tail)
        if item.strip(" ，,。；;？?！!")
    ]
    if len(parts) < 2:
        return []
    result = []
    asks_confirmation = "能确认什么" in normalized
    partner_present = "搭档" in full or "队友" in full or "搭子" in full
    for item in parts:
        item = re.sub(r"^(?:请)?", "", item).strip()
        if partner_present:
            item = re.sub(r"^(?:她|他)的出球", "搭档的出球", item)
        if asks_confirmation and "确认" not in item:
            item = f"{item}现有信息能确认什么"
        result.append(item)
    return result


def analyze_query_units(units):
    records = []
    for source_unit in units:
        explicit_subquestions = _explicit_subquestions(source_unit, units)
        if explicit_subquestions:
            records.extend(
                {
                    "source_unit": source_unit,
                    "evidence_query": item,
                    "role": "explicit_subquestion",
                }
                for item in explicit_subquestions
            )
            continue
        evidence_query = evidence_query_for_unit(source_unit)
        if not evidence_query:
            role = "delivery_instruction"
        elif _is_user_observation(evidence_query):
            role = "user_observation"
        elif _is_contextual_followup(evidence_query):
            role = "contextual_followup"
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
    normalized_units = _normalized(" ".join(map(str, units)))
    explicit_separate_problem_request = (
        "分开解释" in normalized_units
        and any(
            marker in normalized_units
            for marker in ("两个问题", "两项问题", "分别支持", "分别解释")
        )
    )
    if explicit_separate_problem_request:
        for record in records:
            normalized_query = _normalized(record["evidence_query"])
            if (
                record["role"] == "user_observation"
                and not normalized_query.startswith(
                    ("已知", "只知道", "我只知道")
                )
                and any(
                    marker in normalized_query
                    for marker in _OBSERVATION_STATE_MARKERS
                )
            ):
                # “A 有问题；B 也有问题；请把两个问题分开解释”
                # explicitly asks for both symptom reports to be answered.
                record["role"] = "evidence_question"
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

    if unit_role == "explicit_subquestion":
        # Explicitly named actor/action questions must be parsed on their own;
        # inheriting the root player's action can make a partner claim use the
        # player's evidence. Missing scenario detail is safer as a gap.
        return False
    has_local_scope = any((local_constraints or {}).values())
    return not has_local_scope or unit_role in {
        "mixed",
        "delivery_instruction",
        "user_observation",
        "contextual_followup",
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
        "incoming_shot_constraints",
        "incoming_destination_constraints",
    ):
        result[key] = merge_constraints(
            (parent or {}).get(key, {}),
            (child or {}).get(key, {}),
        )
    for key in (
        "requested_action_scopes",
        "scope_boundary_statements",
        "derived_search_terms",
    ):
        result[key] = list(
            dict.fromkeys(
                [
                    *(parent or {}).get(key, []),
                    *(child or {}).get(key, []),
                ]
            )
        )
    result["inherited_root_context"] = bool(
        result["target_constraints"] != result["local_target_constraints"]
    )
    if not result.get("event_chain") and (parent or {}).get("event_chain"):
        result["event_chain"] = list(parent["event_chain"])
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
    if any(
        term in normalized_query
        for term in (
            "检查顺序",
            "排查顺序",
            "现场检查",
            "按什么顺序排查",
            "按哪个顺序排查",
            "按怎样的顺序排查",
        )
    ):
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

    requested_scopes = set(
        question_interpretation.get("actor_context", {}).get(
            "requested_action_scopes", []
        )
    )
    coverage_responsibility = "team_coverage_rotation" in requested_scopes
    if coverage_responsibility:
        conditions = [
            label
            for label, terms in (
                ("搭档已封住直线", ("封住直线", "封直线")),
                ("搭档被带向中路", ("被带向中路", "带向中路")),
                ("搭档守前场", ("搭档守前场", "女搭档守前场")),
            )
            if any(term in normalized_query for term in terms)
        ]
        _append(
            items,
            "tactics.coverage_responsibility",
            "双打轮转补位责任",
            {
                "actors": ["自己", "搭档"],
                "conditions": conditions,
            },
            source_units,
        )

    directions = [] if coverage_responsibility else _direction_branches(query)
    decision_requested = directions and (
        any(
            term in normalized_query
            for term in ("什么时候", "何时", "条件")
        )
        or any(
            term in normalized_query
            for term in ("怎么选择", "如何选择", "选择哪", "该选择")
        )
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
    if any(
        term in normalized_query
        for term in ("证据能不能共用", "证据是否共用", "不能互相借证据", "证据可不可以共用")
    ):
        _append(
            items,
            "evidence.claim_separation",
            "不同结论的证据边界",
            {
                "statement": "不同主体、动作或来球分支的结论必须分别绑定证据，不能因处在同一回合或同一视频中就自动共用。"
            },
            source_units,
        )
    if (
        "证据边界" in normalized_query
        or "不要把原因说死" in normalized_query
        or (
            requested_output == "diagnosis"
            and any(term in normalized_query for term in ("能确定", "不能确定"))
        )
    ):
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
