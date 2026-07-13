# Badminton Skills Coach / 羽毛球技能教练

[![Validate Skill artifacts](https://github.com/MuyuanGuo/badminton-skills-coach/actions/workflows/validate.yml/badge.svg)](https://github.com/MuyuanGuo/badminton-skills-coach/actions/workflows/validate.yml)

## 项目定位 / Scope

**中文**

这个仓库现在只保留一个目标：把 `刘辉羽毛球` 的公开抖音教学内容整理成可在 Codex 中使用的证据型羽毛球教练 Skill，并保留维护这个 Skill 和全量思维图所需的最小流水线。

仓库不再维护网页 MVP、多模型 BYOK 网页、网课导入、回答质量评测报告或 25 条视频的试点版本。当前保留的是稳定可用的全量 Skill、主题索引、Draw.io / Mermaid / HTML 思维图，以及后续检查抖音主页更新、转写新增视频、重建知识库和重建思维图所需的脚本。

这个 Skill 不代表刘辉本人，也不声称获得作者授权或背书。它只是一个个人学习型知识工程项目：尽量用可追溯的视频链接、时间戳、主题索引和人工复核记录来回答羽毛球技术问题。

**English**

This repository now has one purpose: maintain an evidence-backed Codex Skill built from public Douyin teaching videos by `刘辉羽毛球`, plus the minimal pipeline required to update the Skill and the full topic map.

The repository no longer maintains the web MVP, multi-model BYOK web app, course-video import path, answer-quality reports, or the old 25-video pilot build. What remains is the full Skill, topic index, Draw.io / Mermaid / HTML knowledge maps, and the scripts needed to check the Douyin profile for updates, transcribe new videos, rebuild the knowledge base, and regenerate the maps.

This Skill does not impersonate Liu Hui and does not claim endorsement. It is a personal learning and knowledge-engineering project that answers badminton technique questions with traceable video links, timestamps, topic indexes, and manual review notes where available.

## 当前内容 / Current Contents

**中文**

- 获取到的抖音公开视频：`472` 条
- 已排除非教学/广告器材内容：`113` 条
- 可加入 Skill 知识库的教学视频：`359` 条
- 已完成处理流水线：`406` 条
- 待视觉复核：`0` 条
- 最新入库教学视频：[网前框架 这样做不但不会让新手组织框架失误，还能减少身体僵硬](https://www.douyin.com/video/7661940775983482097)（`7661940775983482097`）
- Codex Skill：`skills/liuhui-badminton-coach/`
- 全量思维图：`output/liuhui-full-knowledge-map.drawio`

**English**

- Public Douyin videos collected: `472`
- Excluded as non-teaching, ads, or equipment-only content: `113`
- Teaching videos usable in the Skill knowledge base: `359`
- Processed through the pipeline: `406`
- Pending visual review: `0`
- Latest teaching video added to the knowledge base: [网前框架 这样做不但不会让新手组织框架失误，还能减少身体僵硬](https://www.douyin.com/video/7661940775983482097) (`7661940775983482097`)
- Codex Skill: `skills/liuhui-badminton-coach/`
- Full topic map: `output/liuhui-full-knowledge-map.drawio`

## 仓库结构 / Repository Layout

```text
skills/liuhui-badminton-coach/
  SKILL.md                         Codex Skill instructions
  references/knowledge-base.json   Full structured teaching archive
  references/topic-index.md        Human-readable topic index
  references/topic-map.json        Structured topic map
  references/practice-plan-template.md
  scripts/search_knowledge.py      Offline hybrid retrieval helper
  scripts/navigate_topics.py       Topic-navigation helper

data/
  douyin_video_index.json          Public video index from the Douyin profile
  douyin_teaching_filtered.json    Teaching-candidate list
  processing/douyin_queue.json     Processing queue and status tracking
  knowledge/douyin_knowledge_base.json
  knowledge/topic_index.json
  knowledge/knowledge_graph_summary.json
  knowledge/pilot_teaching_notes.json
  review/visual_review_annotations.json
  review/visual_review_queue.json

output/
  liuhui-full-knowledge-map.drawio Full Draw.io map
  liuhui-knowledge-map.mmd         Mermaid map
  liuhui-knowledge-map.html        Local HTML map
  visual_review_queue.md           Generated manual-review worksheet

config/
  douyin_classification_rules.json Teaching/non-teaching classification rules

scripts/
  douyin_pipeline.py               Shared classification and queue-status helpers
  douyin_profile_snapshot_dom.js   Browser-side Douyin profile snapshot helper
  douyin_video_media_assets_dom.js Browser-side video media asset helper
  check_douyin_updates.py          Compare a profile snapshot with known videos
  monitor_douyin_updates.py        Wrapper for update checks and optional commit
  prepare_douyin_media_batch.py    Create curl configs from media-asset snapshots
  init_douyin_queue.py             Build or refresh the processing queue
  process_douyin_ready_batch.py    Download, transcribe, rebuild, validate, commit
  run_full_update_pipeline.py      One-command local update wrapper
  batch_transcribe_directory.py    Transcribe local media directories
  transcribe_video.py              Transcribe one video/audio file
  build_douyin_knowledge.py        Rebuild the full knowledge base
  build_topic_index.py             Rebuild the topic index
  build_visual_review_queue.py     Rebuild the visual-review queue
  apply_visual_review_notes.py     Apply manual visual-review notes
  generate_knowledge_graph.py      Generate Draw.io / Mermaid / HTML maps
  validate_project.py              Validate core Skill and map artifacts
```

`data/raw_videos/`, `data/transcripts/`, `data/tmp/`, `.venv/`, and runtime caches are intentionally ignored by Git. They may exist locally during processing, but they are not part of the repository artifact.

## 安装 Skill / Install The Skill

**中文**

在本机 Codex 中安装或刷新 Skill：

```bash
cp -R skills/liuhui-badminton-coach ~/.codex/skills/liuhui-badminton-coach
```

使用方式：

```text
$liuhui-badminton-coach 我被动后场总是来不及架拍，应该怎么调整？
```

Skill 会先检索 `references/knowledge-base.json`，再用 `references/topic-index.md` 和 `references/topic-map.json` 定位主题，最后按证据型教练回答合同输出：诊断、原则、纠正提示、练习方法、证据来源和置信边界。

**English**

Install or refresh the Skill in local Codex:

```bash
cp -R skills/liuhui-badminton-coach ~/.codex/skills/liuhui-badminton-coach
```

Usage:

```text
$liuhui-badminton-coach 我被动后场总是来不及架拍，应该怎么调整？
```

The Skill retrieves from `references/knowledge-base.json`, uses `references/topic-index.md` and `references/topic-map.json` to orient the topic, and answers with diagnosis, principle, correction cues, drills, evidence citations, and confidence boundaries.

## 更新流程 / Update Workflow

**中文**

### 1. 抓取抖音主页最新快照

在已登录抖音的浏览器里打开 `刘辉羽毛球` 主页，运行或注入：

```text
scripts/douyin_profile_snapshot_dom.js
```

把得到的 JSON 保存到：

```text
data/tmp/douyin_profile_latest.json
```

### 2. 检查是否有新视频

```bash
python3 scripts/check_douyin_updates.py \
  --input data/tmp/douyin_profile_latest.json \
  --report output/douyin-update-report.json
```

确认新增内容后，应用安全的教学候选新增项。分类关键词、广告/器材排除词、人工排除 ID 都在 `config/douyin_classification_rules.json`，如果新视频误判，优先改配置再重跑：

```bash
python3 scripts/check_douyin_updates.py \
  --input data/tmp/douyin_profile_latest.json \
  --report output/douyin-update-report.json \
  --apply
```

新入队的教学视频会使用 `classified_teaching` 状态，表示已经通过分类、等待提取媒体地址。旧数据中的 `pending` 仍被脚本兼容为同一阶段。

### 3. 下载并转写新增视频

新增视频进入 `data/processing/douyin_queue.json` 后，需要为对应批次准备临时媒体下载配置，再运行：

```text
scripts/douyin_video_media_assets_dom.js
```

将视频页媒体资源快照保存到 `data/tmp/<video_id>-media-assets.json` 后，生成批次下载配置：

```bash
python3 scripts/prepare_douyin_media_batch.py \
  --input data/tmp/<video_id>-media-assets.json \
  --batch batch-048
```

然后运行批处理：

```bash
python3 scripts/process_douyin_ready_batch.py batch-048
```

这个脚本会逐条下载临时媒体、记录下载失败项、转写、重建知识库、重建主题索引、重建思维图、刷新 README、清理本地媒体、验证项目，并可提交变更。

### 4. 重新生成 Skill 与思维图

如果手动改了复核笔记或知识数据，推荐运行总入口：

```bash
python3 scripts/run_full_update_pipeline.py
```

它会重建知识库、主题索引、视觉复核队列、思维图、Skill 引用数据、README 状态，并运行验证。也可以按顺序手动运行：

```bash
python3 scripts/build_douyin_knowledge.py
python3 scripts/build_topic_index.py
python3 scripts/build_visual_review_queue.py
python3 scripts/generate_knowledge_graph.py
cp data/knowledge/douyin_knowledge_base.json skills/liuhui-badminton-coach/references/knowledge-base.json
cp data/knowledge/knowledge_graph_summary.json skills/liuhui-badminton-coach/references/topic-map.json
python3 scripts/update_readme_status.py
python3 scripts/validate_project.py
```

然后刷新本机 Codex Skill：

```bash
cp -R skills/liuhui-badminton-coach ~/.codex/skills/liuhui-badminton-coach
```

**English**

### 1. Capture the latest Douyin profile snapshot

Open the `刘辉羽毛球` profile in a logged-in Douyin browser session, then run or inject:

```text
scripts/douyin_profile_snapshot_dom.js
```

Save the resulting JSON as:

```text
data/tmp/douyin_profile_latest.json
```

### 2. Check for new videos

```bash
python3 scripts/check_douyin_updates.py \
  --input data/tmp/douyin_profile_latest.json \
  --report output/douyin-update-report.json
```

After reviewing the additions, apply safe teaching candidates. Classification keywords, ad/equipment exclusion terms, and manual exclusion IDs live in `config/douyin_classification_rules.json`. If a new post is misclassified, update the config first and rerun the check:

```bash
python3 scripts/check_douyin_updates.py \
  --input data/tmp/douyin_profile_latest.json \
  --report output/douyin-update-report.json \
  --apply
```

New teaching queue items start as `classified_teaching`; legacy `pending` items are still accepted as the same stage.

### 3. Download and transcribe new videos

After new videos enter `data/processing/douyin_queue.json`, open the video page in an authenticated browser session and run:

```text
scripts/douyin_video_media_assets_dom.js
```

Save the media-asset snapshot as `data/tmp/<video_id>-media-assets.json`, then prepare the batch curl config:

```bash
python3 scripts/prepare_douyin_media_batch.py \
  --input data/tmp/<video_id>-media-assets.json \
  --batch batch-048
```

Then run the batch processor:

```bash
python3 scripts/process_douyin_ready_batch.py batch-048
```

This downloads temporary media item by item, records download failures, transcribes the batch, rebuilds the knowledge base, rebuilds topic indexes and maps, refreshes README, removes local media, validates the repository, and can commit the update.

### 4. Regenerate the Skill and maps

If review notes or knowledge data changed manually, prefer the one-command wrapper:

```bash
python3 scripts/run_full_update_pipeline.py
```

It rebuilds the knowledge base, topic index, visual-review queue, maps, Skill reference files, README status, and validation. You can also run the steps manually:

```bash
python3 scripts/build_douyin_knowledge.py
python3 scripts/build_topic_index.py
python3 scripts/build_visual_review_queue.py
python3 scripts/generate_knowledge_graph.py
cp data/knowledge/douyin_knowledge_base.json skills/liuhui-badminton-coach/references/knowledge-base.json
cp data/knowledge/knowledge_graph_summary.json skills/liuhui-badminton-coach/references/topic-map.json
python3 scripts/update_readme_status.py
python3 scripts/validate_project.py
```

Then refresh the local Codex Skill:

```bash
cp -R skills/liuhui-badminton-coach ~/.codex/skills/liuhui-badminton-coach
```

## 队列状态 / Queue Statuses

**中文**

`data/processing/douyin_queue.json` 使用更细的状态来说明每条教学候选视频卡在哪一步：

- `classified_teaching`：已判定为教学候选，等待提取媒体地址。
- `pending`：旧状态，等同于 `classified_teaching`，保留兼容。
- `media_ready`：已经从抖音视频页拿到媒体地址，并生成 curl 配置。
- `downloaded`：临时媒体文件已下载，等待转写。
- `transcribed`：转写文件已生成，可进入知识库构建。
- `download_failed`：下载失败，需要刷新媒体地址或重试。
- `extraction_failed`：媒体地址提取失败，需要重新打开视频页提取。
- `transcription_failed`：本地转写失败，需要检查媒体文件或转写环境。
- `skipped_non_teaching`：已确认非教学，仅用于状态语义和后续扩展；当前非教学主要记录在分类报告和计数中。

**English**

`data/processing/douyin_queue.json` uses explicit statuses to show where each teaching candidate is in the pipeline:

- `classified_teaching`: accepted as a teaching candidate and waiting for media extraction.
- `pending`: legacy alias for `classified_teaching`.
- `media_ready`: media URL captured from the Douyin video page and curl config generated.
- `downloaded`: temporary media downloaded and waiting for transcription.
- `transcribed`: transcript files exist and can be built into the knowledge base.
- `download_failed`: download failed; refresh the media asset or retry.
- `extraction_failed`: media asset extraction failed; reopen the video page and extract again.
- `transcription_failed`: local transcription failed; inspect the media file or transcription environment.
- `skipped_non_teaching`: known non-teaching item retained for status semantics and future expansion; current non-teaching items are mainly tracked in classification reports and counts.

## 技术栈 / Technology Stack

**中文**

- Codex Skills：封装教练工作流和回答规则
- Python 3：队列处理、转写调度、知识库构建、主题索引、验证
- `faster-whisper`：本地中文语音转写
- Node/browser script：从已登录抖音页面提取主页快照
- Draw.io / Mermaid / HTML：生成全量教学主题图谱
- GitHub Actions：验证核心 Skill 与图谱产物是否同步

**English**

- Codex Skills: reusable coaching workflow and answer contract
- Python 3: queue processing, transcription orchestration, knowledge generation, topic indexing, validation
- `faster-whisper`: local Chinese speech transcription
- Node/browser script: snapshot extraction from an authenticated Douyin profile page
- Draw.io / Mermaid / HTML: full teaching-topic maps
- GitHub Actions: validation for core Skill and map artifacts

## 验证 / Validation

```bash
python3 -m py_compile \
  scripts/apply_visual_review_notes.py \
  scripts/batch_transcribe_directory.py \
  scripts/build_douyin_knowledge.py \
  scripts/build_topic_index.py \
  scripts/build_visual_review_queue.py \
  scripts/check_douyin_updates.py \
  scripts/douyin_pipeline.py \
  scripts/generate_knowledge_graph.py \
  scripts/init_douyin_queue.py \
  scripts/monitor_douyin_updates.py \
  scripts/prepare_douyin_media_batch.py \
  scripts/process_douyin_ready_batch.py \
  scripts/run_full_update_pipeline.py \
  scripts/transcribe_video.py \
  scripts/update_readme_status.py \
  skills/liuhui-badminton-coach/scripts/navigate_topics.py \
  skills/liuhui-badminton-coach/scripts/search_knowledge.py

python3 scripts/validate_project.py
```

`validate_project.py` checks JSON validity, Draw.io XML validity, Skill frontmatter, queue counts, full knowledge-base sync, topic-index sync, topic-map sync, practice-plan template coverage, and visual-review queue consistency.

## 边界 / Boundaries

**中文**

- 不提交原始视频、音频、完整转写目录、临时 CDN URL 或本地模型缓存。
- 不把非教学视频作为教练证据。
- 不把自动转写结果当作绝对事实；低置信内容需要复核。
- 不扮演刘辉本人，不暗示官方授权。
- 不提供医学诊断；出现疼痛时应停止相关动作并咨询合格专业人士。

**English**

- Raw videos, audio files, transcript directories, temporary CDN URLs, and local model caches are not committed.
- Non-teaching videos are not used as coaching evidence.
- Automatic transcripts are not treated as absolute truth; low-confidence items need review.
- The Skill does not impersonate Liu Hui or imply official authorization.
- It does not provide medical diagnosis; pain should be handled by stopping the movement and consulting a qualified professional.
