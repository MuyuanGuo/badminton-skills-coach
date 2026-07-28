#!/usr/bin/env python3
import argparse
from contextlib import contextmanager
import importlib.util
import json
import math
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "data" / "evaluation" / "answer_quality_cases.json"
SEARCH_PATH = (
    ROOT
    / "skills"
    / "liuhui-badminton-coach"
    / "scripts"
    / "search_knowledge.py"
)
REGRESSION_SOURCE_TYPES = ("douyin_video",)


def ensure_deterministic_hash_seed():
    if os.environ.get("PYTHONHASHSEED") == "0":
        return
    environment = dict(os.environ)
    environment["PYTHONHASHSEED"] = "0"
    os.execvpe(sys.executable, [sys.executable, *sys.argv], environment)


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


def project_retrieval_index(retrieval_index, allowed_video_ids):
    """Project an inverted index without rebuilding text-derived features."""

    allowed_video_ids = set(allowed_video_ids)
    old_records = retrieval_index["videos"]
    retained_old_indexes = [
        index
        for index, record in enumerate(old_records)
        if record["video_id"] in allowed_video_ids
    ]
    old_to_new = {
        old_index: new_index
        for new_index, old_index in enumerate(retained_old_indexes)
    }
    records = [old_records[index] for index in retained_old_indexes]

    vocabulary = []
    ngram_postings = []
    for gram, postings in zip(
        retrieval_index["ngram_vocabulary"],
        retrieval_index["ngram_postings"],
    ):
        projected = [
            [old_to_new[old_index], channel_mask]
            for old_index, channel_mask in postings
            if old_index in old_to_new
        ]
        if projected:
            vocabulary.append(gram)
            ngram_postings.append(projected)

    def project_named_postings(postings):
        return {
            name: [
                old_to_new[old_index]
                for old_index in indexes
                if old_index in old_to_new
            ]
            for name, indexes in postings.items()
            if any(old_index in old_to_new for old_index in indexes)
        }

    term_postings = project_named_postings(
        retrieval_index.get("term_postings", {})
    )
    topic_postings = project_named_postings(
        retrieval_index.get("topic_postings", {})
    )
    field_length_totals = {
        field: sum(record["field_lengths"].get(field, 0) for record in records)
        for field in retrieval_index["evidence_fields"]
    }
    field_document_counts = {
        field: sum(
            record["field_lengths"].get(field, 0) > 0
            for record in records
        )
        for field in retrieval_index["evidence_fields"]
    }
    field_term_document_frequency = {
        field: dict(
            sorted(
                {
                    term: sum(
                        term
                        in record.get(
                            "field_term_frequencies", {}
                        ).get(field, {})
                        for record in records
                    )
                    for term in {
                        term
                        for record in records
                        for term in record.get(
                            "field_term_frequencies", {}
                        ).get(field, {})
                    }
                }.items()
            )
        )
        for field in retrieval_index["evidence_fields"]
    }
    stable_records = [
        record
        for record in records
        if record.get("retrieval_cohort", "stable_baseline")
        == "stable_baseline"
    ]
    stable_term_document_frequency = {
        term: sum(
            term in record.get("lexicon_terms", [])
            for record in stable_records
        )
        for term in {
            term
            for record in stable_records
            for term in record.get("lexicon_terms", [])
        }
    }
    stable_field_document_counts = {
        field: sum(
            record["field_lengths"].get(field, 0) > 0
            for record in stable_records
        )
        for field in retrieval_index["evidence_fields"]
    }
    stable_field_term_document_frequency = {
        field: dict(
            sorted(
                {
                    term: sum(
                        term
                        in record.get(
                            "field_term_frequencies", {}
                        ).get(field, {})
                        for record in stable_records
                    )
                    for term in {
                        term
                        for record in stable_records
                        for term in record.get(
                            "field_term_frequencies", {}
                        ).get(field, {})
                    }
                }.items()
            )
        )
        for field in retrieval_index["evidence_fields"]
    }
    projected_chunk_index = None
    source_chunk_index = retrieval_index.get("chunk_index")
    if source_chunk_index:
        retained_chunk_indexes = [
            index
            for index, chunk in enumerate(source_chunk_index.get("chunks", []))
            if chunk.get("video_index") in old_to_new
        ]
        old_chunk_to_new = {
            old_index: new_index
            for new_index, old_index in enumerate(retained_chunk_indexes)
        }
        chunks = [
            {
                **source_chunk_index["chunks"][old_index],
                "video_index": old_to_new[
                    source_chunk_index["chunks"][old_index]["video_index"]
                ],
            }
            for old_index in retained_chunk_indexes
        ]
        chunk_term_postings = {
            term: [
                old_chunk_to_new[index]
                for index in indexes
                if index in old_chunk_to_new
            ]
            for term, indexes in source_chunk_index.get(
                "term_postings", {}
            ).items()
        }
        chunk_term_postings = {
            term: indexes
            for term, indexes in chunk_term_postings.items()
            if indexes
        }
        chunk_vocabulary = []
        chunk_ngram_postings = []
        for gram, indexes in zip(
            source_chunk_index.get("ngram_vocabulary", []),
            source_chunk_index.get("ngram_postings", []),
        ):
            projected_indexes = [
                old_chunk_to_new[index]
                for index in indexes
                if index in old_chunk_to_new
            ]
            if projected_indexes:
                chunk_vocabulary.append(gram)
                chunk_ngram_postings.append(projected_indexes)
        cluster_ids = {chunk["cluster_id"] for chunk in chunks}
        stable_chunks = [
            chunk
            for chunk in chunks
            if chunk.get("stable_cluster_id")
            and records[chunk["video_index"]].get(
                "retrieval_cohort", "stable_baseline"
            )
            == "stable_baseline"
        ]
        stable_cluster_ids = {
            chunk["stable_cluster_id"] for chunk in stable_chunks
        }
        projected_chunk_index = {
            **source_chunk_index,
            "chunk_count": len(chunks),
            "cluster_count": len(cluster_ids),
            "stable_cluster_count": len(stable_cluster_ids),
            "average_chunk_length": round(
                sum(chunk["normalized_length"] for chunk in chunks)
                / max(1, len(chunks)),
                4,
            ),
            "stable_average_chunk_length": round(
                sum(
                    chunk["normalized_length"]
                    for chunk in stable_chunks
                )
                / max(1, len(stable_chunks)),
                4,
            ),
            "term_cluster_document_frequency": {
                term: len(
                    {
                        chunks[index]["cluster_id"]
                        for index in indexes
                    }
                )
                for term, indexes in chunk_term_postings.items()
            },
            "stable_term_cluster_document_frequency": {
                term: len(
                    {
                        chunks[index]["stable_cluster_id"]
                        for index in indexes
                        if chunks[index].get("stable_cluster_id")
                    }
                )
                for term, indexes in chunk_term_postings.items()
            },
            "term_postings": chunk_term_postings,
            "ngram_vocabulary": chunk_vocabulary,
            "ngram_postings": chunk_ngram_postings,
            "chunks": chunks,
        }
    projected = dict(retrieval_index)
    projected.update(
        {
            "indexable_video_count": len(records),
            "stable_indexable_video_count": len(stable_records),
            "term_document_frequency": {
                term: len(indexes) for term, indexes in term_postings.items()
            },
            "stable_term_document_frequency": dict(
                sorted(stable_term_document_frequency.items())
            ),
            "field_document_counts": field_document_counts,
            "field_term_document_frequency": (
                field_term_document_frequency
            ),
            "stable_field_document_counts": (
                stable_field_document_counts
            ),
            "stable_field_term_document_frequency": (
                stable_field_term_document_frequency
            ),
            "average_field_lengths": {
                field: round(
                    total / max(1, field_document_counts[field]),
                    4,
                )
                for field, total in field_length_totals.items()
            },
            "stable_average_field_lengths": {
                field: round(
                    sum(
                        record["field_lengths"].get(field, 0)
                        for record in stable_records
                    )
                    / max(1, len(stable_records)),
                    4,
                )
                for field in retrieval_index["evidence_fields"]
            },
            "ngram_vocabulary": vocabulary,
            "ngram_postings": ngram_postings,
            "term_postings": term_postings,
            "topic_postings": topic_postings,
            "topics": [
                {
                    **topic,
                    "video_count": len(
                        topic_postings.get(topic["topic_id"], [])
                    ),
                }
                for topic in retrieval_index["topics"]
            ],
            "videos": records,
        }
    )
    if projected_chunk_index is not None:
        projected["chunk_index"] = projected_chunk_index
    return projected


@contextmanager
def source_scoped_search(search_module, source_types):
    original_resources = search_module.load_resources()
    knowledge, retrieval_index, rules = original_resources
    source_types = set(source_types)
    videos = [
        video
        for video in knowledge["videos"]
        if video.get("source_type") in source_types
    ]
    video_ids = {video["video_id"] for video in videos}
    scoped_knowledge = {**knowledge, "videos": videos}
    scoped_index = project_retrieval_index(retrieval_index, video_ids)
    search_module._RESOURCE_CACHE = (scoped_knowledge, scoped_index, rules)
    search_module._PREPARED_RETRIEVAL_CACHE.clear()
    search_module._VIDEO_CONSTRAINT_SCOPE_CACHE.clear()
    try:
        yield video_ids
    finally:
        search_module._RESOURCE_CACHE = original_resources
        search_module._PREPARED_RETRIEVAL_CACHE.clear()
        search_module._VIDEO_CONSTRAINT_SCOPE_CACHE.clear()


def evaluate_view(
    top_k,
    cases,
    search_module,
    judged_video_ids=None,
    unjudged_new_source_ids=None,
):
    filter_judgments = judged_video_ids is not None
    judged_video_ids = set(judged_video_ids or ())
    unjudged_new_source_ids = set(unjudged_new_source_ids or ())
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
    unjudged_new_source_top_k_total = 0
    unjudged_new_source_review_total = 0
    max_unjudged_new_source_top_k = 0
    max_unjudged_new_source_review = 0
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
        expected = [
            video_id
            for video_id in gold["required_video_ids"]
            if not filter_judgments or video_id in judged_video_ids
        ]
        primary = [
            video_id
            for video_id in gold["primary_video_ids"]
            if not filter_judgments or video_id in judged_video_ids
        ]
        irrelevant = {
            video_id
            for video_id in gold["irrelevant_video_ids"]
            if not filter_judgments or video_id in judged_video_ids
        }
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
        unjudged_new_top = unjudged_new_source_ids & set(top_ids)
        unjudged_new_review = unjudged_new_source_ids & review_ids
        hard_negative_total += len(irrelevant)
        hard_negative_top_k_violations += len(negative_top)
        hard_negative_review_violations += len(negative_review)
        unjudged_new_source_top_k_total += len(unjudged_new_top)
        unjudged_new_source_review_total += len(unjudged_new_review)
        max_unjudged_new_source_top_k = max(
            max_unjudged_new_source_top_k, len(unjudged_new_top)
        )
        max_unjudged_new_source_review = max(
            max_unjudged_new_source_review, len(unjudged_new_review)
        )
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
                "unjudged_new_source_top_k_video_ids": sorted(
                    unjudged_new_top
                ),
                "unjudged_new_source_review_video_ids": sorted(
                    unjudged_new_review
                ),
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
        "unjudged_new_source_exposure": {
            "candidate_videos": len(unjudged_new_source_ids),
            "top_k_count": unjudged_new_source_top_k_total,
            "top_k_rate": (
                unjudged_new_source_top_k_total
                / max(1, len(cases) * top_k)
            ),
            "max_top_k_per_case": max_unjudged_new_source_top_k,
            "review_count": unjudged_new_source_review_total,
            "review_rate": (
                unjudged_new_source_review_total
                / max(1, review_candidate_total)
            ),
            "max_review_per_case": max_unjudged_new_source_review,
        },
        "top_k": top_k,
        "case_results": case_results,
    }


def evaluate(top_k, cases_path=CASES_PATH):
    cases = json.loads(cases_path.read_text(encoding="utf-8"))["cases"]
    search_module = load_search_module()
    knowledge, _, _ = search_module.load_resources()
    all_judged_ids = {
        video_id
        for case in cases
        for field in (
            "required_video_ids",
            "primary_video_ids",
            "irrelevant_video_ids",
        )
        for video_id in case["gold"][field]
    }
    new_source_ids = {
        video["video_id"]
        for video in knowledge["videos"]
        if video.get("retrieval_cohort") == "automatic_expansion"
        and video.get("processing_status") == "ready"
    }
    production = evaluate_view(
        top_k,
        cases,
        search_module,
        unjudged_new_source_ids=new_source_ids - all_judged_ids,
    )
    with source_scoped_search(
        search_module, REGRESSION_SOURCE_TYPES
    ) as regression_video_ids:
        regression = evaluate_view(
            top_k,
            cases,
            search_module,
            judged_video_ids=regression_video_ids,
        )

    production["evaluation_views"] = {
        "production": {
            "source_scope": "all_admitted_sources",
            "ranking_metrics": "informational_when_gold_judgments_are_incomplete",
        },
        "stable_regression": {
            "source_types": list(REGRESSION_SOURCE_TYPES),
            "purpose": "apples_to_apples_retrieval_regression",
        },
    }
    production["stable_regression"] = {
        key: regression[key]
        for key in (
            "cases",
            "expected_videos",
            "found_videos",
            "candidate_recall",
            "primary_top_k",
            "mean_reciprocal_rank",
            "mean_ndcg_at_k",
            "mean_known_precision_at_k",
            "average_review_candidate_count",
            "hard_negative_count",
            "hard_negative_top_k_violations",
            "hard_negative_review_violations",
            "top_k",
        )
    }
    return production


def main():
    ensure_deterministic_hash_seed()
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
