#!/usr/bin/env python3
import json
import re
from pathlib import Path

from project_artifacts import atomic_write_bundle, derive_project_status


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
SKILL = ROOT / "skills" / "liuhui-badminton-coach" / "SKILL.md"
AGENT_METADATA = (
    ROOT / "skills" / "liuhui-badminton-coach" / "agents" / "openai.yaml"
)
VIDEO_INDEX = ROOT / "data" / "douyin_video_index.json"
TEACHING_FILTER = ROOT / "data" / "douyin_teaching_filtered.json"
KNOWLEDGE = ROOT / "data" / "knowledge" / "douyin_knowledge_base.json"
FEEDBACK_SIGNALS = ROOT / "config" / "feedback_signals.json"
ANSWER_CASES = ROOT / "data" / "evaluation" / "answer_quality_cases.json"
QUEUE = ROOT / "data" / "processing" / "douyin_queue.json"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def replace_one(text, pattern, replacement, label="project status"):
    updated, count = re.subn(pattern, replacement, text, flags=re.MULTILINE)
    if count != 1:
        raise ValueError(f"{label} pattern matched {count} times: {pattern}")
    return updated


def replace_optional(text, pattern, replacement, label="project status"):
    updated, count = re.subn(pattern, replacement, text, flags=re.MULTILINE)
    if count > 1:
        raise ValueError(f"{label} pattern matched {count} times: {pattern}")
    return updated


def evidence_counts(knowledge):
    ready = [
        video
        for video in knowledge["videos"]
        if video["processing_status"] == "ready"
    ]
    visual = sum(video.get("confidence") == "visual_reviewed" for video in ready)
    return {
        "processed": len(knowledge["videos"]),
        "ready": len(ready),
        "transcript": len(ready) - visual,
        "visual": visual,
        "pending_visual": sum(
            video["processing_status"]
            in {"needs_visual_review", "needs_correction"}
            for video in knowledge["videos"]
        ),
    }


def update_readme_text(
    readme,
    video_index,
    teaching_filter,
    knowledge,
    feedback_signals,
    answer_cases=None,
    queue=None,
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
    evidence = evidence_counts(knowledge)
    answer_cases = answer_cases or load_json(ANSWER_CASES)
    probe_cases = answer_cases.get("cases", [])
    expected_video_count = sum(
        len(case.get("gold", {}).get("required_video_ids", []))
        for case in probe_cases
    )
    hard_negative_count = sum(
        len(case.get("gold", {}).get("irrelevant_video_ids", []))
        for case in probe_cases
    )
    queue = queue or load_json(QUEUE)
    queue_counts = json.dumps(
        queue.get("counts", {}), ensure_ascii=False, sort_keys=True
    )
    failed_queue_count = sum(
        count
        for status, count in queue.get("counts", {}).items()
        if status.endswith("_failed")
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
    readme = replace_optional(
        readme,
        r"^!\[Badminton Skills Coach：\d+ 条教学视频、证据型检索与刘辉教学图谱\]\(\.github/assets/social-preview\.png\)$",
        f"![Badminton Skills Coach：{ready_count} 条教学视频、证据型检索与刘辉教学图谱](.github/assets/social-preview.png)",
        "README social-preview alt text",
    )
    readme = replace_optional(
        readme,
        r"^- 可理解证据覆盖：`\d+/\d+`（`\d+` 条转写证据，`\d+` 条视觉复核摘要兜底）$",
        f"- 可理解证据覆盖：`{ready_count}/{ready_count}`（`{evidence['transcript']}` 条转写证据，`{evidence['visual']}` 条视觉复核摘要兜底）",
        "README evidence coverage",
    )
    readme = replace_optional(
        readme,
        r"^  evaluate_video_comprehension\.py  审计\d+条可移植证据、本机转写和反向召回$",
        f"  evaluate_video_comprehension.py  审计{ready_count}条可移植证据及独立问题召回",
        "legacy README script inventory",
    )
    readme = replace_optional(
        readme,
        r"^  evaluate_video_comprehension\.py  审计\d+条可移植证据及独立问题召回$",
        f"  evaluate_video_comprehension.py  审计{ready_count}条可移植证据及独立问题召回",
        "README script inventory",
    )
    readme = replace_optional(
        readme,
        r"^- 视频理解审计：GitHub Actions 对 `\d+/\d+` 条 ready 视频检查仓库内可移植的转写证据或视觉复核摘要、运行时读取和自身证据候选召回，三项覆盖率都必须为 `100%`；当前构成为 `\d+ \+ \d+`。原始转写文件不进入 Git，维护者在本机另用 `--require-raw-transcripts` 验证 \d+ 条证据都能回溯到原始转写。$",
        f"- 视频理解审计：GitHub Actions 对 `{ready_count}/{ready_count}` 条 ready 视频检查仓库内可移植的转写证据或视觉复核摘要、运行时读取、索引与分段一致性，三项覆盖率都必须为 `100%`；当前构成为 `{evidence['transcript']} + {evidence['visual']}`。另用 `{len(probe_cases)}` 个独立用户问题、`{expected_video_count}` 个已知相关视频和 `{hard_negative_count}` 个已知负样本检查检索，不再让视频用自己的证据反查自己。原始转写文件不进入 Git，维护者在本机另用 `--require-raw-transcripts` 验证 {evidence['transcript']} 条证据都能回溯到原始转写。",
        "legacy README video-comprehension audit",
    )
    readme = replace_optional(
        readme,
        r"^- 视频理解审计：GitHub Actions 对 `\d+/\d+` 条 ready 视频检查仓库内可移植的转写证据或视觉复核摘要、运行时读取、索引与分段一致性，三项覆盖率都必须为 `100%`；当前构成为 `\d+ \+ \d+`。另用 `\d+` 个独立用户问题、`\d+` 个已知相关视频和 `\d+` 个已知负样本检查检索，不再让视频用自己的证据反查自己。原始转写文件不进入 Git，维护者在本机另用 `--require-raw-transcripts` 验证 \d+ 条证据都能回溯到原始转写。$",
        f"- 视频理解审计：GitHub Actions 对 `{ready_count}/{ready_count}` 条 ready 视频检查仓库内可移植的转写证据或视觉复核摘要、运行时读取、索引与分段一致性，三项覆盖率都必须为 `100%`；当前构成为 `{evidence['transcript']} + {evidence['visual']}`。另用 `{len(probe_cases)}` 个独立用户问题、`{expected_video_count}` 个已知相关视频和 `{hard_negative_count}` 个已知负样本检查检索，不再让视频用自己的证据反查自己。原始转写文件不进入 Git，维护者在本机另用 `--require-raw-transcripts` 验证 {evidence['transcript']} 条证据都能回溯到原始转写。",
        "README video-comprehension audit",
    )
    readme = replace_optional(
        readme,
        r'^1\.0 当前队列为 `\{.*\}`，(?:没有失败项|失败项 `\d+` 条)。$',
        (
            f"1.0 当前队列为 `{queue_counts}`，没有失败项。"
            if failed_queue_count == 0
            else f"1.0 当前队列为 `{queue_counts}`，失败项 `{failed_queue_count}` 条。"
        ),
        "README queue status",
    )
    return readme


def update_skill_status_text(skill, knowledge):
    counts = evidence_counts(knowledge)
    skill = replace_one(
        skill,
        r"including \d+ ready teaching videos\.",
        f"including {counts['ready']} ready teaching videos.",
        "Skill frontmatter count",
    )
    skill = replace_one(
        skill,
        r"including \d+ `ready` teaching entries, \d+ entries awaiting visual review",
        f"including {counts['ready']} `ready` teaching entries, {counts['pending_visual']} entries awaiting visual review",
        "Skill archive count",
    )
    skill = replace_one(
        skill,
        r"Among the ready entries, \d+ are transcript-backed and \d+ use reviewed visual summaries",
        f"Among the ready entries, {counts['transcript']} are transcript-backed and {counts['visual']} use reviewed visual summaries",
        "Skill evidence count",
    )
    skill = replace_one(
        skill,
        r"full structured knowledge entries for \d+ processed videos, including \d+ ready teaching videos \(\d+ transcript-backed and \d+ visual-review fallbacks\) and \d+ entries awaiting visual review\.",
        f"full structured knowledge entries for {counts['processed']} processed videos, including {counts['ready']} ready teaching videos ({counts['transcript']} transcript-backed and {counts['visual']} visual-review fallbacks) and {counts['pending_visual']} entries awaiting visual review.",
        "Skill resource count",
    )
    return skill


def update_agent_metadata_text(metadata, knowledge):
    ready_count = evidence_counts(knowledge)["ready"]
    return replace_one(
        metadata,
        r'^(  short_description: "基于)\d+(条教学视频回答，并安全使用已审核的本地与公共反馈")$',
        rf"\g<1>{ready_count}\g<2>",
        "Agent short description count",
    )


def main():
    readme = README.read_text(encoding="utf-8")
    skill = SKILL.read_text(encoding="utf-8")
    agent_metadata = AGENT_METADATA.read_text(encoding="utf-8")
    knowledge = load_json(KNOWLEDGE)
    updated = update_readme_text(
        readme,
        load_json(VIDEO_INDEX),
        load_json(TEACHING_FILTER),
        knowledge,
        load_json(FEEDBACK_SIGNALS),
        load_json(ANSWER_CASES),
        load_json(QUEUE),
    )
    updated_skill = update_skill_status_text(skill, knowledge)
    updated_agent_metadata = update_agent_metadata_text(agent_metadata, knowledge)
    changed = {
        path: text
        for path, text, original in [
            (README, updated, readme),
            (SKILL, updated_skill, skill),
            (AGENT_METADATA, updated_agent_metadata, agent_metadata),
        ]
        if text != original
    }
    if not changed:
        print(json.dumps({"updated": None, "reason": "already_current"}, ensure_ascii=False))
        return
    atomic_write_bundle(
        {path: text.encode("utf-8") for path, text in changed.items()}
    )
    print(
        json.dumps(
            {"updated": [str(path.relative_to(ROOT)) for path in changed]},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
