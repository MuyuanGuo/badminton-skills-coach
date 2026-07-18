#!/usr/bin/env python3
import json
import re
from pathlib import Path

from project_artifacts import atomic_write_text, derive_project_status


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
VIDEO_INDEX = ROOT / "data" / "douyin_video_index.json"
TEACHING_FILTER = ROOT / "data" / "douyin_teaching_filtered.json"
KNOWLEDGE = ROOT / "data" / "knowledge" / "douyin_knowledge_base.json"
FEEDBACK_SIGNALS = ROOT / "config" / "feedback_signals.json"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def replace_one(text, pattern, replacement):
    updated, count = re.subn(pattern, replacement, text, flags=re.MULTILINE)
    if count != 1:
        raise ValueError(f"README status pattern matched {count} times: {pattern}")
    return updated


def update_readme_text(
    readme, video_index, teaching_filter, knowledge, feedback_signals
):
    status = derive_project_status(video_index, teaching_filter, knowledge)
    latest = status["latest_ready_video"]
    all_count = status["public_videos_collected"]
    ready_count = status["ready_teaching_videos"]
    excluded_count = status["excluded_non_teaching_ads_equipment"]
    pending_count = status["pending_human_review_or_processing"]
    promoted_count = len(feedback_signals["signals"])
    promoted_note = (
        "流水线已就绪，尚无真实 GitHub 反馈被晋升"
        if promoted_count == 0
        else "已通过公开来源、人工核证和回归测试"
    )

    readme = replace_one(
        readme,
        r"^- 获取到的抖音公开视频：`\d+` 条$",
        f"- 获取到的抖音公开视频：`{all_count}` 条",
    )
    readme = replace_one(
        readme,
        r"^- 已排除非教学/广告器材内容：`\d+` 条$",
        f"- 已排除非教学/广告器材内容：`{excluded_count}` 条",
    )
    readme = replace_one(
        readme,
        r"^- 已加入 Skill 知识库的教学视频：`\d+` 条$",
        f"- 已加入 Skill 知识库的教学视频：`{ready_count}` 条",
    )
    readme = replace_one(
        readme,
        r"^- 等待人工复核：`\d+` 条$",
        f"- 等待人工复核：`{pending_count}` 条",
    )
    readme = replace_one(
        readme,
        r"^- 最新入库教学视频:.*$|^- 最新入库教学视频：.*$",
        f'- 最新入库教学视频：[{latest["title"]}]({latest["url"]})（`{latest["video_id"]}`）',
    )
    readme = replace_one(
        readme,
        r"^- 已晋升公共反馈信号：`\d+` 条（.*）$",
        f"- 已晋升公共反馈信号：`{promoted_count}` 条（{promoted_note}）",
    )
    return readme


def main():
    readme = README.read_text(encoding="utf-8")
    updated = update_readme_text(
        readme,
        load_json(VIDEO_INDEX),
        load_json(TEACHING_FILTER),
        load_json(KNOWLEDGE),
        load_json(FEEDBACK_SIGNALS),
    )
    if updated == readme:
        print(json.dumps({"updated": None, "reason": "already_current"}, ensure_ascii=False))
        return
    atomic_write_text(README, updated)
    print(json.dumps({"updated": str(README.relative_to(ROOT))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
