#!/usr/bin/env python3
import json
import re
import unittest
from pathlib import Path

import batch_transcribe_directory as transcriber
import generate_release_sbom


ROOT = Path(__file__).resolve().parents[1]


class TranscriptionSupplyChainTests(unittest.TestCase):
    def test_every_locked_requirement_has_at_least_one_hash(self):
        for relative in ("requirements-transcription.txt", "requirements-dev.txt"):
            lines = (ROOT / relative).read_text(encoding="utf-8").splitlines()
            requirements = [
                index
                for index, line in enumerate(lines)
                if re.match(r"^[A-Za-z0-9_.-]+==[^ ]+ \\$", line)
            ]
            self.assertTrue(requirements, relative)
            for index in requirements:
                following = "\n".join(lines[index + 1 : index + 12])
                self.assertIn("--hash=sha256:", following, lines[index])

    def test_model_aliases_resolve_to_immutable_revisions(self):
        config = json.loads(
            (ROOT / "config" / "transcription_models.json").read_text(
                encoding="utf-8"
            )
        )
        for name, expected_repository in {
            "small": "Systran/faster-whisper-small",
            "medium": "Systran/faster-whisper-medium",
        }.items():
            spec = config["models"][name]
            self.assertEqual(spec["repository"], expected_repository)
            self.assertRegex(spec["revision"], r"^[0-9a-f]{40}$")
            recipe = transcriber.transcription_recipe(name)
            self.assertEqual(recipe["schema_version"], 2)
            self.assertEqual(recipe["model_repository"], spec["repository"])
            self.assertEqual(recipe["model_revision"], spec["revision"])

    def test_sbom_parser_accepts_hash_locked_multiline_format(self):
        dependencies = generate_release_sbom.locked_optional_dependencies()
        refs = [item["bom-ref"] for item in dependencies]
        self.assertTrue(refs)
        self.assertEqual(len(refs), len(set(refs)))
        self.assertTrue(all(item["scope"] == "optional" for item in dependencies))


if __name__ == "__main__":
    unittest.main()
