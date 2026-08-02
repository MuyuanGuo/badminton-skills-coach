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


def _bounded_note_windows(teaching_note):
    windows = []
    seen = set()
    for field in ("key_evidence", "error_evidence", "action_cues"):
        for item in (teaching_note or {}).get(field) or []:
            if not isinstance(item, dict):
                continue
            timestamp = str(item.get("timestamp") or "").strip()
            text = str(item.get("text") or "").strip()
            identity = (timestamp, text)
            if not text or identity in seen:
                continue
            seen.add(identity)
            windows.append(
                {"field": field, "timestamp": timestamp, "text": text}
            )
    return windows


def assess_bounded_note_recovery(record, rules):
    """Assess committed timestamped windows without trusting title metadata.

    The fallback is deliberately supplemental-only.  It exists for domains
    such as equipment, safety and tactics whose useful language is not well
    represented by the stroke-mechanics automatic evidence vocabulary.
    """

    config = (rules.get("evidence") or {}).get("bounded_note_recovery") or {}
    quality = record.get("quality") or {}
    automatic = quality.get("automatic_evidence") or {}
    automatic_issues = set(automatic.get("issues") or [])
    allowed_issues = set(config.get("allowed_automatic_evidence_issues") or [])
    transcript_issues = (quality.get("transcript") or {}).get("issues") or []
    _, blocking_transcript_issues = split_transcript_issues(transcript_issues)
    prerequisites = {
        "processing_status_recoverable": (
            record.get("processing_status") == "low_value"
            or (
                record.get("processing_status") == "ready"
                and record.get("runtime_evidence_mode")
                == "bounded_note_windows"
                and (record.get("automatic_admission") or {}).get(
                    "disposition"
                )
                == "supplemental_bounded_note_recovery"
            )
        ),
        "origin_passed": (
            (quality.get("origin_verification") or {}).get("passed") is True
        ),
        "source_content_safe": (
            (quality.get("source_content_safety") or {}).get("passed") is True
        ),
        "no_blocking_transcript_issues": not blocking_transcript_issues,
        "not_duplicate": not bool(record.get("possible_duplicate_evidence")),
        "automatic_failure_is_bounded": (
            automatic.get("passed") is False
            and bool(automatic_issues)
            and automatic_issues.issubset(allowed_issues)
        ),
    }
    minimum_characters = int(config.get("minimum_window_characters") or 12)
    cues = [str(item).lower() for item in config.get("instruction_terms") or []]
    role_matches = {}
    role_window_indexes = {}
    windows = _bounded_note_windows(record.get("teaching_note"))
    for role, role_config in (config.get("roles") or {}).items():
        terms = [str(item).lower() for item in role_config.get("terms") or []]
        matches = []
        indexes = []
        for index, window in enumerate(windows):
            text = window["text"].lower()
            matched_terms = sorted({term for term in terms if term in text})
            matched_cues = sorted({cue for cue in cues if cue in text})
            if (
                len(window["text"]) >= minimum_characters
                and matched_terms
                and matched_cues
            ):
                matches.append(
                    {
                        "timestamp": window["timestamp"],
                        "terms": matched_terms,
                        "cues": matched_cues,
                    }
                )
                indexes.append(index)
        minimum_windows = int(
            role_config.get("minimum_supported_windows") or 2
        )
        if len(matches) >= minimum_windows:
            role_matches[role] = matches
            role_window_indexes[role] = indexes
    supported_windows = {
        index for indexes in role_window_indexes.values() for index in indexes
    }
    supported_characters = sum(
        len(windows[index]["text"]) for index in supported_windows
    )
    minimum_total = int(
        config.get("minimum_total_supported_characters") or 24
    )
    passed = (
        bool(config)
        and all(prerequisites.values())
        and bool(role_matches)
        and supported_characters >= minimum_total
    )
    issues = [name for name, value in prerequisites.items() if not value]
    if not role_matches:
        issues.append("insufficient_role_supported_windows")
    if supported_characters < minimum_total:
        issues.append("insufficient_supported_characters")
    return {
        "version": config.get("version"),
        "passed": passed,
        "roles": sorted(role_matches),
        "supported_window_count": len(supported_windows),
        "supported_characters": supported_characters,
        "role_matches": role_matches,
        "supported_windows": [
            {
                "field": windows[index]["field"],
                "timestamp": windows[index]["timestamp"],
                "roles": sorted(
                    role
                    for role, indexes in role_window_indexes.items()
                    if index in indexes
                ),
            }
            for index in sorted(supported_windows)
        ],
        "issues": sorted(set(issues)),
    }


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
