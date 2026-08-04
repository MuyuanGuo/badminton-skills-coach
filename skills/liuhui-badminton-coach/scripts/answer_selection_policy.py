#!/usr/bin/env python3
"""Leaf selection policy shared by retrieval and answer-context orchestration."""

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from answer_constraints import (
    constraint_decision,
    query_actor_context,
    query_constraints,
    requested_action_scope_failures,
    required_constraint_support_failures,
    structured_video_text,
    video_constraint_scope,
)

__all__ = [
    "classify_boundary",
    "constraint_decision",
    "load_selection_rules",
    "query_actor_context",
    "query_constraints",
    "requested_action_scope_failures",
    "required_constraint_support_failures",
    "structured_video_text",
    "video_constraint_scope",
]


ROOT = Path(__file__).resolve().parents[1]
SELECTION_RULES_PATH = ROOT / "references" / "answer-selection-rules.json"
RETRIEVAL_RULES_PATH = ROOT / "references" / "retrieval-rules.json"
_STATIC_RESOURCE_CACHE = {}


def load_selection_rules():
    if "selection_rules" in _STATIC_RESOURCE_CACHE:
        return _STATIC_RESOURCE_CACHE["selection_rules"]
    rules = json.loads(SELECTION_RULES_PATH.read_text(encoding="utf-8"))
    retrieval_rules = json.loads(RETRIEVAL_RULES_PATH.read_text(encoding="utf-8"))
    rules["_equivalent_groups"] = retrieval_rules.get("equivalent_groups", [])
    _STATIC_RESOURCE_CACHE["selection_rules"] = rules
    return rules

def classify_boundary(query, rules, requested_constraints=None):
    normalized = query.replace(" ", "").lower()
    requested_constraints = requested_constraints or {}
    matched = {
        boundary: [term for term in terms if term in normalized]
        for boundary, terms in rules["boundary_terms"].items()
    }
    cross_variant_terms = [
        term
        for term in rules.get("cross_variant_transfer_terms", [])
        if term.replace(" ", "").lower() in normalized
    ]
    cross_scope_axes = rules.get(
        "cross_evidence_transfer_axes", ["technique_variant"]
    )
    cross_variant_transfer = bool(
        cross_variant_terms
        and any(
            len(requested_constraints.get(axis_name, [])) >= 2
            for axis_name in cross_scope_axes
        )
    )
    if matched["pain_or_injury"]:
        boundary_type = "pain_or_injury"
        citation_policy = "no_coaching_video_without_direct_safety_evidence"
        required_statement = "停止引发疼痛的动作，并由合格医疗专业人士评估；本 Skill 不作诊断。"
    elif matched["endorsement_or_authorship"]:
        boundary_type = "endorsement_or_authorship"
        citation_policy = "no_video_needed_for_identity_or_endorsement_boundary"
        required_statement = "Skill 的综合回答不代表刘辉本人审阅、认可或背书。"
    elif matched["purchase_advice"]:
        boundary_type = "purchase_advice"
        citation_policy = "equipment_evidence_only"
        required_statement = "只能总结来源中的选拍原则，不能冒充刘辉给出个性化购买背书。"
    elif cross_variant_transfer:
        boundary_type = "cross_variant_evidence_transfer"
        citation_policy = "no_cross_variant_substitution"
        required_statement = (
            "不同动作变体或适用范围的证据不能互相代替；只有明确覆盖目标侧别、"
            "主动被动状态和技术变体的来源才能证明目标动作，其他来源最多支持"
            "单独映射的通用组件。"
        )
    elif matched["visual_confirmation"]:
        boundary_type = "visual_confirmation"
        citation_policy = "technique_video_required_but_user_form_unverified"
        required_statement = "文字和示范视频可以提供检查点，但不能确认用户自己的动作完全正确。"
    elif matched["insufficient_observation"]:
        boundary_type = "insufficient_observation"
        citation_policy = (
            "no_video_needed_for_unique_cause_boundary"
            if "唯一原因" in matched["insufficient_observation"]
            else "literal_problem_evidence_only"
        )
        required_statement = "仅凭文字症状不能确定唯一原因；只能列出证据直接覆盖的可能性和需要补充的观察。"
    else:
        boundary_type = "none"
        citation_policy = "direct_worthwhile_evidence_only"
        required_statement = None
    return {
        "type": boundary_type,
        "matched_terms": (
            cross_variant_terms
            if boundary_type == "cross_variant_evidence_transfer"
            else matched[boundary_type]
            if boundary_type != "none"
            else []
        ),
        "citation_policy": citation_policy,
        "required_statement": required_statement,
    }
