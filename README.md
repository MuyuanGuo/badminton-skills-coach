<!-- README_PROFILE: develop -->
# Badminton Skills Coach — Development

[![Validate Skill artifacts](https://github.com/MuyuanGuo/badminton-skills-coach/actions/workflows/validate.yml/badge.svg?branch=develop)](https://github.com/MuyuanGuo/badminton-skills-coach/actions/workflows/validate.yml)
[![Latest release](https://img.shields.io/github/v/release/MuyuanGuo/badminton-skills-coach)](https://github.com/MuyuanGuo/badminton-skills-coach/releases/latest)
[![Python 3.10–3.12](https://img.shields.io/badge/python-3.10%E2%80%933.12-3776ab.svg)](requirements-dev.txt)
[![License: MIT](https://img.shields.io/badge/code%20license-MIT-2f766d.svg)](LICENSE)
[![Data & sources: separate terms](https://img.shields.io/badge/data%20%26%20sources-separate%20terms-6b5b95.svg)](LICENSE-DATA)

![Badminton Skills Coach：证据驱动的羽毛球视频知识库](.github/assets/social-preview.jpg)

这是 `develop` 分支的工程说明，面向希望理解、验证或维护系统的人。重点是系统边界、证据模型、质量门禁、可复现性与工程取舍；普通用户的安装与使用说明位于 `main`。

This is the engineering guide for the `develop` branch. It explains the system boundaries, evidence model, quality gates, reproducibility, and engineering trade-offs; installation and usage guidance for regular users lives on `main`.

你正在查看 `develop` 分支；当前开发版本是 **2.1.4-dev.1**，发布状态为 **unreleased**。稳定安装仍来自 `main` 与 [v2.1.3](https://github.com/MuyuanGuo/badminton-skills-coach/releases/tag/v2.1.3)。

You are viewing the `develop` branch; the current development version is **2.1.4-dev.1** and its release status is **unreleased**. Stable installs remain on `main` and [v2.1.3](https://github.com/MuyuanGuo/badminton-skills-coach/releases/tag/v2.1.3).

本项目独立开发，不是刘辉本人，也不代表刘辉或来源发布者的认可。 / This independent project is not authored, operated, endorsed, or approved by Liu Hui or the source publishers.

## 工程概览 / Engineering overview

| 维度 / Area | 当前实现 / Implementation |
| --- | --- |
| 产品判断 / Product judgment | 把“给几个羽毛球视频”收敛成有来源、范围、置信边界与反馈闭环的诊断产品。 / Turns “show me badminton videos” into a diagnostic product with provenance, scope, confidence boundaries, and a feedback loop. |
| 数据工程 / Data engineering | 抖音与 B 站异构来源经过准入、媒体校验、确定性 ASR、质量隔离、证据分层和可复现构建。 / Heterogeneous Douyin and Bilibili sources pass admission, media validation, deterministic ASR, quarantine, evidence layering, and reproducible builds. |
| 检索与回答 / Retrieval & answers | 查询被拆成角色、动作、条件与交付项；所有可回答视频先进入完整证据分层，只有逐结论授权的 synthesis evidence 用于技术正文，核心列表与完整列表承担不同展示职责。 / Queries are decomposed into actors, actions, conditions, and delivery items; all answerable videos first enter the complete evidence layers, while only claim-authorized synthesis evidence may support technical prose and the core and complete lists serve different presentation roles. |
| 质量工程 / Quality engineering | 14 套评估、跨 Python 版本测试、运行时预算、机械接线 canary、答案复现与全文审计共同构成发布门禁。 / Fourteen evaluation suites, cross-version tests, runtime budgets, wiring canaries, answer reproduction, and full-context audits form the release gate. |
| 安全与治理 / Safety & governance | 本地反馈默认私有；公开晋升需要脱敏、授权、来源复核与回归测试；发布物带哈希、SBOM 与签名验证。 / Local feedback is private by default; public promotion requires redaction, consent, source re-verification, and regression tests; releases carry hashes, an SBOM, and signature checks. |

当前 build：`f22bc76f44a3…`。`develop` is the integration branch；`main` is the stable release source。

## 从用户提问到最终回答 / From user question to final answer

一次回答不是“把问题变成关键词，再取排名最高的视频”。运行时会保存轮次关系，解析问题结构，对每个子问题分别召回和核查证据，再用受约束的 answer packet 组织内容；只有通过完整上下文审计的结果才能发送。下图中的澄清回复会回到入口重新检索，旧轮次的视频、标签和结论不会直接复用。

An answer is not produced by turning the question into keywords and taking the highest-ranked videos. The runtime preserves turn state, parses the problem structure, retrieves and validates evidence for each query unit, and composes through a constrained answer packet. Only a result that passes the full-context audit can be sent. A clarification reply re-enters the pipeline and reruns retrieval; videos, labels, and claims from the previous turn are not carried forward.

~~~mermaid
flowchart TD
    Q["1. 用户提交完整问题 / User submits the full question"] --> T{"2. 新问题还是澄清回复？ / New question or clarification reply?"}
    T -->|新问题 / New| N["建立新轮次 / Start a new turn"]
    T -->|澄清回复 / Continuation| K["校验旧 context 与 question_id；拒绝猜测绑定 / Validate prior context and question IDs; never guess bindings"]
    K --> N
    N --> U["3. 规范术语；解析意图、主体、事件链、条件、子问题与交付要求 / Canonicalize terms; parse intent, actors, event chain, constraints, query units, and deliverables"]
    U --> P["4. 生成受保护检索单元、扩展词与预算 / Build protected retrieval units, expansions, and a query budget"]
    P --> R["5. 只读 SQLite 混合高召回检索 / Hybrid high-recall retrieval from the read-only SQLite store"]
    R --> E["6. 逐子问题语义准入：ready、来源、主体、动作、场景、概念与症状 / Per-unit semantic admission: readiness, provenance, actors, actions, scope, concepts, and symptoms"]
    E --> L["7. 保留可回答全集；再做去重与合成层限流 / Preserve the full answerable set; then deduplicate and bound synthesis"]
    L --> W["8. 加载教学笔记、时间戳窗口、evidence_id 与 canonical URL / Resolve teaching notes, timestamp windows, evidence IDs, and canonical URLs"]
    W --> C["9. 构建诊断、澄清、完整性、交付与安全边界契约 / Build diagnostic, clarification, completeness, delivery, and safety-boundary contracts"]
    C --> H{"10. 仍有关键歧义？ / Material ambiguity remains?"}
    H -->|是 / Yes| F["保留条件结论并生成带稳定 ID 的聚焦问题 / Keep conclusions conditional and produce focused questions with stable IDs"]
    H -->|否 / No| B["11. 生成完整 audit context 与 SHA-256 绑定的紧凑 answer packet / Build the full audit context and SHA-256-bound compact answer packet"]
    F --> B
    B --> S["12. 仅按 claim allowlist 与 synthesis evidence 组织技术内容 / Compose technical content only from claim allowlists and synthesis evidence"]
    S --> V["13. 选择最多 5 条核心视频（证据不足不补齐），同时保留 packet 授权的完整相关清单 / Choose up to five core videos without padding and preserve the complete packet-authorized list"]
    V --> D["14. 确定性 renderer 输出结论、typed delivery blocks、V 标签、URL 与反馈提示 / Deterministic renderer emits claims, typed delivery blocks, V labels, URLs, and the feedback prompt"]
    D --> A{"15. 完整上下文 auditor 通过？ / Does the full-context audit pass?"}
    A -->|否 / No| X["只修订 ID draft 或措辞；不得削弱 context、证据或门禁 / Revise only the ID draft or wording; never weaken context, evidence, or gates"]
    X --> D
    A -->|是 / Yes| O["16. 向用户发送回答 / Send the answer to the user"]
    O -->|用户补充澄清 / User clarifies| T
~~~

| 阶段 / Stage | 具体处理 / What happens | 失败保护 / Fail-closed behavior |
| --- | --- | --- |
| 轮次绑定 / Turn binding | 新问题建立新状态；澄清回复必须绑定上一轮完整 context 与稳定 `question_id`，随后重新规划。 / A new question starts fresh state; a clarification reply must bind to the complete prior context and stable `question_id` values before replanning. | 空回复、未知或重复 ID、被修改的旧状态以及无法可靠绑定的自由文本都会被拒绝；不沿用旧 packet、V 标签或证据映射。 / Empty replies, unknown or duplicate IDs, modified state, and ambiguous free text are rejected; prior packets, V labels, and evidence mappings are never reused. |
| 问题理解 / Query understanding | 纠正常见术语输入，解析目标主体、指代、对手或搭档、动作顺序、场景条件、否定、独立子问题，以及诊断、训练、战术等交付要求。 / Canonicalizes common terminology and resolves target actors, references, opponent or partner context, event order, scenario constraints, negation, independent query units, and requested diagnostic, practice, or tactical deliverables. | 子问题只继承允许继承的根场景约束；独立问题保持隔离，用户猜测不会被升级为已确认原因。 / Child units inherit only permitted root constraints; independent questions stay isolated, and a user hypothesis never becomes a confirmed cause. |
| 检索规划与召回 / Retrieval planning and recall | 为原问题和每个证据子问题生成受保护 query unit、受控扩展与硬预算，再对只读运行时库执行 hybrid、exhaustive、chunk-first 检索；topic navigation 只提供导航。 / Builds protected query units, controlled expansions, and a hard query budget, then runs hybrid, exhaustive, chunk-first retrieval against the read-only runtime store; topic navigation remains navigational. | 标题、标签、类别、反馈先验和排序分数只能帮助召回，不能证明技术结论；必答单元超过硬上限时明确暴露缺口。 / Titles, tags, categories, feedback priors, and ranking scores may retrieve candidates but cannot prove coaching claims; required units beyond the hard limit surface an explicit gap. |
| 语义准入 / Semantic admission | 每条候选按各自子问题核查 ready 状态、回答资格、来源与证据模式、主体、动作、正反手、场区、单双打、主动被动、概念、症状和关注点。 / Each candidate is checked per query unit for ready state, answer eligibility, provenance and evidence mode, actors, actions, handedness, court zone, singles or doubles, active or passive state, concepts, symptoms, and focus. | 不匹配的记录进入 rejected；仍可回答但因重复簇、扩展配额或补充证据策略不参与合成的记录进入 deferred，而不是被误报为不可回答。 / Non-matches become rejected; answerable records withheld from synthesis by duplicate clustering, expansion limits, or supplemental policy become deferred rather than being mislabeled unanswerable. |
| 证据分层与物化 / Evidence layering and materialization | 保留完整 `semantic_answerable` 集；在其上形成 synthesis candidates、每结论最多三条 synthesis evidence、最多五条且不为凑数而补齐的 `core_videos`，以及 packet 授权范围内完整的 `complete_related_videos`，并加载教学笔记、命中 chunks 或受限窗口、稳定证据 ID 和 canonical URL。 / Preserves the complete `semantic_answerable` set, then derives synthesis candidates, at most three synthesis sources per claim, up to five `core_videos` without padding weak evidence, and the exhaustive packet-authorized `complete_related_videos`, resolving teaching notes, matching chunks or bounded windows, stable evidence IDs, and canonical URLs. | 展示清单不能反向定义“哪些视频能回答”；complete-list-only 证据不得被借来扩张技术正文，补充证据必须保持条件和置信上限。 / The visible list cannot redefine which videos are answerable; complete-list-only evidence cannot expand technical prose, and supplemental evidence retains its conditions and confidence ceiling. |
| 契约与澄清 / Contracts and clarification | 构建 diagnostic model、`claim_evidence_map`、clarification state、completeness contract、typed delivery contract，以及疼痛、购买或来源身份等边界。 / Builds the diagnostic model, `claim_evidence_map`, clarification state, completeness contract, typed delivery contract, and boundaries for pain, purchases, authorship, and related risks. | 缺少关键观察时只给条件结论并提出带稳定 ID 的聚焦问题；训练时长、进阶、检查表、战术分支、成功标准和证据边界均是不可被引用替代的原子交付项。 / Missing observations keep conclusions conditional and produce focused questions with stable IDs; session duration, progressions, checklists, tactical branches, success criteria, and evidence boundaries are atomic obligations that citations cannot replace. |
| 上下文、packet 与组织 / Context, packet, and composition | 完整 context 只供审计；模型读取与其 SHA-256 绑定、受 token budget 约束的紧凑 packet，并且只能使用当前 claim 的 allowlist、reviewed atoms 或绑定窗口组织内容。 / The full context is audit-only; the model reads a token-budgeted compact packet bound to it by SHA-256 and may compose only from the current claim's allowlist, reviewed atoms, or bound windows. | 不允许跨结论转移证据，也不允许从原始转写、旧轮次、被隔离记录或 packet 外信息补洞。 / Evidence permission cannot transfer across claims, and gaps cannot be filled from raw transcripts, prior turns, quarantined records, or information outside the packet. |
| 渲染、审计与发送 / Rendering, audit, and delivery | 确定性 renderer 生成结论、typed delivery blocks、核心视频、完整相关视频、稳定 V 标签、证据 ID、唯一 canonical URL 与反馈提示；auditor 再检查 question/context/packet 绑定、引用、范围、置信度、完整性、澄清和所有交付项。 / The deterministic renderer emits claims, typed delivery blocks, core and complete video lists, stable V labels, evidence IDs, one canonical URL per source, and the feedback prompt; the auditor then checks question/context/packet binding, citations, scope, confidence, completeness, clarification, and every delivery item. | 审计失败只允许修订 ID draft 或措辞并重新渲染，不能修改 context 来“让答案通过”；只有 `passed: true` 才发送。 / An audit failure may revise only the ID draft or wording before rerendering; the context cannot be weakened to make an answer pass, and only `passed: true` may be sent. |

关键不变量 / Key invariants:

- 标题和关键词只能召回候选，不能证明技术结论。 / Titles and keywords may retrieve candidates but cannot prove a coaching claim.
- `candidate → semantic_answerable → synthesis → selected/claim_mapped` 是不同集合，不能用最终展示列表代替完整证据集。 / Candidate, semantically answerable, synthesis, and selected/claim-mapped sets are distinct; the visible list cannot substitute for the complete evidence set.
- 单个结论最多使用 1–3 条最强证据；整篇答案可以因独立子问题而展示更多。 / Each claim uses at most one to three strong sources; a full answer may show more for independent subproblems.
- answer packet 与完整上下文通过 SHA-256 绑定；模型读取紧凑投影，审计器检查完整范围。 / The answer packet and full context are SHA-256 bound; the model sees the compact projection while the auditor checks the complete scope.

## 数据与证据链 / Data and evidence chain

~~~mermaid
flowchart LR
    B["来源准入与媒体校验"] --> C["可解码媒体"]
    C --> D["确定性ASR"]
    D --> P["转写配方、ASR质量、来源安全与重复硬门禁"]
    P --> E["结构化知识库（含隔离审计记录）"]
    E --> A["回答资格分层：primary / supplemental / none"]
    A --> S["只读 SQLite 运行时证据存储"]
    S --> F["45秒 chunk-first + 受限窗口检索"]
    F --> R["answer packet、renderer 与最终审计"]
~~~

~~~mermaid
flowchart LR
    B["Source admission and media validation"] --> C["Decodable media"]
    C --> D["Deterministic ASR"]
    D --> P["Recipe, ASR quality, source-safety, and duplicate hard gates"]
    P --> E["Structured knowledge, including quarantine audit records"]
    E --> A["Answer admission layers: primary / supplemental / none"]
    A --> S["Read-only SQLite runtime evidence store"]
    S --> F["45-second chunk-first plus bounded-window retrieval"]
    F --> R["Answer packet, renderer, and final audit"]
~~~

新增转写不会写入模型权重或成为 Codex 的会话记忆。原始 `.json`、`.srt` 或 `.txt` 文件单独存在不会改变回答。完整通过的记录成为 `primary`；有直接教学窗口但元数据或适用范围需要收窄的记录成为 `supplemental`。来源、安全、转写质量或重复门禁失败时，系统保留审计状态并保持 `answer_eligibility: none`；只有生成级一致性门禁失败时，才回滚本轮生成产物。

A new transcript does not update model weights or become Codex conversational memory. A raw `.json`, `.srt`, or `.txt` file alone changes no answer. A fully aligned record becomes `primary`; a directly useful teaching window with narrower metadata or scope becomes `supplemental`. When provenance, safety, transcription quality, or duplicate gates fail, the audit state is retained with `answer_eligibility: none`; only generation-level consistency failures roll back the current generated artifact set.

## 当前知识与质量基线 / Current knowledge and quality baseline

以下数字由当前分支的受控数据与评估报告渲染，不代表所有自然语言问题都已得到验证。

These values are rendered from the controlled data and evaluation report on this branch; they do not imply that every natural-language question has been validated.

| 指标 | 当前值 | 说明 |
| --- | ---: | --- |
| 已处理公开视频 | 1248 | 完整来源目录，不等于全部可回答内容 |
| B 站完整来源目录 | 767 | 599 条回答就绪、168 条策略排除或质量隔离、0 条待处理 |
| 可用于回答的教学视频 | 959 | 只有 ready 内容进入证据池 |
| 主证据 / 受限补充证据 | 784 / 175 | 主证据优先；补充证据只使用命中的时间戳窗口 |
| 转写证据 | 766 | 7,754/7,754 条转写证据包含时间戳 |
| 受限时间戳窗口证据 | 174 | 1,816 条已提交窗口；标题不得作为结论证据 |
| 视觉复核兜底 | 19 | 语音不足时使用已审核视觉摘要 |
| 回答质量黄金用例 | 57/57 | 覆盖技术、诊断、战术、训练与证据边界 |
| 查询理解 | 145/145 | 结构化意图回归集 |
| 语言变体稳健性 | 30/30 | 5 类问题的变形测试 |
| 硬负例误选 | 0 | 当前黄金用例包含 194 个显式硬负例 |
| 当前运行时自动生成审计 | 20/20 | renderer 字节级复现，完整上下文逐例审计 |
| 质量套件 / 强制基线指标 | 14 / 74 | 任一强制指标回归都会阻断发布 |
| 公共反馈信号 | 0 | 不虚构真实用户数据 |

| Metric | Current value |
| --- | ---: |
| Processed public videos | 1248 |
| Bilibili full source catalog | 767: 599 answer-ready, 168 policy-excluded or quality-isolated, 0 pending |
| Ready teaching videos | 959 |
| Primary / bounded supplemental evidence | 784 / 175 |
| Transcript-backed evidence | 766 |
| Bounded timestamp-window evidence | 174 |
| Reviewed visual-summary fallbacks | 19 |
| Answer-quality gold cases | 57/57 |
| Query-understanding cases | 145/145 |
| Metamorphic variants | 30/30 |
| Current-runtime generated answer audits | 20/20 |
| Evaluation suites / enforced baseline metrics | 14 / 74 |

All 7,754 transcript evidence items have timestamps.

## 回答质量怎样被门禁 / How answer quality is gated

质量报告不是单一“准确率”。它检查不同层次的失败模式：

The quality report is not one accuracy number. It checks distinct failure modes:

1. **问题理解 / Query understanding** — 角色、动作、条件、否定、承接关系和交付要求不能串线。
2. **证据完整性 / Evidence completeness** — 所有可回答视频先进入语义证据集，再分别计算 synthesis、selected、claim-mapped 与 core recall。
3. **展示选择 / Presentation selection** — 视频按结论用途、来源强度、重复簇和场景范围筛选，不用展示列表反向定义“可回答”。
4. **答案契约 / Answer contract** — 诊断比较、训练剂量、成功标准、战术分支等 delivery item 必须真实出现在答案中。
5. **独立审计 / Independent audit** — renderer 输出要逐字复现；auditor 使用完整上下文检查证据、边界、引用与缺失项。
6. **鲁棒性 / Robustness** — 语言改写、硬负例、B 站正例、机械接线 canary、性能预算和 Python 3.10/3.12 兼容性共同阻断回归。

每条新增硬门禁都有“故意破坏该指标时必须失败”的测试，防止配置存在但不生效。完整结果见 [evaluation report](docs/evaluation/index.html)。

Every promoted hard gate has a regression test proving that deliberately breaking the metric fails the comparison, preventing inert configuration. See the [evaluation report](docs/evaluation/index.html) for current results.

## 代码地图 / Repository map

| 路径 / Path | 职责 / Responsibility |
| --- | --- |
| `skills/liuhui-badminton-coach/` | 可安装 Skill、运行时脚本和只读证据资产 / Installable Skill, runtime scripts, and read-only evidence artifacts |
| `skills/.../scripts/prepare_answer_context.py` | 查询规划、证据分层与上下文构建 / Query planning, evidence layering, and context construction |
| `skills/.../scripts/search_knowledge.py` | chunk-first 检索与受限证据窗口 / Chunk-first retrieval and bounded evidence windows |
| `skills/.../scripts/render_answer.py` | 确定性答案 renderer / Deterministic answer renderer |
| `skills/.../scripts/audit_answer.py` | 完整上下文回答审计 / Full-context answer auditor |
| `data/evaluation/` | 黄金用例、运行时快照、基线与报告 / Gold cases, runtime snapshots, baselines, and reports |
| `scripts/run_ci_tests.py` | fast、compatibility、context 与 artifact 测试分组 / Fast, compatibility, context, and artifact test groups |
| `.github/workflows/validate.yml` | 变更范围分类与并行 CI 质量矩阵 / Change classification and parallel CI quality matrix |
| `ARCHITECTURE.md` | 运行时、维护平面与模块边界 / Runtime, maintenance plane, and module boundaries |

## 本地开发 / Local development

~~~bash
git clone https://github.com/MuyuanGuo/badminton-skills-coach.git
cd badminton-skills-coach
git switch develop
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements-dev.txt
.venv/bin/ruff check scripts skills/liuhui-badminton-coach/scripts
.venv/bin/python scripts/run_ci_tests.py fast --workers 2
.venv/bin/python scripts/run_ci_tests.py compatibility --workers 2
~~~

完整质量报告比 fast 组更慢，适合作为 PR 或发布门禁：

The full quality report is slower than the fast group and is intended for PR or release gating:

~~~bash
.venv/bin/python scripts/collect_evaluation_results.py --workers 2 --output /tmp/core-evaluations.json
.venv/bin/python scripts/generate_evaluation_report.py --check --evaluations /tmp/core-evaluations.json
.venv/bin/python scripts/benchmark_runtime.py
.venv/bin/python scripts/evaluate_answer_packet.py
~~~

维护者恢复未完成的 B 站流水线只使用一个入口：

Maintainers resume an incomplete Bilibili pipeline through one entry point:

~~~bash
python3 scripts/run_bilibili_update_pipeline.py --install
~~~

## 稳定版体验 / Try the stable release

开发分支不作为普通用户的安装来源。需要体验稳定行为时，安装 `v2.1.3`：

The development branch is not the end-user installation source. To try stable behavior, install `v2.1.3`:

~~~bash
base="https://github.com/MuyuanGuo/badminton-skills-coach/releases/download/v2.1.3"
curl --fail --show-error --location --retry 3 "$base/liuhui-badminton-coach-2.1.3.zip" -o "/tmp/liuhui-badminton-coach-2.1.3.zip"
curl --fail --show-error --location --retry 3 "$base/SHA256SUMS.txt" -o /tmp/SHA256SUMS.txt
curl --fail --show-error --location --retry 3 "$base/SBOM.cdx.json" -o /tmp/SBOM.cdx.json
(cd /tmp && shasum -a 256 -c SHA256SUMS.txt)
~~~

## 分支、贡献与发布 / Branches, contribution, and release

- 当前分支：`develop`
- 当前开发版本：`2.1.4-dev.1`
- 发布状态：`unreleased`
- 稳定版：`main` / `v2.1.3`
- Current branch: `develop`
- Current development version: `2.1.4-dev.1`
- Release status: `unreleased`
- Stable release: `main` / `v2.1.3`
- Installable package: [v2.1.3](https://github.com/MuyuanGuo/badminton-skills-coach/releases/tag/v2.1.3)

`main` 是稳定发布来源，`develop` 是集成分支。`main` is the stable release source and `develop` is the integration branch. 发布候选从 `develop` 通过受保护 PR 进入 `main`；通过 exact-SHA 校验、签名标签、SBOM 和证明后才发布。合并后的 `main` 会自动提出回同步 PR，把稳定版本元数据切换回下一开发版本，同时保持两条分支各自的 README 受众。

Release candidates move from `develop` to `main` through protected PRs and are published only after exact-SHA validation, a signed tag, an SBOM, and attestations. Validated `main` then proposes an automated back-merge that advances the next development version while preserving the distinct README audience on each branch.

贡献前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md) 和 [ARCHITECTURE.md](ARCHITECTURE.md)。安全发布与签名说明见 [RELEASE_SECURITY.md](RELEASE_SECURITY.md)。软件与原创文档使用 [MIT License](LICENSE)；第三方来源材料适用 [LICENSE-DATA](LICENSE-DATA) 与 [NOTICE](NOTICE)。

Before contributing, read [CONTRIBUTING.md](CONTRIBUTING.md) and [ARCHITECTURE.md](ARCHITECTURE.md). See [RELEASE_SECURITY.md](RELEASE_SECURITY.md) for signing and release security. Software and original documentation use the [MIT License](LICENSE); third-party source material is governed separately by [LICENSE-DATA](LICENSE-DATA) and [NOTICE](NOTICE).
