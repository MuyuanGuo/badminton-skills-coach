# Badminton Skills Coach / 羽毛球技能教练

[![Validate knowledge pipeline](https://github.com/MuyuanGuo/badminton-skills-coach/actions/workflows/validate.yml/badge.svg)](https://github.com/MuyuanGuo/badminton-skills-coach/actions/workflows/validate.yml)

## 项目简介 / Overview

**中文**

Badminton Skills Coach 是一个个人学习型知识工程项目。它把抖音创作者 `刘辉羽毛球` 的公开羽毛球教学视频整理成结构化知识库，并进一步封装为一个可在 Codex 中使用的证据型羽毛球教练 Skill。

这个项目的目标不是模仿刘辉本人，也不声称获得作者背书。目标是建立一个可检索、可引用、可复核的技术学习资料库：回答羽毛球技术问题时，尽量给出来源视频、时间戳、动作要点和置信边界。

**English**

Badminton Skills Coach is a personal-study knowledge project. It turns public badminton teaching videos from the Douyin creator `刘辉羽毛球` into a structured knowledge base and packages the workflow as an evidence-backed Codex Skill.

The project does not impersonate the creator and does not claim endorsement. Its purpose is to provide a searchable, attributable, reviewable coaching reference that answers badminton technique questions with source videos, timestamps, teaching cues, and confidence boundaries.

## 当前状态 / Current Status

**中文**

截至当前已提交版本：

- 已索引 `刘辉羽毛球` 抖音主页公开视频链接：`470` 条
- 已筛选为羽毛球教学候选视频：`405` 条
- 已完成媒体获取、转写、结构化入库：`405 / 405` 条
- 已解决此前 `35` 条媒体提取失败项，最终剩余失败：`0` 条
- 全量知识库视频数：`405` 条
- 可直接用于检索回答：`339` 条
- 需要视觉复核：`66` 条
- GitHub Actions 验证通过，当前队列全部为 `transcribed`

原始视频、音频、完整转写文本、临时 CDN URL、模型缓存和本地虚拟环境都不会提交到 Git。

**English**

As of the latest checked-in version:

- Public Douyin video links indexed from `刘辉羽毛球`: `470`
- Teaching candidates selected: `405`
- Media extracted, transcribed, and structured into the knowledge base: `405 / 405`
- Previously failed media extraction items recovered: `35`, with `0` remaining failures
- Full knowledge-base videos: `405`
- Ready for direct evidence-backed retrieval: `339`
- Marked as requiring visual review: `66`
- GitHub Actions validation is passing, and every queue item is now `transcribed`

Raw video/audio files, full transcripts, temporary CDN URLs, model caches, and local virtual environments are intentionally excluded from Git.

## 这个 Skill 是怎么来的 / How This Skill Was Built

**中文**

项目从一个 25 条视频的试点开始：先收集代表性教学视频，人工复核作者和内容，去除广告与非教学内容，按技术主题分类，再转写语音并提取可引用的教学证据。

之后流程扩展为完整流水线：

1. 收集 `刘辉羽毛球` 抖音公开视频索引。
2. 过滤广告、器材推广和非教学内容。
3. 将教学视频分类到后场技术、步法移动、发力、握拍、单打战术、双打战术、训练纠错等主题。
4. 通过已登录浏览器会话观察抖音页面媒体资源。
5. 将临时媒体 URL 写入批次下载配置。
6. 下载本地媒体文件到 Git 忽略目录。
7. 使用 `faster-whisper` 转写中文教学音频。
8. 从转写结果生成带时间戳的结构化教学证据。
9. 构建 `data/knowledge/douyin_knowledge_base.json`。
10. 运行验证脚本和检索评估。
11. 将稳定的知识与检索逻辑封装为 Codex Skill。

最后阶段重新检查了此前失败的 `35` 条视频。失败原因不是视频不可用，而是旧浏览器标签页失效和部分媒体直链过期。通过重新绑定浏览器、刷新媒体 URL，并拆成 5 条小批次立即下载转写，最终全部成功入库。

**English**

The project began as a 25-video pilot: collect representative teaching videos, verify the creator and content, remove ads and non-teaching posts, classify each video by badminton topic, transcribe the audio, and extract timestamped evidence.

The workflow then expanded into a complete pipeline:

1. Collect public Douyin video metadata from `刘辉羽毛球`.
2. Filter out ads, equipment-only promotions, and non-teaching content.
3. Classify teaching videos into topics such as rear-court technique, footwork, power generation, grip, singles tactics, doubles tactics, and correction drills.
4. Observe media resources through an authenticated browser session.
5. Write temporary media URLs into batch download configs.
6. Download media into Git-ignored local folders.
7. Transcribe Chinese teaching audio with `faster-whisper`.
8. Convert transcripts into timestamped structured teaching evidence.
9. Build `data/knowledge/douyin_knowledge_base.json`.
10. Run validation and retrieval evaluation.
11. Package stable knowledge and retrieval logic as a Codex Skill.

The final pass revisited the previous `35` failed videos. They were not invalid; the failures came from stale browser tabs and expired media URLs. Rebinding the browser, refreshing media URLs, and processing the items in immediate 5-video batches recovered all of them.

## Skill 能做什么 / What The Skill Does

**中文**

Skill 目录：

```text
skills/liuhui-badminton-coach/
```

在 Codex 中安装后，可以这样提问：

```text
$liuhui-badminton-coach 我被动后场总是来不及架拍，应该怎么调整？
```

Skill 的设计原则：

- 检索相关教学条目
- 引用原始抖音视频链接和时间戳
- 区分诊断、原理、动作提示和训练方法
- 优先使用有转写证据或人工整理证据的内容
- 对需要视觉复核的视频保持谨慎
- 不扮演刘辉本人，不暗示官方认可

**English**

The skill lives in:

```text
skills/liuhui-badminton-coach/
```

After installing it in Codex, you can ask:

```text
$liuhui-badminton-coach 我被动后场总是来不及架拍，应该怎么调整？
```

The skill is designed to:

- Retrieve relevant teaching entries
- Cite source Douyin video URLs and timestamp ranges
- Separate diagnosis, principle, correction cues, and drills
- Prefer transcript-backed or curated evidence
- Be cautious when a video needs visual review
- Avoid impersonating 刘辉 or implying official endorsement

## 技术栈 / Technology Stack

**中文**

- Python 3：队列处理、JSON 构建、验证、离线混合检索、评估
- Node.js：抖音目录分类辅助与浏览器页面脚本
- `faster-whisper`：本地中文语音识别
- Codex Skills：封装可复用教练工作流
- Git / GitHub Actions：版本管理和 CI 验证
- Draw.io：早期知识图谱与分类可视化

**English**

- Python 3: queue processing, JSON generation, validation, offline hybrid retrieval, evaluation
- Node.js: Douyin catalog helpers and browser-page scripts
- `faster-whisper`: local Chinese ASR transcription
- Codex Skills: reusable coaching workflow packaging
- Git / GitHub Actions: version control and CI validation
- Draw.io: early knowledge-map and classification visualization

## 仓库结构 / Repository Layout

**中文**

```text
data/
  douyin_video_index.*             抖音公开视频索引
  douyin_teaching_filtered.json    教学候选视频
  processing/douyin_queue.json     处理队列与状态
  knowledge/
    douyin_knowledge_base.json     当前 405 条全量知识库
    pilot_teaching_notes.json      试点人工笔记

scripts/
  classify_douyin_catalog.mjs      目录主题分类
  check_douyin_updates.py          检查主页新增视频
  douyin_profile_snapshot_dom.js   浏览器主页快照采集
  monitor_douyin_updates.py        更新监测封装
  process_douyin_ready_batch.py    批量下载、转写、构建、提交
  batch_transcribe_directory.py    目录转写
  build_douyin_knowledge.py        构建全量知识库
  validate_project.py              项目验证
  evaluate_liuhui_skill.py         检索评估

skills/
  liuhui-badminton-coach/
    SKILL.md
    references/knowledge-base.json
    scripts/search_knowledge.py

output/
  failed_extraction_review.*       35 条失败项复核记录
  liuhui-pilot-knowledge-map.drawio
  liuhui-skill-retrieval-evaluation.json
```

**English**

```text
data/
  douyin_video_index.*             Public Douyin video index
  douyin_teaching_filtered.json    Teaching candidates
  processing/douyin_queue.json     Processing queue and statuses
  knowledge/
    douyin_knowledge_base.json     Current full 405-video knowledge base
    pilot_teaching_notes.json      Curated pilot notes

scripts/
  classify_douyin_catalog.mjs      Topic classification helper
  check_douyin_updates.py          Detect newly observed homepage videos
  douyin_profile_snapshot_dom.js   Browser homepage snapshot collector
  monitor_douyin_updates.py        Update-monitor wrapper
  process_douyin_ready_batch.py    Batch download, transcription, build, commit
  batch_transcribe_directory.py    Directory transcription runner
  build_douyin_knowledge.py        Full knowledge-base builder
  validate_project.py              Repository validation
  evaluate_liuhui_skill.py         Retrieval evaluation

skills/
  liuhui-badminton-coach/
    SKILL.md
    references/knowledge-base.json
    scripts/search_knowledge.py

output/
  failed_extraction_review.*       Review report for the recovered 35 failures
  liuhui-pilot-knowledge-map.drawio
  liuhui-skill-retrieval-evaluation.json
```

Ignored local-only folders:

```text
data/raw_videos/
data/transcripts/
data/tmp/
.venv/
```

## 本地配置 / Local Setup

**中文**

克隆项目：

```bash
git clone https://github.com/MuyuanGuo/badminton-skills-coach.git
cd badminton-skills-coach
```

创建 Python 环境并安装转写依赖：

```bash
python3 -m venv .venv
.venv/bin/pip install faster-whisper
```

运行验证：

```bash
python3 scripts/validate_project.py
python3 scripts/evaluate_liuhui_skill.py
```

直接测试检索：

```bash
python3 skills/liuhui-badminton-coach/scripts/search_knowledge.py \
  "被动后场来不及架拍怎么办"
python3 skills/liuhui-badminton-coach/scripts/search_knowledge.py \
  "被压到底线的时候怎么处理" --mode semantic
```

**English**

Clone the repository:

```bash
git clone https://github.com/MuyuanGuo/badminton-skills-coach.git
cd badminton-skills-coach
```

Create a Python environment and install transcription dependencies:

```bash
python3 -m venv .venv
.venv/bin/pip install faster-whisper
```

Run validation:

```bash
python3 scripts/validate_project.py
python3 scripts/evaluate_liuhui_skill.py
```

Try retrieval directly:

```bash
python3 skills/liuhui-badminton-coach/scripts/search_knowledge.py \
  "被动后场来不及架拍怎么办"
python3 skills/liuhui-badminton-coach/scripts/search_knowledge.py \
  "被压到底线的时候怎么处理" --mode semantic
```

## 安装 Codex Skill / Install The Codex Skill

**中文**

复制 Skill 到个人 Codex skills 目录：

```bash
mkdir -p ~/.codex/skills
cp -R skills/liuhui-badminton-coach ~/.codex/skills/liuhui-badminton-coach
```

然后在 Codex 中调用：

```text
$liuhui-badminton-coach 如何改正杀球发力分散的问题？
```

**English**

Copy the skill into your personal Codex skills directory:

```bash
mkdir -p ~/.codex/skills
cp -R skills/liuhui-badminton-coach ~/.codex/skills/liuhui-badminton-coach
```

Then invoke it in Codex:

```text
$liuhui-badminton-coach 如何改正杀球发力分散的问题？
```

## 自动更新与新增视频 / Updating And Monitoring New Videos

**中文**

安全入口是：

```bash
python3 scripts/check_douyin_updates.py \
  --input data/tmp/douyin_profile_latest.json
```

它会比较新的主页快照和本地索引，输出：

```text
output/douyin-update-report.json
```

默认不会修改仓库。确认新增视频是教学内容后，再运行：

```bash
python3 scripts/check_douyin_updates.py \
  --input data/tmp/douyin_profile_latest.json \
  --apply
```

半自动监测可以使用：

```bash
python3 scripts/monitor_douyin_updates.py \
  --snapshot data/tmp/douyin_profile_latest.json \
  --apply \
  --validate \
  --commit \
  --push
```

主页快照可以通过已登录浏览器页面中的脚本采集：

```text
scripts/douyin_profile_snapshot_dom.js
```

它定义：

```javascript
await window.__collectDouyinProfileSnapshot({ scrollRounds: 8 })
```

**English**

The safe update entrypoint is:

```bash
python3 scripts/check_douyin_updates.py \
  --input data/tmp/douyin_profile_latest.json
```

It compares a new homepage snapshot with the local index and writes:

```text
output/douyin-update-report.json
```

By default it does not modify the repository. After reviewing the new teaching candidates, apply them with:

```bash
python3 scripts/check_douyin_updates.py \
  --input data/tmp/douyin_profile_latest.json \
  --apply
```

For a semi-automatic monitor, use:

```bash
python3 scripts/monitor_douyin_updates.py \
  --snapshot data/tmp/douyin_profile_latest.json \
  --apply \
  --validate \
  --commit \
  --push
```

Homepage snapshots can be collected from an authenticated browser page with:

```text
scripts/douyin_profile_snapshot_dom.js
```

It defines:

```javascript
await window.__collectDouyinProfileSnapshot({ scrollRounds: 8 })
```

## 批处理流程 / Batch Processing Workflow

**中文**

队列文件：

```text
data/processing/douyin_queue.json
```

常见状态：

- `pending`：候选视频等待媒体提取
- `media_ready`：已写入媒体下载配置
- `transcribed`：已转写并可进入知识库
- `extraction_failed`：媒体提取失败
- `transcription_failed`：转写失败

当媒体 URL 已写入 `data/tmp/<batch>/` 后，运行：

```bash
python3 scripts/process_douyin_ready_batch.py <batch>
```

批处理脚本会：

1. 检查磁盘空间。
2. 用 curl 配置下载媒体。
3. 批量转写媒体。
4. 更新队列状态。
5. 重建全量知识库。
6. 删除该批次原始媒体。
7. 运行验证和检索评估。
8. 提交并推送结构化产物。

**English**

Queue file:

```text
data/processing/douyin_queue.json
```

Common statuses:

- `pending`: candidate video awaits media extraction
- `media_ready`: media download config has been prepared
- `transcribed`: transcript exists and can be included in the knowledge base
- `extraction_failed`: media extraction failed
- `transcription_failed`: transcription failed

After media URLs are written under `data/tmp/<batch>/`, run:

```bash
python3 scripts/process_douyin_ready_batch.py <batch>
```

The batch runner:

1. Checks disk space.
2. Downloads media with curl configs.
3. Transcribes the batch.
4. Updates queue status.
5. Rebuilds the full knowledge base.
6. Deletes raw media from the batch.
7. Runs validation and retrieval evaluation.
8. Commits and pushes structured artifacts.

## 全量知识库与 Skill 的关系 / Full Knowledge Base And Skill Packaging

**中文**

全量知识库位于：

```text
data/knowledge/douyin_knowledge_base.json
```

Skill 的引用数据位于：

```text
skills/liuhui-badminton-coach/references/knowledge-base.json
```

当前仓库只保留一个全量 Skill：

- `liuhui-badminton-coach`：405 条全量抖音教学视频证据集，适合实际提问和训练建议。

`scripts/validate_project.py` 会检查 Skill 引用知识库与全量知识库同步。自动更新新增视频后，应重建 `data/knowledge/douyin_knowledge_base.json`，再同步到 `skills/liuhui-badminton-coach/references/knowledge-base.json`。

无论采用哪种方式，都应运行：

```bash
python3 scripts/validate_project.py
python3 scripts/evaluate_liuhui_skill.py
```

**English**

The full knowledge base lives at:

```text
data/knowledge/douyin_knowledge_base.json
```

The skill reference data lives at:

```text
skills/liuhui-badminton-coach/references/knowledge-base.json
```

The repository now keeps one full skill:

- `liuhui-badminton-coach`: the full 405-video Douyin teaching evidence set for practical coaching questions.

`scripts/validate_project.py` checks that the skill stays in sync with the full source knowledge base. After an automated update discovers and processes new videos, rebuild `data/knowledge/douyin_knowledge_base.json`, then sync it into `skills/liuhui-badminton-coach/references/knowledge-base.json`.

Whichever path you choose, run:

```bash
python3 scripts/validate_project.py
python3 scripts/evaluate_liuhui_skill.py
```

## GitHub Actions / CI

**中文**

仓库包含验证工作流：

```text
.github/workflows/validate.yml
```

每次 push 会编译 Python 文件、验证项目产物，并运行检索评估。README 顶部徽章显示最新 CI 状态。

**English**

The repository includes a validation workflow:

```text
.github/workflows/validate.yml
```

On every push, it compiles Python sources, validates repository artifacts, and runs retrieval evaluation. The badge at the top of this README shows the latest CI status.

## 数据与版权边界 / Data And Copyright Boundaries

**中文**

本仓库用于个人学习和私有知识管理。请遵守平台规则、版权、课程授权和教练权益。不要在未获许可的情况下分发下载视频、付费课程、直播切片或完整转写文本。

仓库中提交的内容限定为元数据、结构化知识、引用链接、评估结果和 Skill 代码。回答技术问题时，应尽量引用原始视频链接和时间戳。

**English**

This repository is for personal study and private knowledge management. Please respect platform terms, copyright, course licenses, and instructor rights. Do not redistribute downloaded videos, paid course materials, live-stream clips, or full transcripts without permission.

Checked-in artifacts are limited to metadata, structured knowledge, source links, evaluation results, and skill code. Answers should cite original video URLs and timestamps whenever possible.

## 局限性 / Limitations

**中文**

- 自动语音识别可能误听羽毛球术语。
- 部分视频主要依赖画面示范，已标记为 `needs_visual_review`。
- 当前检索是离线混合检索，不依赖外部向量数据库；口语化问题仍可能需要人工复核召回结果。
- Skill 是学习辅助工具，不能替代合格教练现场诊断。
- Skill 不应扮演刘辉本人，也不应暗示官方背书。

**English**

- ASR can mishear badminton terminology.
- Some videos depend heavily on visual demonstration and are marked `needs_visual_review`.
- Retrieval is offline hybrid search without an external vector database; colloquial queries may still require manual review of retrieved evidence.
- The skill is a study aid, not a replacement for an in-person qualified coach.
- The skill must not impersonate 刘辉 or imply official endorsement.

## 常用命令 / Quick Commands

```bash
python3 scripts/validate_project.py
python3 scripts/evaluate_liuhui_skill.py
python3 scripts/build_douyin_knowledge.py
python3 skills/liuhui-badminton-coach/scripts/search_knowledge.py "后场被动怎么架拍"
python3 skills/liuhui-badminton-coach/scripts/search_knowledge.py "被压到底线怎么办" --mode semantic
```
