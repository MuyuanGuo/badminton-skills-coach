#!/usr/bin/env python3
import copy
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "project_artifacts.py"
SIGNAL_BUILDER_PATH = ROOT / "scripts" / "build_reviewed_evidence_signals.py"
UPDATE_PIPELINE_PATH = ROOT / "scripts" / "run_full_update_pipeline.py"


def load_module(name="project_artifacts_tested", path=MODULE_PATH):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProjectArtifactsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()
        cls.signal_builder = load_module(
            "reviewed_evidence_signal_builder_tested", SIGNAL_BUILDER_PATH
        )
        cls.update_pipeline = load_module(
            "full_update_pipeline_tested", UPDATE_PIPELINE_PATH
        )

    def fixture(self):
        ids = {
            "ready": "100000000000000001",
            "visual": "100000000000000002",
            "unprocessed": "100000000000000003",
            "post-excluded": "100000000000000004",
            "filter-review": "100000000000000005",
            "ad": "100000000000000006",
            "non-teaching": "100000000000000007",
        }

        def record(name):
            video_id = ids[name]
            return {
                "video_id": video_id,
                "url": f"https://www.douyin.com/video/{video_id}",
            }

        index = {
            "videos": [
                record("ready"),
                record("visual"),
                record("unprocessed"),
                record("post-excluded"),
                record("filter-review"),
                record("ad"),
                record("non-teaching"),
            ]
        }
        teaching = {
            "counts": {
                "total": 7,
                "kept_teaching": 4,
                "review": 1,
                "excluded_ads": 1,
                "excluded_non_teaching": 1,
            },
            "videos": [
                record("ready"),
                record("visual"),
                record("unprocessed"),
                record("post-excluded"),
            ],
        }
        knowledge = {
            "videos": [
                {
                    **record("ready"),
                    "title": "Ready",
                    "processing_status": "ready",
                },
                {
                    **record("visual"),
                    "title": "Visual",
                    "processing_status": "needs_visual_review",
                },
                {
                    **record("post-excluded"),
                    "title": "Excluded",
                    "processing_status": "not_teaching",
                },
            ]
        }
        return index, teaching, knowledge

    def test_status_partition_keeps_pending_out_of_excluded(self):
        status = self.module.derive_project_status(*self.fixture())
        self.assertEqual(status["public_videos_collected"], 7)
        self.assertEqual(status["ready_teaching_videos"], 1)
        self.assertEqual(status["pending_human_review_or_processing"], 3)
        self.assertEqual(status["excluded_non_teaching_ads_equipment"], 3)
        self.assertTrue(status["accounting_consistent"])

    def test_inconsistent_filter_partition_is_rejected(self):
        index, teaching, knowledge = self.fixture()
        teaching = copy.deepcopy(teaching)
        teaching["counts"]["excluded_ads"] = 2
        with self.assertRaisesRegex(
            self.module.ArtifactConsistencyError, "complete partition"
        ):
            self.module.derive_project_status(index, teaching, knowledge)

    def test_audited_pre_filter_exclusion_is_not_counted_twice(self):
        index, teaching, knowledge = self.fixture()
        excluded = teaching["videos"].pop()
        teaching["counts"]["kept_teaching"] -= 1
        teaching["counts"]["excluded_non_teaching"] += 1
        status = self.module.derive_project_status(index, teaching, knowledge)
        self.assertEqual(status["ready_teaching_videos"], 1)
        self.assertEqual(status["pending_human_review_or_processing"], 3)
        self.assertEqual(status["excluded_non_teaching_ads_equipment"], 3)
        self.assertEqual(
            status["public_videos_collected"],
            status["ready_teaching_videos"]
            + status["pending_human_review_or_processing"]
            + status["excluded_non_teaching_ads_equipment"],
        )

    def test_noncanonical_public_video_link_is_rejected(self):
        index, teaching, knowledge = self.fixture()
        knowledge = copy.deepcopy(knowledge)
        knowledge["videos"][0]["url"] += "?redirect=1"
        with self.assertRaisesRegex(
            self.module.ArtifactConsistencyError, "canonical Douyin URL"
        ):
            self.module.derive_project_status(index, teaching, knowledge)

    def test_source_neutral_evidence_accepts_livestream_clips(self):
        evidence_id = "live:2026-07-21:clip-003"
        result = self.module.validate_evidence_records(
            [
                {
                    "video_id": evidence_id,
                    "evidence_id": evidence_id,
                    "source_type": "livestream_clip",
                    "canonical_url": "https://example.test/live/2026-07-21?t=315",
                    "parent_source_id": "live:2026-07-21",
                    "clip_start_seconds": 315,
                    "clip_end_seconds": 372,
                }
            ]
        )
        self.assertEqual(result, [evidence_id])

    def test_source_neutral_clip_requires_parent_and_complete_range(self):
        with self.assertRaisesRegex(
            self.module.ArtifactConsistencyError, "partial clip range"
        ):
            self.module.validate_evidence_records(
                [
                    {
                        "video_id": "live:clip-004",
                        "evidence_id": "live:clip-004",
                        "source_type": "livestream_clip",
                        "canonical_url": "https://example.test/live?t=400",
                        "parent_source_id": None,
                        "clip_start_seconds": 400,
                        "clip_end_seconds": None,
                    }
                ]
            )

    def test_real_project_status_reconciles(self):
        status = self.module.derive_project_status(
            json.loads((ROOT / "data/douyin_video_index.json").read_text(encoding="utf-8")),
            json.loads(
                (ROOT / "data/douyin_teaching_filtered.json").read_text(
                    encoding="utf-8"
                )
            ),
            json.loads(
                (ROOT / "data/knowledge/douyin_knowledge_base.json").read_text(
                    encoding="utf-8"
                )
            ),
        )
        self.assertEqual(
            status["public_videos_collected"],
            status["ready_teaching_videos"]
            + status["pending_human_review_or_processing"]
            + status["excluded_non_teaching_ads_equipment"],
        )

    def test_reference_sync_rolls_back_after_partial_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, (source_relative, destination_relative) in enumerate(
                self.module.SKILL_REFERENCE_PATHS
            ):
                source = root / source_relative
                destination = root / destination_relative
                source.parent.mkdir(parents=True, exist_ok=True)
                destination.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(
                    b'{"videos": []}\n'
                    if index == 0
                    else f"new-{index}".encode()
                )
                destination.write_bytes(f"old-{index}".encode())

            replace_count = 0

            def fail_second_replace(source, destination):
                nonlocal replace_count
                replace_count += 1
                if replace_count == 2:
                    raise OSError("injected synchronization failure")
                os.replace(source, destination)

            with self.assertRaisesRegex(OSError, "injected"):
                self.module.sync_skill_references(
                    root=root, replace_func=fail_second_replace
                )
            for index, (_, destination_relative) in enumerate(
                self.module.SKILL_REFERENCE_PATHS
            ):
                self.assertEqual(
                    (root / destination_relative).read_bytes(),
                    f"old-{index}".encode(),
                )

    def test_reference_sync_updates_the_complete_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, (source_relative, destination_relative) in enumerate(
                self.module.SKILL_REFERENCE_PATHS
            ):
                source = root / source_relative
                destination = root / destination_relative
                source.parent.mkdir(parents=True, exist_ok=True)
                destination.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(
                    b'{"videos": []}\n'
                    if index == 0
                    else f"new-{index}".encode()
                )
                destination.write_bytes(f"old-{index}".encode())
            changed = self.module.sync_skill_references(root=root)
            self.assertEqual(len(changed), len(self.module.SKILL_REFERENCE_PATHS))
            self.assertEqual(self.module.skill_reference_mismatches(root), [])

    def test_packaged_knowledge_removes_unbundled_transcript_paths(self):
        source = json.dumps(
            {
                "videos": [
                    {
                        "video_id": "123456789012345678",
                        "transcript_file": "data/transcripts/private.json",
                    }
                ]
            }
        ).encode()
        packaged = json.loads(
            self.module.skill_reference_bytes(
                Path("data/knowledge/douyin_knowledge_base.json"), source
            )
        )
        self.assertFalse(packaged["transcript_files_bundled"])
        self.assertTrue(packaged["runtime_transcript_segments_bundled"])
        self.assertNotIn("transcript_file", packaged["videos"][0])

    def test_reviewed_evidence_signals_match_reviewed_registry(self):
        expected = self.signal_builder.build_payload()
        actual = json.loads(
            (ROOT / "config/reviewed_evidence_signals.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual["signals"]), 57)

    def test_full_update_pipeline_enforces_answer_and_forward_quality(self):
        commands = self.update_pipeline.validation_commands()
        answer_commands = [
            command
            for command in commands
            if "scripts/evaluate_answer_quality.py" in command
        ]
        self.assertEqual(len(answer_commands), 1)
        self.assertEqual(
            answer_commands[0][answer_commands[0].index("--min-approved") + 1],
            "57",
        )
        self.assertEqual(
            answer_commands[0][
                answer_commands[0].index("--min-answer-snapshots") + 1
            ],
            "57",
        )
        self.assertEqual(
            answer_commands[0][
                answer_commands[0].index("--min-answer-snapshot-coverage") + 1
            ],
            "1.0",
        )
        self.assertIn("--require-complete-answer-coverage", answer_commands[0])
        self.assertIn("--require-critical-answer-coverage", answer_commands[0])
        self.assertIn("--require-manual-review", answer_commands[0])
        self.assertTrue(
            any(
                "scripts/evaluate_forward_test_results.py" in command
                for command in commands
            )
        )


if __name__ == "__main__":
    unittest.main()
