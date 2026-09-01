#!/usr/bin/env python3
"""Maintainer CLI for the isolated v3 evidence pipeline."""

import argparse
import json
from pathlib import Path
from typing import Any

from v3.audit import audit_public_v3_tree, audit_shadow_artifacts
from v3.build import build_shadow_artifacts
from v3.ledger import ReviewLedger
from v3.publication import write_publication
from v3.routing import write_pilot_review_queue
from v3.runtime import shadow_answer_packet


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    initialize = subparsers.add_parser("init-ledger")
    initialize.add_argument(
        "--ledger", type=Path, default=ROOT / ".local/v3/review/review-ledger.sqlite3"
    )

    verify = subparsers.add_parser("verify-ledger")
    verify.add_argument(
        "--ledger", type=Path, default=ROOT / ".local/v3/review/review-ledger.sqlite3"
    )

    export = subparsers.add_parser("export-publication")
    export.add_argument(
        "--ledger", type=Path, default=ROOT / ".local/v3/review/review-ledger.sqlite3"
    )
    export.add_argument(
        "--publication", type=Path, default=ROOT / "data/v3/publication.json"
    )
    export.add_argument(
        "--topic",
        dest="topics",
        action="append",
        help="Export only this approved topic; repeat to select several topics.",
    )

    build = subparsers.add_parser("build-shadow")
    build.add_argument(
        "--publication", type=Path, default=ROOT / "data/v3/publication.json"
    )
    build.add_argument(
        "--runtime", type=Path, default=ROOT / ".local/v3/build/shadow-runtime.sqlite3"
    )
    build.add_argument(
        "--manifest", type=Path, default=ROOT / "data/v3/build-manifest.json"
    )

    audit = subparsers.add_parser("audit-shadow")
    audit.add_argument(
        "--publication", type=Path, default=ROOT / "data/v3/publication.json"
    )
    audit.add_argument(
        "--manifest", type=Path, default=ROOT / "data/v3/build-manifest.json"
    )
    audit.add_argument("--runtime", type=Path)

    query = subparsers.add_parser("query-shadow")
    query.add_argument("query")
    query.add_argument(
        "--runtime", type=Path, default=ROOT / ".local/v3/build/shadow-runtime.sqlite3"
    )
    query.add_argument("--limit", type=int, default=5)

    pilot_queue = subparsers.add_parser("build-pilot-queue")
    pilot_queue.add_argument(
        "--output",
        type=Path,
        default=ROOT / ".local/v3/review/pilot-review-queue.json",
    )

    subparsers.add_parser("audit-public-tree")
    args = parser.parse_args()
    result: dict[str, Any]
    if args.command == "init-ledger":
        with ReviewLedger(args.ledger) as ledger:
            result = {"ledger": str(args.ledger), **ledger.verify_integrity()}
    elif args.command == "verify-ledger":
        with ReviewLedger(args.ledger) as ledger:
            result = ledger.verify_integrity()
    elif args.command == "export-publication":
        topics = None if args.topics is None else set(args.topics)
        if topics is not None and any(not topic.strip() for topic in topics):
            parser.error("--topic must not be empty")
        with ReviewLedger(args.ledger) as ledger:
            result = write_publication(ledger, args.publication, topics)
    elif args.command == "build-shadow":
        result = build_shadow_artifacts(
            args.publication, args.runtime, args.manifest
        )
    elif args.command == "audit-shadow":
        result = audit_shadow_artifacts(
            args.publication, args.manifest, args.runtime
        )
    elif args.command == "query-shadow":
        result = shadow_answer_packet(args.runtime, args.query, args.limit)
    elif args.command == "build-pilot-queue":
        queue = write_pilot_review_queue(root=ROOT, output_path=args.output)
        result = {
            "output": str(args.output),
            "routing_fingerprint": queue["routing_fingerprint"],
            "summary": queue["summary"],
        }
    else:
        result = audit_public_v3_tree(ROOT)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
