# Badminton Skills Coach / 刘辉羽毛球教练 Skill

[![Validate Skill artifacts](https://github.com/MuyuanGuo/badminton-skills-coach/actions/workflows/validate.yml/badge.svg)](https://github.com/MuyuanGuo/badminton-skills-coach/actions/workflows/validate.yml)
[![Latest release](https://img.shields.io/github/v/release/MuyuanGuo/badminton-skills-coach)](https://github.com/MuyuanGuo/badminton-skills-coach/releases/latest)
[![License: MIT](https://img.shields.io/badge/code%20license-MIT-2f766d.svg)](LICENSE)

![Badminton Skills Coach：350 条教学视频、证据型检索与刘辉教学图谱](.github/assets/social-preview.png)

这是 `Badminton Skills Coach` 的 **1.1.0-dev.3 开发分支**。GitHub `main` 分支和 [`v1.0.0`](https://github.com/MuyuanGuo/badminton-skills-coach/releases/tag/v1.0.0) Release 是当前稳定版；`develop` 分支用于开发“通过用户反馈提升回答质量”的下一版本。

项目把 `刘辉羽毛球` 的公开抖音教学内容整理成可检索、可引用、可维护的证据型羽毛球教练 Skill，并保留更新 Skill、教学思维图和反馈审核所需的最小流水线。

这个项目尚未得到刘辉本人授权，仅作为个人学习型知识工程项目：回答时尽量使用可追溯的视频链接、时间戳、主题索引和人工视觉复核记录。

## 1.0 状态

- 稳定版：`main` / `v1.0.0`
- 开发版：`develop` / `1.1.0-dev.3`

- 获取到的抖音公开视频：`472` 条
- 已排除非教学/广告器材内容：`113` 条
- 已加入 Skill 知识库的教学视频：`350` 条
- 可理解证据覆盖：`350/350`（`331` 条转写证据，`19` 条视觉复核摘要兜底）
- 等待人工复核：`9` 条
- 最新入库教学视频：[网前框架 这样做不但不会让新手组织框架失误，还能减少身体僵硬](https://www.douyin.com/video/7661940775983482097)（`7661940775983482097`）
- 已晋升公共反馈信号：`0` 条（流水线已就绪，尚无真实 GitHub 反馈被晋升）
- 问题理解回归：`30/30` 条通过，覆盖诊断、复合问题、战术关系、动作示范与证据边界
- 回答质量回归：`30` 条来源契约已核对，`13` 条完整回答快照自动检查通过；不设置真人专家审核门槛
- 当前开发内容：问题理解、全量视频证据审计，以及由用户纠错持续驱动的本地与公共反馈闭环

## 这个 Skill 能做什么

- 回答羽毛球技术问题，例如杀球、吊球、网前、步法、发接发、双打轮转、发力和纠错。
- 通过原词、双向同义词、完整主题归属和全转写哈希特征进行高召回检索，并引用视频标题、时间戳和抖音链接。
- 根据问题内容分配文字与视频的作用：战术和原则用文字完整总结，动作形态与动态细节用文字说明观察点并以视频示范为主。
- 根据主题图谱给出系统学习路径，而不是只回答单个动作。
- 生成保守的训练计划，并按水平、单双打、独练/陪练条件和可用时长调整今日练习、3 天修正、2 周巩固与自测标准。
- 标注置信边界：哪些来自人工复核，哪些来自自动转写，哪些需要用户视频才能进一步诊断。
- 为答案中的视频分配稳定的 `V1...Vn` 编号，并记录价值、无关、遗漏、问题误解、转写错误、视频误解和引用不匹配反馈。
- 只读取用户已确认的本地反馈；相似问题可触发有上限的视频重排、问题重新规划或指定视频证据复核，并可随时关闭本地个性化。
- 把经过公开 GitHub Issue、维护者安全与来源完整性检查、脱敏和回归测试的反馈晋升为公共信号，让没有本地历史的新用户也能受益；这不是教练专家审核。

它不做这些事：

- 不代表刘辉本人。
- 不把自动转写内容当作绝对事实。
- 不提供医学诊断。
- 不提交原始视频、音频、完整转写目录、临时 CDN 地址或本地模型缓存。

## 快速使用

Skill 日常问答只需要 Python 3.10 或更新版本，全部使用标准库，不需要 `OPENAI_API_KEY`，也不需要安装 `requirements-transcription.txt`。直接安装 `v1.0.0` 稳定版 Skill：

```bash
curl -L https://github.com/MuyuanGuo/badminton-skills-coach/releases/download/v1.0.0/liuhui-badminton-coach-v1.0.0.zip \
  -o /tmp/liuhui-badminton-coach-v1.0.0.zip
install_dir="$(mktemp -d)"
unzip -q /tmp/liuhui-badminton-coach-v1.0.0.zip -d "$install_dir"
mkdir -p ~/.codex/skills
cp -R "$install_dir/liuhui-badminton-coach" ~/.codex/skills/
```

Release 同时提供 `SHA256SUMS.txt` 用于校验下载文件。上面的命令适用于当前 `v1.0.0` 稳定包；当前开发版及后续 Release 内置 doctor 和原子安装器。已经克隆仓库时，可用它安装或刷新当前检出的版本，且不会遗留新版已删除的旧文件：

```bash
python3 scripts/install_skill.py --dry-run
python3 scripts/install_skill.py
```

安装后诊断 Skill：

```bash
python3 ~/.codex/skills/liuhui-badminton-coach/scripts/doctor.py
```

维护仓库先运行 `python3 scripts/doctor.py`。只有下载和转写新增视频时才需要额外环境：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-transcription.txt
python3 scripts/doctor.py --profile all
```

Windows 可使用 `.venv\\Scripts\\python.exe`；也可通过 `LIUHUI_TRANSCRIPTION_PYTHON` 指定已有环境。

在 Codex 中使用：

```text
$liuhui-badminton-coach 我被动后场总是来不及架拍，应该怎么调整？
```

收到回答后可以直接反馈：

```text
反馈：V1 最有价值；V2 不相关；文字漏了“被动情况下如何处理”。
```

问题或来源理解有误时，可以直接写：`你理解错了，我真正问的是“……”`，或 `V2 转写错了，原视频说的是“……”`。后一种反馈必须指出具体 `V` 编号。

Skill 会先复述解析结果。用户回复 `确认用于本地个性化` 后，该记录才会变成 `accepted` 并影响后续相似问题；不确认就保持待审核，不参与回答。公开分享是另一项独立操作：必须再提供脱敏问题并确认可公开，导出命令只生成 GitHub Issue 正文，不会自动上传。

Skill 的回答流程是：

1. 先判断用户的问题属于哪个动作、场景和水平。
2. 用 `scripts/search_knowledge.py` 对知识库和全量检索索引执行高召回检索，并读取已晋升的公共反馈；默认同时读取当前本地反馈目录中的 `accepted` 记录。相似反馈若指出问题误解，则按脱敏后的真实意图重新规划；若指出来源错误，则重新核对指定视频并避免把争议证据当成定论。
3. 根据检索返回的 `answer_guidance` 选择“文字为主、文字视频并重、视频为主”，三种模式都必须给出有用文字和完整相关视频。
4. 检查完整候选清单，不因结果排在前 12 条之外就直接丢弃。
5. 必要时用 `scripts/navigate_topics.py` 定位主题图谱，再缩小场景重检。
6. 给最终推荐视频分配不重复的 `V1...Vn` 编号，并在当前任务上下文中保留编号映射。
7. 按“直接回答、文字解释、适用边界、核心视频与观看重点、完整相关视频、置信边界”输出；只有收到明确反馈后，才把问题、编号映射和反馈写入本地待审核队列。
8. 本地反馈可改变排序与表达、触发问题重新规划或来源复核，但不能替代来源证据；用 `--no-local-personalization` 可以忽略本地层。

## 主要产物

```text
skills/liuhui-badminton-coach/
  SKILL.md                         Skill 指令和回答规范
  references/knowledge-base.json   全量结构化知识库
  references/retrieval-index.json  全量教学视频高召回索引
  references/retrieval-rules.json  双向同义词和检索阈值
  references/answer-modality-rules.json
  references/practice-plan-rules.json  水平、项目、训练条件与时长适配规则
  references/feedback-rules.json   反馈解析词和队列状态
  references/feedback-signals.json 已脱敏并通过审核的公共反馈信号
  references/feedback-workflow.md  回答编号、反馈记录和审核流程
  references/topic-index.md        可读主题索引
  references/topic-map.json        结构化主题图谱
  references/practice-plan-template.md
  scripts/search_knowledge.py      本地高召回混合检索
  scripts/navigate_topics.py       主题导航和学习路径
  scripts/feedback.py              回答上下文、反馈解析和用户确认
  scripts/doctor.py                无 API、标准库运行环境自检
  scripts/install.py               原子安装并清理旧版本残留

data/
  douyin_video_index.json          抖音主页公开视频索引
  douyin_teaching_filtered.json    教学候选与排除计数
  processing/douyin_queue.json     入库处理队列
  evaluation/retrieval_cases.json  检索召回回归用例
  evaluation/answer_modality_cases.json
  evaluation/answer_quality_cases.json  最终回答黄金集候选与审核状态
  evaluation/query_understanding_cases.json 问题意图、路由和子问题拆分回归集
  evaluation/feedback_parser_cases.json
  evaluation/feedback_relevance_cases.json
  knowledge/douyin_knowledge_base.json
  knowledge/retrieval_index.json
  knowledge/topic_index.json
  knowledge/knowledge_graph_summary.json
  review/visual_review_annotations.json
  review/visual_review_queue.json

output/
  answer_quality_review_queue.md   来源忠实度与问题意图核对工作表
  liuhui-full-knowledge-map.drawio Draw.io 全量思维图
  liuhui-knowledge-map.mmd         Mermaid 思维图
  liuhui-knowledge-map.html        本地 HTML 思维图
  visual_review_queue.md           视觉复核工作表

config/
  answer_modality_rules.json       文字/视频回答分工规则
  answer_quality_rules.json        回答契约与自动检查规则
  practice_plan_rules.json         个性化训练计划与暂停规则
  douyin_classification_rules.json 教学/非教学分类规则
  feedback_rules.json              反馈解析与开发版本配置
  feedback_signals.json            可发布的脱敏公共反馈信号
  retrieval_rules.json             检索扩展词和阈值

scripts/
  doctor.py                        维护环境与可选转写依赖诊断
  install_skill.py                 原子安装当前检出的 Skill
  build_answer_quality_review_queue.py 生成30题来源与意图核对队列
  evaluate_answer_quality.py       验证黄金集并评测最终回答快照
  evaluate_query_understanding.py  评测问题意图、路由和子问题拆分
  evaluate_video_comprehension.py  审计350条视频证据和反向召回
  report_pipeline_status.py        当前状态、失败项和下一步建议
  check_douyin_updates.py          检查抖音主页是否有新视频
  prepare_douyin_media_batch.py    根据媒体快照生成下载配置
  media_assets.py                  媒体 URL、批次路径与下载内容校验
  process_douyin_ready_batch.py    下载、转写、重建、验证、提交
  run_full_update_pipeline.py      重建知识库、图谱和 Skill 引用
  build_retrieval_index.py         从完整转写生成无正文检索索引
  evaluate_answer_policy.py        评测文字/视频回答模式
  evaluate_feedback_signals.py     评测公共反馈晋升结果
  evaluate_retrieval.py            评测已知相关视频召回率
  package_skill_release.py         生成可安装 Skill 压缩包和 SHA-256
  promote_feedback.py              晋升已审核 GitHub 反馈
  test_feedback_pipeline.py        反馈解析、队列和审核回归测试
  test_answer_quality.py           黄金集门槛和答案检查器回归测试
  test_feedback_personalization.py 本地个性化回归测试
  test_feedback_promotion.py       公共晋升和隐私回归测试
  test_public_feedback_e2e.py      两个隔离安装环境的公共反馈端到端测试
  test_query_understanding.py      问题理解回归测试
  test_video_comprehension.py      转写/视觉证据理解回归测试
  test_doctor.py                   Skill 安装、doctor 与依赖诊断测试
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

准备脚本只接受与页面视频 ID 一致的抖音页面、配置中允许的 HTTPS 媒体 CDN 和仓库内批次路径；下载后还会拒绝过小文件及 HTML/XML 过期响应。媒体地址是短期凭证，失效时重新打开视频页提取，不要提交或分享 `data/tmp/`。

6. 下载、转写、重建和验证：

```bash
python3 scripts/process_douyin_ready_batch.py batch-049
```

7. 如果只是手动改了复核笔记、主题数据或知识库结构，运行：

```bash
python3 scripts/run_full_update_pipeline.py
```

8. 查看并确认本地反馈解析结果：

```bash
python3 skills/liuhui-badminton-coach/scripts/feedback.py list \
  --status pending_review

python3 skills/liuhui-badminton-coach/scripts/feedback.py review \
  --feedback-id FEEDBACK_ID \
  --decision accepted \
  --note "已核对问题、视频和来源证据"
```

默认队列位于 `${CODEX_HOME:-~/.codex}/feedback/liuhui-badminton-coach/`，也可以用 `LIUHUI_FEEDBACK_DIR` 指定其他本地目录。反馈不会自动上传；只有用户确认并标记为 `accepted` 的本地反馈会在相似问题上调整排序与表达、触发问题重规划或指定来源复核，并且不会改变教学事实。

要把一条已接受的本地反馈分享给项目，先用脱敏后的代表性问题生成公开 Issue 正文：

```bash
python3 skills/liuhui-badminton-coach/scripts/feedback.py export-github \
  --feedback-id FEEDBACK_ID \
  --public-question "脱敏后的代表性问题" \
  --public-intended-query "脱敏后的真实意图（仅问题理解错误时需要）" \
  --confirm-public \
  --output /path/to/issue-body.md
```

该命令不上传任何内容；它只返回 Issue 标题、正文和提交地址，并把本地记录标记为“已导出、未上传”。用户检查正文后自行提交。项目维护者取得本仓库真实的公开 Issue URL 后，通过 GitHub API 抓取并导入同一个本地审核队列：

```bash
python3 skills/liuhui-badminton-coach/scripts/feedback.py import-github \
  --fetch-url https://github.com/MuyuanGuo/badminton-skills-coach/issues/NUMBER
```

API 导入会保存仓库、Issue 编号、节点 ID、更新时间和正文哈希。手工 `--body-file` 导入仍可进入本地审核，但不能晋升为公共信号。晋升脚本使用独占锁，并在普通写入异常时回滚整组公共文件。

9. 对已经接受的 GitHub 反馈，先用脱敏问题进行预演：

```bash
python3 scripts/promote_feedback.py \
  --feedback-id FEEDBACK_ID \
  --public-query "脱敏后的代表性问题" \
  --evidence-note "已回看相关公开视频并核对适用边界" \
  --promoted-by MAINTAINER \
  --dry-run
```

确认预演结果后移除 `--dry-run`。脚本会同步 `config/feedback_signals.json`、Skill 公共信号和 `data/evaluation/feedback_relevance_cases.json`，但不会写入原始问题或原始反馈。随后必须运行：

```bash
python3 scripts/evaluate_feedback_signals.py
python3 scripts/evaluate_retrieval.py
python3 scripts/validate_project.py
```

10. 生成或刷新回答质量审核工作表：

```bash
python3 scripts/build_answer_quality_review_queue.py
```

维护者在 `output/answer_quality_review_queue.md` 的结构化 JSON 块中核对问题意图、来源视频、必须覆盖的文字要点和证据边界；这里不设置真人专家审核门槛。先校验、再原子写回 `data/evaluation/answer_quality_cases.json`：

```bash
python3 scripts/apply_answer_quality_review_notes.py --dry-run
python3 scripts/apply_answer_quality_review_notes.py
```

当前 30 条来源契约全部进入自动回归；13 条完整回答快照用于检查文字覆盖、视频引用和边界。问题理解和全量视频理解使用独立评测：

```bash
python3 scripts/evaluate_answer_quality.py
python3 scripts/evaluate_query_understanding.py
python3 scripts/evaluate_video_comprehension.py
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

- `pending_review`：解析成功，等待用户确认本地信号，或等待维护者检查公开信号的安全与来源完整性。
- `needs_clarification`：包含未知编号、冲突信号、缺少真实意图、缺少来源问题视频，或没有可执行信息。
- `accepted`：本地记录已由用户确认，或公开记录已通过维护者安全与来源检查；GitHub 来源仍需单独晋升才会影响公共版本。
- `rejected`：确认不应进入后续质量提升流程。
- `superseded`：同一 GitHub Issue 出现新正文修订，旧修订仅保留审计历史，不能再审核或晋升。

## 验证

本地完整验证：

```bash
git ls-files -z '*.py' | xargs -0 python3 -m py_compile
PYTHONPATH=scripts python3 -m unittest discover -s scripts -p 'test_*.py'
python3 scripts/run_full_update_pipeline.py
python3 scripts/apply_answer_quality_review_notes.py --dry-run
python3 scripts/evaluate_answer_policy.py
python3 scripts/evaluate_answer_quality.py
python3 scripts/evaluate_feedback_signals.py
python3 scripts/evaluate_query_understanding.py
python3 scripts/evaluate_retrieval.py
python3 scripts/evaluate_video_comprehension.py
node scripts/test_douyin_profile_snapshot_dom.mjs
python3 scripts/doctor.py --profile all
python3 scripts/validate_project.py
```

GitHub Actions 会执行同样的核心验证：

- Python 源码编译。
- 分类规则回归测试。
- 回答媒介分工测试：`16` 个问题均正确进入文字为主、文字视频并重或视频为主模式，并检查每种模式同时保留文字与视频义务。
- 问题理解回归：`30` 个问题固定预期的文字/视频分工、检索策略、子问题拆分和证据边界，当前要求 `30/30` 通过。
- 视频理解审计：`350/350` 条 ready 视频必须具有可读取的转写证据或视觉复核摘要，运行时读取覆盖与自身证据候选召回率都必须为 `100%`；当前构成为 `331 + 19`。
- 回答质量回归：`30` 条来源契约覆盖动作、诊断、战术、训练计划和证据边界；`13` 条完整回答快照通过文字覆盖、视频引用与禁止断言检查，不把缺失快照伪造成已评测答案。
- 检索召回回归测试：当前人工已知相关集为 `10` 个问题、`28` 条视频，要求候选召回率为 `100%`，且每题主证据进入前 `12` 条。
- 反馈回归测试：检查连续视频编号、中文自然语言解析、问题误解、转写错误、视频误解、引用不匹配、公开确认、GitHub API 来源校验和审核历史。
- 个性化与晋升测试：检查仅 `accepted` 本地反馈生效、可关闭本地层、问题纠错可触发重新规划、来源纠错可锁定复核视频、公共信号不含原问题/原反馈，并验证并发锁与失败回滚。
- 公共链路端到端测试：从一个隔离的本地反馈目录出发，经脱敏、导入、审核和晋升，把公共信号写入第二个全新 Skill 安装环境，再验证首次用户检索生效；真实平台金丝雀见 [Issue #1](https://github.com/MuyuanGuo/badminton-skills-coach/issues/1)。
- 抖音主页快照过滤回归测试，防止把 footer / 热门推荐视频误当成作者作品。
- 媒体与发布测试：拒绝路径穿越、curl 配置注入、非白名单 CDN、HTML 过期响应、临时媒体 URL 泄漏和不完整压缩包，并在隔离目录运行安装后 doctor。
- 主题与训练计划测试：禁止无关键词的 `curated` 视频混入代表视频，并检查水平、单双打、独练/陪练、时长和疼痛边界的适配。
- 幂等与一致性测试：无内容变化时知识库版本戳不漂移，重复全量构建的核心派生产物哈希保持一致，Skill 参考文件按完整集合原子同步。
- JSON、Draw.io、Skill frontmatter、队列计数、知识库同步、主题索引、主题图谱和视觉复核队列一致性验证。

## 技术栈

- Codex Skills：封装教练工作流和回答规范。
- Python 3：队列处理、知识库构建、高召回检索、本地个性化、公共反馈晋升、回答媒介分工、黄金集评测、主题索引、图谱生成和验证。
- `faster-whisper`：本地中文语音转写。
- Browser-side JavaScript：从已登录抖音页面提取主页快照和视频媒体资源。
- Draw.io / Mermaid / HTML：生成全量教学主题图谱。
- GitHub Actions：持续验证 Skill 与知识库产物一致性。
- GitHub Issue Forms：收集经过用户确认可公开的结构化回答反馈。

## 1.0 之后怎么演进

`main` / `v1.0.0` 继续作为稳定版；反馈闭环只在 `develop` / `1.1.0-dev.3` 开发和验证，成熟后再单独发布：

- 刘辉发布新教学视频：走增量更新流程。
- 分类误判：改 `config/douyin_classification_rules.json` 并补测试。
- 回答质量不足：先判断是问题理解、视频转写/解释、检索召回还是答案组织错误；把真实问题加入对应自动回归集，再按用户纠错调整路由、证据或 Skill 指令。
- 用户反馈：本地 `accepted` 信号只服务使用同一反馈目录的环境；公共信号必须来自 GitHub Issue，并经过脱敏、维护者安全与来源完整性检查、回归测试和版本发布，不要求羽毛球专家审核。
- 主题图谱不够清楚：调整 topic index / graph 生成逻辑。
- 新增大量课程或直播切片：另起分支设计，不混入当前 1.0 稳定版。

## License 和内容边界

本项目原创软件代码和自动化脚本采用 [MIT License](LICENSE)。第三方视频、音频、创作者名称、视频标题、缩略图、转写和其他来源材料不包含在 MIT 授权中，详细边界见 [NOTICE](NOTICE)。

本仓库只保存结构化索引、教学笔记、主题图谱、已脱敏公共反馈信号和维护脚本。检索索引会从本地完整转写生成术语命中、主题归属和不含正文的字符 n-gram 哈希，但不包含完整转写正文。原始视频、音频、完整转写目录、临时媒体 URL、模型缓存和用户本地反馈队列不提交。反馈默认只保存在用户自己的 Codex 目录；公共信号只保留脱敏问题与真实意图、视频 ID、问题类型、来源复核目标、核证说明、公开 Issue 来源及已审核正文的 SHA-256，不保留原始问题或原始反馈。项目未获得刘辉本人或抖音授权，公开视频链接仅作为来源引用；使用者应自行遵守平台规则和相关版权要求。
