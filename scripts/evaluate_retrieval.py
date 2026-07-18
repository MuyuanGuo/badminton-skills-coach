#!/usr/bin/env python3
import argparse
import importlib.util
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "data" / "evaluation" / "retrieval_cases.json"
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


def evaluate(top_k):
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]
    search_module = load_search_module()
    expected_total = 0
    found_total = 0
    primary_top_k = 0
    reciprocal_rank_total = 0.0
    ndcg_total = 0.0
    known_precision_total = 0.0
    review_candidate_total = 0
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
        top_ids = [item["video_id"] for item in payload["results"]]
        expected = case["expected_video_ids"]
        found = [video_id for video_id in expected if video_id in manifest_ids]
        missing = [video_id for video_id in expected if video_id not in manifest_ids]
        primary_rank = (
            manifest_ids.index(case["primary_video_id"]) + 1
            if case["primary_video_id"] in manifest_ids
            else None
        )
        expected_total += len(expected)
        found_total += len(found)
        if case["primary_video_id"] in top_ids:
            primary_top_k += 1
        reciprocal_rank_total += 1 / primary_rank if primary_rank else 0.0
        top_relevance = [1 if video_id in expected else 0 for video_id in top_ids]
        dcg = sum(
            relevance / math.log2(rank + 1)
            for rank, relevance in enumerate(top_relevance, start=1)
        )
        ideal_hits = min(len(expected), top_k)
        ideal_dcg = sum(1 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
        ndcg_total += dcg / ideal_dcg if ideal_dcg else 1.0
        known_precision_total += sum(top_relevance) / max(1, len(top_ids))
        review_candidate_count = payload["coverage"]["review_candidate_count"]
        review_candidate_total += review_candidate_count
        case_results.append(
            {
                "query": case["query"],
                "expected": len(expected),
                "found": len(found),
                "missing_video_ids": missing,
                "candidate_count": payload["coverage"]["candidate_count"],
                "primary_rank": primary_rank,
                "review_candidate_count": review_candidate_count,
            }
        )
    return {
        "cases": len(cases),
        "expected_videos": expected_total,
        "found_videos": found_total,
        "candidate_recall": found_total / expected_total,
        "primary_top_k": primary_top_k / len(cases),
        "mean_reciprocal_rank": reciprocal_rank_total / len(cases),
        "mean_ndcg_at_k": ndcg_total / len(cases),
        "mean_known_precision_at_k": known_precision_total / len(cases),
        "average_review_candidate_count": review_candidate_total / len(cases),
        "top_k": top_k,
        "case_results": case_results,
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate high-recall Skill retrieval.")
    parser.add_argument("--top-k", type=int, default=12)
    parser.add_argument("--min-recall", type=float, default=1.0)
    parser.add_argument("--min-primary-top-k", type=float, default=0.9)
    parser.add_argument("--min-mrr", type=float, default=0.75)
    parser.add_argument("--min-ndcg-at-k", type=float, default=0.65)
    parser.add_argument("--max-average-review-candidates", type=float, default=40)
    args = parser.parse_args()
    result = evaluate(args.top_k)
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


if __name__ == "__main__":
    main()
