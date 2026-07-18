#!/usr/bin/env python3
import argparse
import json
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES_PATH = ROOT / "data" / "evaluation" / "answer_quality_cases.json"
DEFAULT_RULES_PATH = ROOT / "config" / "answer_quality_rules.json"
KNOWLEDGE_PATH = ROOT / "data" / "knowledge" / "douyin_knowledge_base.json"
VIDEO_URL_PATTERN = re.compile(r"https://www\.douyin\.com/video/(\d+)")
CASE_ID_PATTERN = re.compile(r"AQ\d{3}")
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")


class RegistryValidationError(ValueError):
    pass


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def ready_video_ids(knowledge):
    return {
        video["video_id"]
        for video in knowledge["videos"]
        if video["processing_status"] == "ready"
    }


def case_is_regression_ready(case):
    review = case["review"]
    return (
        review["status"] == "maintainer_reviewed"
        and review.get("maintainer_decision") == "approved"
    )


def validate_point(point, case_id, ready_ids, boundary=False):
    required = {"point_id", "description", "acceptable_terms"}
    if not boundary:
        required.add("evidence_video_ids")
    if set(point) != required:
        raise RegistryValidationError(
            f"{case_id} has an invalid {'boundary' if boundary else 'text'} point schema"
        )
    if not point["point_id"] or not point["description"]:
        raise RegistryValidationError(f"{case_id} contains an empty point")
    if not point["acceptable_terms"] or not all(
        isinstance(term, str) and term.strip() for term in point["acceptable_terms"]
    ):
        raise RegistryValidationError(
            f"{case_id} point {point['point_id']} needs acceptable terms"
        )
    if not boundary and not set(point["evidence_video_ids"]).issubset(ready_ids):
        raise RegistryValidationError(
            f"{case_id} point {point['point_id']} references non-ready evidence"
        )


def validate_registry(
    registry, rules, ready_ids, minimum_cases=0, all_video_ids=None
):
    all_video_ids = set(all_video_ids or ready_ids)
    if registry.get("version") != 1:
        raise RegistryValidationError("Answer quality case schema version is unsupported")
    if rules.get("version") != 1:
        raise RegistryValidationError("Answer quality rule schema version is unsupported")
    cases = registry.get("cases", [])
    if len(cases) < minimum_cases:
        raise RegistryValidationError(
            f"Answer quality registry has {len(cases)} cases; expected at least {minimum_cases}"
        )

    allowed_types = set(rules["case_types"])
    allowed_modes = set(rules["answer_modes"])
    allowed_statuses = set(rules["review_statuses"])
    expected_case_fields = {
        "case_id",
        "query",
        "case_type",
        "expected_mode",
        "provenance",
        "review",
        "gold",
    }
    expected_gold_fields = {
        "primary_video_ids",
        "required_video_ids",
        "irrelevant_video_ids",
        "required_text_points",
        "required_boundary_points",
        "forbidden_claims",
    }
    case_ids = []
    queries = []

    for case in cases:
        if set(case) != expected_case_fields:
            raise RegistryValidationError("Answer quality case contains unexpected fields")
        case_id = case["case_id"]
        case_ids.append(case_id)
        queries.append(case["query"])
        if not CASE_ID_PATTERN.fullmatch(case_id):
            raise RegistryValidationError(f"Invalid answer quality case ID: {case_id}")
        if not isinstance(case["query"], str) or not case["query"].strip():
            raise RegistryValidationError(f"{case_id} has an empty query")
        if case["case_type"] not in allowed_types:
            raise RegistryValidationError(f"{case_id} has an invalid case type")
        if case["expected_mode"] not in allowed_modes:
            raise RegistryValidationError(f"{case_id} has an invalid answer mode")
        if not isinstance(case["provenance"], str) or not case["provenance"]:
            raise RegistryValidationError(f"{case_id} is missing provenance")

        review = case["review"]
        if not isinstance(review, dict) or review.get("status") not in allowed_statuses:
            raise RegistryValidationError(f"{case_id} has an invalid review status")
        gold = case["gold"]
        if set(gold) != expected_gold_fields:
            raise RegistryValidationError(f"{case_id} has an invalid gold schema")
        if not all(isinstance(gold[field], list) for field in expected_gold_fields):
            raise RegistryValidationError(f"{case_id} gold fields must all be lists")

        primary_ids = set(gold["primary_video_ids"])
        required_ids = set(gold["required_video_ids"])
        irrelevant_ids = set(gold["irrelevant_video_ids"])
        if not primary_ids.issubset(required_ids):
            raise RegistryValidationError(
                f"{case_id} primary videos must also be required videos"
            )
        if required_ids & irrelevant_ids:
            raise RegistryValidationError(
                f"{case_id} marks the same video required and irrelevant"
            )
        if not (primary_ids | required_ids).issubset(ready_ids):
            raise RegistryValidationError(f"{case_id} references non-ready evidence")
        if not irrelevant_ids.issubset(all_video_ids):
            raise RegistryValidationError(f"{case_id} references an unknown hard negative")

        point_ids = []
        for point in gold["required_text_points"]:
            validate_point(point, case_id, ready_ids)
            point_ids.append(point["point_id"])
        for point in gold["required_boundary_points"]:
            validate_point(point, case_id, ready_ids, boundary=True)
            point_ids.append(point["point_id"])
        if len(point_ids) != len(set(point_ids)):
            raise RegistryValidationError(f"{case_id} has duplicate point IDs")
        if not all(
            isinstance(claim, str) and claim.strip()
            for claim in gold["forbidden_claims"]
        ):
            raise RegistryValidationError(f"{case_id} has an empty forbidden claim")

        if review["status"] != "draft":
            if not review.get("maintainer_reviewer"):
                raise RegistryValidationError(
                    f"{case_id} reviewed case is missing a maintainer reviewer"
                )
            if not DATE_PATTERN.fullmatch(review.get("reviewed_at", "")):
                raise RegistryValidationError(
                    f"{case_id} reviewed case needs a YYYY-MM-DD review date"
                )
            if not (
                gold["required_text_points"] or gold["required_boundary_points"]
            ):
                raise RegistryValidationError(
                    f"{case_id} reviewed case has no approved text or boundary points"
                )
            if case["case_type"] != "evidence_boundary" and not required_ids:
                raise RegistryValidationError(
                    f"{case_id} reviewed coaching case has no required video evidence"
                )
        if any(key.startswith("expert_") for key in review):
            raise RegistryValidationError(
                f"{case_id} still contains retired expert-review fields"
            )

    if len(case_ids) != len(set(case_ids)):
        raise RegistryValidationError("Answer quality case IDs must be unique")
    if len(queries) != len(set(queries)):
        raise RegistryValidationError("Answer quality queries must be unique")

    status_counts = Counter(case["review"]["status"] for case in cases)
    regression_ready = [case for case in cases if case_is_regression_ready(case)]
    return {
        "cases": len(cases),
        "status_counts": dict(status_counts),
        "regression_ready": len(regression_ready),
        "pending_review": len(cases) - len(regression_ready),
    }


def normalized_text_length(text):
    without_urls = VIDEO_URL_PATTERN.sub("", text)
    return len(re.sub(r"\s+", "", without_urls))


def point_is_covered(point, answer_text):
    normalized = answer_text.casefold()
    return any(term.casefold() in normalized for term in point["acceptable_terms"])


def evaluate_case_answer(case, answer, rules, ready_ids, require_manual_review=False):
    failures = []
    answer_text = answer.get("answer_text", "")
    if not isinstance(answer_text, str) or not answer_text.strip():
        failures.append("answer_text_missing")
        answer_text = ""
    if answer.get("answer_mode") != case["expected_mode"]:
        failures.append("answer_mode_mismatch")

    minimum_text = rules["mode_requirements"][case["expected_mode"]][
        "min_text_characters"
    ]
    text_length = normalized_text_length(answer_text)
    if text_length < minimum_text:
        failures.append("text_too_short")

    linked_video_ids = VIDEO_URL_PATTERN.findall(answer_text)
    link_counts = Counter(linked_video_ids)
    duplicate_video_ids = sorted(
        video_id for video_id, count in link_counts.items() if count > 1
    )
    if duplicate_video_ids:
        failures.append("duplicate_video_links")
    linked_set = set(linked_video_ids)
    unknown_video_ids = sorted(linked_set - ready_ids)
    if unknown_video_ids:
        failures.append("unknown_or_excluded_video")

    gold = case["gold"]
    missing_required_videos = sorted(set(gold["required_video_ids"]) - linked_set)
    cited_irrelevant_videos = sorted(set(gold["irrelevant_video_ids"]) & linked_set)
    if missing_required_videos:
        failures.append("required_video_missing")
    if cited_irrelevant_videos:
        failures.append("irrelevant_video_cited")

    missing_text_points = [
        point["point_id"]
        for point in gold["required_text_points"]
        if not point_is_covered(point, answer_text)
    ]
    missing_boundary_points = [
        point["point_id"]
        for point in gold["required_boundary_points"]
        if not point_is_covered(point, answer_text)
    ]
    if missing_text_points:
        failures.append("required_text_point_missing")
    if missing_boundary_points:
        failures.append("required_boundary_missing")

    forbidden_claims_found = [
        claim
        for claim in gold["forbidden_claims"]
        if claim.casefold() in answer_text.casefold()
    ]
    if forbidden_claims_found:
        failures.append("forbidden_claim_present")

    video_notes = answer.get("video_notes", [])
    if not isinstance(video_notes, list):
        video_notes = []
        failures.append("video_notes_invalid")
    note_ids = [note.get("video_id") for note in video_notes if isinstance(note, dict)]
    if len(note_ids) != len(set(note_ids)):
        failures.append("duplicate_video_notes")
    notes_by_id = {
        note.get("video_id"): note
        for note in video_notes
        if isinstance(note, dict) and note.get("video_id")
    }
    note_rules = rules["video_note_requirements"]
    missing_video_notes = []
    incomplete_video_notes = []
    for video_id in gold["required_video_ids"]:
        note = notes_by_id.get(video_id)
        if note is None:
            missing_video_notes.append(video_id)
            continue
        if (
            normalized_text_length(str(note.get("reason", "")))
            < note_rules["min_reason_characters"]
            or normalized_text_length(str(note.get("watch_focus", "")))
            < note_rules["min_watch_focus_characters"]
        ):
            incomplete_video_notes.append(video_id)
    if missing_video_notes:
        failures.append("required_video_note_missing")
    if incomplete_video_notes:
        failures.append("required_video_note_incomplete")

    manual_review = answer.get("manual_review")
    manual_scores = {}
    manual_pass = None
    if manual_review is not None:
        if not isinstance(manual_review, dict):
            failures.append("manual_review_invalid")
        else:
            manual_scores = manual_review.get("scores", {})
            scale = rules["manual_score_scale"]
            missing_dimensions = [
                dimension
                for dimension in rules["manual_dimensions"]
                if dimension not in manual_scores
            ]
            invalid_scores = [
                dimension
                for dimension, score in manual_scores.items()
                if dimension in rules["manual_dimensions"]
                and (
                    not isinstance(score, int)
                    or score < scale["minimum"]
                    or score > scale["maximum"]
                )
            ]
            manual_pass = not missing_dimensions and not invalid_scores and all(
                manual_scores[dimension] >= scale["passing"]
                for dimension in rules["manual_dimensions"]
            )
            if require_manual_review and not manual_review.get("reviewer"):
                failures.append("manual_reviewer_missing")
            if require_manual_review and not manual_pass:
                failures.append("manual_quality_below_threshold")
    elif require_manual_review:
        failures.append("manual_review_missing")

    return {
        "case_id": case["case_id"],
        "query": case["query"],
        "automatic_pass": not failures,
        "failures": failures,
        "text_characters": text_length,
        "linked_video_ids": linked_video_ids,
        "duplicate_video_ids": duplicate_video_ids,
        "unknown_video_ids": unknown_video_ids,
        "missing_required_video_ids": missing_required_videos,
        "cited_irrelevant_video_ids": cited_irrelevant_videos,
        "missing_text_point_ids": missing_text_points,
        "missing_boundary_point_ids": missing_boundary_points,
        "forbidden_claims_found": forbidden_claims_found,
        "missing_video_note_ids": missing_video_notes,
        "incomplete_video_note_ids": incomplete_video_notes,
        "manual_pass": manual_pass,
        "manual_scores": manual_scores,
    }


def evaluate_answers(registry, answers_payload, rules, ready_ids, require_manual_review=False):
    ready_cases = {
        case["case_id"]: case
        for case in registry["cases"]
        if case_is_regression_ready(case)
    }
    answers = answers_payload.get("answers", [])
    answer_ids = [answer.get("case_id") for answer in answers]
    if len(answer_ids) != len(set(answer_ids)):
        raise RegistryValidationError("Answer snapshot contains duplicate case IDs")
    unknown_case_ids = sorted(set(answer_ids) - set(ready_cases))
    if unknown_case_ids:
        raise RegistryValidationError(
            "Answer snapshot includes draft or unknown cases: " + ", ".join(unknown_case_ids)
        )
    answers_by_id = {answer["case_id"]: answer for answer in answers}
    missing_case_ids = sorted(set(ready_cases) - set(answers_by_id))
    results = [
        evaluate_case_answer(
            ready_cases[case_id],
            answers_by_id[case_id],
            rules,
            ready_ids,
            require_manual_review=require_manual_review,
        )
        for case_id in sorted(set(ready_cases) & set(answers_by_id))
    ]
    passed = sum(result["automatic_pass"] for result in results)
    denominator = len(results)
    return {
        "status": "no_approved_cases" if not ready_cases else "evaluated",
        "approved_cases": len(ready_cases),
        "answers_supplied": len(answers),
        "snapshot_coverage": len(answers) / len(ready_cases) if ready_cases else 1.0,
        "missing_case_ids": missing_case_ids,
        "passed": passed,
        "automatic_pass_rate": passed / denominator if denominator else 1.0,
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Validate the answer-quality gold registry and evaluate answer snapshots."
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES_PATH)
    parser.add_argument("--answers", type=Path)
    parser.add_argument("--require-cases", type=int, default=30)
    parser.add_argument("--min-approved", type=int, default=0)
    parser.add_argument("--min-answer-snapshots", type=int, default=0)
    parser.add_argument("--min-automatic-pass-rate", type=float, default=1.0)
    parser.add_argument("--require-complete-answer-coverage", action="store_true")
    parser.add_argument("--require-manual-review", action="store_true")
    args = parser.parse_args()

    registry = load_json(args.cases)
    rules = load_json(args.rules)
    knowledge = load_json(KNOWLEDGE_PATH)
    ready_ids = ready_video_ids(knowledge)
    all_video_ids = {video["video_id"] for video in knowledge["videos"]}
    registry_result = validate_registry(
        registry,
        rules,
        ready_ids,
        minimum_cases=args.require_cases,
        all_video_ids=all_video_ids,
    )
    result = {"registry": registry_result}
    if registry_result["regression_ready"] < args.min_approved:
        raise SystemExit(
            f"Only {registry_result['regression_ready']} answer quality cases are ready; "
            f"expected at least {args.min_approved}"
        )

    if args.answers:
        answers_result = evaluate_answers(
            registry,
            load_json(args.answers),
            rules,
            ready_ids,
            require_manual_review=args.require_manual_review,
        )
        result["answers"] = answers_result
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if answers_result["answers_supplied"] < args.min_answer_snapshots:
            raise SystemExit(
                f"Only {answers_result['answers_supplied']} answer snapshots; "
                f"requires {args.min_answer_snapshots}"
            )
        if args.require_complete_answer_coverage and answers_result["missing_case_ids"]:
            raise SystemExit("Answer snapshot is missing approved cases")
        if answers_result["automatic_pass_rate"] < args.min_automatic_pass_rate:
            raise SystemExit("Answer quality automatic pass rate is below threshold")
        return

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
