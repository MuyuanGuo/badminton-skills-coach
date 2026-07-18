#!/usr/bin/env python3
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "douyin_pipeline.py"


def load_module():
    spec = importlib.util.spec_from_file_location("douyin_transaction_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DouyinTransactionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_interrupted_transaction_is_replayed_to_every_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first.json"
            second = root / "second.json"
            journal = root / ".transaction.json"
            self.module.write_json(first, {"value": "old-first"})
            self.module.write_json(second, {"value": "old-second"})

            real_atomic_copy = self.module.atomic_copy
            calls = 0

            def fail_after_first_copy(source, target):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated interruption")
                real_atomic_copy(source, target)

            with mock.patch.object(
                self.module, "atomic_copy", side_effect=fail_after_first_copy
            ):
                with self.assertRaises(OSError):
                    self.module.commit_json_transaction(
                        {
                            first: {"value": "new-first"},
                            second: {"value": "new-second"},
                        },
                        journal,
                    )

            self.assertTrue(journal.exists())
            self.assertEqual(json.loads(first.read_text())["value"], "new-first")
            self.assertEqual(json.loads(second.read_text())["value"], "old-second")

            self.assertTrue(self.module.recover_json_transaction(journal))
            self.assertEqual(json.loads(first.read_text())["value"], "new-first")
            self.assertEqual(json.loads(second.read_text())["value"], "new-second")
            self.assertFalse(journal.exists())


if __name__ == "__main__":
    unittest.main()
