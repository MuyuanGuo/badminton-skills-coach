#!/usr/bin/env python3
import argparse
import importlib.util
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "data" / "evaluation" / "answer_quality_cases.json"
SEARCH_PATH = (
    ROOT
    / "skills"
    / "liuhui-badminton-coach"
    / "scripts"
    / "search_knowledge.py"
)


def load_search_module():
    spec = importlib.util.spec_from_file_location("liuhui_search_knowledge", SEARCH_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def exhaustive_candidate_ids(search_module, case, primary_payload, top_k):
    candidate_ids = {
        item["video_id"] for item in primary_payload["candidate_manifest"]
    }
    plan = search_module.plan_query(case["query"])
    if plan["retrieval_guidance"].get("strategy") != "split_multi_issue":
        return candidate_ids
    queries = list(plan["retrieval_guidance"].get("query_units") or [])
    for unit in list(queries):
        unit_plan = search_module.plan_query(unit)
        for group in unit_plan["query_expansion"]["matched_synonym_groups"]:
            present = [term for term in group if term in unit]
            if present:
                queries.append(max(present, key=len))
    for query in dict.fromkeys(queries):
        payload = search_module.search(
            query,
            limit=top_k,
            mode="hybrid",
            recall_mode="exhaustive",
            manifest_limit=None,
            local_personalization=False,
        )
        candidate_ids.update(
            item["video_id"] for item in payload["candidate_manifest"]
        )
    return candidate_ids


def evaluate(top_k, cases_path=CASES_PATH):
    cases = json.loads(cases_path.read_text(encoding="utf-8"))["cases"]
    search_module = load_search_module()
    expected_total = 0
    found_total = 0
    primary_top_k = 0
    reciprocal_rank_total = 0.0
    ndcg_total = 0.0
    known_precision_total = 0.0
    review_candidate_total = 0
    primary_case_count = 0
    expected_case_count = 0
    hard_negative_total = 0
    hard_negative_top_k_violations = 0
    hard_negative_review_violations = 0
    case_results = []
    for case in cases:
        payload = search_module.search(
            case["query"],
            limit=top_k,
            mode="hybrid",
            recall_mode="exhaustive",
            local_personalization=False,
        )
        manifest_ids = [item["video_id"] for item in payload["candidate_manifest"]]
        recall_candidate_ids = exhaustive_candidate_ids(
            search_module, case, payload, top_k
        )
        top_ids = [item["video_id"] for item in payload["results"]]
        gold = case["gold"]
        expected = gold["required_video_ids"]
        primary = gold["primary_video_ids"]
        irrelevant = set(gold["irrelevant_video_ids"])
        found = [video_id for video_id in expected if video_id in recall_candidate_ids]
        missing = [video_id for video_id in expected if video_id not in recall_candidate_ids]
        primary_ranks = [
            manifest_ids.index(video_id) + 1
            for video_id in primary
            if video_id in manifest_ids
        ]
        primary_rank = min(primary_ranks) if primary_ranks else None
        expected_total += len(expected)
        found_total += len(found)
        if expected:
            expected_case_count += 1
        if primary:
            primary_case_count += 1
            if set(primary) & set(top_ids):
                primary_top_k += 1
            reciprocal_rank_total += 1 / primary_rank if primary_rank else 0.0
        top_relevance = [
            2 if video_id in primary else 1 if video_id in expected else 0
            for video_id in top_ids
        ]
        dcg = sum(
            relevance / math.log2(rank + 1)
            for rank, relevance in enumerate(top_relevance, start=1)
        )
        ideal_relevance = sorted(
            [2] * len(primary) + [1] * len(set(expected) - set(primary)),
            reverse=True,
        )[:top_k]
        ideal_dcg = sum(
            relevance / math.log2(rank + 1)
            for rank, relevance in enumerate(ideal_relevance, start=1)
        )
        ndcg_total += dcg / ideal_dcg if ideal_dcg else 1.0
        known_precision_total += sum(
            video_id in set(expected) for video_id in top_ids
        ) / max(1, len(top_ids))
        review_candidate_count = payload["coverage"]["review_candidate_count"]
        review_candidate_total += review_candidate_count
        review_ids = {
            item["video_id"]
            for item in payload["candidate_manifest"]
            if item.get("within_review_budget")
        }
        negative_top = irrelevant & set(top_ids)
        negative_review = irrelevant & review_ids
        hard_negative_total += len(irrelevant)
        hard_negative_top_k_violations += len(negative_top)
        hard_negative_review_violations += len(negative_review)
        case_results.append(
            {
                "case_id": case["case_id"],
                "query": case["query"],
                "expected": len(expected),
                "found": len(found),
                "missing_video_ids": missing,
                "candidate_count": payload["coverage"]["candidate_count"],
                "primary_rank": primary_rank,
                "review_candidate_count": review_candidate_count,
                "irrelevant_top_k_video_ids": sorted(negative_top),
                "irrelevant_review_video_ids": sorted(negative_review),
            }
        )
    return {
        "cases": len(cases),
        "expected_videos": expected_total,
        "found_videos": found_total,
        "cases_with_expected_videos": expected_case_count,
        "cases_with_primary_videos": primary_case_count,
        "candidate_recall": found_total / max(1, expected_total),
        "primary_top_k": primary_top_k / max(1, primary_case_count),
        "mean_reciprocal_rank": reciprocal_rank_total / max(1, primary_case_count),
        "mean_ndcg_at_k": ndcg_total / len(cases),
        "mean_known_precision_at_k": known_precision_total / len(cases),
        "average_review_candidate_count": review_candidate_total / len(cases),
        "hard_negative_count": hard_negative_total,
        "hard_negative_top_k_violations": hard_negative_top_k_violations,
        "hard_negative_review_violations": hard_negative_review_violations,
        "top_k": top_k,
        "case_results": case_results,
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate high-recall Skill retrieval.")
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--top-k", type=int, default=12)
    parser.add_argument("--min-recall", type=float, default=1.0)
    parser.add_argument("--min-primary-top-k", type=float, default=0.85)
    parser.add_argument("--min-mrr", type=float, default=0.55)
    parser.add_argument("--min-ndcg-at-k", type=float, default=0.70)
    parser.add_argument("--max-average-review-candidates", type=float, default=40)
    parser.add_argument(
        "--max-hard-negative-top-k-violations", type=int, default=0
    )
    args = parser.parse_args()
    result = evaluate(args.top_k, args.cases)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["candidate_recall"] < args.min_recall:
        raise SystemExit(
            f"Candidate recall {result['candidate_recall']:.3f} is below {args.min_recall:.3f}"
        )
    if result["primary_top_k"] < args.min_primary_top_k:
        raise SystemExit(
            f"Primary top-{args.top_k} rate {result['primary_top_k']:.3f} "
            f"is below {args.min_primary_top_k:.3f}"
        )
    if result["mean_reciprocal_rank"] < args.min_mrr:
        raise SystemExit(
            f"MRR {result['mean_reciprocal_rank']:.3f} is below {args.min_mrr:.3f}"
        )
    if result["mean_ndcg_at_k"] < args.min_ndcg_at_k:
        raise SystemExit(
            f"nDCG@{args.top_k} {result['mean_ndcg_at_k']:.3f} is below "
            f"{args.min_ndcg_at_k:.3f}"
        )
    if result["average_review_candidate_count"] > args.max_average_review_candidates:
        raise SystemExit(
            "Average review candidate count "
            f"{result['average_review_candidate_count']:.1f} exceeds "
            f"{args.max_average_review_candidates:.1f}"
        )
    if (
        args.max_hard_negative_top_k_violations is not None
        and result["hard_negative_top_k_violations"]
        > args.max_hard_negative_top_k_violations
    ):
        raise SystemExit(
            "Known irrelevant videos appeared in top-k: "
            f"{result['hard_negative_top_k_violations']} violations"
        )


if __name__ == "__main__":
    main()
