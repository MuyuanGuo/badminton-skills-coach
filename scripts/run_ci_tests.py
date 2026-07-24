#!/usr/bin/env python3
"""Run repository tests in validated CI groups and stable context shards."""

import argparse
import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEST_DIR = ROOT / "scripts"
CONTEXT_TEST_FILE = "test_answer_context.py"
ARTIFACT_TEST_FILES = {
    "test_build_reproducibility.py",
    "test_knowledge_graph_html.py",
    "test_media_assets.py",
    "test_project_artifacts.py",
    "test_project_site.py",
    "test_release_package.py",
    "test_repository_links.py",
    "test_skill_portability.py",
}


def discover_test_files():
    return {path.name for path in TEST_DIR.glob("test_*.py")}


def test_groups():
    discovered = discover_test_files()
    explicit = ARTIFACT_TEST_FILES | {CONTEXT_TEST_FILE}
    missing = explicit - discovered
    if missing:
        raise ValueError(f"configured CI tests do not exist: {sorted(missing)}")
    groups = {
        "artifacts": set(ARTIFACT_TEST_FILES),
        "context": {CONTEXT_TEST_FILE},
        "fast": discovered - explicit,
    }
    assigned = [name for files in groups.values() for name in files]
    if len(assigned) != len(set(assigned)) or set(assigned) != discovered:
        raise ValueError("every Python test must belong to exactly one CI group")
    return groups


def _flatten_suite(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _flatten_suite(item)
        else:
            yield item


def context_tests():
    path = TEST_DIR / CONTEXT_TEST_FILE
    spec = importlib.util.spec_from_file_location("ci_answer_context_tests", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    return sorted(_flatten_suite(suite), key=lambda test: test.id())


def partition_context_test_ids(shard_count):
    if shard_count < 1:
        raise ValueError("shard count must be positive")
    partitions = [[] for _ in range(shard_count)]
    for index, test in enumerate(context_tests()):
        partitions[index % shard_count].append(test.id())
    return partitions


def run_files(files):
    for filename in sorted(files):
        print(f"::group::{filename}", flush=True)
        completed = subprocess.run(
            [sys.executable, str(TEST_DIR / filename)],
            cwd=ROOT,
            check=False,
        )
        print("::endgroup::", flush=True)
        if completed.returncode:
            return completed.returncode
    return 0


def run_context_shard(shard_index, shard_count):
    if not 0 <= shard_index < shard_count:
        raise ValueError("shard index must be within the configured shard count")
    tests = context_tests()
    selected = [
        test for index, test in enumerate(tests) if index % shard_count == shard_index
    ]
    print(
        f"Running answer-context shard {shard_index + 1}/{shard_count} "
        f"with {len(selected)} of {len(tests)} tests",
        flush=True,
    )
    result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(selected))
    return 0 if result.wasSuccessful() else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("group", choices=("fast", "artifacts", "context", "check"))
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    args = parser.parse_args()
    groups = test_groups()
    if args.group == "check":
        for name, files in groups.items():
            print(f"{name}: {len(files)} files")
        return
    if args.group == "context":
        raise SystemExit(run_context_shard(args.shard_index, args.shard_count))
    if args.shard_index != 0 or args.shard_count != 1:
        parser.error("shard options are supported only for the context group")
    raise SystemExit(run_files(groups[args.group]))


if __name__ == "__main__":
    main()
