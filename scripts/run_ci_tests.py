#!/usr/bin/env python3
"""Run repository tests in validated CI groups and stable context shards."""

import argparse
import concurrent.futures
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
COMPATIBILITY_TEST_FILES = {
    "test_answer_audit.py",
    "test_answer_packet.py",
    "test_delivery_contract.py",
    "test_render_answer.py",
    "test_runtime_store.py",
    "test_search_knowledge.py",
}
SERIAL_TEST_FILES = {
    # These suites all load the production retrieval/runtime artifacts. Running
    # them together causes memory and storage contention on two-core CI runners
    # and iCloud-backed local checkouts, so only the lighter suites run in
    # bounded parallel batches.
    "test_evaluate_retrieval.py",
    "test_render_answer.py",
    "test_runtime_store.py",
    "test_search_knowledge.py",
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
    incompatible = COMPATIBILITY_TEST_FILES - groups["fast"]
    if incompatible:
        raise ValueError(
            "compatibility tests must belong to the fast group: "
            f"{sorted(incompatible)}"
        )
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


def run_file(filename, capture_output=False):
    return subprocess.run(
        [sys.executable, str(TEST_DIR / filename)],
        cwd=ROOT,
        check=False,
        text=capture_output,
        stdout=subprocess.PIPE if capture_output else None,
        stderr=subprocess.STDOUT if capture_output else None,
    )


def print_captured_result(filename, completed):
    print(f"::group::{filename}", flush=True)
    if completed.stdout:
        print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
    print("::endgroup::", flush=True)


def run_files(files, workers=1):
    if workers < 1:
        raise ValueError("workers must be positive")
    ordered = sorted(files)
    parallel = [name for name in ordered if name not in SERIAL_TEST_FILES]
    serial = [name for name in ordered if name in SERIAL_TEST_FILES]

    for offset in range(0, len(parallel), workers):
        batch = parallel[offset : offset + workers]
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(workers, len(batch))
        ) as executor:
            futures = {
                filename: executor.submit(run_file, filename, True)
                for filename in batch
            }
            completed_batch = {
                filename: futures[filename].result() for filename in batch
            }
        for filename in batch:
            completed = completed_batch[filename]
            print_captured_result(filename, completed)
            if completed.returncode:
                return completed.returncode

    for filename in serial:
        print(f"::group::{filename}", flush=True)
        completed = run_file(filename)
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
    parser.add_argument(
        "group",
        choices=("fast", "artifacts", "context", "compatibility", "check"),
    )
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    groups = test_groups()
    if args.group == "check":
        for name, files in groups.items():
            print(f"{name}: {len(files)} files")
        print(f"compatibility: {len(COMPATIBILITY_TEST_FILES)} fast-file subset")
        return
    if args.group == "context":
        if args.workers != 1:
            parser.error("context shards do not support --workers")
        raise SystemExit(run_context_shard(args.shard_index, args.shard_count))
    if args.shard_index != 0 or args.shard_count != 1:
        parser.error("shard options are supported only for the context group")
    files = (
        COMPATIBILITY_TEST_FILES
        if args.group == "compatibility"
        else groups[args.group]
    )
    try:
        raise SystemExit(run_files(files, workers=args.workers))
    except ValueError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
