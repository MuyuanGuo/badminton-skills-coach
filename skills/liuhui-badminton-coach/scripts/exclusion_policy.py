#!/usr/bin/env python3
"""Semantic hard-exclusion checks shared by selection and answer audit."""

import json
import re


def normalized(value):
    return re.sub(r"[^0-9A-Za-z\u3400-\u9fff]+", "", str(value)).lower()


def searchable_text(payload):
    return normalized(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def matched_hard_exclusions(
    payload,
    hard_excluded_terms,
    rules,
    hard_excluded_scope_groups=None,
):
    """Return excluded concepts whose literal or semantic signatures occur."""

    text = searchable_text(payload)
    normalized_hard_terms = {
        normalized(term): term
        for term in hard_excluded_terms
        if normalized(term)
    }
    normalized_scope_groups = [
        [normalized(term) for term in group if normalized(term)]
        for group in (hard_excluded_scope_groups or [])
    ]
    normalized_scope_groups = [group for group in normalized_scope_groups if group]
    if normalized_scope_groups:
        matches = {
            " + ".join(group)
            for group in normalized_scope_groups
            if all(term in text for term in group)
        }
    else:
        # Backward compatibility for older stored contexts.
        matches = {
            original
            for term, original in normalized_hard_terms.items()
            if term in text
        }
    for profile in rules.get("hard_exclusion_evidence_signatures", []):
        excluded_terms = {
            normalized(term) for term in profile.get("excluded_terms", [])
        }
        active_terms = excluded_terms.intersection(normalized_hard_terms)
        if not active_terms:
            continue
        direct_match = any(
            normalized(term) and normalized(term) in text
            for term in profile.get("any_terms", [])
        )
        grouped_match = any(
            group
            and all(
                normalized(term) in text
                for term in group
                if normalized(term)
            )
            for group in profile.get("all_term_groups", [])
        )
        if direct_match or grouped_match:
            matches.update(normalized_hard_terms[term] for term in active_terms)
    return sorted(matches)
