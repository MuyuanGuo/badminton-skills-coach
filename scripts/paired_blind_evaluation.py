#!/usr/bin/env python3
"""Create and score blinded main/develop answer comparisons."""

import argparse
import hashlib
import json
import random
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOLDOUT_PATH = ROOT / "data" / "evaluation" / "paired_blind_holdout.json"
RUBRIC = [
    "real_question_understanding",
    "factual_correctness",
    "source_entailment",
    "important_omissions",
    "unsupported_claims",
    "clarity",
]


class BlindEvaluationError(ValueError):
    pass


def canonical_digest(payload):
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_holdout(holdout):
    if holdout.get("schema_version") != 1:
        raise BlindEvaluationError("unsupported holdout schema_version")
    if not holdout.get("development_use_forbidden"):
        raise BlindEvaluationError("holdout must forbid use for rule development")
    cases = holdout.get("cases", [])
    case_ids = [case.get("case_id") for case in cases]
    queries = [case.get("query", "").strip() for case in cases]
    if not cases or any(not item for item in case_ids + queries):
        raise BlindEvaluationError("holdout cases must have IDs and queries")
    if len(case_ids) != len(set(case_ids)) or len(queries) != len(set(queries)):
        raise BlindEvaluationError("holdout cases and queries must be unique")
    return {case["case_id"]: case for case in cases}


def validate_answer_run(run, holdout, expected_role):
    if run.get("schema_version") != 1:
        raise BlindEvaluationError(f"{expected_role} answer run schema is unsupported")
    if run.get("branch_role") != expected_role:
        raise BlindEvaluationError(f"expected branch_role {expected_role}")
    if run.get("holdout_digest") != canonical_digest(holdout):
        raise BlindEvaluationError(f"{expected_role} answer run uses another holdout")
    required_metadata = ("commit_sha", "model", "generated_at")
    if any(not str(run.get(key, "")).strip() for key in required_metadata):
        raise BlindEvaluationError(f"{expected_role} generation metadata is incomplete")
    if not isinstance(run.get("generation_settings"), dict):
        raise BlindEvaluationError(f"{expected_role} settings must be an object")
    cases = validate_holdout(holdout)
    answers = run.get("answers", [])
    by_id = {item.get("case_id"): item for item in answers}
    if set(by_id) != set(cases) or len(answers) != len(by_id):
        raise BlindEvaluationError(
            f"{expected_role} answers must cover every holdout case exactly once"
        )
    if any(not item.get("answer", "").strip() for item in answers):
        raise BlindEvaluationError(f"{expected_role} contains an empty answer")
    return by_id


def build_blinded_pairs(holdout, main_run, develop_run, seed):
    cases = validate_holdout(holdout)
    main_answers = validate_answer_run(main_run, holdout, "main")
    develop_answers = validate_answer_run(develop_run, holdout, "develop")
    comparable_metadata = ("model", "generation_settings")
    for key in comparable_metadata:
        if main_run[key] != develop_run[key]:
            raise BlindEvaluationError(f"branch answer runs differ in {key}")
    rng = random.Random(seed)
    pairs = []
    mappings = []
    for case_id in sorted(cases):
        main_is_a = bool(rng.getrandbits(1))
        answers = {
            "A": main_answers[case_id]["answer"] if main_is_a else develop_answers[case_id]["answer"],
            "B": develop_answers[case_id]["answer"] if main_is_a else main_answers[case_id]["answer"],
        }
        pair_id = "PAIR-" + hashlib.sha256(
            f"{holdout['holdout_id']}:{case_id}".encode("utf-8")
        ).hexdigest()[:12].upper()
        pairs.append(
            {
                "pair_id": pair_id,
                "case_id": case_id,
                "query": cases[case_id]["query"],
                "answers": answers,
            }
        )
        mappings.append(
            {
                "pair_id": pair_id,
                "A": "main" if main_is_a else "develop",
                "B": "develop" if main_is_a else "main",
            }
        )
    created_at = datetime.now(timezone.utc).isoformat()
    blinded = {
        "schema_version": 1,
        "evaluation_id": holdout["holdout_id"],
        "holdout_digest": canonical_digest(holdout),
        "created_at": created_at,
        "rubric": RUBRIC,
        "score_scale": {"minimum": 1, "maximum": 5, "higher_is_better": True},
        "pairs": pairs,
    }
    key = {
        "schema_version": 1,
        "evaluation_id": holdout["holdout_id"],
        "blinded_pairs_digest": canonical_digest(blinded),
        "main_commit_sha": main_run["commit_sha"],
        "develop_commit_sha": develop_run["commit_sha"],
        "model": main_run["model"],
        "generation_settings": main_run["generation_settings"],
        "mappings": mappings,
    }
    return blinded, key


def review_template(blinded):
    return {
        "schema_version": 1,
        "evaluation_id": blinded["evaluation_id"],
        "blinded_pairs_digest": canonical_digest(blinded),
        "reviewer": {
            "reviewer_id": "",
            "reviewer_type": "human",
            "independent_of_implementation": True,
            "branch_identity_known_during_review": False,
            "reviewed_at": "",
        },
        "reviews": [
            {
                "pair_id": pair["pair_id"],
                "preference": None,
                "scores": {
                    label: {dimension: None for dimension in RUBRIC}
                    for label in ("A", "B")
                },
                "unsupported_claims": {"A": [], "B": []},
                "important_omissions": {"A": [], "B": []},
                "notes": "",
            }
            for pair in blinded["pairs"]
        ],
    }


def score_reviews(blinded, key, reviews):
    if key.get("blinded_pairs_digest") != canonical_digest(blinded):
        raise BlindEvaluationError("branch key does not match blinded pairs")
    if reviews.get("blinded_pairs_digest") != canonical_digest(blinded):
        raise BlindEvaluationError("reviews do not match blinded pairs")
    reviewer = reviews.get("reviewer", {})
    if (
        reviewer.get("reviewer_type") != "human"
        or not reviewer.get("independent_of_implementation")
        or reviewer.get("branch_identity_known_during_review") is not False
        or not reviewer.get("reviewer_id", "").strip()
        or not reviewer.get("reviewed_at", "").strip()
    ):
        raise BlindEvaluationError("independent blinded human review metadata is required")
    mappings = {item["pair_id"]: item for item in key.get("mappings", [])}
    pair_ids = {item["pair_id"] for item in blinded["pairs"]}
    review_items = reviews.get("reviews", [])
    review_by_id = {item.get("pair_id"): item for item in review_items}
    if set(review_by_id) != pair_ids or len(review_by_id) != len(review_items):
        raise BlindEvaluationError("reviews must cover every pair exactly once")
    wins = {"main": 0, "develop": 0, "tie": 0}
    score_totals = {"main": 0, "develop": 0}
    score_counts = {"main": 0, "develop": 0}
    for pair_id, review in review_by_id.items():
        preference = review.get("preference")
        if preference not in {"A", "B", "tie"}:
            raise BlindEvaluationError(f"{pair_id} has an invalid preference")
        winner = "tie" if preference == "tie" else mappings[pair_id][preference]
        wins[winner] += 1
        if not review.get("notes", "").strip():
            raise BlindEvaluationError(f"{pair_id} is missing review notes")
        for label in ("A", "B"):
            scores = review.get("scores", {}).get(label, {})
            if set(scores) != set(RUBRIC) or any(
                not isinstance(value, int) or not 1 <= value <= 5
                for value in scores.values()
            ):
                raise BlindEvaluationError(f"{pair_id} has invalid {label} scores")
            branch = mappings[pair_id][label]
            score_totals[branch] += sum(scores.values())
            score_counts[branch] += len(scores)
    return {
        "schema_version": 1,
        "evaluation_id": blinded["evaluation_id"],
        "reviewer_id": reviewer["reviewer_id"],
        "pair_count": len(pair_ids),
        "wins": wins,
        "mean_rubric_score": {
            branch: round(score_totals[branch] / score_counts[branch], 4)
            for branch in ("main", "develop")
        },
        "main_commit_sha": key["main_commit_sha"],
        "develop_commit_sha": key["develop_commit_sha"],
        "model": key["model"],
        "generation_settings": key["generation_settings"],
    }


def write_json(path, payload):
    Path(path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--holdout", type=Path, default=HOLDOUT_PATH)
    prepare.add_argument("--main-answers", type=Path, required=True)
    prepare.add_argument("--develop-answers", type=Path, required=True)
    prepare.add_argument("--seed", required=True)
    prepare.add_argument("--pairs", type=Path, required=True)
    prepare.add_argument("--key", type=Path, required=True)
    prepare.add_argument("--review-template", type=Path, required=True)
    score = subparsers.add_parser("score")
    score.add_argument("--pairs", type=Path, required=True)
    score.add_argument("--key", type=Path, required=True)
    score.add_argument("--reviews", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        holdout = load_json(args.holdout)
        blinded, key = build_blinded_pairs(
            holdout,
            load_json(args.main_answers),
            load_json(args.develop_answers),
            args.seed,
        )
        write_json(args.pairs, blinded)
        write_json(args.key, key)
        write_json(args.review_template, review_template(blinded))
        return
    result = score_reviews(
        load_json(args.pairs), load_json(args.key), load_json(args.reviews)
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
