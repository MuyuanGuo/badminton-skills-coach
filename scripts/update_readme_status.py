#!/usr/bin/env python3
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
VIDEO_INDEX = ROOT / "data" / "douyin_video_index.json"
KNOWLEDGE = ROOT / "data" / "knowledge" / "douyin_knowledge_base.json"
REVIEW_QUEUE = ROOT / "data" / "review" / "visual_review_queue.json"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def current_contents_section():
    video_index = load_json(VIDEO_INDEX)
    knowledge = load_json(KNOWLEDGE)
    review_queue = load_json(REVIEW_QUEUE)

    ready_videos = [
        video
        for video in knowledge["videos"]
        if video["processing_status"] == "ready"
    ]
    if not ready_videos:
        raise SystemExit("No ready teaching videos found in knowledge base")

    latest = ready_videos[0]
    all_count = len(video_index["videos"])
    ready_count = len(ready_videos)
    excluded_count = all_count - ready_count
    processed_count = len(knowledge["videos"])
    pending_review = review_queue["total_pending"]

    return f"""## 当前内容 / Current Contents

**中文**

- 获取到的抖音公开视频：`{all_count}` 条
- 已排除非教学/广告器材内容：`{excluded_count}` 条
- 可加入 Skill 知识库的教学视频：`{ready_count}` 条
- 已完成处理流水线：`{processed_count}` 条
- 待视觉复核：`{pending_review}` 条
- 最新入库教学视频：[{latest["title"]}]({latest["url"]})（`{latest["video_id"]}`）
- Codex Skill：`skills/liuhui-badminton-coach/`
- 全量思维图：`output/liuhui-full-knowledge-map.drawio`

**English**

- Public Douyin videos collected: `{all_count}`
- Excluded as non-teaching, ads, or equipment-only content: `{excluded_count}`
- Teaching videos usable in the Skill knowledge base: `{ready_count}`
- Processed through the pipeline: `{processed_count}`
- Pending visual review: `{pending_review}`
- Latest teaching video added to the knowledge base: [{latest["title"]}]({latest["url"]}) (`{latest["video_id"]}`)
- Codex Skill: `skills/liuhui-badminton-coach/`
- Full topic map: `output/liuhui-full-knowledge-map.drawio`
"""


def main():
    readme = README.read_text(encoding="utf-8")
    replacement = current_contents_section()
    updated = re.sub(
        r"## 当前内容 / Current Contents\n.*?(?=\n## 仓库结构 / Repository Layout)",
        replacement,
        readme,
        flags=re.DOTALL,
    )
    if updated == readme:
        raise SystemExit("README current-contents section was not found or unchanged")
    README.write_text(updated, encoding="utf-8")
    print(json.dumps({"updated": str(README.relative_to(ROOT))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
