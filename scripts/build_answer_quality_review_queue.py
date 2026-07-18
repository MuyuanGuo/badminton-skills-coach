#!/usr/bin/env python3
import argparse
import importlib.util
from collections import Counter
from pathlib import Path

from evaluate_answer_quality import (
    DEFAULT_CASES_PATH,
    DEFAULT_RULES_PATH,
    KNOWLEDGE_PATH,
    case_is_regression_ready,
    load_json,
    ready_video_ids,
    validate_registry,
)
from apply_answer_quality_review_notes import (
    ReviewApplicationError,
    extract_review_blocks,
    render_review_block,
    render_review_payload,
)


ROOT = Path(__file__).resolve().parents[1]
SEARCH_PATH = (
    ROOT
    / "skills"
    / "liuhui-badminton-coach"
    / "scripts"
    / "search_knowledge.py"
)
DEFAULT_OUTPUT = ROOT / "output" / "answer_quality_review_queue.md"


def load_search_module():
    spec = importlib.util.spec_from_file_location("answer_quality_queue_search", SEARCH_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def video_line(video_id, videos_by_id, label):
    video = videos_by_id.get(video_id)
    if not video:
        return f"- {label}: `{video_id}`（知识库中未找到）"
    return f"- {label}: [{video['title']}]({video['url']}) (`{video_id}`)"


def render_review_queue(
    registry, rules, knowledge, suggestion_limit, existing_review_blocks=None
):
    ready_ids = ready_video_ids(knowledge)
    summary = validate_registry(
        registry,
        rules,
        ready_ids,
        minimum_cases=30,
        all_video_ids={video["video_id"] for video in knowledge["videos"]},
    )
    search_module = load_search_module()
    videos_by_id = {video["video_id"]: video for video in knowledge["videos"]}
    type_counts = Counter(case["case_type"] for case in registry["cases"])
    lines = [
        "# 回答质量黄金集审核队列",
        "",
        f"知识库版本：`{knowledge['updated_at']}`",
        f"候选问题：`{summary['cases']}`",
        f"可进入自动回归：`{summary['regression_ready']}`",
        f"仍待审核：`{summary['pending_review']}`",
        "",
        "问题类型："
        + "、".join(f"`{name}` {count} 条" for name, count in sorted(type_counts.items())),
        "",
        "## 审核方法",
        "",
        "1. 维护者核对问题理解、推荐视频、转写和 Review notes，写出必须覆盖的文字要点、证据视频、适用边界和禁止断言。",
        "2. 审核关注来源忠实度和用户问题是否被正确理解；回答质量通过自动回归与后续用户反馈持续改进。",
        "3. 在每题的 `Review notes` JSON 块中填写审核意见；不要改字段名或删除案例。",
        "4. 先运行 `python3 scripts/apply_answer_quality_review_notes.py --dry-run` 校验，再去掉 `--dry-run` 原子写回黄金集。",
        "5. 机器候选只是减轻找视频的工作量，不是黄金答案；`draft` 案例不会进入自动回答回归。",
        "",
    ]

    for case in registry["cases"]:
        gold = case["gold"]
        required_ids = list(gold["required_video_ids"])
        payload = search_module.search(
            case["query"],
            limit=suggestion_limit,
            manifest_limit=max(suggestion_limit * 2, 10),
            local_personalization=False,
        )
        suggested = [
            item["video_id"]
            for item in payload["results"]
            if item["video_id"] not in set(required_ids)
        ][:suggestion_limit]
        lines.extend(
            [
                f"## {case['case_id']} · {case['query']}",
                "",
                f"- 类型：`{case['case_type']}`",
                f"- 预期模式：`{case['expected_mode']}`",
                f"- 来源：`{case['provenance']}`",
                f"- 当前状态：`{case['review']['status']}`",
                f"- 自动回归资格：{'已有' if case_is_regression_ready(case) else '暂无'}",
                "",
                "### 已有视频标签",
                "",
            ]
        )
        if required_ids:
            primary_ids = set(gold["primary_video_ids"])
            for video_id in required_ids:
                label = "主证据候选" if video_id in primary_ids else "必看候选"
                lines.append(video_line(video_id, videos_by_id, label))
        else:
            lines.append("- 暂无人工确认的视频标签。")

        lines.extend(["", "### 机器补充候选", ""])
        if suggested:
            for video_id in suggested:
                lines.append(video_line(video_id, videos_by_id, "机器候选"))
        else:
            lines.append("- 没有额外候选。")

        lines.extend(
            [
                "",
                "### Review notes",
                "",
                (
                    render_review_payload(existing_review_blocks[case["case_id"]])
                    if existing_review_blocks
                    and case["case_id"] in existing_review_blocks
                    else render_review_block(case)
                ),
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def main():
    parser = argparse.ArgumentParser(
        description="Build a source-review queue for answer quality regression cases."
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--suggestion-limit", type=int, default=3)
    args = parser.parse_args()
    if args.suggestion_limit < 1:
        raise SystemExit("--suggestion-limit must be positive")

    existing_review_blocks = {}
    if args.output.exists():
        existing_text = args.output.read_text(encoding="utf-8")
        try:
            existing_review_blocks = extract_review_blocks(
                existing_text
            )
        except ReviewApplicationError as error:
            if '"maintainer_decision"' in existing_text or "```json" in existing_text:
                raise SystemExit(
                    "Existing structured review notes are invalid; refusing to overwrite: "
                    + str(error)
                ) from error
    text = render_review_queue(
        load_json(args.cases),
        load_json(args.rules),
        load_json(KNOWLEDGE_PATH),
        args.suggestion_limit,
        existing_review_blocks=existing_review_blocks,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
