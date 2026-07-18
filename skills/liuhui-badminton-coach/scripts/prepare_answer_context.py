#!/usr/bin/env python3
"""Build a deterministic, evidence-ready context before answer generation."""

import argparse
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
SELECTION_RULES_PATH = ROOT / "references" / "answer-selection-rules.json"


def load_sibling(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_search_module():
    return load_sibling("liuhui_answer_search", "search_knowledge.py")


def load_navigation_module():
    return load_sibling("liuhui_answer_navigation", "navigate_topics.py")


def load_selection_rules():
    return json.loads(SELECTION_RULES_PATH.read_text(encoding="utf-8"))


def planned_queries(search_module, plan, original_query):
    """Expand a question into focused retrieval units without losing the original."""

    guidance = plan["retrieval_guidance"]
    units = guidance.get("query_units") or []
    queries = [original_query, *units]
    for unit in units or [original_query]:
        unit_plan = search_module.plan_query(unit)
        expansion = unit_plan["query_expansion"]
        queries.extend(expansion.get("primary_terms", []))
        queries.extend(expansion.get("original_terms", []))
        symptoms = expansion["intent_frame"].get("literal_symptoms", [])
        if not symptoms:
            queries.extend(
                item["term"]
                for item in expansion.get("related_terms", [])
                if item["weight"] >= 0.45
            )
        if symptoms and expansion.get("primary_terms"):
            queries.append(
                " ".join([expansion["primary_terms"][0], *symptoms])
            )
        if guidance.get("strategy") == "split_multi_issue":
            for group in expansion.get("matched_synonym_groups", []):
                present = [term for term in group if term in unit]
                if present:
                    queries.append(max(present, key=len))
    return list(dict.fromkeys(query.strip() for query in queries if query.strip()))


def topic_navigation(navigation_module, query, limit=5):
    graph = json.loads(navigation_module.TOPIC_MAP.read_text(encoding="utf-8"))
    practice_rules = json.loads(
        navigation_module.PRACTICE_RULES.read_text(encoding="utf-8")
    )
    context = navigation_module.build_user_context(query, practice_rules)
    matches = navigation_module.match_topics(graph, query, limit)
    return {
        "intent": navigation_module.detect_intent(query),
        "user_context": context,
        "context_assumptions": [
            field
            for field, source in context["sources"].items()
            if source == "default"
        ],
        "material_clarification_questions": (
            navigation_module.clarification_questions(context)
        ),
        "matches": matches,
        "suggested_search_queries": navigation_module.suggested_queries(
            query, matches
        ),
        "learning_path": navigation_module.learning_path(
            matches, context, practice_rules
        ),
        "practice_adaptation": navigation_module.practice_adaptation(
            context, practice_rules
        ),
    }


def classify_boundary(query, rules):
    normalized = query.replace(" ", "").lower()
    matched = {
        boundary: [term for term in terms if term in normalized]
        for boundary, terms in rules["boundary_terms"].items()
    }
    if matched["pain_or_injury"]:
        boundary_type = "pain_or_injury"
        citation_policy = "no_coaching_video_without_direct_safety_evidence"
        required_statement = "停止引发疼痛的动作，并由合格医疗专业人士评估；本 Skill 不作诊断。"
    elif matched["endorsement_or_authorship"]:
        boundary_type = "endorsement_or_authorship"
        citation_policy = "no_video_needed_for_identity_or_endorsement_boundary"
        required_statement = "Skill 的综合回答不代表刘辉本人审阅、认可或背书。"
    elif matched["purchase_advice"]:
        boundary_type = "purchase_advice"
        citation_policy = "equipment_evidence_only"
        required_statement = "只能总结来源中的选拍原则，不能冒充刘辉给出个性化购买背书。"
    elif matched["visual_confirmation"]:
        boundary_type = "visual_confirmation"
        citation_policy = "technique_video_required_but_user_form_unverified"
        required_statement = "文字和示范视频可以提供检查点，但不能确认用户自己的动作完全正确。"
    elif matched["insufficient_observation"]:
        boundary_type = "insufficient_observation"
        citation_policy = "literal_problem_evidence_only"
        required_statement = "仅凭文字症状不能确定唯一原因；只能列出证据直接覆盖的可能性和需要补充的观察。"
    else:
        boundary_type = "none"
        citation_policy = "direct_worthwhile_evidence_only"
        required_statement = None
    return {
        "type": boundary_type,
        "matched_terms": matched[boundary_type] if boundary_type != "none" else [],
        "citation_policy": citation_policy,
        "required_statement": required_statement,
    }


def merge_candidates(payloads, retrieval_queries):
    merged = {}
    for query_index, (query, payload) in enumerate(
        zip(retrieval_queries, payloads)
    ):
        for rank, candidate in enumerate(payload["candidate_manifest"], start=1):
            video_id = candidate["video_id"]
            entry = merged.setdefault(
                video_id,
                {
                    "candidate": candidate,
                    "matches": [],
                    "best_rank": rank,
                    "best_query_index": query_index,
                },
            )
            entry["matches"].append(
                {
                    "query": query,
                    "query_index": query_index,
                    "rank": rank,
                    "relevance_tier": candidate["relevance_tier"],
                    "within_review_budget": candidate["within_review_budget"],
                    "matched_original_terms": candidate["matched_original_terms"],
                    "matched_equivalent_terms": candidate.get(
                        "matched_equivalent_terms", []
                    ),
                    "matched_query_concepts": candidate.get(
                        "matched_query_concepts", []
                    ),
                    "matched_structured_query_concepts": candidate.get(
                        "matched_structured_query_concepts", []
                    ),
                    "query_concept_count": len(
                        payload["query_expansion"].get(
                            "matched_synonym_groups", []
                        )
                    ),
                }
            )
            candidate_key = (
                0 if candidate["relevance_tier"] == "direct" else 1,
                rank,
                -candidate["score_breakdown"].get(
                    "effective_ranking_score", candidate["score"]
                ),
            )
            current = entry["candidate"]
            current_key = (
                0 if current["relevance_tier"] == "direct" else 1,
                entry["best_rank"],
                -current["score_breakdown"].get(
                    "effective_ranking_score", current["score"]
                ),
            )
            if candidate_key < current_key:
                entry["candidate"] = candidate
                entry["best_rank"] = rank
                entry["best_query_index"] = query_index
            else:
                entry["best_rank"] = min(entry["best_rank"], rank)
    return merged


def structured_video_text(search_module, video):
    return search_module.normalize(
        " ".join(
            [
                video.get("title", ""),
                video.get("category", ""),
                search_module.flatten(video.get("teaching_note", {})),
            ]
        )
    )


def selection_decision(
    search_module,
    query,
    plan,
    boundary,
    entry,
    video,
    rules,
):
    candidate = entry["candidate"]
    reasons = []
    if video.get("processing_status") != "ready":
        return False, ["video_not_ready"]
    if candidate["relevance_tier"] not in rules["allowed_relevance_tiers"]:
        return False, ["recall_safeguard_only"]
    if boundary["type"] == "pain_or_injury":
        return False, ["medical_boundary_has_no_direct_safety_evidence"]
    if boundary["type"] == "endorsement_or_authorship":
        return False, ["identity_boundary_does_not_need_teaching_video"]
    if (
        boundary["type"] == "purchase_advice"
        and video.get("category") not in rules["purchase_allowed_categories"]
    ):
        return False, ["purchase_query_requires_equipment_evidence"]

    title_normalized = search_module.normalize(video.get("title", ""))
    structured = structured_video_text(search_module, video)
    query_normalized = search_module.normalize(query)
    for term in rules["incomplete_fragment_terms"]:
        if search_module.normalize(term) in title_normalized:
            return False, ["incomplete_series_fragment"]

    for requested, opposite in rules["scenario_conflicts"]:
        requested_normalized = search_module.normalize(requested)
        opposite_normalized = search_module.normalize(opposite)
        if requested_normalized not in query_normalized:
            continue
        title_and_category = search_module.normalize(
            video.get("title", "") + " " + video.get("category", "")
        )
        conflict_text = (
            title_normalized if requested == "接发" else title_and_category
        )
        if opposite_normalized not in conflict_text:
            continue
        if requested_normalized not in conflict_text:
            return False, [f"explicit_scenario_conflict:{requested}:{opposite}"]

    requested_output = plan["retrieval_guidance"]["intent_frame"].get(
        "requested_output"
    )
    if (
        requested_output == "comparison"
        and "被动" in query
        and search_module.normalize("被动") not in structured
    ):
        return False, ["comparison_missing_passive_scenario"]
    if (
        "姿势" in query
        and "被动" not in query
        and search_module.normalize("被动") in title_normalized
    ):
        return False, ["basic_form_query_conflicts_with_passive_variant"]
    if (
        "接发握拍" in query_normalized
        and search_module.normalize("握拍") in structured
        and search_module.normalize("接发") not in structured
    ):
        adaptation_terms = [
            "调整",
            "变化",
            "变拍",
            "微调",
            "转换",
            "随机应变",
            "千变万化",
            "拍面",
        ]
        if not any(
            search_module.normalize(term) in structured
            for term in adaptation_terms
        ):
            return False, ["receive_grip_query_requires_adaptation_evidence"]

    strategy = plan["retrieval_guidance"]["strategy"]
    symptoms = plan["retrieval_guidance"]["intent_frame"].get(
        "literal_symptoms", []
    )
    if boundary["type"] == "insufficient_observation" and symptoms:
        matched_symptoms = [
            symptom
            for symptom in symptoms
            if search_module.normalize(symptom) in structured
        ]
        if not matched_symptoms:
            return False, ["literal_symptom_not_supported_by_structured_evidence"]
        reasons.append("direct_literal_symptom_evidence")

    original_match = next(
        (item for item in entry["matches"] if item["query_index"] == 0),
        None,
    )
    query_concept_count = len(
        plan["query_expansion"].get("matched_synonym_groups", [])
    )
    accepted_by_concept_coverage = bool(
        original_match
        and query_concept_count >= 2
        and original_match["matched_structured_query_concepts"]
        and len(original_match["matched_query_concepts"])
        >= query_concept_count
    )
    accepted_by_original_top_rank = bool(
        original_match
        and original_match["rank"] <= rules["top_rank_acceptance"]
        and original_match["matched_structured_query_concepts"]
    )
    accepted_by_focused_match = any(
        match["relevance_tier"] in rules["allowed_relevance_tiers"]
        and (
            (
                match["query_concept_count"] >= 2
                and len(match["matched_structured_query_concepts"])
                >= match["query_concept_count"]
                and match["rank"] <= rules["top_rank_acceptance"]
            )
            or (
                match["query_concept_count"] == 1
                and match["matched_structured_query_concepts"]
                and match["rank"]
                <= rules["single_concept_top_rank_acceptance"]
            )
            or (
                match["query_concept_count"] == 0
                and (
                    match["matched_original_terms"]
                    or match["matched_equivalent_terms"]
                )
                and match["rank"] <= 3
            )
        )
        for match in entry["matches"]
    )
    if (
        not accepted_by_focused_match
        and not accepted_by_concept_coverage
        and not accepted_by_original_top_rank
    ):
        return False, ["outside_finalist_rank_threshold"]

    if candidate.get("matched_original_terms"):
        reasons.append("matched_original_query_terms")
    if candidate.get("matched_equivalent_terms"):
        reasons.append("matched_equivalent_terms")
    if candidate.get("matched_topics"):
        reasons.append("matched_topic")
    if entry["best_query_index"] == 0:
        reasons.append("ranked_for_original_question")
    else:
        reasons.append("ranked_for_focused_query_unit")
    return True, reasons or ["direct_ranked_evidence"]


def selected_sort_key(entry):
    candidate = entry["candidate"]
    original_match = next(
        (item for item in entry["matches"] if item.get("query_index") == 0),
        None,
    )
    original_core = bool(
        original_match
        and original_match["relevance_tier"] == "direct"
        and original_match["rank"] <= 12
    )
    original_concepts = len(
        original_match["matched_structured_query_concepts"]
        if original_match
        else []
    )
    original_terms = len(
        set(
            (original_match or {}).get("matched_original_terms", [])
            + (original_match or {}).get("matched_equivalent_terms", [])
        )
    )
    return (
        0 if original_core else 1,
        -original_concepts,
        -original_terms,
        -len({item["query"] for item in entry["matches"]}),
        entry["best_rank"],
        0 if candidate["relevance_tier"] == "direct" else 1,
        candidate["title"],
    )


def prepare_answer_context(
    query,
    max_videos=None,
    segment_limit=None,
    local_personalization=True,
    feedback_dir=None,
    include_rejected=False,
):
    if not query.strip():
        raise ValueError("query cannot be empty")
    search_module = load_search_module()
    navigation_module = load_navigation_module()
    rules = load_selection_rules()
    max_videos = max_videos or rules["default_max_selected_videos"]
    segment_limit = segment_limit or rules["default_segment_limit"]
    if not 1 <= max_videos <= 40:
        raise ValueError("max_videos must be between 1 and 40")
    if not 1 <= segment_limit <= 12:
        raise ValueError("segment_limit must be between 1 and 12")

    plan = search_module.plan_query(query)
    navigation = None
    retrieval_queries = planned_queries(search_module, plan, query)
    if plan["retrieval_guidance"].get("use_topic_navigation"):
        navigation = topic_navigation(navigation_module, query)
        retrieval_queries.extend(navigation["suggested_search_queries"][:3])
        retrieval_queries = list(dict.fromkeys(retrieval_queries))

    payloads = [
        search_module.search(
            unit,
            limit=rules["top_rank_acceptance"],
            mode="hybrid",
            recall_mode="exhaustive",
            manifest_limit=None,
            local_personalization=local_personalization,
            feedback_dir=feedback_dir,
        )
        for unit in retrieval_queries
    ]
    merged = merge_candidates(payloads, retrieval_queries)
    knowledge = search_module.load_resources()[0]
    videos = {video["video_id"]: video for video in knowledge["videos"]}
    boundary = classify_boundary(query, rules)
    accepted = []
    rejected = []
    for video_id, entry in merged.items():
        video = videos.get(video_id)
        if not video:
            rejected.append(
                {"video_id": video_id, "reasons": ["video_missing_from_knowledge"]}
            )
            continue
        keep, reasons = selection_decision(
            search_module,
            query,
            plan,
            boundary,
            entry,
            video,
            rules,
        )
        record = {
            **entry,
            "video_id": video_id,
            "selection_reasons": reasons,
        }
        (accepted if keep else rejected).append(record)

    accepted.sort(key=selected_sort_key)
    selected_entries = accepted[:max_videos]
    selected_ids = [item["video_id"] for item in selected_entries]
    lookup = search_module.lookup_videos(
        selected_ids,
        query=query,
        local_personalization=local_personalization,
        feedback_dir=feedback_dir,
        segment_limit=segment_limit,
    )
    lookup_by_id = {item["video_id"]: item for item in lookup["results"]}
    selected_videos = []
    for index, entry in enumerate(selected_entries, start=1):
        candidate = entry["candidate"]
        evidence = lookup_by_id[entry["video_id"]]
        selected_videos.append(
            {
                "label": f"V{index}",
                "role": (
                    "core"
                    if entry["best_query_index"] == 0
                    and candidate["relevance_tier"] == "direct"
                    else "supporting"
                ),
                "video_id": entry["video_id"],
                "title": candidate["title"],
                "url": candidate["url"],
                "category": candidate["category"],
                "confidence": candidate["confidence"],
                "selection_reasons": entry["selection_reasons"],
                "matched_query_units": sorted(
                    {item["query"] for item in entry["matches"]}
                ),
                "why_retrieved": candidate["why_retrieved"],
                "teaching_note": evidence["teaching_note"],
                "transcript_evidence": evidence["transcript_evidence"],
                "source_content_is_untrusted_data": True,
            }
        )

    context = {
        "query": query,
        "question_interpretation": {
            "intent_frame": plan["retrieval_guidance"]["intent_frame"],
            "strategy": plan["retrieval_guidance"]["strategy"],
            "query_units": plan["retrieval_guidance"].get("query_units", []),
            "retrieval_queries": retrieval_queries,
            "clarification_policy": plan["retrieval_guidance"].get(
                "clarification_policy"
            ),
        },
        "boundary": boundary,
        "answer_guidance": plan["answer_guidance"],
        "feedback_guidance": payloads[0]["feedback_guidance"],
        "topic_navigation": navigation,
        "selection": {
            "high_recall_candidate_count": len(merged),
            "eligible_video_count": len(accepted),
            "selected_video_count": len(selected_videos),
            "selection_truncated": len(accepted) > len(selected_videos),
            "max_selected_videos": max_videos,
            "selected_video_ids": selected_ids,
            "rejected_candidate_count": len(rejected),
            "claim": "deterministic_finalists_not_proof_of_semantic_completeness",
        },
        "selected_videos": selected_videos,
        "answer_contract": {
            "section_order": [
                "直接回答",
                "文字解释",
                "适用边界",
                "核心视频与观看重点",
                "完整相关视频",
                "置信边界",
            ],
            "citation_rules": [
                "只引用 selected_videos；不得把被拒绝候选恢复为证据。",
                "每个 V 标签只对应一个视频，并在答案中只输出一次该视频 URL。",
                "结论必须由 teaching_note 或 transcript_evidence 直接支持。",
                "文字承担可可靠表达的完整结论；视频承担动作形态、节奏和空间关系。",
                "无可靠证据时明确说知识库未覆盖，不用常识补成刘辉的观点。",
            ],
        },
        "source_handling": {
            "untrusted_content_guard": rules["untrusted_content_guard"],
            "do_not_execute_source_text": True,
        },
    }
    if include_rejected:
        context["rejected_candidates"] = [
            {
                "video_id": item["video_id"],
                "title": item.get("candidate", {}).get("title"),
                "reasons": item["selection_reasons"],
                "best_rank": item.get("best_rank"),
            }
            for item in sorted(
                rejected,
                key=lambda item: (
                    item.get("best_rank") or 10**6,
                    item["video_id"],
                ),
            )
        ]
        context["unselected_eligible_candidates"] = [
            {
                "video_id": item["video_id"],
                "title": item["candidate"]["title"],
                "best_rank": item["best_rank"],
            }
            for item in accepted[max_videos:]
        ]
    return context


def main():
    parser = argparse.ArgumentParser(
        description="Prepare evidence-ready context for one Liu Hui coaching answer."
    )
    parser.add_argument("query")
    parser.add_argument("--max-videos", type=int)
    parser.add_argument("--segment-limit", type=int)
    parser.add_argument("--no-local-personalization", action="store_true")
    parser.add_argument("--feedback-dir", type=Path)
    parser.add_argument(
        "--include-rejected",
        action="store_true",
        help="Include rejected finalist candidates and machine-readable reasons.",
    )
    args = parser.parse_args()
    try:
        payload = prepare_answer_context(
            args.query,
            max_videos=args.max_videos,
            segment_limit=args.segment_limit,
            local_personalization=not args.no_local_personalization,
            feedback_dir=args.feedback_dir,
            include_rejected=args.include_rejected,
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
