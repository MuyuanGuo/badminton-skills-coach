#!/usr/bin/env python3
"""Audit a generated coaching answer against its prepared answer context."""

import argparse
import hashlib
import json
import re
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RULES_PATH = SKILL_ROOT / "references" / "answer-audit-rules.json"
CONFIDENCE_RANK = {"none": 0, "low": 1, "moderate": 2, "high": 3}
ANSWER_TURN_CONTRACT_SCHEMA_VERSION = 1


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_rules(path=DEFAULT_RULES_PATH):
    return load_json(path)


def normalized(value):
    return re.sub(r"[^0-9A-Za-z\u3400-\u9fff]+", "", str(value)).lower()


def compile_any(patterns):
    return re.compile("(?:" + "|".join(f"(?:{item})" for item in patterns) + ")")


def answer_units(answer):
    return [
        unit.strip()
        for unit in re.split(r"\n+", answer)
        if unit.strip()
    ]


def content_ngrams(value, rules, width=2):
    text = normalized(value)
    for phrase in rules.get("coverage_stop_phrases", []):
        text = text.replace(normalized(phrase), "")
    if not text:
        return set()
    if len(text) < width:
        return {text}
    return {text[index : index + width] for index in range(len(text) - width + 1)}


def text_match_score(needle, haystack, rules):
    needle_text = normalized(needle)
    haystack_text = normalized(haystack)
    if not needle_text or not haystack_text:
        return 0.0
    if needle_text in haystack_text:
        return 1.0
    needle_grams = content_ngrams(needle, rules)
    if not needle_grams:
        return 0.0
    return len(needle_grams & content_ngrams(haystack, rules)) / len(needle_grams)


def selected_video_maps(context):
    by_label = {}
    by_evidence_id = {}
    for video in context.get("selected_videos", []):
        label = video.get("label")
        evidence_id = str(video.get("evidence_id", video.get("video_id", "")))
        canonical_url = video.get("canonical_url") or video.get("url")
        if label:
            by_label[label] = {
                "evidence_id": evidence_id,
                "canonical_url": canonical_url,
            }
        if evidence_id:
            by_evidence_id[evidence_id] = label
    return by_label, by_evidence_id


def labels_in(text, label_pattern):
    return {f'V{match.group("number")}' for match in label_pattern.finditer(text)}


def matched_claims(unit, claims, rules, marker_pattern):
    explicit = {
        match.group("claim_id") for match in marker_pattern.finditer(unit)
    }
    if explicit:
        return [claim for claim in claims if claim.get("claim_id") in explicit]
    scored = [
        (text_match_score(claim.get("text", ""), unit, rules), claim)
        for claim in claims
    ]
    scored = [item for item in scored if item[0] >= rules["claim_match_threshold"]]
    if not scored:
        return []
    best = max(score for score, _ in scored)
    return [claim for score, claim in scored if score >= best - 0.05]


def add_violation(violations, code, message, *, claim_id=None, unit=None, details=None):
    violation = {
        "code": code,
        "severity": "error",
        "message": message,
    }
    if claim_id:
        violation["claim_id"] = claim_id
    if unit:
        violation["answer_excerpt"] = unit[:240]
    if details:
        violation["details"] = details
    signature = (
        violation["code"],
        violation.get("claim_id"),
        violation.get("answer_excerpt"),
        json.dumps(violation.get("details"), ensure_ascii=False, sort_keys=True),
    )
    if signature not in {
        (
            item["code"],
            item.get("claim_id"),
            item.get("answer_excerpt"),
            json.dumps(item.get("details"), ensure_ascii=False, sort_keys=True),
        )
        for item in violations
    }:
        violations.append(violation)


def expected_evidence_state(context):
    return {
        "selected_videos": [
            {
                "label": item.get("label"),
                "evidence_id": str(
                    item.get("evidence_id", item.get("video_id", ""))
                ),
                "canonical_url": item.get("canonical_url") or item.get("url"),
            }
            for item in context.get("selected_videos", [])
        ],
        "claim_evidence": [
            {
                "claim_id": item.get("claim_id"),
                "kind": item.get("kind"),
                "status": item.get("status"),
                "eligible_video_labels": item.get(
                    "eligible_video_labels", []
                ),
                "confidence_ceiling": item.get("confidence_ceiling", "none"),
                "evidence": [
                    {
                        "label": evidence.get("label"),
                        "evidence_id": str(evidence.get("evidence_id", "")),
                        "directness": evidence.get("directness"),
                        "scope": evidence.get("scope"),
                    }
                    for evidence in item.get("evidence", [])
                ],
            }
            for item in context.get("claim_evidence_map", [])
        ],
    }


def canonical_json_digest(payload):
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_answer_turn_contract(context):
    contract = context.get("answer_turn_contract")
    if contract is None:
        return None, []
    errors = []
    state = context.get("clarification_state")
    required = {
        "schema_version",
        "original_query",
        "effective_query",
        "turn_number",
        "resolved_clarifications",
        "pending_clarifications",
        "resolved_question_ids_must_not_be_reasked",
        "evidence_state",
        "evidence_state_digest",
    }
    if not isinstance(contract, dict) or required - set(contract):
        return contract, ["missing required answer-turn fields"]
    if contract.get("schema_version") != ANSWER_TURN_CONTRACT_SCHEMA_VERSION:
        errors.append("unsupported schema_version")
    if not all(
        isinstance(contract.get(field), str) and contract[field].strip()
        for field in ("original_query", "effective_query")
    ):
        errors.append("original_query and effective_query must be non-empty")
    if not isinstance(contract.get("turn_number"), int) or contract["turn_number"] < 1:
        errors.append("turn_number must be a positive integer")
    if not isinstance(state, dict):
        errors.append("missing clarification_state")
    else:
        comparisons = {
            "original_query": state.get("original_query"),
            "effective_query": state.get("effective_query"),
            "turn_number": len(state.get("turns", [])),
            "resolved_clarifications": state.get("resolved_answers"),
            "pending_clarifications": state.get("pending_requests"),
            "resolved_question_ids_must_not_be_reasked": [
                item.get("question_id")
                for item in state.get("resolved_answers", [])
            ],
        }
        for field, expected in comparisons.items():
            if contract.get(field) != expected:
                errors.append(f"{field} does not match clarification_state")
    resolved = contract.get("resolved_clarifications", [])
    if not isinstance(resolved, list) or any(
        not isinstance(item, dict)
        or not all(
            isinstance(item.get(field), str) and item[field].strip()
            for field in ("question_id", "question", "answer")
        )
        for item in resolved
    ):
        errors.append("resolved clarifications require question_id, question, and answer")
    pending = contract.get("pending_clarifications", [])
    if not isinstance(pending, list) or any(
        not isinstance(item, dict)
        or not isinstance(item.get("question_id"), str)
        or not item.get("question_id").strip()
        or not isinstance(item.get("question"), str)
        or not item.get("question").strip()
        or not isinstance(item.get("purpose"), str)
        or not item.get("purpose").strip()
        for item in pending
    ):
        errors.append("pending clarifications require question_id, question, and purpose")
    resolved_ids = [
        item.get("question_id") for item in resolved if isinstance(item, dict)
    ]
    pending_ids = [
        item.get("question_id") for item in pending if isinstance(item, dict)
    ]
    if len(resolved_ids) != len(set(resolved_ids)):
        errors.append("resolved clarification IDs must be unique")
    if len(pending_ids) != len(set(pending_ids)):
        errors.append("pending clarification IDs must be unique")
    if set(resolved_ids) & set(pending_ids):
        errors.append("resolved and pending clarification IDs must not overlap")
    evidence_state = expected_evidence_state(context)
    if contract.get("evidence_state") != evidence_state:
        errors.append("evidence_state does not match the current context")
    if contract.get("evidence_state_digest") != canonical_json_digest(
        evidence_state
    ):
        errors.append("evidence_state_digest does not match the current context")
    return contract, errors


def item_coverage(item, context, units, rules, marker_pattern):
    item_id = item["item_id"]
    explicit = [unit for unit in units if any(
        match.group("claim_id") == item_id for match in marker_pattern.finditer(unit)
    )]
    if explicit:
        return explicit
    if item_id.startswith("B"):
        branch = next(
            (
                candidate
                for candidate in context.get("diagnostic_model", {}).get("material_branches", [])
                if candidate.get("id") == item_id
            ),
            None,
        )
        if branch:
            required = [
                value.get("label", "")
                for value in branch.get("branches", [])
                if value.get("eligible_video_labels")
            ]
            branch_units = [
                unit
                for unit in units
                if text_match_score(branch.get("label", ""), unit, rules)
                >= rules["claim_match_threshold"]
                or any(normalized(label) in normalized(unit) for label in required)
            ]
            covered = {
                label
                for label in required
                if any(normalized(label) in normalized(unit) for unit in branch_units)
            }
            return branch_units if covered == set(required) else []
    return [
        unit
        for unit in units
        if text_match_score(item.get("text", ""), unit, rules)
        >= rules["claim_match_threshold"]
    ]


def audit_answer(question, context, answer, rules=None):
    rules = rules or load_rules()
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string")
    if not isinstance(context, dict):
        raise ValueError("context must be a JSON object")
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("answer must be a non-empty string")

    violations = []
    feedback_prompt = context.get("answer_contract", {}).get(
        "feedback_prompt"
    )
    auditable_answer = answer
    if feedback_prompt:
        if not answer.rstrip().endswith(feedback_prompt):
            add_violation(
                violations,
                "missing_feedback_prompt",
                "The answer does not end with the exact required feedback prompt.",
            )
        else:
            auditable_answer = answer.rstrip()[: -len(feedback_prompt)].rstrip()
    units = answer_units(auditable_answer)
    claims = context.get("claim_evidence_map", [])
    claim_by_id = {claim.get("claim_id"): claim for claim in claims}
    selected_by_label, selected_by_evidence_id = selected_video_maps(context)
    label_pattern = re.compile(rules["video_label_pattern"])
    evidence_id_pattern = re.compile(rules["evidence_id_pattern"])
    marker_pattern = re.compile(rules["claim_marker_pattern"])
    conditional_pattern = compile_any(rules["conditional_markers"])
    uncertainty_pattern = compile_any(rules["uncertainty_markers"])
    certainty_pattern = compile_any(rules["hard_certainty_markers"])
    universal_pattern = compile_any(rules["universal_markers"])

    turn_contract, turn_contract_errors = validate_answer_turn_contract(context)
    if turn_contract_errors:
        add_violation(
            violations,
            "invalid_clarification_contract",
            "The answer-turn contract is missing or inconsistent.",
            details={"errors": turn_contract_errors},
        )
        if any("evidence_state" in error for error in turn_contract_errors):
            add_violation(
                violations,
                "answer_turn_evidence_state_mismatch",
                "The answer-turn contract does not describe the current evidence state.",
            )

    expected_question = (
        turn_contract.get("original_query", "")
        if isinstance(turn_contract, dict)
        else context.get("query", "")
    )
    if normalized(expected_question) != normalized(question):
        add_violation(
            violations,
            "question_context_mismatch",
            "The supplied question does not match the question used to prepare the context.",
        )

    all_labels = labels_in(auditable_answer, label_pattern)
    for label in sorted(all_labels):
        if label not in selected_by_label:
            add_violation(
                violations,
                "unmapped_video_label",
                f"{label} is not in selected_videos.",
                details={"label": label, "allowed_labels": sorted(selected_by_label)},
            )

    answer_evidence_ids = set(evidence_id_pattern.findall(auditable_answer))
    for evidence_id in sorted(answer_evidence_ids):
        if evidence_id not in selected_by_evidence_id:
            add_violation(
                violations,
                "unmapped_evidence_id",
                f"Evidence ID {evidence_id} is not in selected_videos.",
                details={"evidence_id": evidence_id},
            )

    for unit in units:
        unit_labels = labels_in(unit, label_pattern)
        unit_claims = matched_claims(unit, claims, rules, marker_pattern)
        for claim in unit_claims:
            eligible = set(claim.get("eligible_video_labels", []))
            invalid = (unit_labels & set(selected_by_label)) - eligible
            if invalid:
                add_violation(
                    violations,
                    "citation_claim_mismatch",
                    "A claim cites evidence that is not mapped to that claim.",
                    claim_id=claim.get("claim_id"),
                    unit=unit,
                    details={
                        "cited_labels": sorted(unit_labels),
                        "eligible_labels": sorted(eligible),
                    },
                )

            if claim.get("kind") == "user_hypothesis" and claim.get("status") in {
                "unverified",
                "conditional",
            }:
                if certainty_pattern.search(unit) and not uncertainty_pattern.search(unit):
                    add_violation(
                        violations,
                        "unsupported_causal_certainty",
                        "A user-proposed cause is stated as confirmed.",
                        claim_id=claim.get("claim_id"),
                        unit=unit,
                    )
                continue

            if claim.get("status") not in {"supported", "conditional"}:
                continue
            ceiling = claim.get("confidence_ceiling", "none")
            assertion_rank = 3 if certainty_pattern.search(unit) else (
                1 if conditional_pattern.search(unit) else 2
            )
            if assertion_rank > CONFIDENCE_RANK.get(ceiling, 0):
                add_violation(
                    violations,
                    "confidence_ceiling_exceeded",
                    f"The wording exceeds the claim's {ceiling} confidence ceiling.",
                    claim_id=claim.get("claim_id"),
                    unit=unit,
                    details={"confidence_ceiling": ceiling},
                )

            cited_entries = [
                evidence
                for evidence in claim.get("evidence", [])
                if evidence.get("label") in unit_labels
            ]
            limited = cited_entries and all(
                any(
                    fragment in evidence.get("scope", "")
                    for fragment in rules["limited_scope_fragments"]
                )
                or evidence.get("directness") == "component"
                for evidence in cited_entries
            )
            if limited and universal_pattern.search(unit):
                add_violation(
                    violations,
                    "evidence_scope_overreach",
                    "Limited-scope evidence is used to make a universal claim.",
                    claim_id=claim.get("claim_id"),
                    unit=unit,
                )

        unit_without_urls = re.sub(r"https?://\S+", "", unit)
        unit_ids = set(evidence_id_pattern.findall(unit_without_urls))
        for label in unit_labels & set(selected_by_label):
            expected_id = selected_by_label[label]["evidence_id"]
            other_selected_ids = unit_ids & set(selected_by_evidence_id)
            if other_selected_ids and expected_id not in other_selected_ids:
                add_violation(
                    violations,
                    "citation_evidence_id_mismatch",
                    f"{label} is paired with the wrong evidence ID.",
                    unit=unit,
                    details={
                        "label": label,
                        "expected_evidence_id": expected_id,
                        "found_evidence_ids": sorted(other_selected_ids),
                    },
                )

    coverage = []
    for item in context.get("completeness_contract", {}).get("items", []):
        covered_units = item_coverage(item, context, units, rules, marker_pattern)
        covered = bool(covered_units)
        coverage.append(
            {
                "item_id": item.get("item_id"),
                "status": item.get("status"),
                "covered": covered,
            }
        )
        if not covered:
            add_violation(
                violations,
                "missing_completeness_item",
                "A required completeness item is absent from the answer.",
                claim_id=item.get("item_id"),
                details={"text": item.get("text"), "status": item.get("status")},
            )
            continue
        if item.get("status") in {"conditional", "unresolved"} and not any(
            conditional_pattern.search(unit) or uncertainty_pattern.search(unit)
            for unit in covered_units
        ):
            add_violation(
                violations,
                "conditionality_lost",
                "A conditional or unresolved item is presented without its required qualification.",
                claim_id=item.get("item_id"),
                unit=covered_units[0],
            )

        claim = claim_by_id.get(item.get("item_id"))
        if claim and claim.get("eligible_video_labels") and claim.get("status") in {
            "supported",
            "conditional",
        }:
            eligible = set(claim["eligible_video_labels"])
            if not any(labels_in(unit, label_pattern) & eligible for unit in covered_units):
                add_violation(
                    violations,
                    "missing_claim_citation",
                    "A supported claim is not accompanied by one of its mapped citations.",
                    claim_id=claim.get("claim_id"),
                    details={"eligible_labels": sorted(eligible)},
                )

    diagnostic = context.get("diagnostic_model", {})
    if diagnostic.get("do_not_claim_unique_cause"):
        boundary_pattern = compile_any(rules["unique_cause_boundary_patterns"])
        if not boundary_pattern.search(auditable_answer):
            add_violation(
                violations,
                "missing_unique_cause_boundary",
                "The answer does not state that the user's unique cause cannot be confirmed from the available observation.",
            )

    clarification = context.get("clarification_decision", {})
    if isinstance(turn_contract, dict) and not turn_contract_errors:
        for resolved in turn_contract.get("resolved_clarifications", []):
            if (
                text_match_score(
                    resolved.get("answer", ""), auditable_answer, rules
                )
                < rules["resolved_clarification_match_threshold"]
            ):
                add_violation(
                    violations,
                    "missing_resolved_clarification",
                    "A resolved clarification is not acknowledged in the answer.",
                    details={"question_id": resolved.get("question_id")},
                )
            if (
                text_match_score(
                    resolved.get("question", ""), auditable_answer, rules
                )
                >= rules["reasked_question_match_threshold"]
            ):
                add_violation(
                    violations,
                    "resolved_clarification_reasked",
                    "The answer repeats a clarification question that the user already resolved.",
                    details={"question_id": resolved.get("question_id")},
                )
        for request in turn_contract.get("pending_clarifications", []):
            if (
                text_match_score(
                    request.get("question", ""), auditable_answer, rules
                )
                < rules["required_clarification_match_threshold"]
            ):
                add_violation(
                    violations,
                    "missing_required_clarification",
                    "The answer omits a required focused clarification.",
                    details={"question_id": request.get("question_id")},
                )
    elif clarification.get("action") in {
        "ask_first",
        "answer_conditionally",
    } and clarification.get("questions"):
        question_match = any(
            text_match_score(question_text, auditable_answer, rules)
            >= rules["claim_match_threshold"]
            for question_text in clarification["questions"]
        )
        has_clarification_marker = any(
            marker in auditable_answer for marker in rules["clarification_markers"]
        )
        if not has_clarification_marker and not question_match:
            add_violation(
                violations,
                "missing_required_clarification",
                "The answer omits the focused clarification required by the context.",
            )

    boundary = context.get("boundary", {})
    required_statement = boundary.get("required_statement")
    if (
        required_statement
        and text_match_score(required_statement, auditable_answer, rules)
        < rules["boundary_match_threshold"]
    ):
        add_violation(
            violations,
            "missing_required_boundary",
            "The answer omits the required safety or scope boundary.",
            details={"boundary_type": boundary.get("type")},
        )

    for label in sorted(all_labels & set(selected_by_label)):
        metadata = selected_by_label[label]
        evidence_id = metadata["evidence_id"]
        canonical_url = metadata["canonical_url"]
        answer_without_urls = re.sub(r"https?://\S+", "", auditable_answer)
        if evidence_id and evidence_id not in answer_without_urls:
            add_violation(
                violations,
                "missing_citation_evidence_id",
                f"{label} is cited without its stable evidence ID.",
                details={"label": label, "evidence_id": evidence_id},
            )
        if canonical_url and canonical_url not in auditable_answer:
            add_violation(
                violations,
                "missing_citation_url",
                f"{label} is cited without its canonical URL.",
                details={"label": label, "canonical_url": canonical_url},
            )
        if canonical_url and auditable_answer.count(canonical_url) > 1:
            add_violation(
                violations,
                "duplicate_citation_url",
                f"{label}'s canonical URL appears more than once.",
                details={
                    "label": label,
                    "occurrences": auditable_answer.count(canonical_url),
                },
            )

    violations.sort(
        key=lambda item: (
            item["code"],
            item.get("claim_id", ""),
            item.get("answer_excerpt", ""),
        )
    )
    return {
        "schema_version": 1,
        "question": question,
        "passed": not violations,
        "summary": {
            "errors": len(violations),
            "completeness_items": len(coverage),
            "completeness_items_covered": sum(item["covered"] for item in coverage),
            "cited_labels": sorted(all_labels),
        },
        "coverage": coverage,
        "violations": violations,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", help="The exact original user question")
    parser.add_argument("--context", type=Path, required=True, help="JSON output from prepare_answer_context.py")
    answer_input = parser.add_mutually_exclusive_group(required=True)
    answer_input.add_argument("--answer", type=Path, help="UTF-8 final-answer text file")
    answer_input.add_argument("--answer-text", help="Final answer supplied directly")
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES_PATH)
    args = parser.parse_args()

    context = load_json(args.context)
    answer = args.answer.read_text(encoding="utf-8") if args.answer else args.answer_text
    result = audit_answer(args.question, context, answer, load_rules(args.rules))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
