#!/usr/bin/env python3
import copy
import json
import tempfile
import unittest
from pathlib import Path

from build_douyin_knowledge import (
    assess_transcript,
    automatic_note,
    build_record,
    build_knowledge,
    runtime_transcript_segments,
    reconcile_updated_at,
)
from build_retrieval_index import build_index


ROOT = Path(__file__).resolve().parents[1]
RULES = json.loads(
    (ROOT / "config" / "knowledge_quality_rules.json").read_text(encoding="utf-8")
)


def transcript(text, language="zh", probability=1.0, segment_count=5):
    segments = [
        {"start": index, "end": index + 1, "text": text}
        for index in range(segment_count)
    ]
    return {
        "language": language,
        "language_probability": probability,
        "full_text": text * segment_count,
        "segments": segments,
    }


class KnowledgeQualityTests(unittest.TestCase):
    def test_douyin_builder_persists_source_neutral_evidence_identity(self):
        video_id = "123456789012345678"
        record = build_record(
            {
                "video_id": video_id,
                "title": "击球教学",
                "url": f"https://www.douyin.com/video/{video_id}",
                "category": "握拍与基本动作",
                "tags": "握拍与基本动作；训练与纠错",
                "classification_decision": "保留：教学",
            },
            ROOT / "data" / "transcripts" / "douyin" / f"{video_id}.json",
            transcript("击球时先放松再发力。"),
            {},
            {},
            RULES,
        )
        self.assertEqual(record["evidence_id"], video_id)
        self.assertEqual(record["source_type"], "douyin_video")
        self.assertEqual(record["canonical_url"], record["url"])
        self.assertIsNone(record["parent_source_id"])
        self.assertIsNone(record["clip_start_seconds"])
        self.assertIsNone(record["clip_end_seconds"])

    def test_unprocessed_queue_items_are_skipped_but_transcribed_items_are_required(self):
        pending_queue = {
            "counts": {"classified_teaching": 1},
            "items": [
                {
                    "video_id": "123456789012345678",
                    "status": "classified_teaching",
                }
            ],
        }
        knowledge = build_knowledge(
            pending_queue,
            {"videos": []},
            {"items": []},
            {},
            RULES,
        )
        self.assertEqual(knowledge["knowledge_counts"]["videos"], 0)

        pending_queue["items"][0]["status"] = "transcribed"
        pending_queue["counts"] = {"transcribed": 1}
        with self.assertRaisesRegex(SystemExit, "Missing transcripts"):
            build_knowledge(
                pending_queue,
                {"videos": []},
                {"items": []},
                {},
                RULES,
            )

    def test_rebuild_preserves_version_when_corpus_is_unchanged(self):
        existing = {
            "version": 1,
            "updated_at": "2026-07-16T00:00:00Z",
            "videos": [{"video_id": "123456789012345678"}],
        }
        candidate = copy.deepcopy(existing)
        candidate["updated_at"] = "2026-07-17T00:00:00Z"
        reconciled, changed = reconcile_updated_at(
            candidate, existing, now="2026-07-18T00:00:00Z"
        )
        self.assertFalse(changed)
        self.assertEqual(reconciled["updated_at"], existing["updated_at"])

        candidate["videos"].append({"video_id": "123456789012345679"})
        reconciled, changed = reconcile_updated_at(
            candidate, existing, now="2026-07-18T00:00:00Z"
        )
        self.assertTrue(changed)
        self.assertEqual(reconciled["updated_at"], "2026-07-18T00:00:00Z")

    def test_traditional_chinese_teaching_terms_are_evidence(self):
        item = {
            "title": "相同的框架下，一个是锁住，一个是释放",
            "category": "握拍与基本动作",
            "tags": "握拍与基本动作；训练与纠错",
        }
        source = transcript("小臂帶動手腕，手指鎖住卸力；推球時順勢釋放並瞬間發力。")
        note = automatic_note(item, source["segments"], RULES)
        self.assertTrue(note["quality"]["passed"])
        self.assertGreaterEqual(note["quality"]["key_evidence_count"], 1)

    def test_sparse_non_instructional_speech_requires_review(self):
        item = {
            "title": "朋友们让我完成这个挑战",
            "category": "训练与纠错",
            "tags": "训练与纠错",
        }
        source = transcript("朋友们继续挑战接力，今天给大家献丑了。")
        note = automatic_note(item, source["segments"], RULES)
        self.assertFalse(note["quality"]["passed"])
        self.assertIn("missing_key_evidence", note["quality"]["issues"])

    def test_single_technique_mention_is_not_enough_for_automatic_evidence(self):
        item = {
            "title": "挑战接力",
            "category": "训练与纠错",
            "tags": "训练与纠错",
        }
        source = transcript("今天参加挑战，羽毛球只要找到合适击球感觉就行。")
        note = automatic_note(item, source["segments"][:1], RULES)
        self.assertFalse(note["quality"]["passed"])
        self.assertIn("insufficient_context_for_single_match", note["quality"]["issues"])

    def test_repeated_topic_mention_without_instruction_is_not_evidence(self):
        item = {
            "title": "谁的杀球更重",
            "category": "杀球",
            "tags": "杀球",
        }
        source = transcript("今天大家比较谁的杀球更重，欢迎在评论区讨论。")
        note = automatic_note(item, source["segments"], RULES)
        self.assertFalse(note["quality"]["passed"])
        self.assertIn(
            "single_term_without_instruction_signal", note["quality"]["issues"]
        )

    def test_asr_terms_are_canonicalized_but_raw_text_is_retained(self):
        segments = runtime_transcript_segments(
            [
                {
                    "start": 1,
                    "end": 2,
                    "text": "先架盘握盘挥盘，再贴盘做隐拍，向前挥帕完成机球，用顿地炮。",
                },
                {
                    "start": 2,
                    "end": 3,
                    "text": "蹲地炮也是自动转写错词。",
                }
            ],
            RULES,
        )
        self.assertEqual(
            segments[0]["text"],
            "先架拍握拍挥拍，再贴拍做引拍，向前挥拍完成击球，用遁地炮。",
        )
        self.assertEqual(
            segments[0]["raw_text"],
            "先架盘握盘挥盘，再贴盘做隐拍，向前挥帕完成机球，用顿地炮。",
        )
        self.assertEqual(segments[1]["text"], "遁地炮也是自动转写错词。")
        self.assertEqual(segments[1]["raw_text"], "蹲地炮也是自动转写错词。")

    def test_overlapping_evidence_windows_are_deduplicated(self):
        item = {"title": "击球发力", "category": "发力", "tags": "发力"}
        source = transcript("击球时先放松再发力。", segment_count=8)
        note = automatic_note(item, source["segments"], RULES)
        evidence = note["note"]["key_evidence"]
        self.assertLess(len(evidence), RULES["evidence"]["key_evidence_limit"])
        self.assertEqual(
            len({item["timestamp"] for item in evidence}), len(evidence)
        )

    def test_long_transcript_key_evidence_covers_later_time_buckets(self):
        item = {
            "title": "后场架拍和发力",
            "category": "后场技术",
            "tags": "后场技术；训练与纠错",
        }
        early_evidence_indexes = {0, 3, 6, 9, 11}
        segments = [
            {
                "start": index * 12,
                "end": index * 12 + 4,
                "text": (
                    "先检查后场架拍和发力是否完整。"
                    if index in early_evidence_indexes
                    else "明显的直线挥拍更稳定。"
                    if index == 17
                    else "继续说明动作。"
                ),
            }
            for index in range(18)
        ]
        note = automatic_note(item, segments, RULES)
        evidence = note["note"]["coverage_evidence"]
        self.assertTrue(any(item["timestamp"].startswith("03:12") for item in evidence))

    def test_language_and_han_quality_are_both_enforced(self):
        source = transcript("bad audio transcript ", language="en", probability=0.3)
        quality = assess_transcript(source, RULES)
        self.assertFalse(quality["passed"])
        self.assertIn("unexpected_language", quality["issues"])
        self.assertIn("low_language_probability", quality["issues"])
        self.assertIn("low_han_ratio", quality["issues"])

    def test_retrieval_index_only_accepts_ready_records(self):
        topic_index = {
            "categories": [
                {
                    "name": "基础",
                    "subtopics": [
                        {
                            "name": "握拍",
                            "keywords": ["握拍"],
                            "video_ids": ["ready"],
                        }
                    ],
                }
            ]
        }
        rules = {
            "version": "test",
            "synonym_groups": [["握拍"]],
            "retrieval": {"transcript_ngram_sizes": [2]},
        }
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            transcript_path = Path(directory) / "transcript.json"
            transcript_path.write_text(
                json.dumps({"full_text": "握拍教学"}, ensure_ascii=False),
                encoding="utf-8",
            )
            relative = str(transcript_path.relative_to(ROOT))
            knowledge = {
                "updated_at": "2026-01-01T00:00:00+00:00",
                "videos": [
                    {
                        "video_id": "ready",
                        "evidence_id": "ready",
                        "source_type": "test_video",
                        "canonical_url": "https://example.test/ready",
                        "parent_source_id": None,
                        "clip_start_seconds": None,
                        "clip_end_seconds": None,
                        "processing_status": "ready",
                        "transcript_file": relative,
                        "title": "握拍",
                        "category": "基础",
                        "tags": [],
                        "teaching_note": {},
                        "transcript_segments": [
                            {"start": 0, "end": 1, "text": "握拍教学"}
                        ],
                    },
                    {
                        "video_id": "review",
                        "evidence_id": "review",
                        "source_type": "test_video",
                        "canonical_url": "https://example.test/review",
                        "parent_source_id": None,
                        "clip_start_seconds": None,
                        "clip_end_seconds": None,
                        "processing_status": "needs_visual_review",
                        "transcript_file": relative,
                        "title": "握拍",
                        "category": "基础",
                        "tags": [],
                        "teaching_note": {},
                    },
                ],
            }
            index = build_index(knowledge, topic_index, rules)
        self.assertEqual([item["video_id"] for item in index["videos"]], ["ready"])

    def test_screening_tags_do_not_create_evidence_topics(self):
        topic_index = {
            "categories": [
                {
                    "name": "基础",
                    "subtopics": [
                        {"name": "握拍", "keywords": ["握拍"], "video_ids": []},
                        {
                            "name": "框架",
                            "keywords": ["框架"],
                            "video_ids": ["tagged"],
                        },
                    ],
                }
            ]
        }
        rules = {
            "version": "test",
            "synonym_groups": [["握拍"], ["框架"]],
            "retrieval": {"transcript_ngram_sizes": [2]},
        }
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            transcript_path = Path(directory) / "transcript.json"
            transcript_path.write_text(
                json.dumps({"full_text": "网前框架"}, ensure_ascii=False),
                encoding="utf-8",
            )
            knowledge = {
                "updated_at": "2026-01-01T00:00:00+00:00",
                "videos": [
                    {
                        "video_id": "tagged",
                        "evidence_id": "tagged",
                        "source_type": "test_video",
                        "canonical_url": "https://example.test/tagged",
                        "parent_source_id": None,
                        "clip_start_seconds": None,
                        "clip_end_seconds": None,
                        "processing_status": "ready",
                        "transcript_file": str(transcript_path.relative_to(ROOT)),
                        "title": "网前框架",
                        "category": "基础",
                        "tags": ["握拍"],
                        "teaching_note": {"topic": "网前框架"},
                        "transcript_segments": [
                            {"start": 0, "end": 1, "text": "网前框架"}
                        ],
                    }
                ],
            }
            record = build_index(knowledge, topic_index, rules)["videos"][0]
        self.assertIn("基础/框架", record["topic_ids"])
        self.assertNotIn("基础/握拍", record["topic_ids"])
        self.assertNotIn("握拍", record["lexicon_terms"])


if __name__ == "__main__":
    unittest.main()
