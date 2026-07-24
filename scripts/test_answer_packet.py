#!/usr/bin/env python3

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PATH = (
    ROOT
    / "skills"
    / "liuhui-badminton-coach"
    / "scripts"
    / "prepare_answer_context.py"
)


def load_runtime():
    spec = importlib.util.spec_from_file_location("answer_packet_runtime", RUNTIME_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AnswerPacketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = load_runtime()
        cls.context = cls.runtime.prepare_answer_context(
            "双打接杀挡网总冒高，是拍面还是击球点问题？",
            local_personalization=False,
        )
        cls.packet = cls.runtime.build_answer_packet(cls.context, "context.json")

    def test_packet_is_bound_to_the_complete_audit_context(self):
        self.assertTrue(
            self.runtime.validate_answer_packet(self.packet, self.context)
        )
        self.assertEqual(
            self.packet["audit_context"]["digest"],
            self.runtime.canonical_json_digest(self.context),
        )

    def test_tampered_packet_or_context_is_rejected(self):
        packet = copy.deepcopy(self.packet)
        packet["claim_evidence_map"][0]["text"] = "tampered"
        with self.assertRaisesRegex(ValueError, "projection"):
            self.runtime.validate_answer_packet(packet, self.context)
        context = copy.deepcopy(self.context)
        context["query"] = "tampered"
        with self.assertRaisesRegex(ValueError, "digest"):
            self.runtime.validate_answer_packet(self.packet, context)

    def test_planner_exposes_only_reviewed_atom_ids(self):
        plan = self.packet["answer_plan"]
        allowed = set(plan["composer_contract"]["allowed_atom_ids"])
        selected = {item["atom_id"] for item in plan["selected_evidence_atoms"]}
        self.assertEqual(allowed, selected)
        self.assertEqual(
            selected,
            {
                "EA-NET-BLOCK-CONTACT-001",
                "EA-NET-BLOCK-FACE-001",
                "EA-NET-BLOCK-TRAJECTORY-001",
            },
        )
        self.assertTrue(plan["composer_contract"]["unknown_atom_ids_forbidden"])

    def test_unatomized_scope_keeps_claim_scoped_source_evidence(self):
        context = copy.deepcopy(self.context)
        context["answer_plan"] = self.runtime.build_closed_answer_plan(context, [])
        packet = self.runtime.build_answer_packet(context, "context.json")
        self.assertEqual(packet["answer_plan"]["mode"], "claim_evidence_fallback")
        self.assertEqual(
            packet["answer_plan"]["composer_contract"]["technical_claim_policy"],
            "claim_scoped_source_evidence_only",
        )
        self.assertTrue(
            any(video["evidence_windows"] for video in packet["selected_videos"])
        )

    def test_packet_omits_retrieval_diagnostics_and_repeated_policy(self):
        encoded = json.dumps(self.packet, ensure_ascii=False)
        self.assertNotIn("why_retrieved", encoded)
        self.assertNotIn("selection_reasons", encoded)
        self.assertNotIn("citation_rules", encoded)
        full_size = len(json.dumps(self.context, ensure_ascii=False).encode("utf-8"))
        packet_size = len(encoded.encode("utf-8"))
        self.assertLessEqual(packet_size / full_size, 0.5)

    def test_cli_writes_full_context_and_prints_packet(self):
        with tempfile.TemporaryDirectory() as directory:
            context_path = Path(directory) / "context.json"
            packet = self.runtime.build_answer_packet(self.context, context_path)
            context_path.write_text(
                json.dumps(self.context, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            loaded = json.loads(context_path.read_text(encoding="utf-8"))
        self.assertTrue(self.runtime.validate_answer_packet(packet, loaded))
        self.assertEqual(packet["audit_context"]["reference"], str(context_path))


if __name__ == "__main__":
    unittest.main()
