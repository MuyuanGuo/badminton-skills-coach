# Badminton Skills Coach / 刘辉羽毛球教练 Skill

[![Validate Skill artifacts](https://github.com/MuyuanGuo/badminton-skills-coach/actions/workflows/validate.yml/badge.svg)](https://github.com/MuyuanGuo/badminton-skills-coach/actions/workflows/validate.yml)
[![Latest release](https://img.shields.io/github/v/release/MuyuanGuo/badminton-skills-coach)](https://github.com/MuyuanGuo/badminton-skills-coach/releases/latest)
[![License: MIT](https://img.shields.io/badge/code%20license-MIT-2f766d.svg)](LICENSE)

![Badminton Skills Coach：352 条教学视频、证据型检索与刘辉教学图谱](.github/assets/social-preview.png)

这是 `Badminton Skills Coach` 的 **1.1.0 稳定版**。GitHub `main` 分支和 [`v1.1.0`](https://github.com/MuyuanGuo/badminton-skills-coach/releases/tag/v1.1.0) Release 提供当前正式版本；`develop` 分支用于后续增量维护。

项目把 `刘辉羽毛球` 的公开抖音教学内容整理成可检索、可引用、可维护的证据型羽毛球教练 Skill，并保留更新 Skill、教学思维图和反馈审核所需的最小流水线。

这个项目尚未得到刘辉本人授权，仅作为个人学习型知识工程项目：回答时尽量使用可追溯的视频链接、时间戳、主题索引和人工视觉复核记录。

## 当前状态

- 稳定版：`main` / `v1.1.0`
- 开发分支：`develop`

- 获取到的抖音公开视频：`473` 条
- 已排除非教学/广告器材内容：`121` 条
- 已加入 Skill 知识库的教学视频：`352` 条
- 可理解证据覆盖：`352/352`（`333` 条转写证据，`19` 条视觉复核摘要兜底）
- 等待人工复核：`0` 条
- 最新入库教学视频：[4280 多点位抽球应用 这种准备就是应对快速腹部胸口位置的准备，可以有效的优化两边的出拍速度的合理性，一般对口抽挡中](https://www.douyin.com/video/7663523942439940453)（`7663523942439940453`）
- 已晋升公共反馈信号：`0` 条（流水线已就绪，尚无真实 GitHub 反馈被晋升）
- 问题理解回归：`34/34` 条通过（`30` 条来源契约问题 + `4` 条对抗问题），覆盖诊断、复合问题、否定条件、战术关系、动作示范与证据边界
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

Skill 日常问答只需要 Python 3.10 或更新版本，全部使用标准库，不需要 `OPENAI_API_KEY`，也不需要安装 `requirements-transcription.txt`。直接安装 `v1.1.0` 稳定版 Skill：

```bash
curl -L https://github.com/MuyuanGuo/badminton-skills-coach/releases/download/v1.1.0/liuhui-badminton-coach-v1.1.0.zip \
  -o /tmp/liuhui-badminton-coach-v1.1.0.zip
install_dir="$(mktemp -d)"
unzip -q /tmp/liuhui-badminton-coach-v1.1.0.zip -d "$install_dir"
mkdir -p ~/.codex/skills
cp -R "$install_dir/liuhui-badminton-coach" ~/.codex/skills/
```

Release 同时提供 `SHA256SUMS.txt` 用于校验下载文件。当前 Release 内置 doctor 和原子安装器。已经克隆仓库时，可用它安装或刷新当前检出的版本，且不会遗留新版已删除的旧文件：

```bash
python3 scripts/install_skill.py --dry-run
python3 scripts/install_skill.py
```

安装后诊断 Skill：

```bash
python3 ~/.codex/skills/liuhui-badminton-coach/scripts/doctor.py
```

维护仓库先运行 `python3 scripts/doctor.py`。只有下载和转写新增视频时才需要额外环境；自动下载还需要 Chrome 或 Edge，以及带内置 WebSocket 的 Node.js 22 或更新版本：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-transcription.txt
python3 scripts/doctor.py --profile all
```

Windows 可使用 `.venv\\Scripts\\python.exe`；也可通过 `LIUHUI_TRANSCRIPTION_PYTHON` 指定已有环境，通过 `LIUHUI_CHROME` 指定 Chrome/Edge 可执行文件。

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

1. 用 `scripts/prepare_answer_context.py` 接收用户的完整原问题，一次完成动作、症状、场景、排除条件、所需回答形式和证据边界解析。
2. 编排器按问题类型组合主题导航、原问题和定向扩展问题，对完整知识库执行多路高召回检索；同时读取已晋升的公共反馈，并默认读取当前本地反馈目录中的 `accepted` 记录。
3. 确定性最终选择器检查完整候选清单，综合结构化意图、主题、转写证据、负向条件和来源状态选择视频；输出每条入选/拒绝理由，并在结果过多时明确标记 `selection_truncated`。
4. 编排器只对 `ready` 视频读取可引用证据、分配不重复的 `V1...Vn` 编号，并返回时间戳证据片段；非教学、待复核和不存在的视频 ID 会被明确拒绝。
5. 根据 `answer_guidance` 选择“文字为主、文字视频并重、视频为主”；三种模式都必须先给出有用文字，再让视频承担动作示范、动态细节或实战演示。
6. Skill 按“直接回答、文字解释、适用边界、核心视频与观看重点、完整相关视频、置信边界”组织答案，并只能基于编排器提供的证据陈述刘辉的教学内容。
7. 相似的正向反馈可以在等价问法间迁移；负向、问题纠错和来源纠错只有在动作、症状、场景、排除词和回答目标严格兼容时才会生效，且不能替代来源证据。
8. 只有收到明确反馈后，Skill 才把当前问题、`V` 编号映射和反馈写入本地待审核队列；用 `--no-local-personalization` 可以忽略本地层。

## 主要产物

```text
skills/liuhui-badminton-coach/
  SKILL.md                         Skill 指令和回答规范
  references/knowledge-base.json   全量结构化知识库
  references/retrieval-index.json  全量教学视频高召回索引
  references/retrieval-rules.json  双向同义词和检索阈值
  references/answer-selection-rules.json 最终视频选择与负向边界规则
  references/answer-modality-rules.json
  references/practice-plan-rules.json  水平、项目、训练条件与时长适配规则
  references/feedback-rules.json   反馈解析词和队列状态
  references/feedback-signals.json 已脱敏并通过审核的公共反馈信号
  references/feedback-workflow.md  回答编号、反馈记录和审核流程
  references/answer-workflow.md    统一检索、证据读取与回答流程
  references/build-manifest.json   语料、规则和安装产物哈希清单
  references/topic-index.md        可读主题索引
  references/topic-map.json        结构化主题图谱
  references/practice-plan-template.md
  scripts/search_knowledge.py      本地高召回混合检索
  scripts/prepare_answer_context.py 统一问题规划、召回、选择和证据编排
  scripts/navigate_topics.py       主题导航和学习路径
  scripts/feedback.py              回答上下文、反馈解析和用户确认
  scripts/doctor.py                无 API、标准库运行环境自检
  scripts/install.py               原子安装并清理旧版本残留

data/
  douyin_video_index.json          抖音主页公开视频索引
  douyin_teaching_filtered.json    教学候选与排除计数
  douyin_classification_ledger.json 分类规则版本、决定与迁移账本
  processing/douyin_queue.json     入库处理队列
  evaluation/retrieval_cases.json  检索召回回归用例
  evaluation/answer_modality_cases.json
  evaluation/answer_quality_cases.json  最终回答黄金集候选与审核状态
  evaluation/query_understanding_cases.json 问题意图、路由和子问题拆分回归集
  evaluation/feedback_parser_cases.json
  evaluation/feedback_relevance_cases.json
  knowledge/douyin_knowledge_base.json
  knowledge/retrieval_index.json
  knowledge/build_manifest.json    可复现构建与 Skill 文件哈希
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
  classification-drift-report.json 分类规则漂移报告
  video-link-health.json           抖音链接语法与抽样健康检查

config/
  answer_modality_rules.json       文字/视频回答分工规则
  answer_selection_rules.json      最终视频选择、排除和数量规则
  answer_quality_rules.json        回答契约与自动检查规则
  practice_plan_rules.json         个性化训练计划与暂停规则
  douyin_classification_rules.json 教学/非教学分类规则
  feedback_rules.json              反馈解析与版本配置
  feedback_signals.json            可发布的脱敏公共反馈信号
  retrieval_rules.json             检索扩展词和阈值
  topic_taxonomy.json              主题层级和动作归属配置

scripts/
  doctor.py                        维护环境与可选转写依赖诊断
  install_skill.py                 原子安装当前检出的 Skill
  build_answer_quality_review_queue.py 生成30题来源与意图核对队列
  evaluate_answer_quality.py       验证黄金集并评测最终回答快照
  evaluate_answer_context.py       评测编排器最终选择、主证据和负样本
  evaluate_query_understanding.py  评测问题意图、路由和子问题拆分
  evaluate_video_comprehension.py  审计352条可移植证据及独立问题召回
  report_pipeline_status.py        当前状态、失败项和下一步建议
  check_douyin_updates.py          检查抖音主页是否有新视频
  download_douyin_browser_batch.py 隔离匿名浏览器下载、作者校验和队列断点
  export_douyin_cookies_cdp.mjs    通过 CDP 临时导出匿名抖音 Cookie
  prepare_douyin_media_batch.py    根据媒体快照生成下载配置
  media_assets.py                  媒体 URL、批次路径与下载内容校验
  process_douyin_ready_batch.py    下载、转写、完整质量门禁、提交
  run_full_update_pipeline.py      重建知识库、图谱和 Skill 引用
  build_retrieval_index.py         从完整转写生成无正文检索索引
  build_manifest.py                生成确定性构建和安装产物哈希清单
  check_video_links.py             检查全部链接语法及确定性网络抽样
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
  test_answer_context.py           统一编排器和最终选择器回归测试
  test_build_reproducibility.py    索引、清单和链接抽样可复现测试
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

5. 下载新增教学视频时，推荐让批处理脚本自动创建隔离的匿名 Chrome 会话。它通过 CDP 取得本次会话的匿名抖音 Cookie，交给 `yt-dlp` 识别视频，再核对视频 ID、刘辉主页 ID、时长和媒体格式。Cookie 和临时浏览器资料只存在于系统临时目录，处理结束即删除，不读取个人 Chrome 登录资料，也不写入仓库。先预检：

```bash
python3 scripts/process_douyin_ready_batch.py batch-049 \
  --auto-download \
  --video-id <video_id> \
  --preflight-only
```

原有的页面直链方案仍然保留。视频开始播放后，可在普通浏览器的 DevTools Console 中运行：

```text
scripts/douyin_video_media_assets_dom.js
```

必须在页面自身的浏览器上下文中运行，不能使用看不到网络资源记录的只读 Agent 页面求值接口。保存为 `data/tmp/<video_id>-media-assets.json`；只有结果中的 `collection_status` 为 `ready` 且存在 `preferred_video` 或 `preferred_audio` 时，才准备批次：

```bash
python3 scripts/prepare_douyin_media_batch.py \
  --input data/tmp/<video_id>-media-assets.json \
  --batch batch-049
```

准备脚本只接受 20 分钟内、与页面视频 ID 一致的抖音页面快照、配置中允许的 HTTPS 媒体 CDN 和仓库内批次路径。默认优先选择当前页面主视频元素对应的视频轨，避免把页面预加载的其他音频误当成目标视频；下载后还会拒绝过小文件、HTML/XML 过期响应和无法识别的媒体文件。媒体地址是短期凭证，不要提交或分享 `data/tmp/`。如果采集结果是 `no_downloadable_media`，或者只看到 `blob:`/MediaSource 播放地址，直接使用上面的 `--auto-download` 路径；不要反复刷新已经无法暴露直链的页面。

6. 下载、转写、重建和验证：

```bash
python3 scripts/doctor.py --profile transcription
python3 scripts/process_douyin_ready_batch.py batch-049 \
  --auto-download \
  --video-id <video_id>
```

预检会确认工作区边界、磁盘、curl、Chrome/Edge、Node.js、`yt-dlp`、`faster-whisper` 和本地 `small` 模型都可用，但不会联网或下载媒体。正式处理优先处理已经准备好的原直链下载；直链过期或页面只有 `blob:` 播放流时，`--auto-download` 会自动切换到隔离匿名浏览器路径。下载完成后，流程会校验媒体签名，把转写结果与源媒体 SHA-256 绑定，清理临时媒体状态，再运行完整回归、回答质量、问题理解、检索、视频理解、构建清单和链接门禁；全部通过后才提交并推送。脚本会拒绝把无关的既有工作区改动一起提交；需要只提交到本地时加 `--no-push`。

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
python3 scripts/evaluate_video_comprehension.py --require-raw-transcripts
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

当前队列为 `{"transcribed": 407}`，没有失败项。

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
python3 scripts/evaluate_answer_context.py
python3 scripts/evaluate_answer_quality.py
python3 scripts/evaluate_feedback_signals.py
python3 scripts/evaluate_query_understanding.py
python3 scripts/evaluate_retrieval.py
python3 scripts/evaluate_video_comprehension.py --require-raw-transcripts
python3 scripts/build_manifest.py --check
python3 scripts/check_video_links.py
node scripts/test_douyin_profile_snapshot_dom.mjs
python3 scripts/doctor.py --profile all
python3 scripts/validate_project.py
```

GitHub Actions 会执行同样的核心验证：

- Python 源码编译。
- 分类规则回归测试。
- 回答媒介分工测试：`16` 个问题均正确进入文字为主、文字视频并重或视频为主模式，并检查每种模式同时保留文字与视频义务。
- 问题理解回归：`30` 个来源契约问题和 `4` 个对抗问题固定预期的动作、症状、否定条件、文字/视频分工、检索策略、子问题拆分和证据边界，当前要求 `34/34` 通过。
- 视频理解审计：GitHub Actions 对 `352/352` 条 ready 视频检查仓库内可移植的转写证据或视觉复核摘要、运行时读取、索引与分段一致性，三项覆盖率都必须为 `100%`；当前构成为 `333 + 19`。另用 `30` 个独立用户问题、`83` 个已知相关视频和 `21` 个已知负样本检查检索，不再让视频用自己的证据反查自己。原始转写文件不进入 Git，维护者在本机另用 `--require-raw-transcripts` 验证 333 条证据都能回溯到原始转写。
- 回答质量回归：`30` 条来源契约覆盖动作、诊断、战术、训练计划和证据边界；`13` 条完整回答快照通过文字覆盖、视频引用与禁止断言检查，不把缺失快照伪造成已评测答案。
- 检索与最终选择回归：`30` 个独立问题的 `83/83` 个已知相关视频进入高召回候选集，原始排序有 `25/27` 个问题在前 `12` 条命中主证据；最终编排器选入 `82/83` 个已知相关视频并在 `27/27` 个问题中选中主证据，`21` 个已知负样本入选数为 `0`。
- 反馈回归测试：检查连续视频编号、中文自然语言解析、问题误解、转写错误、视频误解、引用不匹配、公开确认、GitHub API 来源校验和审核历史。
- 个性化与晋升测试：检查仅 `accepted` 本地反馈生效、可关闭本地层、正向信号可在等价问法间迁移、负向与纠错信号必须严格匹配结构化意图、公共信号不含原问题/原反馈，并验证并发锁与失败回滚。尚无真实公共信号时，仍运行 `7` 个对抗检查，但不把合成用例报告成真实用户反馈。
- 公共链路端到端测试：从一个隔离的本地反馈目录出发，经脱敏、导入、审核和晋升，把公共信号写入第二个全新 Skill 安装环境，再验证首次用户检索生效；真实平台金丝雀见 [Issue #1](https://github.com/MuyuanGuo/badminton-skills-coach/issues/1)。
- 抖音主页快照过滤回归测试，防止把 footer / 热门推荐视频误当成作者作品。
- 媒体与发布测试：拒绝路径穿越、curl 配置注入、非白名单 CDN、HTML 过期响应、临时媒体 URL 泄漏和不完整压缩包，并在隔离目录运行安装后 doctor。
- 主题与训练计划测试：禁止无关键词的 `curated` 视频混入代表视频，并检查水平、单双打、独练/陪练、时长和疼痛边界的适配。
- 幂等与一致性测试：无内容变化时知识库版本戳不漂移，重复全量构建的检索索引和构建清单逐字节一致，Skill 参考文件按完整集合原子同步；清单记录语料、分类、检索、回答规则和全部可安装文件的 SHA-256。
- JSON、Draw.io、Skill frontmatter、队列计数、知识库同步、主题索引、主题图谱和视觉复核队列一致性验证。

## 技术栈

- Codex Skills：封装教练工作流和回答规范。
- Python 3：队列处理、知识库构建、高召回检索、统一问答编排、最终视频选择、本地个性化、公共反馈晋升、回答媒介分工、独立评测、主题索引、可复现清单、图谱生成和验证。
- `faster-whisper`：本地中文语音转写。
- Browser-side JavaScript：从已登录抖音页面提取主页快照和视频媒体资源。
- Draw.io / Mermaid / HTML：生成全量教学主题图谱。
- GitHub Actions：持续验证 Skill 与知识库产物一致性。
- GitHub Issue Forms：收集经过用户确认可公开的结构化回答反馈。

## 后续怎么演进

`main` / `v1.1.0` 是当前稳定版；后续内容和功能更新先在 `develop` 验证，成熟后再单独发布：

- 刘辉发布新教学视频：走增量更新流程。
- 分类误判：改 `config/douyin_classification_rules.json` 并补测试。
- 回答质量不足：先判断是问题理解、视频转写/解释、检索召回还是答案组织错误；把真实问题加入对应自动回归集，再按用户纠错调整路由、证据或 Skill 指令。
- 用户反馈：本地 `accepted` 信号只服务使用同一反馈目录的环境；公共信号必须来自 GitHub Issue，并经过脱敏、维护者安全与来源完整性检查、回归测试和版本发布，不要求羽毛球专家审核。
- 主题图谱不够清楚：调整 topic index / graph 生成逻辑。
- 新增大量课程或直播切片：另起分支设计，不直接混入当前稳定版。

## License 和内容边界

本项目原创软件代码和自动化脚本采用 [MIT License](LICENSE)。第三方视频、音频、创作者名称、视频标题、缩略图、转写和其他来源材料不包含在 MIT 授权中，详细边界见 [NOTICE](NOTICE)。

本仓库只保存结构化索引、教学笔记、主题图谱、已脱敏公共反馈信号和维护脚本。检索索引会从本地完整转写生成术语命中、主题归属和不含正文的字符 n-gram 哈希，但不包含完整转写正文。原始视频、音频、完整转写目录、临时媒体 URL、模型缓存和用户本地反馈队列不提交。反馈默认只保存在用户自己的 Codex 目录；公共信号只保留脱敏问题与真实意图、视频 ID、问题类型、来源复核目标、核证说明、公开 Issue 来源及已审核正文的 SHA-256，不保留原始问题或原始反馈。项目未获得刘辉本人或抖音授权，公开视频链接仅作为来源引用；使用者应自行遵守平台规则和相关版权要求。
