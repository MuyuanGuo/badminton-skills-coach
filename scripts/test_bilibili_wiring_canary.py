#!/usr/bin/env python3
import copy
import importlib.util
import json
import unittest
from pathlib import Path

import bilibili_wiring_canary as canary


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_STORE_MODULE = (
    ROOT / "skills/liuhui-badminton-coach/scripts/runtime_store.py"
)
RUNTIME_STORE_PATH = (
    ROOT / "skills/liuhui-badminton-coach/references/runtime-store.sqlite3"
)
RETRIEVAL_INDEX_PATH = ROOT / "data/knowledge/retrieval_index.json"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeSearch:
    def __init__(self, knowledge, index, results, manifest=None):
        self.knowledge = knowledge
        self.index = index
        self.results = results
        self.manifest = results if manifest is None else manifest

    def load_resources(self):
        return self.knowledge, self.index, {}

    def search(
        self,
        query,
        limit,
        local_personalization,
        manifest_limit=None,
    ):
        return {
            "results": self.results[:limit],
            "candidate_manifest": self.manifest,
        }

    def lookup_videos(
        self,
        video_ids,
        query,
        local_personalization,
        include_query_match,
        chunk_hints_by_video,
    ):
        return {
            "results": [
                {
                    "video_id": video_id,
                    "transcript_evidence": [{"text": query}],
                    "bounded_note_evidence": [{"text": query}],
                }
                for video_id in video_ids
            ]
        }


class FakeContext:
    def __init__(self, expected_id, selected_ids=None):
        self.expected_id = expected_id
        self.selected_ids = selected_ids or [expected_id]

    def prepare_answer_context(self, query, local_personalization):
        return {
            "claim_evidence_map": [
                {
                    "evidence": [
                        {
                            "evidence_id": self.expected_id,
                            "window_support": {"rank": 2},
                        }
                    ]
                }
            ]
        }

    def build_answer_packet(self, context):
        windows = {}
        selected = []
        for index, evidence_id in enumerate(self.selected_ids, start=1):
            window_id = f"W{index}"
            windows[window_id] = {
                "label": f"V{index}",
                "timestamp": "00:00-00:10",
                "text": "反手过渡球先稳定拍面再加速。",
            }
            selected.append(
                {
                    "evidence_id": evidence_id,
                    "window_ids": [window_id],
                }
            )
        return {
            "evidence_windows": windows,
            "selected_videos": selected,
        }


class BilibiliWiringCanaryTests(unittest.TestCase):
    def setUp(self):
        self.evidence_id = "bilibili:BV1test00001"
        self.segments = [
            {
                "start": 0,
                "end": 10,
                "text": "反手过渡球先稳定拍面。",
            },
            {
                "start": 10,
                "end": 20,
                "text": "然后注意击球点再逐步加速。",
            },
            {
                "start": 20,
                "end": 30,
                "text": "练习时应该保持动作连贯。",
            },
        ]
        self.video = {
            "video_id": self.evidence_id,
            "evidence_id": self.evidence_id,
            "source_type": "bilibili_video",
            "processing_status": "ready",
            "retrieval_title": "反手过渡球怎么打",
            "title": "反手过渡球怎么打？刘辉教练教你",
            "quality": {
                "transcript": {
                    "integrity": {"transcript_sha256": "a" * 64},
                    "title_content_consistency": {
                        "passed": True,
                        "supported_terms": ["反手过渡球", "击球点"],
                    },
                }
            },
            "transcript_segments": self.segments,
        }
        self.knowledge = {"videos": [self.video]}
        self.index = {
            "videos": [{"video_id": self.evidence_id}],
            "chunk_index": {
                "chunks": [
                    {
                        "chunk_id": f"{self.evidence_id}#t000000000-000030000",
                        "video_index": 0,
                        "start_segment": 0,
                        "end_segment": 3,
                        "cluster_id": "CCprimary",
                    }
                ]
            },
        }
        self.rules = {
            "bilibili_unattended": {
                "title_consistency_terms": [
                    "反手过渡球",
                    "击球点",
                ]
            }
        }

    def generated_registry(self):
        return canary.generate_registry(
            self.knowledge,
            self.index,
            self.rules,
        )

    def target_result(self):
        chunk = self.index["chunk_index"]["chunks"][0]
        return {
            "video_id": self.evidence_id,
            "transcript_retrieval": {
                "mode": "chunk_first",
                "best_chunk_id": chunk["chunk_id"],
                "matched_chunk_ids": [chunk["chunk_id"]],
                "matched_cluster_ids": [chunk["cluster_id"]],
            },
        }

    def test_generation_is_deterministic_and_explicitly_not_semantic_gold(self):
        first = self.generated_registry()
        second = self.generated_registry()
        self.assertEqual(first, second)
        self.assertEqual(first["case_count"], 1)
        case = first["cases"][0]
        self.assertFalse(first["semantic_gold"])
        self.assertFalse(case["semantic_gold"])
        self.assertEqual(case["query"], "反手过渡球怎么打")
        self.assertEqual(
            case["query_derivation"],
            "cleaned_retrieval_title_with_separate_transcript_anchor_probe",
        )
        self.assertEqual(
            case["transcript_probe"],
            "反手过渡球先稳定拍面。然后注意击球点再逐步加速。",
        )
        self.assertEqual(case["expected_cluster_ids"], ["CCprimary"])
        canary.validate_registry(first)

    def test_registry_shards_are_deterministic_and_cover_every_case_once(self):
        registry = self.generated_registry()
        base_case = registry["cases"][0]
        cases = []
        for index in range(7):
            case = copy.deepcopy(base_case)
            case["case_id"] = f"mechanical-{index}"
            case["case_sha256"] = canary.stable_payload_hash(
                {
                    key: value
                    for key, value in case.items()
                    if key != "case_sha256"
                }
            )
            cases.append(case)
        registry["cases"] = cases
        registry["case_count"] = len(cases)

        shards = [
            canary.shard_registry(registry, index, 3)
            for index in range(3)
        ]
        self.assertEqual([shard["case_count"] for shard in shards], [3, 2, 2])
        self.assertEqual(
            sorted(case["case_id"] for shard in shards for case in shard["cases"]),
            sorted(case["case_id"] for case in cases),
        )
        self.assertEqual(shards[0], canary.shard_registry(registry, 0, 3))
        with self.assertRaisesRegex(ValueError, "shard count"):
            canary.shard_registry(registry, 0, 0)
        with self.assertRaisesRegex(ValueError, "shard index"):
            canary.shard_registry(registry, 3, 3)

    def test_runtime_store_retrieval_hash_matches_canonical_json(self):
        runtime = load_module("wiring_canary_runtime_store", RUNTIME_STORE_MODULE)
        store = runtime.RuntimeStore(RUNTIME_STORE_PATH)
        try:
            canonical = json.loads(RETRIEVAL_INDEX_PATH.read_text(encoding="utf-8"))
            self.assertEqual(
                canary.stable_payload_hash(store.retrieval_index),
                canary.stable_payload_hash(canonical),
            )
        finally:
            store.close()

    def test_committed_json_schema_matches_runtime_contract(self):
        schema = json.loads(
            (
                ROOT
                / "data"
                / "evaluation"
                / "bilibili_mechanical_canary.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            schema["properties"]["schema_version"]["const"],
            canary.SCHEMA_VERSION,
        )
        self.assertEqual(
            schema["properties"]["measurement_type"]["const"],
            canary.MEASUREMENT_TYPE,
        )
        self.assertEqual(
            set(schema["properties"]["thresholds"]["required"]),
            set(canary.DEFAULT_THRESHOLDS),
        )

    def test_shadow_quality_candidate_is_included(self):
        shadow = copy.deepcopy(self.video)
        shadow["processing_status"] = "low_value"
        shadow["promotion_state"] = "shadow"
        registry = canary.generate_registry(
            {"videos": [shadow]},
            self.index,
            self.rules,
        )
        self.assertEqual(registry["cases"][0]["admission_state"], "shadow")

    def test_missing_chunk_is_reported_as_exclusion(self):
        registry = canary.generate_registry(
            self.knowledge,
            {"videos": self.index["videos"], "chunk_index": {"chunks": []}},
            self.rules,
        )
        self.assertEqual(registry["case_count"], 0)
        self.assertEqual(
            registry["exclusions"][0]["reason"],
            "missing_chunk_for_transcript_anchor",
        )
        result = canary.evaluate_registry(
            registry,
            FakeSearch(self.knowledge, self.index, []),
            FakeContext(self.evidence_id),
            validate_source_hashes=False,
        )
        self.assertIn(
            "blocking_mechanical_case_generation_exclusions_present",
            result["global_failures"],
        )

    def test_bounded_note_supplemental_gets_a_separate_wiring_contract(self):
        supplemental = copy.deepcopy(self.video)
        supplemental.update(
            {
                "answer_eligibility": "supplemental",
                "runtime_evidence_mode": "bounded_note_windows",
                "metadata_title_trust": "limited",
                "transcript_segments": [],
                "teaching_note": {
                    "topic": "球拍重量选择",
                    "key_evidence": [
                        {
                            "timestamp": "00:23-00:28",
                            "text": "初学者先用四优球拍建立稳定动作",
                        }
                    ],
                    "error_evidence": [],
                    "action_cues": [],
                },
            }
        )
        knowledge = {"videos": [supplemental]}
        index = {
            "videos": [{"video_id": self.evidence_id}],
            "chunk_index": {"chunks": []},
        }
        registry = canary.generate_registry(knowledge, index, self.rules)
        self.assertEqual(registry["case_count"], 1)
        self.assertEqual(registry["excluded_count"], 0)
        case = registry["cases"][0]
        self.assertEqual(case["evidence_mode"], "bounded_note_windows")
        self.assertEqual(
            case["query_derivation"], "committed_bounded_note_window"
        )
        self.assertNotIn("transcript_anchor", case)
        canary.validate_registry(registry)

        result = canary.evaluate_registry(
            registry,
            FakeSearch(
                knowledge,
                index,
                [
                    {
                        "video_id": self.evidence_id,
                        "answer_eligibility": "supplemental",
                    }
                ],
            ),
            FakeContext(self.evidence_id),
        )
        self.assertTrue(result["passed"], result["failures"])
        self.assertTrue(result["results"][0]["claim_mapped"])
        self.assertEqual(result["results"][0]["packet_window_count"], 1)

    def test_packaging_only_knowledge_fields_do_not_change_source_hash(self):
        packaged = copy.deepcopy(self.knowledge)
        packaged["transcript_files_bundled"] = False
        packaged["videos"][0]["transcript_file"] = "maintainer-only.json"
        self.assertEqual(
            canary.mechanical_knowledge_hash(self.knowledge),
            canary.mechanical_knowledge_hash(packaged),
        )

    def test_compact_skill_segments_preserve_hash_and_anchor_contract(self):
        registry = self.generated_registry()
        packaged = copy.deepcopy(self.knowledge)
        video = packaged["videos"][0]
        video["transcript_segments_json"] = json.dumps(
            video.pop("transcript_segments"),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        self.assertEqual(
            canary.mechanical_knowledge_hash(self.knowledge),
            canary.mechanical_knowledge_hash(packaged),
        )
        self.assertEqual(
            canary.current_anchor_hash(
                video,
                registry["cases"][0]["transcript_anchor"],
            ),
            registry["cases"][0]["transcript_anchor"]["text_sha256"],
        )
        result = canary.evaluate_registry(
            registry,
            FakeSearch(packaged, self.index, [self.target_result()]),
            FakeContext(self.evidence_id),
        )
        self.assertTrue(result["passed"], result["failures"])

    def test_malformed_compact_segments_fail_closed(self):
        packaged = copy.deepcopy(self.video)
        packaged.pop("transcript_segments")
        packaged["transcript_segments_json"] = "{not-json"
        self.assertEqual(canary.runtime_transcript_segments(packaged), [])

    def test_evaluator_accepts_complete_transcript_chunk_claim_and_packet_wiring(self):
        registry = self.generated_registry()
        search = FakeSearch(
            self.knowledge,
            self.index,
            [self.target_result()],
        )
        context = FakeContext(self.evidence_id)
        result = canary.evaluate_registry(registry, search, context)
        self.assertTrue(result["passed"], result["failures"])
        self.assertEqual(result["results"][0]["packet_window_count"], 1)

    def test_policy_guarded_manifest_proves_wiring_without_bypassing_policy(self):
        registry = self.generated_registry()
        manifest_target = {
            **self.target_result(),
            "retrieval_policy_eligible": False,
            "retrieval_policy_reasons": [
                "medical_boundary_has_no_direct_safety_evidence"
            ],
            "review_priority": "policy_rejected",
        }
        result = canary.evaluate_registry(
            registry,
            FakeSearch(
                self.knowledge,
                self.index,
                [],
                manifest=[manifest_target],
            ),
            FakeContext(self.evidence_id),
        )
        self.assertTrue(result["passed"], result["failures"])
        self.assertEqual(
            result["results"][0]["retrieval_surface_disposition"],
            "policy_guarded_manifest",
        )

    def test_unexplained_top_k_miss_is_still_a_failure(self):
        registry = self.generated_registry()
        manifest_target = {
            **self.target_result(),
            "retrieval_policy_eligible": True,
            "retrieval_policy_reasons": [],
            "review_priority": "priority_review",
        }
        result = canary.evaluate_registry(
            registry,
            FakeSearch(
                self.knowledge,
                self.index,
                [],
                manifest=[manifest_target],
            ),
            FakeContext(self.evidence_id),
        )
        self.assertIn(
            "expected_evidence_not_in_top_k",
            {item["reason"] for item in result["failures"]},
        )

    def test_content_cluster_suppressed_manifest_is_not_treated_as_loss(self):
        registry = self.generated_registry()
        representative = {
            "video_id": "bilibili:BV1representative",
            "transcript_retrieval": {
                "mode": "chunk_first",
                "best_chunk_id": "representative#chunk",
                "matched_chunk_ids": ["representative#chunk"],
                "matched_cluster_ids": ["CCprimary"],
            },
        }
        manifest_target = {
            **self.target_result(),
            "retrieval_policy_eligible": True,
            "retrieval_policy_reasons": [],
            "review_priority": "priority_review",
        }
        result = canary.evaluate_registry(
            registry,
            FakeSearch(
                self.knowledge,
                self.index,
                [representative],
                manifest=[manifest_target],
            ),
            FakeContext(self.evidence_id),
        )
        self.assertTrue(result["passed"], result["failures"])
        self.assertEqual(
            result["results"][0]["retrieval_surface_disposition"],
            "content_cluster_deferred_manifest",
        )

    def test_evaluator_rejects_duplicate_content_clusters_in_top_k_and_packet(self):
        duplicate_id = "bilibili:BV1duplicate1"
        duplicate_video = {
            **copy.deepcopy(self.video),
            "video_id": duplicate_id,
            "evidence_id": duplicate_id,
        }
        knowledge = {"videos": [self.video, duplicate_video]}
        duplicate_chunk = {
            **self.index["chunk_index"]["chunks"][0],
            "chunk_id": f"{duplicate_id}#t000000000-000030000",
            "video_index": 1,
        }
        index = {
            "videos": [
                {"video_id": self.evidence_id},
                {"video_id": duplicate_id},
            ],
            "chunk_index": {
                "chunks": [
                    self.index["chunk_index"]["chunks"][0],
                    duplicate_chunk,
                ]
            },
        }
        registry = canary.generate_registry(knowledge, index, self.rules)
        registry["cases"] = [
            case
            for case in registry["cases"]
            if case["expected_evidence_id"] == self.evidence_id
        ]
        registry["case_count"] = 1
        target = self.target_result()
        duplicate_result = {
            "video_id": duplicate_id,
            "transcript_retrieval": {
                "mode": "chunk_first",
                "best_chunk_id": duplicate_chunk["chunk_id"],
                "matched_chunk_ids": [duplicate_chunk["chunk_id"]],
                "matched_cluster_ids": ["CCprimary"],
            },
        }
        result = canary.evaluate_registry(
            registry,
            FakeSearch(knowledge, index, [target, duplicate_result]),
            FakeContext(self.evidence_id, [self.evidence_id, duplicate_id]),
        )
        reasons = {item["reason"] for item in result["failures"]}
        self.assertIn(
            "top_k_content_cluster_duplicate_limit_exceeded",
            reasons,
        )
        self.assertIn(
            "packet_content_cluster_duplicate_limit_exceeded",
            reasons,
        )

    def test_registry_rejects_any_semantic_gold_claim(self):
        registry = self.generated_registry()
        registry["semantic_gold"] = True
        with self.assertRaisesRegex(ValueError, "cannot claim semantic gold"):
            canary.validate_registry(registry)


if __name__ == "__main__":
    unittest.main()
