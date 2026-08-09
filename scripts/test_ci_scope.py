#!/usr/bin/env python3
import unittest

from classify_ci_scope import classify_paths


class CiScopeTests(unittest.TestCase):
    def test_documentation_change_uses_only_documentation_validation(self):
        self.assertEqual(
            classify_paths(["README.md", "docs/index.html"]),
            {
                "static": False,
                "artifact": False,
                "quality": False,
                "docs_only": True,
            },
        )

    def test_workflow_change_skips_expensive_knowledge_evaluations(self):
        self.assertEqual(
            classify_paths([".github/workflows/release.yml"]),
            {
                "static": True,
                "artifact": False,
                "quality": False,
                "docs_only": False,
            },
        )

    def test_validation_workflow_change_runs_quality_evaluations(self):
        self.assertEqual(
            classify_paths([".github/workflows/validate.yml"]),
            {
                "static": True,
                "artifact": True,
                "quality": True,
                "docs_only": False,
            },
        )

    def test_test_only_change_skips_expensive_knowledge_evaluations(self):
        scope = classify_paths(["scripts/test_release_workflow_contract.py"])
        self.assertTrue(scope["static"])
        self.assertFalse(scope["artifact"])
        self.assertFalse(scope["quality"])

    def test_release_orchestration_skips_knowledge_evaluations(self):
        scope = classify_paths(["scripts/require_successful_validation.py"])
        self.assertTrue(scope["static"])
        self.assertFalse(scope["artifact"])
        self.assertFalse(scope["quality"])

    def test_runtime_or_corpus_change_runs_every_validation_group(self):
        for path in (
            "skills/liuhui-badminton-coach/scripts/search_knowledge.py",
            "skills/liuhui-badminton-coach/SKILL.md",
            "data/knowledge/retrieval_index.json",
            "scripts/bilibili_wiring_canary.py",
            "scripts/validate_live_generation_results.py",
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    classify_paths([path]),
                    {
                        "static": True,
                        "artifact": True,
                        "quality": True,
                        "docs_only": False,
                    },
                )

    def test_context_test_change_runs_only_static_and_quality_groups(self):
        self.assertEqual(
            classify_paths(["scripts/test_answer_context.py"]),
            {
                "static": True,
                "artifact": False,
                "quality": True,
                "docs_only": False,
            },
        )

    def test_artifact_test_and_packaging_inputs_run_artifact_validation(self):
        for path in (
            "scripts/test_release_package.py",
            "scripts/release_inventory.py",
            "requirements-dev.txt",
        ):
            with self.subTest(path=path):
                scope = classify_paths([path])
                self.assertTrue(scope["static"])
                self.assertTrue(scope["artifact"])
                self.assertFalse(scope["quality"])

    def test_mixed_docs_and_tooling_is_not_docs_only(self):
        scope = classify_paths(["README.md", ".github/workflows/release.yml"])
        self.assertTrue(scope["static"])
        self.assertFalse(scope["artifact"])
        self.assertFalse(scope["quality"])
        self.assertFalse(scope["docs_only"])

    def test_empty_path_set_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "at least one path"):
            classify_paths([])


if __name__ == "__main__":
    unittest.main()
