#!/usr/bin/env python3
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "web"))

from server import answer_query  # noqa: E402


def main():
    answer = answer_query(
        "我想系统学杀球，按什么顺序学最合理？",
        "learning_path",
    )
    if answer["mode"] != "learning_path":
        raise SystemExit("Expected learning_path mode")
    if not answer["search"]["results"]:
        raise SystemExit("Expected evidence results")
    if "学习顺序" not in answer["answer"]:
        raise SystemExit("Expected learning path section")
    print(
        json.dumps(
            {"ok": True, "mode": answer["mode"], "sources": len(answer["search"]["results"])},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
