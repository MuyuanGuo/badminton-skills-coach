# Badminton Skills Coach / 刘辉羽毛球教练 Skill

[![Validate Skill artifacts](https://github.com/MuyuanGuo/badminton-skills-coach/actions/workflows/validate.yml/badge.svg)](https://github.com/MuyuanGuo/badminton-skills-coach/actions/workflows/validate.yml)

这是 `Badminton Skills Coach` 的 **1.1.0-dev 开发分支**。GitHub `main` 分支和 [`v1.0.0`](https://github.com/MuyuanGuo/badminton-skills-coach/releases/tag/v1.0.0) Release 是当前稳定版；`develop` 分支用于开发“通过用户反馈提升回答质量”的下一版本。

项目把 `刘辉羽毛球` 的公开抖音教学内容整理成可检索、可引用、可维护的证据型羽毛球教练 Skill，并保留更新 Skill、教学思维图和反馈审核所需的最小流水线。

这个项目尚未得到刘辉本人授权，仅作为个人学习型知识工程项目：回答时尽量使用可追溯的视频链接、时间戳、主题索引和人工视觉复核记录。

## 1.0 状态

- 稳定版：`main` / `v1.0.0`
- 开发版：`develop` / `1.1.0-dev`

- 获取到的抖音公开视频：`472` 条
- 已排除非教学/广告器材内容：`113` 条
- 已加入 Skill 知识库的教学视频：`359` 条
- 最新入库教学视频：[网前框架 这样做不但不会让新手组织框架失误，还能减少身体僵硬](https://www.douyin.com/video/7661940775983482097)（`7661940775983482097`）
- 当前开发内容：视频统一编号、自然语言反馈解析、本地反馈队列、GitHub 反馈模板和人工审核流程

## 这个 Skill 能做什么

- 回答羽毛球技术问题，例如杀球、吊球、网前、步法、发接发、双打轮转、发力和纠错。
- 通过原词、双向同义词、完整主题归属和全转写哈希特征进行高召回检索，并引用视频标题、时间戳和抖音链接。
- 根据问题内容分配文字与视频的作用：战术和原则用文字完整总结，动作形态与动态细节用文字说明观察点并以视频示范为主。
- 根据主题图谱给出系统学习路径，而不是只回答单个动作。
- 生成保守的训练计划，包括今日练习、3 天修正、2 周巩固和自测标准。
- 标注置信边界：哪些来自人工复核，哪些来自自动转写，哪些需要用户视频才能进一步诊断。
- 为答案中的视频分配稳定的 `V1...Vn` 编号，并把用户明确提供的价值、无关、遗漏和文字质量反馈放入本地人工审核队列。

它不做这些事：

- 不代表刘辉本人。
- 不把自动转写内容当作绝对事实。
- 不提供医学诊断。
- 不提交原始视频、音频、完整转写目录、临时 CDN 地址或本地模型缓存。

## 快速使用

把 Skill 安装或刷新到本机 Codex：

```bash
mkdir -p ~/.codex/skills/liuhui-badminton-coach
cp -R skills/liuhui-badminton-coach/. ~/.codex/skills/liuhui-badminton-coach/
```

在 Codex 中使用：

```text
$liuhui-badminton-coach 我被动后场总是来不及架拍，应该怎么调整？
```

收到回答后可以直接反馈：

```text
反馈：V1 最有价值；V2 不相关；文字漏了“被动情况下如何处理”。
```

Skill 的回答流程是：

1. 先判断用户的问题属于哪个动作、场景和水平。
2. 用 `scripts/search_knowledge.py` 对知识库和全量检索索引执行高召回检索。
3. 根据检索返回的 `answer_guidance` 选择“文字为主、文字视频并重、视频为主”，三种模式都必须给出有用文字和完整相关视频。
4. 检查完整候选清单，不因结果排在前 12 条之外就直接丢弃。
5. 必要时用 `scripts/navigate_topics.py` 定位主题图谱，再缩小场景重检。
6. 给最终推荐视频分配不重复的 `V1...Vn` 编号，并在当前任务上下文中保留编号映射。
7. 按“直接回答、文字解释、适用边界、核心视频与观看重点、完整相关视频、置信边界”输出；只有收到明确反馈后，才把问题、编号映射和反馈写入本地待审核队列。

## 主要产物

```text
skills/liuhui-badminton-coach/
  SKILL.md                         Skill 指令和回答规范
  references/knowledge-base.json   全量结构化知识库
  references/retrieval-index.json  全量教学视频高召回索引
  references/retrieval-rules.json  双向同义词和检索阈值
  references/answer-modality-rules.json
  references/feedback-rules.json   反馈解析词和队列状态
  references/feedback-workflow.md  回答编号、反馈记录和审核流程
  references/topic-index.md        可读主题索引
  references/topic-map.json        结构化主题图谱
  references/practice-plan-template.md
  scripts/search_knowledge.py      本地高召回混合检索
  scripts/navigate_topics.py       主题导航和学习路径
  scripts/feedback.py              回答上下文、反馈解析和人工审核

data/
  douyin_video_index.json          抖音主页公开视频索引
  douyin_teaching_filtered.json    教学候选与排除计数
  processing/douyin_queue.json     入库处理队列
  evaluation/retrieval_cases.json  检索召回回归用例
  evaluation/answer_modality_cases.json
  evaluation/feedback_parser_cases.json
  knowledge/douyin_knowledge_base.json
  knowledge/retrieval_index.json
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
  answer_modality_rules.json       文字/视频回答分工规则
  douyin_classification_rules.json 教学/非教学分类规则
  feedback_rules.json              反馈解析与开发版本配置
  retrieval_rules.json             检索扩展词和阈值

scripts/
  report_pipeline_status.py        当前状态、失败项和下一步建议
  check_douyin_updates.py          检查抖音主页是否有新视频
  prepare_douyin_media_batch.py    根据媒体快照生成下载配置
  process_douyin_ready_batch.py    下载、转写、重建、验证、提交
  run_full_update_pipeline.py      重建知识库、图谱和 Skill 引用
  build_retrieval_index.py         从完整转写生成无正文检索索引
  evaluate_answer_policy.py        评测文字/视频回答模式
  evaluate_retrieval.py            评测已知相关视频召回率
  test_feedback_pipeline.py        反馈解析、队列和审核回归测试
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

8. 查看并人工审核本地反馈：

```bash
python3 skills/liuhui-badminton-coach/scripts/feedback.py list \
  --status pending_review

python3 skills/liuhui-badminton-coach/scripts/feedback.py review \
  --feedback-id FEEDBACK_ID \
  --decision accepted \
  --note "已核对问题、视频和来源证据"
```

默认队列位于 `${CODEX_HOME:-~/.codex}/feedback/liuhui-badminton-coach/`，也可以用 `LIUHUI_FEEDBACK_DIR` 指定其他本地目录。反馈不会自动上传，也不会在人工接受后直接修改检索权重。

GitHub 用户可以使用仓库的 `Skill 回答反馈` Issue Form。维护者把 Issue body 导出后，可导入同一个本地审核队列：

```bash
python3 skills/liuhui-badminton-coach/scripts/feedback.py import-github \
  --body-file /path/to/issue-body.md \
  --source-url https://github.com/OWNER/REPO/issues/NUMBER
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

用户反馈使用独立的本地队列状态：

- `pending_review`：解析成功，等待人工核对问题、视频和来源证据。
- `needs_clarification`：包含未知编号、冲突信号或没有可执行信息。
- `accepted`：人工确认反馈有效，但尚未自动晋升为检索或评测数据。
- `rejected`：人工确认不应进入后续质量提升流程。

## 验证

本地完整验证：

```bash
python3 -m py_compile \
  scripts/apply_visual_review_notes.py \
  scripts/batch_transcribe_directory.py \
  scripts/build_douyin_knowledge.py \
  scripts/build_retrieval_index.py \
  scripts/build_topic_index.py \
  scripts/build_visual_review_queue.py \
  scripts/check_douyin_updates.py \
  scripts/douyin_pipeline.py \
  scripts/evaluate_answer_policy.py \
  scripts/evaluate_retrieval.py \
  scripts/generate_knowledge_graph.py \
  scripts/init_douyin_queue.py \
  scripts/monitor_douyin_updates.py \
  scripts/prepare_douyin_media_batch.py \
  scripts/process_douyin_ready_batch.py \
  scripts/report_pipeline_status.py \
  scripts/run_full_update_pipeline.py \
  scripts/test_douyin_pipeline.py \
  scripts/test_feedback_pipeline.py \
  scripts/test_search_knowledge.py \
  scripts/transcribe_video.py \
  scripts/update_readme_status.py \
  scripts/validate_project.py \
  skills/liuhui-badminton-coach/scripts/feedback.py \
  skills/liuhui-badminton-coach/scripts/navigate_topics.py \
  skills/liuhui-badminton-coach/scripts/search_knowledge.py

python3 scripts/test_douyin_pipeline.py
python3 scripts/test_feedback_pipeline.py
python3 scripts/test_search_knowledge.py
python3 scripts/evaluate_answer_policy.py
python3 scripts/evaluate_retrieval.py
node scripts/test_douyin_profile_snapshot_dom.mjs
python3 scripts/validate_project.py
```

GitHub Actions 会执行同样的核心验证：

- Python 源码编译。
- 分类规则回归测试。
- 回答媒介分工测试：`16` 个问题均正确进入文字为主、文字视频并重或视频为主模式，并检查每种模式同时保留文字与视频义务。
- 检索召回回归测试：当前人工已知相关集为 `10` 个问题、`28` 条视频，要求候选召回率为 `100%`，且每题主证据进入前 `12` 条。
- 反馈回归测试：检查连续视频编号、中文自然语言解析、未选择不等于负面、GitHub Issue 导入和人工审核历史。
- 抖音主页快照过滤回归测试，防止把 footer / 热门推荐视频误当成作者作品。
- JSON、Draw.io、Skill frontmatter、队列计数、知识库同步、主题索引、主题图谱和视觉复核队列一致性验证。

## 技术栈

- Codex Skills：封装教练工作流和回答规范。
- Python 3：队列处理、知识库构建、高召回检索、回答媒介分工、主题索引、图谱生成和验证。
- `faster-whisper`：本地中文语音转写。
- Browser-side JavaScript：从已登录抖音页面提取主页快照和视频媒体资源。
- Draw.io / Mermaid / HTML：生成全量教学主题图谱。
- GitHub Actions：持续验证 Skill 与知识库产物一致性。
- GitHub Issue Forms：收集经过用户确认可公开的结构化回答反馈。

## 1.0 之后怎么演进

`main` / `v1.0.0` 继续作为稳定版；反馈闭环只在 `develop` / `1.1.0-dev` 开发和验证，成熟后再单独发布：

- 刘辉发布新教学视频：走增量更新流程。
- 分类误判：改 `config/douyin_classification_rules.json` 并补测试。
- 回答质量不足：优先检查检索结果和证据引用，再改 Skill 指令。
- 用户反馈：先进入本地队列并人工复核，不直接在线修改检索或知识库。
- 主题图谱不够清楚：调整 topic index / graph 生成逻辑。
- 新增大量课程或直播切片：另起分支设计，不混入当前 1.0 稳定版。

## License 和内容边界

本仓库只保存结构化索引、教学笔记、主题图谱和维护脚本。检索索引会从本地完整转写生成术语命中、主题归属和不含正文的字符 n-gram 哈希，但不包含完整转写正文。原始视频、音频、完整转写目录、临时媒体 URL、模型缓存和用户本地反馈队列不提交。反馈默认只保存在用户自己的 Codex 目录，只有用户主动提交 GitHub Issue 时才会公开。公开视频链接仅作为来源引用；使用者应自行遵守平台规则和相关版权要求。
