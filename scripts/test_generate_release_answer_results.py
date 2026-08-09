#!/usr/bin/env python3
import importlib.util
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "generate_release_answer_results.py"


def load_module():
    spec = importlib.util.spec_from_file_location(
        "release_answer_generation_test", MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReleaseAnswerGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_release_registry_covers_all_eighteen_cases(self):
        self.assertEqual(len(self.module.required_release_case_ids()), 18)

    def test_generation_runs_each_case_once_and_avoids_a_second_runtime_rerun(self):
        case = {"case_id": "DQ-TEST", "query": "怎么练？"}

        class ContextModule:
            @staticmethod
            def prepare_answer_context(query, local_personalization=False):
                self.assertEqual(query, case["query"])
                self.assertFalse(local_personalization)
                return {"delivery_contract": {"items": []}}

            @staticmethod
            def build_answer_packet(context):
                return {"context": context}

            @staticmethod
            def validate_answer_packet(packet, context):
                self.assertIs(packet["context"], context)

        class RendererModule:
            @staticmethod
            def render_answer(packet):
                return "轻量生成答案"

        class AuditModule:
            @staticmethod
            def audit_answer(query, context, answer):
                return {"passed": True}

        modules = iter((ContextModule, RendererModule, AuditModule))
        validation = {
            "status": "pass",
            "release_eligible": True,
            "current_renderer_reproduced": False,
            "automated_audit_pass_rate": 1.0,
        }
        with mock.patch.object(
            self.module,
            "release_case_registry",
            return_value={case["case_id"]: case},
        ), mock.patch.object(
            self.module,
            "required_release_case_ids",
            return_value={case["case_id"]},
        ), mock.patch.object(
            self.module,
            "load_module",
            side_effect=lambda *_args, **_kwargs: next(modules),
        ), mock.patch.object(
            self.module,
            "delivery_case_failures",
            return_value=[],
        ) as delivery_failures, mock.patch.object(
            self.module,
            "runtime_fingerprint",
            return_value="a" * 64,
        ), mock.patch.object(
            self.module,
            "answer_runtime_fingerprint",
            return_value="b" * 64,
        ), mock.patch.object(
            self.module,
            "validate_results",
            return_value=validation,
        ) as validate:
            payload = self.module.build_results(generated_at="2026-08-03")

        self.assertEqual(payload["schema_version"], 3)
        self.assertEqual(len(payload["cases"]), 1)
        self.assertEqual(payload["cases"][0]["answer_text"], "轻量生成答案")
        delivery_failures.assert_called_once()
        validate.assert_called_once_with(
            payload,
            root=self.module.ROOT,
            rerun_runtime=False,
        )


if __name__ == "__main__":
    unittest.main()
