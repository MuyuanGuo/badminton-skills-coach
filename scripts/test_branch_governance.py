#!/usr/bin/env python3
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BranchGovernanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = (
            ROOT / ".github" / "workflows" / "pr-policy.yml"
        ).read_text(encoding="utf-8")
        cls.sync = (
            ROOT / ".github" / "workflows" / "sync-main-to-develop.yml"
        ).read_text(encoding="utf-8")
        cls.validate = (
            ROOT / ".github" / "workflows" / "validate.yml"
        ).read_text(encoding="utf-8")
        cls.repository_settings = (
            ROOT / ".github" / "REPOSITORY_SETTINGS.md"
        ).read_text(encoding="utf-8")

    def test_main_pr_policy_uses_trusted_base_workflow(self):
        self.assertIn("pull_request_target:", self.policy)
        self.assertIn('BASE_BRANCH" != "main', self.policy)
        self.assertIn('HEAD_REPOSITORY" != "$BASE_REPOSITORY', self.policy)
        self.assertIn("release/*|hotfix/*", self.policy)
        self.assertIn("codex/release-*|codex/hotfix-*", self.policy)
        self.assertIn("permissions: {}", self.policy)
        self.assertNotIn("actions/checkout", self.policy)

    def test_successful_main_validation_proposes_a_develop_sync(self):
        self.assertIn('workflows: ["Validate knowledge pipeline"]', self.sync)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", self.sync)
        self.assertIn("github.event.workflow_run.head_branch == 'main'", self.sync)
        self.assertIn("python scripts/prepare_develop_sync.py", self.sync)
        self.assertIn("--base develop", self.sync)
        self.assertIn("automation/sync-main-to-develop", self.sync)
        self.assertIn("gh workflow run validate.yml", self.sync)
        self.assertIn("actions: write", self.sync)
        self.assertIn("pull-requests: write", self.sync)

    def test_repository_contract_requires_policy_and_backmerge(self):
        self.assertIn("`branch-policy`", self.repository_settings)
        self.assertIn("main-to-develop", self.repository_settings)
        self.assertIn("workflow_dispatch:", self.validate)


if __name__ == "__main__":
    unittest.main()
