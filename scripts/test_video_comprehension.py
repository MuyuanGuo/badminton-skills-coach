#!/usr/bin/env python3
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "evaluate_video_comprehension.py"


def load_module():
    spec = importlib.util.spec_from_file_location("video_comprehension_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VideoComprehensionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def transcript_video(self, transcript_file):
        return {
            "video_id": "7000000000000000001",
            "processing_status": "ready",
            "confidence": "medium",
            "transcript_file": transcript_file,
            "transcript_segments": [
                {
                    "start": 1.0,
                    "end": 3.0,
                    "timestamp": "00:01-00:03",
                    "text": "先准备最快的回球线路",
                }
            ],
            "quality": {
                "transcript": {"passed": True},
                "automatic_evidence": {"passed": True},
            },
            "teaching_note": {
                "topic": "接发准备",
                "key_evidence": [
                    {"timestamp": "00:01-00:03", "text": "先准备最快的回球线路"}
                ],
                "error_evidence": [],
                "action_cues": [],
            },
        }

    def test_transcript_evidence_must_roundtrip_to_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transcript_path = root / "transcript.json"
            transcript_path.write_text(
                json.dumps(
                    {
                        "full_text": "接发时先准备最快的回球线路，再处理慢线路。",
                        "segments": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            audit = self.module.audit_video_content(
                self.transcript_video("transcript.json"),
                root=root,
                indexed_video_ids={"7000000000000000001"},
            )
        self.assertEqual(audit["source_kind"], "automatic_transcript")
        self.assertEqual(audit["raw_transcript_status"], "verified")
        self.assertEqual(audit["failures"], [])

    def test_missing_raw_transcript_is_optional_only_for_portable_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            portable = self.module.audit_video_content(
                self.transcript_video("transcript.json"),
                root=root,
                indexed_video_ids={"7000000000000000001"},
            )
            strict = self.module.audit_video_content(
                self.transcript_video("transcript.json"),
                root=root,
                indexed_video_ids={"7000000000000000001"},
                require_raw_transcript=True,
            )
        self.assertEqual(portable["raw_transcript_status"], "unavailable")
        self.assertEqual(portable["failures"], [])
        self.assertIn("missing_transcript_file", strict["failures"])
        self.assertNotIn("empty_transcript", strict["failures"])

    def test_source_scoped_raw_gate_ignores_unmodified_source_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = self.transcript_video("transcript.json")
            video["source_type"] = "bilibili_video"
            audit = self.module.audit_video_content(
                video,
                root=root,
                indexed_video_ids={video["video_id"]},
                require_raw_transcript=True,
                required_raw_transcript_sources={"douyin_video"},
                bilibili_transcript_candidates={},
            )
        self.assertEqual(audit["raw_transcript_status"], "unavailable")
        self.assertNotIn("missing_transcript_file", audit["failures"])

    def test_bilibili_raw_transcript_prefers_readable_external_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            preferred = root / "external" / "BV1External.json"
            fallback = root / "repository" / "BV1External.json"
            preferred.parent.mkdir()
            fallback.parent.mkdir()
            preferred.write_text(
                json.dumps(
                    {
                        "full_text": (
                            "接发时先准备最快的回球线路，再处理慢线路。"
                        )
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            fallback.write_text("placeholder", encoding="utf-8")
            video = self.transcript_video(
                "data/transcripts/bilibili/BV1External.json"
            )
            video.update(
                {
                    "video_id": "bilibili:BV1External",
                    "source_video_id": "BV1External",
                    "source_type": "bilibili_video",
                }
            )
            with mock.patch.object(
                self.module,
                "load_json",
                wraps=self.module.load_json,
            ) as load_json:
                audit = self.module.audit_video_content(
                    video,
                    root=root,
                    indexed_video_ids={"bilibili:BV1External"},
                    require_raw_transcript=True,
                    bilibili_transcript_candidates={
                        "BV1External": [preferred, fallback]
                    },
                )
            loaded_paths = [call.args[0] for call in load_json.call_args_list]
        self.assertEqual(audit["raw_transcript_status"], "verified")
        self.assertEqual(audit["failures"], [])
        self.assertIn(preferred, loaded_paths)
        self.assertNotIn(fallback, loaded_paths)

    def test_bilibili_redacted_evidence_roundtrips_through_safe_transcript(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transcript_path = root / "BV1Redacted.json"
            transcript_path.write_text(
                json.dumps(
                    {
                        "full_text": "关注我。先准备最快的回球线路",
                        "segments": [
                            {
                                "start": 1.0,
                                "end": 3.0,
                                "text": "关注我。先准备最快的回球线路",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            video = self.transcript_video(
                "data/transcripts/bilibili/BV1Redacted.json"
            )
            video.update(
                {
                    "video_id": "bilibili:BV1Redacted",
                    "source_video_id": "BV1Redacted",
                    "source_type": "bilibili_video",
                    "title": "接发准备教学",
                }
            )
            audit = self.module.audit_video_content(
                video,
                root=root,
                indexed_video_ids={"bilibili:BV1Redacted"},
                require_raw_transcript=True,
                bilibili_transcript_candidates={
                    "BV1Redacted": [transcript_path]
                },
            )

        self.assertEqual(audit["raw_transcript_status"], "verified")
        self.assertEqual(audit["failures"], [])

    def test_bilibili_runtime_transcript_must_roundtrip_after_redaction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transcript_path = root / "BV1RedactedMismatch.json"
            transcript_path.write_text(
                json.dumps(
                    {
                        "full_text": "关注我。先准备最快的回球线路",
                        "segments": [
                            {
                                "start": 1.0,
                                "end": 3.0,
                                "text": "关注我。先准备最快的回球线路",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            video = self.transcript_video(
                "data/transcripts/bilibili/BV1RedactedMismatch.json"
            )
            video.update(
                {
                    "video_id": "bilibili:BV1RedactedMismatch",
                    "source_video_id": "BV1RedactedMismatch",
                    "source_type": "bilibili_video",
                    "title": "接发准备教学",
                }
            )
            video["transcript_segments"][0]["text"] = "已被错误改写的文本"
            audit = self.module.audit_video_content(
                video,
                root=root,
                indexed_video_ids={
                    "bilibili:BV1RedactedMismatch"
                },
                require_raw_transcript=True,
                bilibili_transcript_candidates={
                    "BV1RedactedMismatch": [transcript_path]
                },
            )

        self.assertIn(
            "runtime_transcript_raw_roundtrip_mismatch",
            audit["failures"],
        )

    def test_douyin_raw_transcript_uses_external_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "external"
            transcript_path = cache / "batch-001" / "source.json"
            transcript_path.parent.mkdir(parents=True)
            transcript_path.write_text(
                json.dumps(
                    {
                        "full_text": (
                            "接发时先准备最快的回球线路，再处理慢线路。"
                        )
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            video = self.transcript_video(
                "data/transcripts/douyin/batch-001/source.json"
            )
            video["source_type"] = "douyin_video"
            audit = self.module.audit_video_content(
                video,
                root=root,
                indexed_video_ids={video["video_id"]},
                require_raw_transcript=True,
                douyin_transcript_root=cache,
            )

        self.assertEqual(audit["raw_transcript_status"], "verified")
        self.assertEqual(audit["failures"], [])

    def test_bilibili_raw_transcript_falls_back_after_dataless_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            preferred = root / "external" / "BV1Fallback.json"
            fallback = root / "repository" / "BV1Fallback.json"
            preferred.parent.mkdir()
            fallback.parent.mkdir()
            preferred.write_text("placeholder", encoding="utf-8")
            fallback.write_text(
                json.dumps(
                    {
                        "full_text": (
                            "接发时先准备最快的回球线路，再处理慢线路。"
                        )
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            video = self.transcript_video(
                "data/transcripts/bilibili/BV1Fallback.json"
            )
            video.update(
                {
                    "video_id": "bilibili:BV1Fallback",
                    "source_video_id": "BV1Fallback",
                    "source_type": "bilibili_video",
                }
            )
            original_open = Path.open

            def open_with_eviction(path, *args, **kwargs):
                if path == preferred:
                    raise OSError(60, "Operation timed out")
                return original_open(path, *args, **kwargs)

            with mock.patch.object(Path, "open", open_with_eviction):
                audit = self.module.audit_video_content(
                    video,
                    root=root,
                    indexed_video_ids={"bilibili:BV1Fallback"},
                    require_raw_transcript=True,
                    bilibili_transcript_candidates={
                        "BV1Fallback": [preferred, fallback]
                    },
                )
        self.assertEqual(audit["raw_transcript_status"], "verified")
        self.assertEqual(audit["failures"], [])

    def test_transcript_mismatch_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "transcript.json").write_text(
                json.dumps({"full_text": "这段转写讲的是其他内容。"}, ensure_ascii=False),
                encoding="utf-8",
            )
            audit = self.module.audit_video_content(
                self.transcript_video("transcript.json"),
                root=root,
                indexed_video_ids={"7000000000000000001"},
            )
        self.assertTrue(
            any(item.startswith("evidence_not_in_transcript") for item in audit["failures"])
        )

    def test_visual_demo_requires_review_summary_and_evidence(self):
        video = {
            "video_id": "7000000000000000002",
            "processing_status": "ready",
            "confidence": "visual_reviewed",
            "teaching_note": {
                "topic": "正手握拍",
                "review_summary": "纯动作示范，展示正手握拍手型。",
                "visual_review_evidence": [
                    {
                        "timestamp": "visual_review_no_timestamp",
                        "text": "纯动作示范，展示正手握拍手型。",
                    }
                ],
            },
        }
        audit = self.module.audit_video_content(
            video, indexed_video_ids={"7000000000000000002"}
        )
        self.assertEqual(audit["source_kind"], "visual_review")
        self.assertEqual(audit["failures"], [])
        video["teaching_note"]["visual_review_evidence"] = []
        audit = self.module.audit_video_content(
            video, indexed_video_ids={"7000000000000000002"}
        )
        self.assertIn("missing_visual_review_evidence", audit["failures"])

    def test_reviewed_transcript_uses_review_decision_instead_of_auto_gate(self):
        video = self.transcript_video("")
        video["confidence"] = "reviewed_transcript"
        video["quality"]["transcript"]["passed"] = False
        video["quality"]["automatic_evidence"]["passed"] = False
        video["teaching_note"] = {
            "topic": "接发准备",
            "review_summary": "按转写结果确认这是接发准备教学。",
        }
        audit = self.module.audit_video_content(
            video, indexed_video_ids={video["video_id"]}
        )
        self.assertNotIn("transcript_quality_not_passed", audit["failures"])
        self.assertNotIn("automatic_evidence_quality_not_passed", audit["failures"])
        self.assertNotIn("missing_teaching_evidence", audit["failures"])

    def supplemental_video(self):
        return {
            "video_id": "bilibili:BV1Supplemental",
            "evidence_id": "bilibili:BV1Supplemental",
            "source_video_id": "BV1Supplemental",
            "source_type": "bilibili_video",
            "processing_status": "ready",
            "confidence": "supplemental_note_only",
            "answer_eligibility": "supplemental",
            "runtime_evidence_mode": "bounded_note_windows",
            "metadata_title_trust": "limited",
            "transcript_file": (
                "data/transcripts/bilibili/BV1Supplemental.json"
            ),
            "transcript_segments": [],
            "quality": {
                "origin_verification": {"passed": True},
                "source_content_safety": {"passed": True},
                "transcript": {
                    "passed": False,
                    "issues": ["title_has_no_technical_concept"],
                },
                "automatic_evidence": {"passed": True},
            },
            "teaching_note": {
                "topic": "接发准备",
                "key_evidence": [
                    {
                        "timestamp": "00:01-00:03",
                        "text": "先准备最快的回球线路",
                    }
                ],
                "error_evidence": [],
                "action_cues": [],
            },
        }

    def supplemental_index_record(self, video):
        note_text = self.module.flatten_retrieval_value(
            self.module.searchable_teaching_note(video["teaching_note"])
        )
        return {
            "answer_eligibility": "supplemental",
            "runtime_evidence_mode": "bounded_note_windows",
            "metadata_title_trust": "limited",
            "field_lengths": {
                "title": 0,
                "teaching_note": len(
                    self.module.normalize_index_text(note_text)
                ),
                "transcript": 0,
            },
            "ngram_counts": {
                "title": 0,
                "teaching_note": len(
                    self.module.hashed_ngrams(note_text, [2, 3])
                ),
                "transcript": 0,
            },
        }

    def test_bounded_note_windows_are_audited_as_supplemental_evidence(self):
        video = self.supplemental_video()
        note_text = self.module.flatten_retrieval_value(
            self.module.searchable_teaching_note(video["teaching_note"])
        )
        audit = self.module.audit_video_content(
            video,
            indexed_video_ids={video["video_id"]},
            index_record=self.supplemental_index_record(video),
            indexed_title_ngrams=set(),
            indexed_teaching_note_ngrams=self.module.hashed_ngrams(
                note_text, [2, 3]
            ),
            indexed_transcript_ngrams=set(),
            bilibili_transcript_candidates={},
        )
        self.assertEqual(audit["source_kind"], "bounded_note_windows")
        self.assertEqual(audit["raw_transcript_status"], "unavailable")
        self.assertEqual(audit["failures"], [])

    def test_bounded_note_windows_reject_unbounded_or_unindexed_evidence(self):
        video = self.supplemental_video()
        video["teaching_note"]["key_evidence"][0]["timestamp"] = ""
        index_record = self.supplemental_index_record(video)
        index_record["field_lengths"]["transcript"] = 10
        index_record["ngram_counts"]["transcript"] = 2
        audit = self.module.audit_video_content(
            video,
            indexed_video_ids={video["video_id"]},
            index_record=index_record,
            indexed_title_ngrams=set(),
            indexed_teaching_note_ngrams=set(),
            indexed_transcript_ngrams={"unexpected"},
            bilibili_transcript_candidates={},
        )
        self.assertIn(
            "bounded_note_evidence_missing_timestamp", audit["failures"]
        )
        self.assertIn("bounded_note_contains_transcript_index", audit["failures"])
        self.assertIn("bounded_note_index_mismatch", audit["failures"])

    def test_bounded_note_windows_roundtrip_when_raw_cache_is_present(self):
        with tempfile.TemporaryDirectory() as directory:
            transcript_path = Path(directory) / "BV1Supplemental.json"
            transcript_path.write_text(
                json.dumps(
                    {"full_text": "接发时先准备最快的回球线路。"},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            video = self.supplemental_video()
            audit = self.module.audit_video_content(
                video,
                indexed_video_ids={video["video_id"]},
                bilibili_transcript_candidates={
                    "BV1Supplemental": [transcript_path]
                },
            )
        self.assertEqual(audit["raw_transcript_status"], "verified")
        self.assertEqual(audit["failures"], [])

    def test_runtime_transcript_must_match_retrieval_index(self):
        video = self.transcript_video("")
        transcript = "先准备最快的回球线路"
        sizes = [2, 3]
        record = {
            "transcript_ngrams": sorted(self.module.hashed_ngrams(transcript, sizes)),
            "field_lengths": {
                "transcript": len(self.module.normalize_index_text(transcript))
            },
        }
        audit = self.module.audit_video_content(
            video,
            indexed_video_ids={video["video_id"]},
            index_record=record,
            transcript_ngram_sizes=sizes,
        )
        self.assertNotIn("runtime_transcript_index_mismatch", audit["failures"])
        record["transcript_ngrams"] = []
        audit = self.module.audit_video_content(
            video,
            indexed_video_ids={video["video_id"]},
            index_record=record,
            transcript_ngram_sizes=sizes,
        )
        self.assertIn("runtime_transcript_index_mismatch", audit["failures"])

    def test_chunk_first_transcript_must_match_gap_free_chunk_index(self):
        video = self.transcript_video("")
        video["source_type"] = "bilibili_video"
        video["evidence_id"] = "bilibili:BV1test"
        transcript = "先准备最快的回球线路"
        sizes = [2, 3]
        raw_hash = self.module.hashlib.sha256(
            transcript.encode("utf-8")
        ).hexdigest()
        chunk_id = "bilibili:BV1test#t000001000-000003000"
        record = {
            "field_lengths": {"transcript": 0},
            "transcript_ngrams": [],
        }
        chunk = {
            "chunk_id": chunk_id,
            "start_segment": 0,
            "end_segment": 1,
            "start_ms": 1000,
            "end_ms": 3000,
            "normalized_length": len(
                self.module.normalize_index_text(transcript)
            ),
            "text_sha256": raw_hash,
            "field_term_frequencies": {"回球": 1},
        }
        audit = self.module.audit_video_content(
            video,
            indexed_video_ids={video["video_id"]},
            index_record=record,
            chunk_first_sources={"bilibili_video"},
            chunks=[chunk],
            indexed_chunk_ngrams={
                chunk_id: self.module.hashed_ngrams(transcript, sizes)
            },
            chunk_lexicon={"回球"},
            transcript_ngram_sizes=sizes,
        )
        self.assertFalse(
            [
                item
                for item in audit["failures"]
                if "chunk" in item or "transcript_index" in item
            ]
        )

        chunk["text_sha256"] = "0" * 64
        audit = self.module.audit_video_content(
            video,
            indexed_video_ids={video["video_id"]},
            index_record=record,
            chunk_first_sources={"bilibili_video"},
            chunks=[chunk],
            indexed_chunk_ngrams={
                chunk_id: self.module.hashed_ngrams(transcript, sizes)
            },
            chunk_lexicon={"回球"},
            transcript_ngram_sizes=sizes,
        )
        self.assertIn("runtime_chunk_text_hash_mismatch", audit["failures"])

    def test_chunk_first_transcript_rejects_partition_gap(self):
        video = self.transcript_video("")
        video["source_type"] = "bilibili_video"
        record = {
            "field_lengths": {"transcript": 0},
            "transcript_ngrams": [],
        }
        chunk = {
            "chunk_id": "bilibili:BV1test#t000001000-000003000",
            "start_segment": 1,
            "end_segment": 2,
        }
        audit = self.module.audit_video_content(
            video,
            indexed_video_ids={video["video_id"]},
            index_record=record,
            chunk_first_sources={"bilibili_video"},
            chunks=[chunk],
            indexed_chunk_ngrams={},
            chunk_lexicon=set(),
        )
        self.assertIn("runtime_chunk_partition_mismatch", audit["failures"])

    def test_runtime_lookup_can_run_without_duplicate_semantic_probes(self):
        video = {
            "video_id": "7000000000000000003",
            "processing_status": "ready",
            "confidence": "visual_reviewed",
            "teaching_note": {
                "topic": "步法",
                "review_summary": "人工确认的步法示范。",
                "visual_review_evidence": [
                    {
                        "timestamp": "visual_review_no_timestamp",
                        "text": "人工确认的步法示范。",
                    }
                ],
            },
        }
        fake_search = SimpleNamespace(
            load_resources=lambda: ({}, {}, {}),
            lookup_videos=lambda video_ids, local_personalization=False: {
                "results": [
                    {
                        "video_id": video_ids[0],
                        "teaching_note": {"summary": "人工确认的步法示范。"},
                    }
                ]
            },
        )
        original_loader = self.module.load_search_module
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            knowledge_path = root / "knowledge.json"
            index_path = root / "index.json"
            knowledge_path.write_text(
                json.dumps({"videos": [video]}, ensure_ascii=False),
                encoding="utf-8",
            )
            index_path.write_text(
                json.dumps({"videos": [{"video_id": video["video_id"]}]}),
                encoding="utf-8",
            )
            try:
                self.module.load_search_module = lambda: fake_search
                result = self.module.evaluate(
                    knowledge_path,
                    index_path,
                    root=root,
                    run_retrieval_roundtrip=True,
                    run_semantic_probes=False,
                )
            finally:
                self.module.load_search_module = original_loader
        self.assertEqual(result["runtime_lookup_coverage"], 1.0)
        self.assertEqual(result["independent_probe_cases"], 0)
        self.assertIsNone(result["independent_probe_candidate_recall"])

    def test_evidence_provenance_separates_source_and_synthesis(self):
        transcript = self.transcript_video("")
        transcript["teaching_note"]["principles"] = [
            {"timestamp": "00:01-00:03", "text": "优先准备快线路"}
        ]
        visual = {
            "video_id": "7000000000000000002",
            "processing_status": "ready",
            "confidence": "visual_reviewed",
            "transcript_segments": [],
            "teaching_note": {
                "visual_review_evidence": [
                    {
                        "timestamp": "visual_review_no_timestamp",
                        "text": "动作画面显示向前启动。",
                    }
                ]
            },
        }
        metrics = self.module.evidence_provenance_metrics(
            [transcript, visual],
            {"asr_canonicalization": {"架盘": "架拍"}},
        )
        self.assertEqual(metrics["transcript_evidence_items"], 1)
        self.assertEqual(metrics["transcript_timestamp_coverage"], 1.0)
        self.assertEqual(metrics["reviewed_visual_observation_items"], 1)
        self.assertEqual(metrics["synthesized_principle_items"], 1)
        self.assertEqual(metrics["noncanonical_asr_occurrence_count"], 0)

    def test_noncanonical_asr_terms_do_not_span_segment_boundaries(self):
        transcript = self.transcript_video("")
        transcript["transcript_segments"] = [
            {"start": 1.0, "end": 2.0, "text": "保持高框架"},
            {"start": 2.0, "end": 3.0, "text": "攀头下去"},
        ]
        metrics = self.module.evidence_provenance_metrics(
            [transcript],
            {"asr_canonicalization": {"架攀": "架拍"}},
        )
        self.assertEqual(metrics["noncanonical_asr_occurrence_count"], 0)


if __name__ == "__main__":
    unittest.main()
