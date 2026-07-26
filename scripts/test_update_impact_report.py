#!/usr/bin/env python3
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "build_update_impact_report.py"


def load_module():
    spec = importlib.util.spec_from_file_location(
        "update_impact_report_test", MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def state(*, ready, retrieval, statuses, sources=None, queue=None, build_id="b1"):
    return {
        "knowledge_sha256": "knowledge-" + build_id,
        "retrieval_sha256": "retrieval-" + build_id,
        "build_id": build_id,
        "video_statuses": statuses,
        "ready_video_ids": ready,
        "retrieval_video_ids": retrieval,
        "evidence_sources": sources or {},
        "queue_counts": queue or {},
    }


class UpdateImpactReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_report_lists_additions_transitions_and_count_deltas(self):
        before = state(
            ready=["1"],
            retrieval=["1"],
            statuses={"1": "ready", "2": "needs_visual_review"},
            sources={"automatic_transcript": 1},
            queue={"transcribed": 1},
        )
        after = state(
            ready=["1", "2"],
            retrieval=["1", "2"],
            statuses={"1": "ready", "2": "ready"},
            sources={"automatic_transcript": 2},
            queue={"transcribed": 2},
            build_id="b2",
        )
        report = self.module.build_report(before, after)
        self.assertEqual(report["ready_videos"]["added_video_ids"], ["2"])
        self.assertEqual(report["status_transitions"][0]["after"], "ready")
        self.assertEqual(
            report["evidence_source_delta"],
            {"automatic_transcript": 1},
        )
        self.assertTrue(report["invariants"]["ready_matches_retrieval"])

    def test_report_detects_silent_ready_removal(self):
        before = state(
            ready=["1", "2"],
            retrieval=["1", "2"],
            statuses={"1": "ready", "2": "ready"},
        )
        after = state(
            ready=["1"],
            retrieval=["1"],
            statuses={"1": "ready", "2": "low_value"},
            build_id="b2",
        )
        report = self.module.build_report(before, after)
        self.assertFalse(report["invariants"]["no_silent_ready_removals"])


if __name__ == "__main__":
    unittest.main()
