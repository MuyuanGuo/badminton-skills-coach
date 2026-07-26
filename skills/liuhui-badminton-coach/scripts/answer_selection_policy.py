#!/usr/bin/env python3
"""Leaf selection policy shared by retrieval and answer-context orchestration."""

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
SELECTION_RULES_PATH = ROOT / "references" / "answer-selection-rules.json"
RETRIEVAL_RULES_PATH = ROOT / "references" / "retrieval-rules.json"
_STATIC_RESOURCE_CACHE = {}


def _load_constraints():
    spec = importlib.util.spec_from_file_location(
        "liuhui_answer_selection_constraints",
        SCRIPT_DIR / "answer_constraints.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_constraints = _load_constraints()
constraint_decision = _constraints.constraint_decision
query_actor_context = _constraints.query_actor_context
query_constraints = _constraints.query_constraints
requested_action_scope_failures = _constraints.requested_action_scope_failures
required_constraint_support_failures = _constraints.required_constraint_support_failures
structured_video_text = _constraints.structured_video_text
video_constraint_scope = _constraints.video_constraint_scope

def load_selection_rules():
    if "selection_rules" in _STATIC_RESOURCE_CACHE:
        return _STATIC_RESOURCE_CACHE["selection_rules"]
    rules = json.loads(SELECTION_RULES_PATH.read_text(encoding="utf-8"))
    retrieval_rules = json.loads(RETRIEVAL_RULES_PATH.read_text(encoding="utf-8"))
    rules["_equivalent_groups"] = retrieval_rules.get("equivalent_groups", [])
    _STATIC_RESOURCE_CACHE["selection_rules"] = rules
    return rules

def classify_boundary(query, rules):
    normalized = query.replace(" ", "").lower()
    matched = {
        boundary: [term for term in terms if term in normalized]
        for boundary, terms in rules["boundary_terms"].items()
    }
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
        "matched_terms": matched[boundary_type] if boundary_type != "none" else [],
        "citation_policy": citation_policy,
        "required_statement": required_statement,
    }
