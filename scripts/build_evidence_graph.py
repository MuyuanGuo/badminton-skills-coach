#!/usr/bin/env python3
"""Build a compact concept-topic-role evidence graph for answer planning.

The graph intentionally contains no transcript text.  It connects answer-
eligible evidence to the concepts, topics, and evidence roles it can support,
while keeping primary and supplemental postings separate.
"""

import json
import re
from collections import defaultdict
from pathlib import Path

from project_artifacts import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_PATH = ROOT / "data/knowledge/douyin_knowledge_base.json"
RETRIEVAL_PATH = ROOT / "data/knowledge/retrieval_index.json"
TOPIC_PATH = ROOT / "data/knowledge/topic_index.json"
OUTPUT_PATH = ROOT / "data/knowledge/evidence_graph.json"


def _support_bucket():
    return {"primary": [], "supplemental": []}


def _flatten(value):
    if isinstance(value, dict):
        return " ".join(_flatten(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_flatten(item) for item in value)
    return str(value or "")


def _normalize(value):
    return "".join(
        re.findall(r"[\u4e00-\u9fff]+|[a-z0-9]+", str(value).lower())
    )


def build_graph(knowledge, retrieval, topic_index):
    videos = {item["video_id"]: item for item in knowledge["videos"]}
    concept_support = defaultdict(_support_bucket)
    topic_support = defaultdict(_support_bucket)
    role_support = defaultdict(_support_bucket)
    concept_role_support = defaultdict(lambda: defaultdict(_support_bucket))
    profiles = {}
    lexicon = sorted(
        retrieval.get("term_document_frequency", {})
        or {
            term
            for record in retrieval.get("videos", [])
            for term in record.get("lexicon_terms", [])
        }
    )
    for record in retrieval["videos"]:
        video_id = record["video_id"]
        video = videos[video_id]
        eligibility = record.get("answer_eligibility", "primary")
        if eligibility not in {"primary", "supplemental"}:
            raise ValueError(f"ineligible evidence leaked into graph: {video_id}")
        evidence_text = _normalize(
            _flatten(video.get("teaching_note"))
            + " "
            + _flatten(video.get("transcript_segments"))
        )
        concepts = [
            term
            for term in lexicon
            if _normalize(term) and _normalize(term) in evidence_text
        ]
        topics = sorted(set(record.get("topic_ids", [])))
        roles = sorted(set(record.get("evidence_roles", ["context"])))
        profiles[video_id] = {
            "answer_eligibility": eligibility,
            "runtime_evidence_mode": record.get(
                "runtime_evidence_mode", "full_transcript"
            ),
            "metadata_title_trust": record.get(
                "metadata_title_trust", "not_applicable"
            ),
            "source_type": record["source_type"],
            "concepts": concepts,
            "topic_ids": topics,
            "evidence_roles": roles,
        }
        for concept in concepts:
            concept_support[concept][eligibility].append(video_id)
            for role in roles:
                concept_role_support[concept][role][eligibility].append(video_id)
        for topic_id in topics:
            topic_support[topic_id][eligibility].append(video_id)
        for role in roles:
            role_support[role][eligibility].append(video_id)

    def sorted_support(mapping):
        return {
            key: {
                eligibility: sorted(values[eligibility])
                for eligibility in ("primary", "supplemental")
            }
            for key, values in sorted(mapping.items())
        }

    concept_role_index = {
        concept: sorted_support(role_mapping)
        for concept, role_mapping in sorted(concept_role_support.items())
    }
    video_concept_edges = sum(
        len(profile["concepts"]) for profile in profiles.values()
    )
    video_topic_edges = sum(
        len(profile["topic_ids"]) for profile in profiles.values()
    )
    video_role_edges = sum(
        len(profile["evidence_roles"]) for profile in profiles.values()
    )
    topic_ids = {
        topic_id
        for profile in profiles.values()
        for topic_id in profile["topic_ids"]
    }
    graph = {
        "schema_version": 2,
        "version": "evidence-graph-v2",
        "source": {
            "knowledge": str(KNOWLEDGE_PATH.relative_to(ROOT)),
            "retrieval_index": str(RETRIEVAL_PATH.relative_to(ROOT)),
            "topic_index": str(TOPIC_PATH.relative_to(ROOT)),
        },
        "source_updated_at": knowledge["updated_at"],
        "counts": {
            "video_nodes": len(profiles),
            "concept_nodes": len(concept_support),
            "topic_nodes": len(topic_ids),
            "role_nodes": len(role_support),
            "primary_videos": sum(
                profile["answer_eligibility"] == "primary"
                for profile in profiles.values()
            ),
            "supplemental_videos": sum(
                profile["answer_eligibility"] == "supplemental"
                for profile in profiles.values()
            ),
            "video_concept_edges": video_concept_edges,
            "video_topic_edges": video_topic_edges,
            "video_role_edges": video_role_edges,
            "total_edges": video_concept_edges + video_topic_edges + video_role_edges,
        },
        "video_profiles": dict(sorted(profiles.items())),
        "concept_support": sorted_support(concept_support),
        "topic_support": sorted_support(topic_support),
        "role_support": sorted_support(role_support),
        "concept_role_support": concept_role_index,
    }
    return graph


def main():
    knowledge = json.loads(KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    retrieval = json.loads(RETRIEVAL_PATH.read_text(encoding="utf-8"))
    topic_index = json.loads(TOPIC_PATH.read_text(encoding="utf-8"))
    graph = build_graph(knowledge, retrieval, topic_index)
    atomic_write_text(
        OUTPUT_PATH,
        json.dumps(graph, ensure_ascii=False, indent=2) + "\n",
    )
    print(json.dumps(graph["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
