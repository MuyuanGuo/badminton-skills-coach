#!/usr/bin/env python3
"""Evaluate mechanical Bilibili wiring canaries against the current Skill."""

import argparse
import importlib.util
import json
from pathlib import Path

from bilibili_wiring_canary import evaluate_registry


ROOT = Path(__file__).resolve().parents[1]
SKILL_SCRIPTS = ROOT / "skills" / "liuhui-badminton-coach" / "scripts"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registry", type=Path)
    args = parser.parse_args()
    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    search = load_module(
        "bilibili_mechanical_canary_search",
        SKILL_SCRIPTS / "search_knowledge.py",
    )
    context_runtime = load_module(
        "bilibili_mechanical_canary_context",
        SKILL_SCRIPTS / "prepare_answer_context.py",
    )
    result = evaluate_registry(registry, search, context_runtime)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
