# 运行时架构 / Runtime Architecture

## 边界 / Boundaries

可安装 Skill 是一个可直接复制的目录，而不是 Python 包。运行时数据由只读、
`immutable=1` 的 SQLite 存储按需读取；大型 JSON 只保留为维护输入，不进入发布清单。
检索先命中确定性前缀索引，再读取候选记录；转录字段位于独立表，只为最终候选按视频
懒加载并裁成回答证据窗口，避免主记录重复封装转录或把整个语料载入内存。

The installable Skill is a directly copyable directory, not a Python package.
Runtime data is fetched lazily from a read-only SQLite store opened with
`immutable=1`; large JSON files remain maintenance inputs and are excluded from
the release inventory. Retrieval hits the deterministic prefix index first.
Transcript fields live in a separate table and are hydrated only for finalist
videos before being reduced to bounded answer windows, so primary records do
not duplicate transcripts and the corpus is never materialized as a whole.

## 模块加载 / Module loading

叶子模块使用普通静态导入。只有 `search_knowledge.py` 和
`prepare_answer_context.py` 两个可独立执行的编排入口按文件路径加载相邻模块。
这是有意保留的可移植隔离边界：仓库目录名含连字符，Skill 安装后也不要求修改
`PYTHONPATH` 或安装包；编排器缓存每个模块实例，避免在单次请求内重复加载。业务规则、
排序和约束逻辑不得新增动态加载；新逻辑应放入静态导入的叶子模块并接受单元测试。

Leaf modules use ordinary static imports. Only the two standalone orchestrators,
`search_knowledge.py` and `prepare_answer_context.py`, load adjacent modules by
file path. This is the intentional portable isolation boundary: the repository
directory contains a hyphen, and an installed Skill must run without package
installation or `PYTHONPATH` changes. Each orchestrator caches module instances
within a request. New business rules, ranking, or constraint logic must live in
statically imported leaf modules with unit tests.

## 回答与评测 / Answers and evaluation

检索审计上下文是权威状态；紧凑 answer packet 以规范 JSON 摘要绑定它。封闭渲染器只
接受 packet 中的 claim、evidence atom 和窗口 ID，最终审计检查完整性、引用映射、
置信上限和逐字反馈提示。运行时先验不得包含评测用例 ID；召回金标、诊断金标和变形
稳定性测试相互独立，已判定受污染的历史指标不会参与基线门禁。

The retrieval audit context is authoritative, and the compact answer packet is
bound to it by a canonical JSON digest. The closed renderer accepts only packet
claim, evidence-atom, and window IDs; final audit checks completeness, citation
mapping, confidence ceilings, and the exact feedback prompt. Runtime priors may
not contain evaluation case IDs. Retrieval gold, diagnostic gold, and
metamorphic stability remain separate, and invalidated historical metrics do
not gate releases.

## 更新与发布 / Updates and release

维护流水线在跨平台文件锁内运行，以临时文件和原子替换提交生成物；失败时恢复原状态。
批处理默认不提交、不推送。发布清单是显式白名单，并由散列、可复现 manifest、SBOM、
签名标签和 CI 超时门禁约束。GitHub 端的分支保护、环境审批、About 与 topics 以
`.github/REPOSITORY_SETTINGS.md` 为可审计配置契约。

The maintenance pipeline runs under a cross-platform file lock and commits
artifacts through temporary files plus atomic replacement, restoring the prior
state on failure. Batch commands do not commit or push by default. The release
inventory is an explicit allowlist guarded by hashes, a reproducible manifest,
an SBOM, signed tags, and CI timeouts. Repository-side branch protection,
environment approvals, About metadata, and topics are specified by the
auditable `.github/REPOSITORY_SETTINGS.md` contract.
