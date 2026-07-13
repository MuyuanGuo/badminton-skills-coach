# Badminton Skills Coach 1.0 / 刘辉羽毛球教练 Skill

[![Validate Skill artifacts](https://github.com/MuyuanGuo/badminton-skills-coach/actions/workflows/validate.yml/badge.svg)](https://github.com/MuyuanGuo/badminton-skills-coach/actions/workflows/validate.yml)

这是一个 **1.0 稳定版 Codex Skill 项目**。它把 `刘辉羽毛球` 的公开抖音教学内容整理成可检索、可引用、可维护的证据型羽毛球教练 Skill，并保留更新 Skill 与教学思维图所需的最小流水线。

当前仓库已经停止维护网页 MVP、多模型 BYOK 网页、网课导入、回答质量评测报告和 25 条视频试点版本。1.0 版本只保留稳定可用的 Skill、知识库、主题索引、Draw.io / Mermaid / HTML 思维图，以及后续发现新抖音教学视频并更新入库的脚本。

这个项目不代表刘辉本人，不声称获得官方授权或背书。它是一个个人学习型知识工程项目：回答时尽量使用可追溯的视频链接、时间戳、主题索引和人工视觉复核记录。

## 1.0 状态

- 获取到的抖音公开视频：`472` 条
- 已排除非教学/广告器材内容：`113` 条
- 可加入 Skill 知识库的教学视频：`359` 条
- 已完成处理流水线：`406` 条
- 待视觉复核：`0` 条
- 队列状态：`{"transcribed": 406}`
- 最新入库教学视频：[网前框架 这样做不但不会让新手组织框架失误，还能减少身体僵硬](https://www.douyin.com/video/7661940775983482097)（`7661940775983482097`）
- 当前维护模式：稳定版维护，只在刘辉发布新的教学视频后增量更新

## 这个 Skill 能做什么

- 回答羽毛球技术问题，例如杀球、吊球、网前、步法、发接发、双打轮转、发力和纠错。
- 从知识库中检索相关视频证据，并引用视频标题、时间戳和抖音链接。
- 根据主题图谱给出系统学习路径，而不是只回答单个动作。
- 生成保守的训练计划，包括今日练习、3 天修正、2 周巩固和自测标准。
- 标注置信边界：哪些来自人工复核，哪些来自自动转写，哪些需要用户视频才能进一步诊断。

它不做这些事：

- 不扮演刘辉本人。
- 不把非教学视频作为教练证据。
- 不把自动转写内容当作绝对事实。
- 不提供医学诊断。
- 不提交原始视频、音频、完整转写目录、临时 CDN 地址或本地模型缓存。

## 快速使用

把 Skill 安装或刷新到本机 Codex：

```bash
cp -R skills/liuhui-badminton-coach ~/.codex/skills/liuhui-badminton-coach
```

在 Codex 中使用：

```text
$liuhui-badminton-coach 我被动后场总是来不及架拍，应该怎么调整？
```

Skill 的回答流程是：

1. 先判断用户的问题属于哪个动作、场景和水平。
2. 用 `scripts/search_knowledge.py` 检索 `references/knowledge-base.json`。
3. 必要时用 `scripts/navigate_topics.py` 定位主题图谱。
4. 按“诊断、刘辉相关原则、纠正提示、练习方法、证据来源、置信边界”输出。

## 主要产物

```text
skills/liuhui-badminton-coach/
  SKILL.md                         Skill 指令和回答规范
  references/knowledge-base.json   全量结构化知识库
  references/topic-index.md        可读主题索引
  references/topic-map.json        结构化主题图谱
  references/practice-plan-template.md
  scripts/search_knowledge.py      本地混合检索
  scripts/navigate_topics.py       主题导航和学习路径

data/
  douyin_video_index.json          抖音主页公开视频索引
  douyin_teaching_filtered.json    教学候选与排除计数
  processing/douyin_queue.json     入库处理队列
  knowledge/douyin_knowledge_base.json
  knowledge/topic_index.json
  knowledge/knowledge_graph_summary.json
  review/visual_review_annotations.json
  review/visual_review_queue.json

output/
  liuhui-full-knowledge-map.drawio Draw.io 全量思维图
  liuhui-knowledge-map.mmd         Mermaid 思维图
  liuhui-knowledge-map.html        本地 HTML 思维图
  visual_review_queue.md           视觉复核工作表

config/
  douyin_classification_rules.json 教学/非教学分类规则

scripts/
  report_pipeline_status.py        当前状态、失败项和下一步建议
  check_douyin_updates.py          检查抖音主页是否有新视频
  prepare_douyin_media_batch.py    根据媒体快照生成下载配置
  process_douyin_ready_batch.py    下载、转写、重建、验证、提交
  run_full_update_pipeline.py      重建知识库、图谱和 Skill 引用
  validate_project.py              项目一致性验证
```

`data/raw_videos/`、`data/transcripts/`、`data/tmp/`、`.venv/` 和运行缓存不进入 Git。它们只在本地处理新增视频时使用。

## 维护流程

1. 查看当前状态：

```bash
python3 scripts/report_pipeline_status.py
```

2. 在已登录抖音的浏览器里打开 `刘辉羽毛球` 主页，运行或注入：

```text
scripts/douyin_profile_snapshot_dom.js
```

把结果保存为：

```text
data/tmp/douyin_profile_latest.json
```

3. 检查是否有新视频：

```bash
python3 scripts/check_douyin_updates.py \
  --input data/tmp/douyin_profile_latest.json \
  --report output/douyin-update-report.json
```

4. 如果报告里出现明确教学候选，确认无误后入队：

```bash
python3 scripts/check_douyin_updates.py \
  --input data/tmp/douyin_profile_latest.json \
  --report output/douyin-update-report.json \
  --apply
```

分类关键词、广告/器材排除词和人工排除 ID 在：

```text
config/douyin_classification_rules.json
```

如果误判，优先改这个配置，再重跑检查。

5. 对新增教学视频，打开视频页并运行：

```text
scripts/douyin_video_media_assets_dom.js
```

保存为 `data/tmp/<video_id>-media-assets.json`，然后准备批次：

```bash
python3 scripts/prepare_douyin_media_batch.py \
  --input data/tmp/<video_id>-media-assets.json \
  --batch batch-049
```

6. 下载、转写、重建和验证：

```bash
python3 scripts/process_douyin_ready_batch.py batch-049
```

7. 如果只是手动改了复核笔记、主题数据或知识库结构，运行：

```bash
python3 scripts/run_full_update_pipeline.py
```

## 队列状态

`data/processing/douyin_queue.json` 使用这些状态描述每条教学候选视频的位置：

- `classified_teaching`：已判定为教学候选，等待提取媒体地址。
- `pending`：旧状态，等同于 `classified_teaching`，保留兼容。
- `media_ready`：已经拿到媒体地址，并生成 curl 配置。
- `downloaded`：临时媒体已下载，等待转写。
- `transcribed`：转写文件已生成，可进入知识库构建。
- `download_failed`：下载失败，需要刷新媒体地址或重试。
- `extraction_failed`：媒体地址提取失败，需要重新打开视频页提取。
- `transcription_failed`：本地转写失败，需要检查媒体文件或转写环境。
- `skipped_non_teaching`：确认非教学，仅用于状态语义和后续扩展。

1.0 当前队列为 `{"transcribed": 406}`，没有失败项。

## 验证

本地完整验证：

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
  scripts/report_pipeline_status.py \
  scripts/run_full_update_pipeline.py \
  scripts/test_douyin_pipeline.py \
  scripts/transcribe_video.py \
  scripts/update_readme_status.py \
  scripts/validate_project.py \
  skills/liuhui-badminton-coach/scripts/navigate_topics.py \
  skills/liuhui-badminton-coach/scripts/search_knowledge.py

python3 scripts/test_douyin_pipeline.py
node scripts/test_douyin_profile_snapshot_dom.mjs
python3 scripts/validate_project.py
```

GitHub Actions 会执行同样的核心验证：

- Python 源码编译。
- 分类规则回归测试。
- 抖音主页快照过滤回归测试，防止把 footer / 热门推荐视频误当成作者作品。
- JSON、Draw.io、Skill frontmatter、队列计数、知识库同步、主题索引、主题图谱和视觉复核队列一致性验证。

## 技术栈

- Codex Skills：封装教练工作流和回答规范。
- Python 3：队列处理、知识库构建、主题索引、图谱生成和验证。
- `faster-whisper`：本地中文语音转写。
- Browser-side JavaScript：从已登录抖音页面提取主页快照和视频媒体资源。
- Draw.io / Mermaid / HTML：生成全量教学主题图谱。
- GitHub Actions：持续验证 Skill 与知识库产物一致性。

## 1.0 之后怎么演进

默认不再扩功能，进入稳定维护模式。只有出现明确问题时再小步优化：

- 刘辉发布新教学视频：走增量更新流程。
- 分类误判：改 `config/douyin_classification_rules.json` 并补测试。
- 回答质量不足：优先检查检索结果和证据引用，再改 Skill 指令。
- 主题图谱不够清楚：调整 topic index / graph 生成逻辑。
- 新增大量课程或直播切片：另起分支设计，不混入当前 1.0 稳定版。

## License 和内容边界

本仓库只保存结构化索引、教学笔记、主题图谱和维护脚本。原始视频、音频、完整转写目录、临时媒体 URL 和模型缓存不提交。公开视频链接仅作为来源引用；使用者应自行遵守平台规则和相关版权要求。
