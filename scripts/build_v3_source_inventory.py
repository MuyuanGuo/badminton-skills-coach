#!/usr/bin/env python3
"""Build or check the sanitized v3 source-input inventory."""

import argparse
import json
from pathlib import Path

from v3.canonical import read_json
from v3.inventory import (
    build_source_inventory,
    validate_inventory_source_coverage,
    validate_source_inventory,
    write_source_inventory,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data/v3/source-inventory.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--check-local-inputs", action="store_true")
    args = parser.parse_args()
    if args.check and args.check_local_inputs:
        parser.error("choose --check or --check-local-inputs")
    if args.check_local_inputs:
        expected = build_source_inventory(
            ROOT,
            ROOT / "data/knowledge/douyin_knowledge_base.json",
            ROOT / "config/douyin_source.json",
        )
        if not args.output.is_file() or read_json(args.output) != expected:
            raise SystemExit("v3 source inventory is stale; rebuild it")
        result = expected
    elif args.check:
        result = read_json(args.output)
        validate_source_inventory(result)
        validate_inventory_source_coverage(
            result,
            ROOT / "data/knowledge/douyin_knowledge_base.json",
            ROOT / "config/douyin_source.json",
        )
    else:
        result = write_source_inventory(ROOT, args.output)
    print(json.dumps(result["summary"], ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
