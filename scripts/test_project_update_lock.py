#!/usr/bin/env python3

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "scripts" / "project_update_lock.py"


def load_module():
    spec = importlib.util.spec_from_file_location("project_lock_test", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProjectUpdateLockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_second_writer_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            os.environ, {self.module.LOCK_OWNER_ENV: ""}, clear=False
        ):
            first = self.module.acquire_project_update_lock(directory)
            try:
                with self.assertRaisesRegex(RuntimeError, "Another project update"):
                    self.module.acquire_project_update_lock(directory)
            finally:
                first.close()

    def test_owned_child_process_does_not_relock(self):
        with mock.patch.dict(
            os.environ, {self.module.LOCK_OWNER_ENV: "1"}, clear=False
        ):
            self.assertIsNone(self.module.acquire_project_update_lock("/missing"))


if __name__ == "__main__":
    unittest.main()
