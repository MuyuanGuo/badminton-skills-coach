#!/usr/bin/env python3
"""Deterministic answer-evidence admission and facet classification.

Keep source integrity separate from answer usefulness.  A metadata/title
alignment warning may lower an item's answer role without discarding direct,
safe transcript evidence.
"""

import re


TITLE_ALIGNMENT_ISSUES = frozenset(
    {
        "title_has_no_technical_concept",
        "title_technical_concept_not_supported_by_transcript",
    }
)
ANSWER_ELIGIBILITIES = frozenset({"primary", "supplemental", "none"})


def split_transcript_issues(issues):
    values = sorted(set(issues or []))
    advisory = [item for item in values if item in TITLE_ALIGNMENT_ISSUES]
    blocking = [item for item in values if item not in TITLE_ALIGNMENT_ISSUES]
    return advisory, blocking


def answer_admission(
    *,
    origin_passed,
    transcript_issues,
    source_content_safe,
    automatic_evidence_passed,
    duplicate=False,
):
    advisory, blocking = split_transcript_issues(transcript_issues)
    if duplicate:
        eligibility = "none"
        disposition = "duplicate"
    elif not origin_passed:
        eligibility = "none"
        disposition = "quarantined_origin_verification"
    elif not source_content_safe:
        eligibility = "none"
        disposition = "quarantined_source_content_safety"
    elif blocking:
        eligibility = "none"
        disposition = "quarantined_transcript_quality"
    elif not automatic_evidence_passed:
        eligibility = "none"
        disposition = "quarantined_automatic_evidence_quality"
    elif advisory:
        eligibility = "supplemental"
        disposition = "supplemental_title_alignment"
    else:
        eligibility = "primary"
        disposition = "quality_gate_passed"
    return {
        "answer_eligibility": eligibility,
        "disposition": disposition,
        "answer_evidence_eligible": eligibility != "none",
        "advisory_issues": advisory,
        "blocking_issues": blocking,
        "metadata_title_trust": (
            "limited" if advisory else "transcript_aligned"
        ),
    }


def _flatten_note(note):
    values = []

    def visit(value):
        if isinstance(value, dict):
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif value is not None:
            values.append(str(value))

    visit(note or {})
    return " ".join(values)


def infer_evidence_roles(category, title, teaching_note):
    note = teaching_note or {}
    text = f"{category or ''} {title or ''} {_flatten_note(note)}"
    roles = set()
    if note.get("key_evidence"):
        roles.add("principle")
    if note.get("action_cues"):
        roles.add("action")
    if note.get("error_evidence"):
        roles.add("correction")
    if re.search(r"训练|练习|多球|热身|喂球|球感|怎么练", text):
        roles.add("practice")
    if category in {"单打战术", "双打战术"} or re.search(
        r"战术|轮转|补位|线路|落点|球路|站位", text
    ):
        roles.add("tactics")
    if category == "装备选择" or re.search(
        r"球拍|拍线|磅数|平衡点|中杆|[2345][uU]", text
    ):
        roles.add("equipment")
    if re.search(r"疼|痛|受伤|损伤|保护|安全|康复", text):
        roles.add("safety_boundary")
    if re.search(r"因为|原理|机制|传导|释放|卸力|发力", text):
        roles.add("mechanism")
    if not roles:
        roles.add("context")
    return sorted(roles)


def validate_answer_evidence_fields(record):
    eligibility = record.get("answer_eligibility")
    if eligibility not in ANSWER_ELIGIBILITIES:
        raise ValueError(f"invalid answer_eligibility: {eligibility!r}")
    roles = record.get("evidence_roles")
    if not isinstance(roles, list) or not roles or not all(
        isinstance(item, str) and item for item in roles
    ):
        raise ValueError("evidence_roles must be a non-empty string list")
    if record.get("processing_status") != "ready" and eligibility != "none":
        raise ValueError("non-ready evidence cannot be answer eligible")
