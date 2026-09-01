#!/usr/bin/env python3
import copy
import json
import unittest
from pathlib import Path
from typing import Any

from v3.routing import build_pilot_review_queue, validate_pilot_review_queue


ROOT = Path(__file__).resolve().parents[1]


def empty_publication() -> dict[str, Any]:
    return {"kind": "v3-shadow-publication", "sources": []}


class V3PilotRoutingFixtureTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(
            (ROOT / "config/v3/pilot-routing.json").read_text(encoding="utf-8")
        )
        self.config["review_budget_per_topic"] = 1
        self.quality_gates = json.loads(
            (ROOT / "config/v3/quality-gates.json").read_text(encoding="utf-8")
        )
        self.source_config = {"profile_id": "fixture-owner"}
        self.knowledge = {
            "videos": [
                self.video("101", "正手头顶高远架拍", "后场技术", ["后场技术"]),
                self.video("102", "反手高远架拍", "后场技术", ["后场技术"]),
                self.video("103", "网前搓球", "网前技术", ["网前技术"]),
                self.video(
                    "104",
                    "双打接发抢主动",
                    "发球与接发",
                    ["发球与接发", "双打战术"],
                ),
                self.video("105", "启动回动步法", "步法与移动", ["步法与移动"]),
                self.video("106", "装备参数", "装备与参数", []),
                self.video(
                    "bilibili:BVmirror",
                    "正手头顶高远镜像",
                    "后场技术",
                    ["后场技术"],
                    source_type="bilibili_video",
                    source_video_id="BVmirror",
                    duplicate_target="101",
                ),
            ]
        }
        self.inventory = self.make_inventory(self.knowledge["videos"])

    @staticmethod
    def video(
        video_id: str,
        title: str,
        category: str,
        tags: list[str],
        *,
        source_type: str = "douyin_video",
        source_video_id: str = "",
        duplicate_target: str = "",
    ) -> dict[str, Any]:
        native = source_video_id or video_id
        platform = "bilibili" if source_type == "bilibili_video" else "douyin"
        return {
            "video_id": video_id,
            "source_video_id": source_video_id or None,
            "source_type": source_type,
            "uploader_profile_id": "fixture-uploader" if platform == "bilibili" else None,
            "canonical_url": f"https://example.test/{platform}/{native}",
            "title": title,
            "category": category,
            "tags": tags,
            "answer_eligibility": "primary",
            "evidence_roles": ["action", "mechanism"],
            "possible_duplicate_evidence": (
                [{"evidence_id": duplicate_target}] if duplicate_target else []
            ),
            "parent_source_id": None,
            "transcript_file": f"ignored/{native}.json",
            "quality": {"automatic_evidence": {"key_evidence_count": 2}},
        }

    @staticmethod
    def make_inventory(videos: list[dict[str, Any]]) -> dict[str, Any]:
        sources = []
        for video in videos:
            if video["source_type"] == "bilibili_video":
                source_id = (
                    f"bilibili:{video['uploader_profile_id']}:{video['source_video_id']}"
                )
                platform = "bilibili"
                native = video["source_video_id"]
            else:
                source_id = f"douyin:fixture-owner:{video['video_id']}"
                platform = "douyin"
                native = video["video_id"]
            sources.append(
                {
                    "source_id": source_id,
                    "legacy_evidence_id": video["video_id"],
                    "platform": platform,
                    "native_video_id": native,
                    "canonical_url": video["canonical_url"],
                    "answer_eligibility": "primary",
                    "candidate_transcript_status": "local_candidate_present",
                    "candidate_transcript_fingerprint": "a" * 64,
                    "candidate_media_status": "local_candidate_present_unhashed",
                    "mirror_resolution_status": "unresolved",
                    "v3_formal_status": "missing",
                }
            )
        return {"sources": sources, "inventory_fingerprint": "b" * 64}

    def build(self, **overrides: Any) -> dict[str, Any]:
        values = {
            "knowledge": self.knowledge,
            "source_config": self.source_config,
            "inventory": self.inventory,
            "publication": empty_publication(),
            "routing_config": self.config,
            "quality_gates": self.quality_gates,
            "priority_payloads": [{"cases": [{"required_video_ids": ["104"]}]}],
        }
        values.update(overrides)
        return build_pilot_review_queue(**values)

    def test_every_source_is_routed_and_explicit_mirror_counts_once(self):
        queue = self.build()
        self.assertEqual(queue["summary"]["answer_eligible_sources_considered"], 7)
        self.assertEqual(queue["summary"]["answer_eligible_source_groups"], 6)
        self.assertEqual(queue["summary"]["explicit_mirror_groups"], 1)
        self.assertEqual(validate_pilot_review_queue(queue)["queued"], 5)
        mirrored = next(route for route in queue["routes"] if len(route["eligible_source_ids"]) == 2)
        self.assertEqual(mirrored["mirror_resolution_status"], "resolved_explicit")
        self.assertEqual(len(mirrored["alternate_urls"]), 1)

    def test_global_assignment_is_independent_of_topic_declaration_order(self):
        forward = self.build()
        reversed_config = copy.deepcopy(self.config)
        reversed_config["topic_rules"].reverse()
        reverse = self.build(routing_config=reversed_config)
        forward_assignments = {
            route["source_group_id"]: route["assigned_topic"]
            for route in forward["routes"]
        }
        reverse_assignments = {
            route["source_group_id"]: route["assigned_topic"]
            for route in reverse["routes"]
        }
        self.assertEqual(forward_assignments, reverse_assignments)

    def test_platform_and_candidate_metadata_never_gain_evidence_authority(self):
        queue = self.build()
        self.assertEqual(queue["routing_policy"]["platform_weighting"], "none")
        self.assertFalse(
            queue["routing_policy"]["candidate_metadata_is_answer_evidence"]
        )
        self.assertFalse(queue["routing_policy"]["machine_topic_assignment_is_formal"])
        self.assertEqual(
            {route["evidence_status"] for route in queue["routes"]},
            {"candidate_only"},
        )
        self.assertNotIn("transcript_segments", json.dumps(queue, ensure_ascii=False))

    def test_title_category_conflict_is_deprioritized_and_serve_phrase_is_disambiguated(self):
        conflicting = self.video(
            "107",
            "启动回动步法",
            "发球与接发",
            ["发球与接发"],
        )
        serving = self.video(
            "108",
            "正手发高远球教学",
            "后场技术",
            ["正手发高远球"],
        )
        knowledge = {"videos": [*self.knowledge["videos"], conflicting, serving]}
        inventory = self.make_inventory(knowledge["videos"])
        queue = self.build(knowledge=knowledge, inventory=inventory)
        conflict_route = next(
            route for route in queue["routes"] if route["knowledge_video_id"] == "107"
        )
        conflict_signals = {
            signal["topic_id"]: signal for signal in conflict_route["candidate_topics"]
        }
        self.assertGreater(
            conflict_signals["footwork"]["specificity"],
            conflict_signals["serve_receive"]["specificity"],
        )
        serve_route = next(
            route for route in queue["routes"] if route["knowledge_video_id"] == "108"
        )
        self.assertEqual(
            [signal["topic_id"] for signal in serve_route["candidate_topics"]],
            ["serve_receive"],
        )

    def test_historical_case_priority_is_counted_once_per_case(self):
        queue = self.build(
            priority_payloads=[
                {
                    "cases": [
                        {"ids": ["104", "104", "104"]},
                        {"ids": ["104"]},
                    ]
                }
            ]
        )
        route = next(route for route in queue["routes"] if route["knowledge_video_id"] == "104")
        self.assertEqual(route["priority"]["historical_case_count"], 2)

    def test_same_inputs_have_same_fingerprint(self):
        self.assertEqual(
            self.build()["routing_fingerprint"], self.build()["routing_fingerprint"]
        )


class V3PilotRoutingRepositoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = json.loads(
            (ROOT / "config/v3/pilot-routing.json").read_text(encoding="utf-8")
        )
        priority_payloads = [
            json.loads((ROOT / path).read_text(encoding="utf-8"))
            for path in config["priority_signal_files"]
        ]
        cls.queue = build_pilot_review_queue(
            knowledge=json.loads(
                (ROOT / "data/knowledge/douyin_knowledge_base.json").read_text(
                    encoding="utf-8"
                )
            ),
            source_config=json.loads(
                (ROOT / "config/douyin_source.json").read_text(encoding="utf-8")
            ),
            inventory=json.loads(
                (ROOT / "data/v3/source-inventory.json").read_text(encoding="utf-8")
            ),
            publication=json.loads(
                (ROOT / "data/v3/publication.json").read_text(encoding="utf-8")
            ),
            routing_config=config,
            quality_gates=json.loads(
                (ROOT / "config/v3/quality-gates.json").read_text(encoding="utf-8")
            ),
            priority_payloads=priority_payloads,
        )

    def test_repository_queue_covers_all_959_sources_once(self):
        result = validate_pilot_review_queue(self.queue)
        self.assertEqual(result["sources"], 959)
        self.assertEqual(len(self.queue["topics"]), 6)
        self.assertTrue(all(len(topic["entries"]) <= 20 for topic in self.queue["topics"]))

    def test_published_vertical_slice_does_not_consume_a_queue_slot(self):
        route = next(
            route
            for route in self.queue["routes"]
            if route["knowledge_video_id"] == "7589749293205363633"
        )
        self.assertEqual(route["route_status"], "already_published")
        self.assertIsNone(route["queue_rank"])


if __name__ == "__main__":
    unittest.main()
