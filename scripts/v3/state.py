"""Explicit, fail-closed v3 review state machines."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Transition:
    entity_type: str
    action: str
    from_state: str
    to_state: str
    requires_human: bool


_TRANSITIONS: dict[str, dict[tuple[str, str], str]] = {
    "transcript": {
        ("missing", "register_raw"): "raw_available",
        ("raw_available", "create_candidate"): "candidate",
        ("candidate", "begin_review"): "in_review",
        ("candidate", "reject"): "rejected",
        ("in_review", "source_verify"): "source_verified",
        ("in_review", "reject"): "rejected",
        ("source_verified", "invalidate"): "stale",
        ("stale", "create_candidate"): "candidate",
        ("stale", "reject"): "rejected",
        ("rejected", "reopen"): "candidate",
    },
    "video_summary": {
        ("missing", "create_draft"): "draft",
        ("draft", "source_verify"): "source_verified",
        ("draft", "reject"): "rejected",
        ("source_verified", "invalidate"): "stale",
        ("source_verified", "reject"): "rejected",
        ("stale", "reopen"): "draft",
        ("stale", "reject"): "rejected",
        ("rejected", "reopen"): "draft",
    },
    "teaching_event": {
        ("missing", "create_draft"): "draft",
        ("draft", "source_verify"): "source_verified",
        ("draft", "reject"): "rejected",
        ("source_verified", "invalidate"): "stale",
        ("source_verified", "reject"): "rejected",
        ("stale", "reopen"): "draft",
        ("stale", "reject"): "rejected",
        ("rejected", "reopen"): "draft",
    },
    "semantic_claim": {
        ("missing", "create_draft"): "draft",
        ("draft", "source_verify"): "source_verified",
        ("draft", "reject"): "rejected",
        ("source_verified", "domain_approve"): "domain_approved",
        ("source_verified", "invalidate"): "stale",
        ("source_verified", "reject"): "rejected",
        ("domain_approved", "publish"): "published",
        ("domain_approved", "invalidate"): "stale",
        ("domain_approved", "reject"): "rejected",
        ("published", "invalidate"): "stale",
        ("published", "withdraw"): "withdrawn",
        ("stale", "reopen"): "draft",
        ("stale", "reject"): "rejected",
        ("rejected", "reopen"): "draft",
        ("withdrawn", "reopen"): "draft",
    },
}

_MACHINE_ACTIONS = {"register_raw", "create_candidate", "create_draft", "invalidate"}
_AUTOMATION_WORDS = {
    "assistant",
    "automation",
    "bot",
    "codex",
    "gpt",
    "machine",
    "model",
    "openai",
    "pipeline",
    "system",
}


def entity_types() -> tuple[str, ...]:
    return tuple(_TRANSITIONS)


def is_automated_reviewer(reviewer_id: str) -> bool:
    folded = reviewer_id.casefold().strip()
    if not folded:
        return True
    if folded.startswith(("system:", "automation:", "machine:")):
        return True
    words = {word for word in re.split(r"[^a-z0-9]+", folded) if word}
    return bool(words & _AUTOMATION_WORDS) or "模型" in folded or "自动" in folded


def resolve_transition(
    entity_type: str,
    current_state: str,
    action: str,
    reviewer_id: str,
    human_confirmation: bool,
) -> Transition:
    if entity_type not in _TRANSITIONS:
        raise ValueError(f"unsupported entity type: {entity_type}")
    destination = _TRANSITIONS[entity_type].get((current_state, action))
    if destination is None:
        raise ValueError(
            f"invalid {entity_type} transition: {current_state} --{action}--> ?"
        )
    requires_human = action not in _MACHINE_ACTIONS
    if not reviewer_id.strip():
        raise ValueError("reviewer identity is required")
    if requires_human and not human_confirmation:
        raise ValueError(f"{action} requires explicit human confirmation")
    if requires_human and is_automated_reviewer(reviewer_id):
        raise ValueError(f"automated reviewer cannot perform {action}")
    return Transition(
        entity_type=entity_type,
        action=action,
        from_state=current_state,
        to_state=destination,
        requires_human=requires_human,
    )
