#!/usr/bin/env python3
import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD_PATH = ROOT / "scripts" / "build_retrieval_index.py"
EVALUATE_PATH = ROOT / "scripts" / "evaluate_retrieval.py"
SEARCH_PATH = (
    ROOT
    / "skills"
    / "liuhui-badminton-coach"
    / "scripts"
    / "search_knowledge.py"
)
DOCTOR_PATH = (
    ROOT
    / "skills"
    / "liuhui-badminton-coach"
    / "scripts"
    / "doctor.py"
)
ANSWER_PACKET_PATH = (
    ROOT
    / "skills"
    / "liuhui-badminton-coach"
    / "scripts"
    / "answer_packet.py"
)
ANSWER_RETRIEVAL_PLAN_PATH = (
    ROOT
    / "skills"
    / "liuhui-badminton-coach"
    / "scripts"
    / "answer_retrieval_plan.py"
)
RULES_PATH = ROOT / "config" / "retrieval_rules.json"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def timestamp(seconds):
    minutes, remainder = divmod(int(seconds), 60)
    return f"{minutes:02d}:{remainder:02d}"


def transcript_segments():
    groups = [
        "反手握拍拇指顶住拍柄快速变拍隐藏动态短语",
        "杀球贴球发力顶肘打透保持拍面向前",
        "步法启动回动还原衔接保持身体平衡",
    ]
    segments = []
    for index in range(27):
        start = index * 5.0
        end = start + 5.0
        text = f"{groups[index // 9]}第{index % 9 + 1}拍。"
        segments.append(
            {
                "start": start,
                "end": end,
                "timestamp": f"{timestamp(start)}-{timestamp(end)}",
                "text": text,
            }
        )
    return segments


def video(
    video_id,
    source_type,
    segments,
    *,
    title="教学片段",
    retrieval_cohort="stable_baseline",
):
    return {
        "video_id": video_id,
        "evidence_id": video_id,
        "source_type": source_type,
        "retrieval_cohort": retrieval_cohort,
        "canonical_url": f"https://example.test/{video_id}",
        "parent_source_id": None,
        "clip_start_seconds": None,
        "clip_end_seconds": None,
        "title": title,
        "retrieval_title": title,
        "url": f"https://example.test/{video_id}",
        "category": "测试",
        "duration_seconds": (
            segments[-1]["end"] if segments else 0.0
        ),
        "processing_status": "ready",
        "confidence": "medium",
        "teaching_note": {},
        "transcript_segments": copy.deepcopy(segments),
    }


class ChunkRetrievalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = load_module("chunk_build_tested", BUILD_PATH)
        cls.evaluate = load_module("chunk_evaluate_tested", EVALUATE_PATH)
        cls.search = load_module("chunk_search_tested", SEARCH_PATH)
        cls.doctor = load_module("chunk_doctor_tested", DOCTOR_PATH)
        cls.answer_packet = load_module(
            "chunk_answer_packet_tested",
            ANSWER_PACKET_PATH,
        )
        cls.answer_retrieval_plan = load_module(
            "chunk_answer_retrieval_plan_tested",
            ANSWER_RETRIEVAL_PLAN_PATH,
        )
        cls.rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
        long_segments = transcript_segments()
        cls.knowledge = {
            "updated_at": "2026-07-28T00:00:00Z",
            "videos": [
                video("douyin:fixture", "douyin_video", long_segments),
                video("bilibili:one", "bilibili_video", long_segments),
                video("bilibili:two", "bilibili_video", long_segments),
            ],
        }
        cls.topic_index = {"categories": []}
        cls.index = cls.build.build_index(
            cls.knowledge,
            cls.topic_index,
            cls.rules,
        )

    def test_ranges_are_deterministic_gap_free_and_in_envelope(self):
        segments = transcript_segments()[:20]
        first = self.build.deterministic_chunk_ranges(segments)
        second = self.build.deterministic_chunk_ranges(copy.deepcopy(segments))
        self.assertEqual(first, second)
        self.assertEqual(first[0][0], 0)
        self.assertEqual(first[-1][1], len(segments))
        self.assertTrue(
            all(left[1] == right[0] for left, right in zip(first, first[1:]))
        )
        durations = [
            self.build.chunk_duration(segments, start, end)
            for start, end in first
        ]
        self.assertTrue(all(25.0 <= value <= 75.0 for value in durations))

    def test_ranges_avoid_overshooting_maximum_when_a_valid_cut_exists(self):
        segments = [
            {
                "start": index * 40.0,
                "end": (index + 1) * 40.0,
                "text": str(index),
            }
            for index in range(3)
        ]
        ranges = self.build.deterministic_chunk_ranges(segments)
        self.assertEqual(ranges, [(0, 1), (1, 2), (2, 3)])
        self.assertTrue(
            all(
                self.build.chunk_duration(segments, start, end) <= 75.0
                for start, end in ranges
            )
        )

    def test_build_is_reproducible_and_does_not_duplicate_legacy_bilibili_text(self):
        rebuilt = self.build.build_index(
            copy.deepcopy(self.knowledge),
            copy.deepcopy(self.topic_index),
            copy.deepcopy(self.rules),
        )
        self.assertEqual(
            json.dumps(self.index, ensure_ascii=False, sort_keys=True),
            json.dumps(rebuilt, ensure_ascii=False, sort_keys=True),
        )
        records = {
            record["video_id"]: record for record in self.index["videos"]
        }
        self.assertGreater(
            records["douyin:fixture"]["field_lengths"]["transcript"],
            0,
        )
        self.assertEqual(
            records["bilibili:one"]["field_lengths"]["transcript"],
            0,
        )
        self.assertEqual(
            records["bilibili:one"]["field_term_frequencies"]["transcript"],
            {},
        )

    def test_unrelated_bilibili_growth_does_not_shift_legacy_transcript_idf(self):
        target_segments = transcript_segments()
        for segment in target_segments:
            segment["text"] = "反手握拍快速变拍。"
        unrelated_segments = transcript_segments()
        for segment in unrelated_segments:
            segment["text"] = "完全无关的体能训练说明。"
        base_knowledge = {
            "updated_at": "2026-07-28T00:00:00Z",
            "videos": [
                video(
                    "douyin:target",
                    "douyin_video",
                    target_segments,
                )
            ],
        }
        expanded_knowledge = copy.deepcopy(base_knowledge)
        expanded_knowledge["videos"].extend(
            video(
                f"bilibili:unrelated:{index}",
                "bilibili_video",
                unrelated_segments,
                retrieval_cohort="automatic_expansion",
            )
            for index in range(12)
        )
        base_index = self.build.build_index(
            base_knowledge,
            self.topic_index,
            self.rules,
        )
        expanded_index = self.build.build_index(
            expanded_knowledge,
            self.topic_index,
            self.rules,
        )
        base_score, _, _ = self.search.bm25_record_fields(
            base_index["videos"][0],
            {"反手握拍": 1.0},
            base_index,
            self.rules,
        )
        expanded_score, _, _ = self.search.bm25_record_fields(
            expanded_index["videos"][0],
            {"反手握拍": 1.0},
            expanded_index,
            self.rules,
        )
        self.assertAlmostEqual(base_score, expanded_score, places=8)
        self.assertEqual(
            expanded_index["field_document_counts"]["transcript"],
            1,
        )
        self.assertEqual(
            expanded_index["field_term_document_frequency"]["transcript"][
                "反手握拍"
            ],
            1,
        )

    def test_automatic_growth_does_not_shift_stable_chunk_scores_or_clusters(self):
        stable = video(
            "bilibili:stable",
            "bilibili_video",
            transcript_segments(),
            title="反手握拍教学",
        )
        base_knowledge = {
            "updated_at": "2026-07-28T00:00:00Z",
            "videos": [stable],
        }
        expanded_knowledge = copy.deepcopy(base_knowledge)
        for index in range(12):
            segments = [
                {
                    "start": item * 5.0,
                    "end": (item + 1) * 5.0,
                    "timestamp": (
                        f"{timestamp(item * 5.0)}-"
                        f"{timestamp((item + 1) * 5.0)}"
                    ),
                    "text": (
                        f"反手握拍扩容样本{index}，"
                        f"独立训练主题{index}-{item}。"
                    ),
                }
                for item in range(9)
            ]
            expanded_knowledge["videos"].append(
                video(
                    f"bilibili:auto:{index}",
                    "bilibili_video",
                    segments,
                    title=f"反手握拍扩容样本{index}",
                    retrieval_cohort="automatic_expansion",
                )
            )

        base_index = self.build.build_index(
            base_knowledge,
            self.topic_index,
            self.rules,
        )
        expanded_index = self.build.build_index(
            expanded_knowledge,
            self.topic_index,
            self.rules,
        )
        expansion = {"term_weights": {"反手握拍": 1.0}}
        query_grams = self.search.hashed_ngrams(
            "反手握拍",
            base_index["transcript_ngram_sizes"],
        )
        base_match = self.search._retrieval_ranking.chunk_query_scores(
            base_index,
            expansion,
            query_grams,
            self.rules,
        )["bilibili:stable"]
        expanded_match = self.search._retrieval_ranking.chunk_query_scores(
            expanded_index,
            expansion,
            query_grams,
            self.rules,
        )["bilibili:stable"]

        self.assertEqual(
            base_match["matched_cluster_ids"],
            expanded_match["matched_cluster_ids"],
        )
        self.assertAlmostEqual(
            base_match["bm25_score"],
            expanded_match["bm25_score"],
            places=8,
        )
        self.assertAlmostEqual(
            base_match["ngram_score"],
            expanded_match["ngram_score"],
            places=8,
        )
        self.assertEqual(
            base_index["chunk_index"][
                "stable_term_cluster_document_frequency"
            ],
            expanded_index["chunk_index"][
                "stable_term_cluster_document_frequency"
            ],
        )
        self.assertGreater(
            expanded_index["chunk_index"][
                "term_cluster_document_frequency"
            ]["反手握拍"],
            base_index["chunk_index"][
                "term_cluster_document_frequency"
            ]["反手握拍"],
        )

    def test_automatic_titles_are_binary_and_chunk_notes_are_not_double_indexed(self):
        repeated_title = "杀球杀球杀球教学"
        stable = video(
            "bilibili:stable-title",
            "bilibili_video",
            transcript_segments(),
            title=repeated_title,
        )
        stable["teaching_note"] = {"summary": "杀球发力教学"}
        automatic = video(
            "bilibili:auto-title",
            "bilibili_video",
            transcript_segments(),
            title=repeated_title,
            retrieval_cohort="automatic_expansion",
        )
        automatic["teaching_note"] = {"summary": "杀球发力教学"}
        index = self.build.build_index(
            {
                "updated_at": "2026-07-28T00:00:00Z",
                "videos": [stable, automatic],
            },
            self.topic_index,
            self.rules,
        )
        records = {record["video_id"]: record for record in index["videos"]}
        self.assertEqual(
            records["bilibili:stable-title"][
                "field_term_frequencies"
            ]["title"]["杀球"],
            3,
        )
        self.assertEqual(
            records["bilibili:auto-title"][
                "field_term_frequencies"
            ]["title"]["杀球"],
            1,
        )
        for record in records.values():
            self.assertEqual(record["field_lengths"]["teaching_note"], 0)
            self.assertEqual(
                record["field_term_frequencies"]["teaching_note"],
                {},
            )

    def test_chunk_postings_use_cluster_document_frequency(self):
        chunk_index = self.index["chunk_index"]
        self.assertEqual(chunk_index["chunk_count"], 9)
        self.assertEqual(chunk_index["cluster_count"], 3)
        postings = chunk_index["term_postings"]["反手握拍"]
        self.assertEqual(len(postings), 3)
        self.assertEqual(
            chunk_index["term_cluster_document_frequency"]["反手握拍"],
            1,
        )
        self.assertEqual(
            {
                self.index["videos"][chunk["video_index"]]["source_type"]
                for chunk in chunk_index["chunks"]
            },
            {"bilibili_video", "douyin_video"},
        )

    def test_near_duplicate_cluster_recall_uses_guaranteed_simhash_banding(self):
        base = "反手握拍快速变拍拇指顶住拍柄然后保持拍面稳定" * 4
        texts = [base, base + "啊"]
        chunks = []
        for index, text in enumerate(texts):
            normalized = self.build.normalize(text)
            shingles = self.build.text_shingles(normalized)
            fingerprint = self.build.simhash64(shingles)
            chunks.append(
                {
                    "chunk_id": f"fixture:{index}",
                    "video_index": index,
                    "normalized_length": len(normalized),
                    "_normalized_text": normalized,
                    "_shingles": shingles,
                    "_simhash": fingerprint,
                }
            )
        self.assertLessEqual(
            self.build.hamming_distance(
                chunks[0]["_simhash"],
                chunks[1]["_simhash"],
            ),
            self.build.CHUNK_SIMHASH_MAX_DISTANCE,
        )
        self.assertEqual(self.build.assign_content_clusters(chunks), 1)
        self.assertEqual(chunks[0]["cluster_id"], chunks[1]["cluster_id"])

    def test_clustering_does_not_single_link_drift_through_similarity_chain(self):
        shingle_sets = [
            set(range(100)),
            set(range(88)) | set(range(100, 112)),
            set(range(76)) | set(range(100, 124)),
        ]
        chunks = [
            {
                "chunk_id": f"chain:{index}",
                "video_index": index,
                "normalized_length": 100,
                "_normalized_text": f"chain-{index}",
                "_shingles": shingles,
                "_simhash": 0,
            }
            for index, shingles in enumerate(shingle_sets)
        ]
        self.assertGreaterEqual(
            self.build.shingle_jaccard(
                shingle_sets[0],
                shingle_sets[1],
            ),
            self.build.CHUNK_CLUSTER_MIN_JACCARD,
        )
        self.assertGreaterEqual(
            self.build.shingle_jaccard(
                shingle_sets[1],
                shingle_sets[2],
            ),
            self.build.CHUNK_CLUSTER_MIN_JACCARD,
        )
        self.assertLess(
            self.build.shingle_jaccard(
                shingle_sets[0],
                shingle_sets[2],
            ),
            self.build.CHUNK_CLUSTER_MIN_JACCARD,
        )
        self.assertEqual(self.build.assign_content_clusters(chunks), 2)
        self.assertEqual(chunks[0]["cluster_id"], chunks[1]["cluster_id"])
        self.assertNotEqual(chunks[0]["cluster_id"], chunks[2]["cluster_id"])

    def test_runtime_aggregates_best_and_second_distinct_cluster(self):
        query = "反手握拍杀球"
        expansion = {
            "term_weights": {
                "反手握拍": 2.0,
                "杀球": 1.0,
            }
        }
        query_grams = self.search.hashed_ngrams(
            query,
            self.index["transcript_ngram_sizes"],
        )
        scores = self.search._retrieval_ranking.chunk_query_scores(
            self.index,
            expansion,
            query_grams,
            self.rules,
        )
        match = scores["bilibili:one"]
        self.assertEqual(len(match["matched_chunk_ids"]), 2)
        self.assertEqual(len(set(match["matched_cluster_ids"])), 2)
        self.assertIn("#t000000000-000045000", match["best_chunk_id"])
        self.assertEqual(len(match["chunk_hints"]), 2)

    def test_rank_candidates_projects_chunk_mode_and_legacy_fallback(self):
        ranked, _ = self.search.rank_candidates(
            "反手握拍杀球",
            self.knowledge,
            self.index,
            self.rules,
        )
        by_id = {candidate["video_id"]: candidate for candidate in ranked}
        self.assertEqual(
            by_id["bilibili:one"]["transcript_retrieval"]["mode"],
            "chunk_first",
        )
        self.assertIn(
            "chunk_transcript_lexicon",
            by_id["bilibili:one"]["retrieval_channels"],
        )
        self.assertEqual(
            by_id["douyin:fixture"]["transcript_retrieval"]["mode"],
            "legacy_video",
        )
        self.assertEqual(
            by_id["douyin:fixture"]["transcript_retrieval"][
                "matched_cluster_ids"
            ][0],
            by_id["bilibili:one"]["transcript_retrieval"][
                "matched_cluster_ids"
            ][0],
        )

        original_index_allowlist = self.build.CHUNK_INDEX_SOURCE_ALLOWLIST
        original_first_allowlist = self.build.CHUNK_FIRST_SOURCE_ALLOWLIST
        self.build.CHUNK_INDEX_SOURCE_ALLOWLIST = set()
        self.build.CHUNK_FIRST_SOURCE_ALLOWLIST = set()
        try:
            legacy_index = self.build.build_index(
                self.knowledge,
                self.topic_index,
                self.rules,
            )
        finally:
            self.build.CHUNK_INDEX_SOURCE_ALLOWLIST = (
                original_index_allowlist
            )
            self.build.CHUNK_FIRST_SOURCE_ALLOWLIST = (
                original_first_allowlist
            )
        legacy_ranked, _ = self.search.rank_candidates(
            "反手握拍杀球",
            self.knowledge,
            legacy_index,
            self.rules,
        )
        legacy_by_id = {
            candidate["video_id"]: candidate for candidate in legacy_ranked
        }
        self.assertEqual(
            legacy_by_id["bilibili:one"]["transcript_retrieval"]["mode"],
            "legacy_video",
        )
        self.assertIn(
            "full_transcript_lexicon",
            legacy_by_id["bilibili:one"]["retrieval_channels"],
        )

    def test_result_and_claim_candidate_caps_keep_one_cross_source_cluster(self):
        ranked, _ = self.search.rank_candidates(
            "反手握拍杀球",
            self.knowledge,
            self.index,
            self.rules,
        )
        by_id = {candidate["video_id"]: candidate for candidate in ranked}
        same_cluster = [
            by_id["douyin:fixture"],
            by_id["bilibili:one"],
            by_id["bilibili:two"],
        ]
        kept, suppressed = self.search.cap_content_clusters(same_cluster)
        self.assertEqual(
            [candidate["video_id"] for candidate in kept],
            ["douyin:fixture"],
        )
        self.assertEqual(len(suppressed), 2)

        entries = [
            {"video_id": candidate["video_id"], "candidate": candidate}
            for candidate in same_cluster
        ]
        claim_kept, claim_suppressed = self.search.cap_content_clusters(
            entries,
            candidate_getter=lambda entry: entry["candidate"],
        )
        self.assertEqual(
            [entry["video_id"] for entry in claim_kept],
            ["douyin:fixture"],
        )
        self.assertEqual(len(claim_suppressed), 2)
        self.assertEqual(
            self.search.cap_content_clusters(same_cluster, limit=0),
            ([], []),
        )

    def test_cluster_cap_keeps_candidate_with_unique_secondary_cluster(self):
        candidates = [
            {
                "video_id": "shared-a",
                "transcript_retrieval": {
                    "matched_cluster_ids": ["CC-shared", "CC-a"],
                },
            },
            {
                "video_id": "shared-b",
                "transcript_retrieval": {
                    "matched_cluster_ids": ["CC-shared", "CC-b"],
                },
            },
            {
                "video_id": "fully-covered",
                "transcript_retrieval": {
                    "matched_cluster_ids": ["CC-shared", "CC-a"],
                },
            },
        ]
        kept, suppressed = self.search.cap_content_clusters(candidates)
        self.assertEqual(
            [candidate["video_id"] for candidate in kept],
            ["shared-a", "shared-b"],
        )
        self.assertEqual(
            [item["item"]["video_id"] for item in suppressed],
            ["fully-covered"],
        )

    def test_packet_carries_and_enforces_primary_query_cluster(self):
        compact = self.answer_packet.compact_video(
            {
                "label": "V1",
                "video_id": "bilibili:one",
                "evidence_id": "bilibili:one",
                "transcript_retrieval": {
                    "matched_cluster_ids": ["CC-primary", "CC-support"],
                },
            },
            [],
            False,
        )
        self.assertEqual(
            compact["content_cluster_ids"],
            ["CC-primary", "CC-support"],
        )
        with self.assertRaisesRegex(
            ValueError,
            "duplicate query-relevant content cluster",
        ):
            self.answer_packet.validate_answer_packet(
                {
                    "schema_version": (
                        self.answer_packet.ANSWER_PACKET_SCHEMA_VERSION
                    ),
                    "packet_type": "liuhui_badminton_answer_packet",
                    "selected_videos": [
                        {"content_cluster_ids": ["CC-same", "CC-one"]},
                        {"content_cluster_ids": ["CC-same", "CC-one"]},
                    ],
                },
                {},
            )

    def test_packet_budget_prunes_only_low_priority_fallback_windows(self):
        window_ids = [f"W{index}" for index in range(8)]
        packet = {
            "answer_plan": {"mode": "claim_evidence_fallback"},
            "selected_videos": [
                {"label": "V1", "window_ids": list(window_ids[:4])},
                {"label": "V2", "window_ids": list(window_ids[4:])},
            ],
            "evidence_windows": {
                window_id: {
                    "label": "V1" if index < 4 else "V2",
                    "timestamp": f"00:{index:02d}-00:{index + 1:02d}",
                    "text": "长证据窗口" * 300,
                }
                for index, window_id in enumerate(window_ids)
            },
        }
        compact = self.answer_packet.enforce_answer_packet_budget(
            copy.deepcopy(packet)
        )
        self.assertLessEqual(
            self.answer_packet.encoded_packet_size(compact),
            self.answer_packet.ANSWER_PACKET_TARGET_BYTES,
        )
        self.assertTrue(
            all(
                video["window_ids"]
                for video in compact["selected_videos"]
            )
        )
        retained = {
            window_id
            for video in compact["selected_videos"]
            for window_id in video["window_ids"]
        }
        self.assertEqual(
            retained,
            set(compact["evidence_windows"]),
        )

    def test_packet_budget_fails_closed_when_required_content_exceeds_hard_cap(self):
        packet = {
            "answer_plan": {"mode": "reviewed_atoms_closed"},
            "selected_videos": [],
            "evidence_windows": {},
            "required_claim_contract": "不可删除" * 6000,
        }
        with self.assertRaisesRegex(ValueError, "hard size budget"):
            self.answer_packet.enforce_answer_packet_budget(packet)

    def test_dynamic_term_scan_skips_chunk_indexed_long_transcripts(self):
        term = "隐藏动态短语"
        _, unrestricted = self.search.dynamic_term_statistics(
            self.knowledge,
            {term},
        )
        _, chunk_scoped = self.search.dynamic_term_statistics(
            self.knowledge,
            {term},
            transcript_excluded_video_ids={
                "bilibili:one",
                "bilibili:two",
            },
        )
        self.assertIn("bilibili:one", unrestricted)
        self.assertNotIn("bilibili:one", chunk_scoped)
        self.assertNotIn("bilibili:two", chunk_scoped)

    def test_dynamic_term_document_frequency_is_field_specific(self):
        term = "动态稀有术语"
        first = video(
            "douyin:title",
            "douyin_video",
            transcript_segments(),
            title=f"{term}标题",
        )
        second = video(
            "douyin:note",
            "douyin_video",
            transcript_segments(),
        )
        second["teaching_note"] = {"summary": f"{term}讲解"}
        global_df, _, field_df = self.search.dynamic_term_statistics(
            {"videos": [first, second]},
            {term},
            include_field_document_frequency=True,
        )
        self.assertEqual(global_df[term], 2)
        self.assertEqual(field_df["title"][term], 1)
        self.assertEqual(field_df["teaching_note"][term], 1)
        self.assertEqual(field_df["transcript"][term], 0)
        retrieval_index = {
            "indexable_video_count": 2,
            "term_document_frequency": {},
            "field_document_counts": {
                "title": 2,
                "teaching_note": 2,
                "transcript": 2,
            },
            "field_term_document_frequency": {
                "title": {},
                "teaching_note": {},
                "transcript": {},
            },
            "average_field_lengths": {
                "title": 10,
                "teaching_note": 10,
                "transcript": 10,
            },
        }
        record = {
            "field_lengths": {
                "title": 10,
                "teaching_note": 0,
                "transcript": 0,
            },
            "field_term_frequencies": {
                "title": {},
                "teaching_note": {},
                "transcript": {},
            },
        }
        union_score, _, _ = self.search.bm25_record_fields(
            record,
            {term: 1.0},
            retrieval_index,
            self.rules,
            dynamic_document_frequency=global_df,
            dynamic_field_frequencies={"title": {term: 1}},
        )
        field_score, _, _ = self.search.bm25_record_fields(
            record,
            {term: 1.0},
            retrieval_index,
            self.rules,
            dynamic_document_frequency=global_df,
            dynamic_field_document_frequency=field_df,
            dynamic_field_frequencies={"title": {term: 1}},
        )
        self.assertGreater(field_score, union_score)

    def test_prepared_index_cache_retains_and_checks_owner_identity(self):
        first = {"videos": [{"video_id": "first"}]}
        second = {"videos": [{"video_id": "second"}]}
        first_prepared = self.search.prepared_retrieval_index(first)
        cache_entry = self.search._PREPARED_RETRIEVAL_CACHE[id(first)]
        self.assertIs(cache_entry[0], first)
        self.assertIs(cache_entry[1], first_prepared)
        second_prepared = self.search.prepared_retrieval_index(second)
        self.assertEqual(second_prepared["video_ids"], ["second"])
        self.assertIs(
            self.search._PREPARED_RETRIEVAL_CACHE[id(second)][0],
            second,
        )

    def test_chunk_hints_bound_transcript_window_search(self):
        target = self.knowledge["videos"][1]
        expansion = {"term_weights": {"步法": 1.0, "启动": 1.0}}
        unrestricted = self.search.rank_transcript_evidence(
            target,
            "步法启动",
            expansion,
            limit=2,
        )
        restricted = self.search.rank_transcript_evidence(
            target,
            "步法启动",
            expansion,
            limit=2,
            chunk_hints=[
                {
                    "start_segment": 0,
                    "end_segment": 9,
                }
            ],
        )
        self.assertTrue(unrestricted)
        self.assertEqual(restricted, [])

    def test_chunk_hints_fallback_recovers_unmet_original_query_term(self):
        target = self.knowledge["videos"][1]
        windows = self.search.rank_transcript_evidence(
            target,
            "反手握拍杀球步法启动",
            {
                "original_terms": [
                    "反手握拍",
                    "杀球",
                    "步法",
                    "启动",
                ],
                "term_weights": {
                    "反手握拍": 1.0,
                    "杀球": 1.0,
                    "步法": 1.0,
                    "启动": 1.0,
                },
            },
            limit=6,
            chunk_hints=[
                {"start_segment": 0, "end_segment": 9},
                {"start_segment": 9, "end_segment": 18},
            ],
        )
        text = "".join(window["text"] for window in windows)
        self.assertIn("反手握拍", text)
        self.assertIn("杀球", text)
        self.assertIn("步法启动", text)

    def test_split_query_candidate_merge_preserves_distinct_chunk_hints(self):
        def candidate(chunk_id, cluster_id, start, rank_score):
            return {
                "video_id": "bilibili:multi",
                "relevance_tier": "direct",
                "within_review_budget": True,
                "matched_original_terms": [],
                "matched_equivalent_terms": [],
                "matched_query_concepts": [],
                "matched_structured_query_concepts": [],
                "score": rank_score,
                "score_breakdown": {
                    "effective_ranking_score": rank_score,
                },
                "transcript_retrieval": {
                    "mode": "chunk_first",
                    "best_chunk_id": chunk_id,
                    "matched_chunk_ids": [chunk_id],
                    "matched_cluster_ids": [cluster_id],
                    "chunk_hints": [
                        {
                            "chunk_id": chunk_id,
                            "cluster_id": cluster_id,
                            "start_segment": start,
                            "end_segment": start + 9,
                        }
                    ],
                },
            }

        payloads = [
            {
                "candidate_manifest": [
                    candidate("chunk:grip", "CC-grip", 0, 10.0)
                ],
                "query_expansion": {"matched_synonym_groups": []},
            },
            {
                "candidate_manifest": [
                    candidate("chunk:footwork", "CC-footwork", 18, 9.0)
                ],
                "query_expansion": {"matched_synonym_groups": []},
            },
        ]
        merged = self.answer_retrieval_plan.merge_candidates(
            payloads,
            ["握拍", "步法"],
        )
        retrieval = merged["bilibili:multi"]["candidate"][
            "transcript_retrieval"
        ]
        self.assertEqual(
            retrieval["matched_chunk_ids"],
            ["chunk:grip", "chunk:footwork"],
        )
        self.assertEqual(
            [hint["start_segment"] for hint in retrieval["chunk_hints"]],
            [0, 18],
        )
        windows = self.search.rank_transcript_evidence(
            self.knowledge["videos"][1],
            "反手握拍和步法启动",
            {
                "term_weights": {
                    "反手握拍": 1.0,
                    "步法": 1.0,
                    "启动": 1.0,
                }
            },
            limit=6,
            chunk_hints=retrieval["chunk_hints"],
        )
        evidence_text = "".join(window["text"] for window in windows)
        self.assertIn("反手握拍", evidence_text)
        self.assertIn("步法启动", evidence_text)

    def test_projection_remaps_chunks_and_recomputes_cluster_df(self):
        projected = self.evaluate.project_retrieval_index(
            self.index,
            {"douyin:fixture", "bilibili:one"},
        )
        chunk_index = projected["chunk_index"]
        self.assertEqual(chunk_index["chunk_count"], 6)
        self.assertEqual(chunk_index["cluster_count"], 3)
        self.assertEqual(
            {chunk["video_index"] for chunk in chunk_index["chunks"]},
            {0, 1},
        )
        self.assertEqual(
            chunk_index["term_cluster_document_frequency"]["反手握拍"],
            1,
        )

    def test_doctor_validates_integrity_and_reports_tampering(self):
        self.assertEqual(
            self.doctor.validate_chunk_index(self.knowledge, self.index),
            [],
        )
        tampered = copy.deepcopy(self.index)
        tampered["chunk_index"]["chunks"][0]["text_sha256"] = "bad"
        tampered["chunk_index"]["chunks"][0]["start_ms"] = None
        errors = self.doctor.validate_chunk_index(self.knowledge, tampered)
        self.assertIn("chunk[0].text_sha256", errors)
        self.assertIn("chunk[0].time_range", errors)


if __name__ == "__main__":
    unittest.main()
