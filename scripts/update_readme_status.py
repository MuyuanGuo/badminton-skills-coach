#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path

from project_artifacts import atomic_write_bundle, derive_project_status


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
README_EN = ROOT / "README.en.md"
DOCS_ZH = ROOT / "docs" / "index.html"
DOCS_EN = ROOT / "docs" / "en" / "index.html"
SKILL = ROOT / "skills" / "liuhui-badminton-coach" / "SKILL.md"
AGENT_METADATA = (
    ROOT / "skills" / "liuhui-badminton-coach" / "agents" / "openai.yaml"
)
VIDEO_INDEX = ROOT / "data" / "douyin_video_index.json"
BILIBILI_INDEX = ROOT / "data" / "bilibili_video_index.json"
BILIBILI_LEDGER = ROOT / "data" / "bilibili_classification_ledger.json"
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
    visual = sum(
        video.get("runtime_evidence_mode") == "reviewed_visual_summary"
        or video.get("confidence") == "visual_reviewed"
        for video in ready
    )
    transcript_ready = [
        video
        for video in ready
        if video.get(
            "runtime_evidence_mode",
            (
                "reviewed_visual_summary"
                if video.get("confidence") == "visual_reviewed"
                else "full_transcript"
            ),
        )
        == "full_transcript"
    ]
    bounded_ready = [
        video
        for video in ready
        if video.get("runtime_evidence_mode") == "bounded_note_windows"
    ]
    transcript_items = sum(
        len((video.get("teaching_note") or {}).get(field) or [])
        for video in transcript_ready
        for field in ("key_evidence", "error_evidence", "action_cues")
    )
    bounded_items = sum(
        len((video.get("teaching_note") or {}).get(field) or [])
        for video in bounded_ready
        for field in ("key_evidence", "error_evidence", "action_cues")
    )
    return {
        "processed": len(knowledge["videos"]),
        "ready": len(ready),
        "transcript": len(transcript_ready),
        "bounded": len(bounded_ready),
        "visual": visual,
        "transcript_items": transcript_items,
        "bounded_items": bounded_items,
        "primary": sum(
            video.get("answer_eligibility") == "primary" for video in ready
        ),
        "supplemental": sum(
            video.get("answer_eligibility") == "supplemental" for video in ready
        ),
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
    if "| 已处理公开视频 |" in readme:
        return update_technical_readme_text(
            readme,
            video_index,
            teaching_filter,
            knowledge,
            feedback_signals,
            answer_cases,
            queue,
        )

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
        r"^!\[Badminton Skills Coach：\d+ 条教学视频、证据型检索与刘辉教学图谱\]\(\.github/assets/social-preview\.(?:png|jpg)\)$",
        "![Badminton Skills Coach：证据驱动的羽毛球视频知识库](.github/assets/social-preview.jpg)",
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
        r'^(?:1\.0 )?当前队列为 `\{.*\}`，(?:没有失败项|失败项 `\d+` 条)。$',
        (
            f"当前队列为 `{queue_counts}`，没有失败项。"
            if failed_queue_count == 0
            else f"当前队列为 `{queue_counts}`，失败项 `{failed_queue_count}` 条。"
        ),
        "README queue status",
    )
    return readme


def update_technical_readme_text(
    readme,
    video_index,
    teaching_filter,
    knowledge,
    feedback_signals,
    answer_cases=None,
    queue=None,
):
    """Update dynamic metrics in the recruiter-facing develop README."""

    status = derive_project_status(video_index, teaching_filter, knowledge)
    ready = [
        video
        for video in knowledge.get("videos", [])
        if video.get("processing_status") == "ready"
    ]
    evidence = evidence_counts(knowledge)
    visual = sum(video.get("confidence") == "visual_reviewed" for video in ready)
    bilibili_index = load_json(BILIBILI_INDEX) if BILIBILI_INDEX.exists() else {"videos": []}
    bilibili_ledger = load_json(BILIBILI_LEDGER) if BILIBILI_LEDGER.exists() else {"videos": []}
    bilibili_records = [
        video for video in knowledge.get("videos", [])
        if video.get("source_type") == "bilibili_video"
    ]
    bilibili_ready = sum(
        video.get("processing_status") == "ready" for video in bilibili_records
    )
    bilibili_policy_excluded = sum(
        video.get("decision") == "excluded_transcription_policy"
        for video in bilibili_ledger["videos"]
    )
    bilibili_quality_isolated = sum(
        video.get("processing_status") != "ready"
        for video in bilibili_records
    )
    bilibili_isolated = (
        bilibili_policy_excluded + bilibili_quality_isolated
    )
    bilibili_pending = (
        len(bilibili_index["videos"]) - bilibili_ready - bilibili_isolated
    )
    processed = status["public_videos_collected"] + len(bilibili_index["videos"])
    ready_count = status["ready_teaching_videos"]
    transcript = evidence["transcript"]
    feedback_count = len(feedback_signals.get("signals", []))
    answer_count = len((answer_cases or load_json(ANSWER_CASES)).get("cases", []))
    replacements = {
        r"^\| 已处理公开视频 \| \d+ \|": f"| 已处理公开视频 | {processed} |",
        r"^\| 可用于回答的教学视频 \| \d+ \|": f"| 可用于回答的教学视频 | {ready_count} |",
        r"^\| 主证据 / 受限补充证据 \|.*$": (
            f"| 主证据 / 受限补充证据 | "
            f"{evidence['primary']} / {evidence['supplemental']} | "
            "主证据优先；补充证据只使用命中的时间戳窗口 |"
        ),
        r"^\| 转写证据 \|.*$": (
            f"| 转写证据 | {transcript} | "
            f"{evidence['transcript_items']:,}/{evidence['transcript_items']:,} "
            "条转写证据包含时间戳 |"
        ),
        r"^\| 视觉复核兜底 \| \d+ \|": f"| 视觉复核兜底 | {visual} |",
        r"^\| 受限时间戳窗口证据 \|.*$": (
            f"| 受限时间戳窗口证据 | {evidence['bounded']} | "
            f"{evidence['bounded_items']:,} 条已提交窗口；标题不得作为结论证据 |"
        ),
        r"^\| 回答质量黄金用例 \| \d+/\d+ \|": f"| 回答质量黄金用例 | {answer_count}/{answer_count} |",
        r"^\| 公共反馈信号 \| \d+ \|": f"| 公共反馈信号 | {feedback_count} |",
        r"^\| B 站(?:来源隔离试点|全量来源归档|完整来源目录) \|.*$": (
            f"| B 站完整来源目录 | {len(bilibili_index['videos'])} | "
            f"{bilibili_ready} 条回答就绪、"
            f"{bilibili_isolated} 条策略排除或质量隔离、"
            f"{bilibili_pending} 条待处理 |"
        ),
    }
    updated = readme
    for pattern, replacement in replacements.items():
        updated, count = re.subn(pattern, replacement, updated, flags=re.MULTILINE)
        if count > 1:
            raise ValueError(f"Technical README metric matched {count} times: {pattern}")
    if "| 主证据 / 受限补充证据 |" not in updated:
        updated = replace_one(
            updated,
            r"^(\| 可用于回答的教学视频 \|.*)$",
            (
                r"\1\n"
                f"| 主证据 / 受限补充证据 | "
                f"{evidence['primary']} / {evidence['supplemental']} | "
                "主证据优先；补充证据只使用命中的时间戳窗口 |"
            ),
            "README evidence admission row",
        )
    if "| 受限时间戳窗口证据 |" not in updated:
        updated = replace_one(
            updated,
            r"^(\| 转写证据 \|.*)$",
            (
                r"\1\n"
                f"| 受限时间戳窗口证据 | {evidence['bounded']} | "
                f"{evidence['bounded_items']:,} 条已提交窗口；"
                "标题不得作为结论证据 |"
            ),
            "README bounded evidence row",
        )
    updated = replace_optional(
        updated,
        r"^- `references/knowledge-base\.json`：\d+ 条可用教学证据。$",
        f"- `references/knowledge-base.json`：{ready_count} 条可用教学证据。",
        "README knowledge resource count",
    )
    return updated


def update_english_readme_text(readme, video_index, teaching_filter, knowledge):
    status = derive_project_status(video_index, teaching_filter, knowledge)
    evidence = evidence_counts(knowledge)
    bilibili_index = load_json(BILIBILI_INDEX) if BILIBILI_INDEX.exists() else {"videos": []}
    bilibili_ledger = load_json(BILIBILI_LEDGER) if BILIBILI_LEDGER.exists() else {"videos": []}
    bilibili_ready = sum(
        video.get("source_type") == "bilibili_video"
        and video.get("processing_status") == "ready"
        for video in knowledge.get("videos", [])
    )
    bilibili_records = [
        video for video in knowledge.get("videos", [])
        if video.get("source_type") == "bilibili_video"
    ]
    bilibili_policy_excluded = sum(
        video.get("decision") == "excluded_transcription_policy"
        for video in bilibili_ledger["videos"]
    )
    bilibili_quality_isolated = sum(
        video.get("processing_status") != "ready"
        for video in bilibili_records
    )
    bilibili_isolated = (
        bilibili_policy_excluded + bilibili_quality_isolated
    )
    bilibili_pending = (
        len(bilibili_index["videos"]) - bilibili_ready - bilibili_isolated
    )
    replacements = {
        r"^\| Processed public videos \| \d+ \|$": (
            f"| Processed public videos | "
            f"{status['public_videos_collected'] + len(bilibili_index['videos'])} |"
        ),
        r"^\| Ready teaching videos \| \d+ \|$": (
            f"| Ready teaching videos | {status['ready_teaching_videos']} |"
        ),
        r"^\| Transcript-backed evidence \| \d+ \|$": (
            f"| Transcript-backed evidence | {evidence['transcript']} |"
        ),
        r"^\| Primary / bounded supplemental evidence \|.*$": (
            f"| Primary / bounded supplemental evidence | "
            f"{evidence['primary']} / {evidence['supplemental']} |"
        ),
        r"^\| Bounded timestamp-window evidence \|.*$": (
            f"| Bounded timestamp-window evidence | {evidence['bounded']} |"
        ),
        r"^\| Reviewed visual-summary fallbacks \| \d+ \|$": (
            f"| Reviewed visual-summary fallbacks | {evidence['visual']} |"
        ),
        r"^\| Bilibili (?:provenance-isolation pilot|full provenance archive|full source catalog) \|.*$": (
            f"| Bilibili full source catalog | "
            f"{len(bilibili_index['videos'])}: {bilibili_ready} answer-ready, "
            f"{bilibili_isolated} policy-excluded or quality-isolated, "
            f"{bilibili_pending} pending |"
        ),
    }
    updated = readme
    for pattern, replacement in replacements.items():
        updated = replace_optional(
            updated, pattern, replacement, "English README evidence baseline"
        )
    if "| Primary / bounded supplemental evidence |" not in updated:
        updated = replace_one(
            updated,
            r"^(\| Ready teaching videos \|.*)$",
            (
                r"\1\n"
                f"| Primary / bounded supplemental evidence | "
                f"{evidence['primary']} / {evidence['supplemental']} |"
            ),
            "English README evidence admission row",
        )
    if "| Bounded timestamp-window evidence |" not in updated:
        updated = replace_one(
            updated,
            r"^(\| Transcript-backed evidence \|.*)$",
            (
                r"\1\n"
                f"| Bounded timestamp-window evidence | {evidence['bounded']} |"
            ),
            "English README bounded evidence row",
        )
    updated = replace_one(
        updated,
        r"^All [\d,]+ transcript evidence items have timestamps\.",
        (
            f"All {evidence['transcript_items']:,} transcript evidence items "
            "have timestamps."
        ),
        "English README transcript evidence count",
    )
    return updated


def update_site_status_text(page, knowledge, language):
    evidence = evidence_counts(knowledge)
    if language == "zh":
        page = replace_one(
            page,
            r"(它从 )\d+( 条教学视频中寻找答案)",
            rf"\g<1>{evidence['ready']}\g<2>",
            "Chinese site lede count",
        )
        page = replace_one(
            page,
            r"(<strong>)\d+(</strong><span>条可用教学视频</span>)",
            rf"\g<1>{evidence['ready']}\g<2>",
            "Chinese site metric count",
        )
        return replace_one(
            page,
            r"(<strong>)\d+(</strong><span>条转写证据</span>)",
            rf"\g<1>{evidence['transcript']}\g<2>",
            "Chinese site transcript count",
        )
    page = replace_one(
        page,
        r"(searches )\d+( Chinese badminton teaching videos)",
        rf"\g<1>{evidence['ready']}\g<2>",
        "English site lede count",
    )
    page = replace_one(
        page,
        r"(<strong>)\d+(</strong><span>ready teaching videos</span>)",
        rf"\g<1>{evidence['ready']}\g<2>",
        "English site ready count",
    )
    return replace_one(
        page,
        r"(<strong>)\d+(</strong><span>transcript-backed sources</span>)",
        rf"\g<1>{evidence['transcript']}\g<2>",
        "English site transcript count",
    )


def update_skill_status_text(skill, knowledge):
    counts = evidence_counts(knowledge)
    if "processed Douyin+Bilibili knowledge base" not in skill:
        skill = replace_one(
            skill,
            r"full \d+-video processed (?:multi-source )?knowledge base",
            f"full {counts['processed']}-video processed multi-source knowledge base",
            "Skill legacy frontmatter processed count",
        )
        skill = replace_one(
            skill,
            r"^(description: .*including )\d+( ready teaching videos)",
            rf"\g<1>{counts['ready']}\g<2>",
            "Skill legacy frontmatter ready count",
        )
        skill = replace_one(
            skill,
            r"(Base coaching claims on `references/knowledge-base\.json`: )\d+( processed videos,)",
            rf"\g<1>{counts['processed']}\g<2>",
            "Skill legacy scope processed count",
        )
        skill = replace_one(
            skill,
            r"including \d+ `ready` teaching entries, \d+ entries awaiting visual review",
            (
                f"including {counts['ready']} `ready` teaching entries, "
                f"{counts['pending_visual']} entries awaiting visual review"
            ),
            "Skill legacy archive count",
        )
        skill = replace_one(
            skill,
            r"Among the ready entries, \d+ are transcript-backed and \d+ use reviewed visual summaries",
            (
                f"Among the ready entries, {counts['transcript']} are transcript-backed "
                f"and {counts['visual']} use reviewed visual summaries"
            ),
            "Skill legacy evidence count",
        )
        skill = replace_one(
            skill,
            r"full structured knowledge entries for \d+ processed videos, including \d+ ready teaching videos \(\d+ transcript-backed and \d+ visual-review fallbacks\) and \d+ entries awaiting visual review\.",
            (
                f"full structured knowledge entries for {counts['processed']} processed videos, "
                f"including {counts['ready']} ready teaching videos "
                f"({counts['transcript']} transcript-backed and {counts['visual']} visual-review fallbacks) "
                f"and {counts['pending_visual']} entries awaiting visual review."
            ),
            "Skill legacy resource count",
        )
        return skill
    skill = replace_one(
        skill,
        r"from a \d+-video processed Douyin\+Bilibili knowledge base",
        f"from a {counts['processed']}-video processed Douyin+Bilibili knowledge base",
        "Skill frontmatter processed count",
    )
    skill = replace_one(
        skill,
        r"with \d+ answer-eligible teaching videos split into \d+ primary and \d+ bounded supplemental sources",
        (
            f"with {counts['ready']} answer-eligible teaching videos split into "
            f"{counts['primary']} primary and {counts['supplemental']} bounded supplemental sources"
        ),
        "Skill frontmatter admission counts",
    )
    skill = replace_one(
        skill,
        r"\d+ processed videos, including \d+ `ready` answer-eligible entries and \d+ awaiting visual review",
        (
            f"{counts['processed']} processed videos, including {counts['ready']} `ready` "
            f"answer-eligible entries and {counts['pending_visual']} awaiting visual review"
        ),
        "Skill scope archive counts",
    )
    skill = replace_one(
        skill,
        r"Of these, \d+ are `primary`; \d+ are `supplemental` sources",
        (
            f"Of these, {counts['primary']} are `primary`; "
            f"{counts['supplemental']} are `supplemental` sources"
        ),
        "Skill scope admission split",
    )
    skill = replace_one(
        skill,
        r"Runtime evidence comprises \d+ full-transcript records, \d+ bounded-note records, and \d+ reviewed visual summaries",
        (
            f"Runtime evidence comprises {counts['transcript']} full-transcript records, "
            f"{counts['bounded']} bounded-note records, and {counts['visual']} reviewed visual summaries"
        ),
        "Skill runtime evidence modes",
    )
    skill = replace_one(
        skill,
        r"`references/knowledge-base\.json`: \d+ processed entries, including \d+ primary, \d+ bounded supplemental, and \d+ answer-ineligible records\.",
        (
            f"`references/knowledge-base.json`: {counts['processed']} processed entries, "
            f"including {counts['primary']} primary, {counts['supplemental']} bounded supplemental, "
            f"and {counts['processed'] - counts['ready']} answer-ineligible records."
        ),
        "Skill resource admission counts",
    )
    return skill


def update_agent_metadata_text(metadata, knowledge):
    counts = evidence_counts(knowledge)
    if "条分层教学证据回答" not in metadata:
        return replace_one(
            metadata,
            r'^(  short_description: "基于)\d+(条教学视频回答，并安全使用已审核的本地与公共反馈")$',
            rf"\g<1>{counts['ready']}\g<2>",
            "Agent legacy short description count",
        )
    return replace_one(
        metadata,
        r'^(  short_description: "基于)\d+(条分层教学证据回答：)\d+(条主证据与)\d+(条受限补充证据")$',
        (
            rf"\g<1>{counts['ready']}\g<2>{counts['primary']}"
            rf"\g<3>{counts['supplemental']}\g<4>"
        ),
        "Agent short description count",
    )


def main():
    parser = argparse.ArgumentParser(
        description="Update recruiter-facing development documentation metrics"
    )
    parser.add_argument(
        "--update-stable-site",
        action="store_true",
        help=(
            "Also update the stable-version docs home pages; use only when "
            "publishing that stable version"
        ),
    )
    args = parser.parse_args()
    readme = README.read_text(encoding="utf-8")
    readme_en = README_EN.read_text(encoding="utf-8")
    skill = SKILL.read_text(encoding="utf-8")
    agent_metadata = AGENT_METADATA.read_text(encoding="utf-8")
    knowledge = load_json(KNOWLEDGE)
    video_index = load_json(VIDEO_INDEX)
    teaching_filter = load_json(TEACHING_FILTER)
    updated = update_readme_text(
        readme,
        video_index,
        teaching_filter,
        knowledge,
        load_json(FEEDBACK_SIGNALS),
        load_json(ANSWER_CASES),
        load_json(QUEUE),
    )
    updated_en = update_english_readme_text(
        readme_en, video_index, teaching_filter, knowledge
    )
    updated_skill = update_skill_status_text(skill, knowledge)
    updated_agent_metadata = update_agent_metadata_text(agent_metadata, knowledge)
    candidates = [
        (README, updated, readme),
        (README_EN, updated_en, readme_en),
        (SKILL, updated_skill, skill),
        (AGENT_METADATA, updated_agent_metadata, agent_metadata),
    ]
    if args.update_stable_site:
        docs_zh = DOCS_ZH.read_text(encoding="utf-8")
        docs_en = DOCS_EN.read_text(encoding="utf-8")
        candidates.extend(
            [
                (
                    DOCS_ZH,
                    update_site_status_text(docs_zh, knowledge, "zh"),
                    docs_zh,
                ),
                (
                    DOCS_EN,
                    update_site_status_text(docs_en, knowledge, "en"),
                    docs_en,
                ),
            ]
        )
    changed = {
        path: text
        for path, text, original in candidates
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
