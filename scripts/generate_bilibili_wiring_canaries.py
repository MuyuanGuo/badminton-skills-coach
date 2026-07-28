#!/usr/bin/env python3
"""Generate deterministic mechanical Bilibili wiring canaries."""

import argparse
import json
from pathlib import Path

from bilibili_wiring_canary import generate_registry


ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_PATH = ROOT / "data" / "knowledge" / "douyin_knowledge_base.json"
RETRIEVAL_INDEX_PATH = ROOT / "data" / "knowledge" / "retrieval_index.json"
QUALITY_RULES_PATH = ROOT / "config" / "knowledge_quality_rules.json"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--knowledge", type=Path, default=KNOWLEDGE_PATH)
    parser.add_argument(
        "--retrieval-index", type=Path, default=RETRIEVAL_INDEX_PATH
    )
    parser.add_argument("--quality-rules", type=Path, default=QUALITY_RULES_PATH)
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the registry atomically; omit to print it without changing files.",
    )
    args = parser.parse_args()
    registry = generate_registry(
        load_json(args.knowledge),
        load_json(args.retrieval_index),
        load_json(args.quality_rules),
    )
    serialized = json.dumps(registry, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        from project_artifacts import atomic_write_text

        atomic_write_text(args.output, serialized)
    else:
        print(serialized, end="")


if __name__ == "__main__":
    main()
