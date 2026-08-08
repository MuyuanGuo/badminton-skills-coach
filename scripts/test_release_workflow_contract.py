#!/usr/bin/env python3
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReleaseWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )
        cls.release_signers = (
            ROOT / ".github" / "release-signers"
        ).read_text(encoding="utf-8")

    def test_release_assets_are_immutable_and_tag_is_on_main_history(self):
        self.assertNotIn("--clobber", self.workflow)
        self.assertIn("fetch-depth: 0", self.workflow)
        self.assertIn("git merge-base --is-ancestor", self.workflow)
        self.assertIn("git config gpg.format ssh", self.workflow)
        self.assertIn("gpg.ssh.allowedSignersFile", self.workflow)
        self.assertIn("git verify-tag", self.workflow)
        self.assertIn("environment: release", self.workflow)
        self.assertIn("timeout-minutes:", self.workflow)
        self.assertIn("release $RELEASE_TAG already exists", self.workflow)
        self.assertIn("gh release create", self.workflow)

    def test_release_requires_reproducible_current_runtime_answers(self):
        self.assertIn(
            "Require reproducible current-runtime release answers", self.workflow
        )
        self.assertIn(
            "python scripts/validate_live_generation_results.py", self.workflow
        )
        self.assertNotIn("independently reviewed model generations", self.workflow)

    def test_release_signer_is_public_ssh_material_only(self):
        lines = self.release_signers.splitlines()
        self.assertEqual(len(lines), 1)
        self.assertRegex(
            lines[0],
            r'^gmyymg666@gmail\.com namespaces="git" ssh-ed25519 [A-Za-z0-9+/=]+$',
        )
        self.assertNotIn("PRIVATE KEY", self.release_signers)


if __name__ == "__main__":
    unittest.main()
