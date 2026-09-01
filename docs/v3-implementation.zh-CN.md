# v3 证据重构实施手册

- 状态：M1、M2 已实现；M3 全局来源路由与六类首轮审核队列已实现
- 日期：2026-08-31
- 权威规格：[`spec-v3.zh-CN.md`](spec-v3.zh-CN.md)
- 决策记录：[`adr/0001-v3-evidence-boundary.md`](adr/0001-v3-evidence-boundary.md)

## 1. 当前交付边界

这批代码建立了与稳定 v2 隔离的 shadow 路径：

```text
私有候选 + 本地原视频
→ append-only 审核账本
→ 当前状态与依赖投影
→ 净化 publication
→ 只读 shadow SQLite
→ claim-scoped answer packet
```

当前 v2 Skill、v2 runtime、发行清单和回答路径均未改变。仓库中的
`data/v3/publication.json` 已包含首条经完整人工门禁批准的最小投影；
`data/v3/build-manifest.json` 仍明确记录 `switch_eligible: false`。

## 2. M1 已实现内容

- 规范 JSON、内容哈希、稳定内容 ID 和原子写入；
- SQLite append-only review events、可重建 current heads 和可恢复草稿；
- 正式转写、教学事件与语义主张的显式状态机；
- 自动审核者阻断、显式人类确认、乐观并发和防跳级；
- 正式转写逐段处理与完整媒体播放两个独立门禁；
- 内容/时间/媒体变化后的递归 stale 传播；
- publication 最小投影、私有字段扫描、引用完整性和内容指纹；
- 只读 shadow runtime、逻辑 runtime fingerprint 和空证据缺口回答；
- 959 条可回答来源的净化输入快照不伪造正式状态；首条已批准主张只通过
  publication 投影进入 shadow runtime。

输入清单当前事实：

| 项目 | 数量 |
| --- | ---: |
| 可回答来源 | 959 |
| 抖音 / B 站 | 360 / 599 |
| 本地候选转写文件 | 747 |
| 仅有嵌入式旧候选转写 | 148 |
| 候选转写缺失 | 64 |
| 可定位但尚未哈希的本地候选媒体 | 415 |
| 已进入 v3 publication 的来源 | 1 |

这些数字描述 2026-08-31 本机私有输入快照的可用性，不代表审核通过率或回答质量。
公开 CI 校验其内容指纹、统计一致性和 959 条公共来源身份覆盖；只有持有私有输入的维护机
才能用 `--check-local-inputs` 逐文件重建并比较可用性状态。

## 3. M2 真实纵切

首条纵切使用公开视频 `7589749293205363633`。选择它是因为本地同时存在原视频和
28 段旧 ASR，且内容包含明显的术语/同音词风险，适合验证完整校正工作流。旧教学笔记、
旧 evidence atom 和候选纠错都不会继承任何 v3 批准状态。

准备私有会话：

```bash
.venv/bin/python scripts/seed_v3_vertical_slice.py
```

该命令会：

1. 计算本地原视频和旧转写的内容哈希；
2. 在 `.local/v3/candidates/` 生成 immutable candidate；
3. 在私有账本追加 `raw_available → candidate`；
4. 明确返回 `formal_approvals_created: 0`。

它不会开始人工审核、接受机器纠错、确认正式转写或生成公开主张。
未经审核的纠错提示同样属于私有输入：如需预载提示，应按
`schemas/v3/private-suggestions.schema.json` 写入
`.local/v3/inputs/suggestions/<video_id>.json`。每条提示通过片段序号和原文 SHA-256
绑定，公开脚本不包含任何真实转写原文或建议文本；未提供该文件时，所有片段默认保留
原始候选并等待人工逐段判断。

## 4. 启动本地审核台

```bash
.venv/bin/python scripts/run_v3_review.py
```

使用终端输出的完整本地地址。审核台只监听 loopback，使用随机会话令牌、同源检查和
CSRF 令牌，不加载远程脚本、字体、分析或遥测。视频按需从本地流式读取，并校验候选中
绑定的 SHA-256；路径不会返回给浏览器 API。

视觉或多模态 teaching event 必须额外记录画面审核依据和实际核对的时间点。本地媒体
只有音轨时，审核台会禁止选择 `local_media` 作为视觉依据；可以显式打开 canonical
来源页面，并以 `source_page` 连同来源 URL 和时间点写入私有审核账本。该记录不会公开
本地路径，自动系统也不能据此代替人工执行来源确认。

审核顺序固定为：

1. 填写稳定审核者身份并开始人工审核；
2. 对每个 ASR 片段选择保留、接受建议、人工改写或删除误识别；
3. 补录完整播放时发现的漏句，并调整时间边界；
4. 从头到尾自然播放原视频，完成四项独立完整性确认；
5. 确认正式转写；
6. 建立并核对 teaching event；新事件默认全选整条正式转写，仅在同一视频拆分多个事件时缩小窗口；
7. 写出条件、机制、纠正方向与排除项，依次执行来源确认、领域批准和发布批准；
8. 预览净化 publication，确认不存在完整转写或审核身份。

草稿可以更新，正式操作只能追加。审核台不会批量批准意义敏感修改、正式转写、事件或
主张。

## 5. 确定性构建与审计

导出当前已批准的最小 publication，并构建 shadow runtime：

```bash
.venv/bin/python scripts/v3_tool.py export-publication
.venv/bin/python scripts/v3_tool.py build-shadow
.venv/bin/python scripts/v3_tool.py audit-shadow \
  --runtime .local/v3/build/shadow-runtime.sqlite3
.venv/bin/python scripts/v3_tool.py audit-public-tree
.venv/bin/python scripts/build_v3_source_inventory.py --check
.venv/bin/python scripts/v3_tool.py query-shadow \
  '正手后场被动球时，为什么球拍追着球走，来不及架拍和发力？'
```

真实主张经用户审核前，不得把私有账本直接写进 `data/v3/publication.json`。
`export-publication` 只投影当前 `published` 主张，并继续经过 publication 净化器、
隐私扫描和原子写入；不得复制账本 payload。

## 6. 验证

核心测试覆盖：

- 自动审核者、状态跳级、篡改和陈旧浏览器提交失败；
- 全片播放与逐段处理相互独立；
- 来源变化使 event 和 published claim 递归失效；
- publication/runtime 同输入同指纹；
- 公开投影无私有路径、raw ASR、完整转写或审核身份；
- 审核台 token、Origin、CSRF、Range 媒体和草稿恢复；
- 959 条来源逐条存在且没有伪造 v3 正式状态。

```bash
.venv/bin/python scripts/test_v3_evidence_core.py
.venv/bin/python scripts/test_v3_publication_runtime.py
.venv/bin/python scripts/test_v3_review_workbench.py
.venv/bin/python scripts/test_v3_source_inventory.py
node --check review-ui/v3/app.js
```

自动测试使用的 `fixture-reviewer` 和合成主张只存在于临时目录，不进入仓库
publication。真实纵切的转写、教学事件、来源支持、领域判断和 publication 已分别由
产品所有者完成显式确认；这些确认只绑定该来源的当前媒体、正式投影与修订指纹。

## 7. M3 全局来源路由与六类队列

先生成 Git 忽略的私有审核队列：

```bash
.venv/bin/python scripts/v3_tool.py build-pilot-queue
```

输出位于 `.local/v3/review/pilot-review-queue.json`。构建器会先处理全部 959 条可回答
来源，再形成任何单主题队列：

- 显式镜像先合并为一个 source group，canonical 与 alternate URLs 均保留；
- 每条来源都落到 `already_published`、`queued`、`candidate_not_selected` 或
  `out_of_pilot`；
- 六类各选 20 条本地媒体与候选转写均可用的首轮来源；
- 历史 development 问题覆盖、可审核性、来源资格和候选教学信号参与排序；
- 平台没有权重或配额，当前平台分布只是上述规则的结果；
- 标题、分类、标签和机器路由仍是 `candidate_routing_only`，主题分配必须由人确认，
  更不能直接进入回答证据。

跨主题来源由全局稀缺度分配器一次性分派，配置中的主题先后顺序不会改变分配结果。
标题和旧分类冲突时，标题与分类一致的来源优先；冲突来源仍保留在候选池，等待来源队列
人工确认。

从队列装载某条候选时，使用主题与队列序号：

```bash
.venv/bin/python scripts/seed_v3_vertical_slice.py \
  --topic backhand_rearcourt --rank 2
```

脚本会从知识索引解析抖音或 B 站身份、候选转写和本地媒体，生成独立候选会话，并更新
默认活动会话。它仍只追加 `raw_available → candidate`，不会创建转写确认、教学事件、
领域批准或 publication。每个候选的可恢复会话保存在
`.local/v3/review/sessions/`。

M3 新增回归：

```bash
.venv/bin/python scripts/test_v3_source_routing.py
```

该回归覆盖 959/959 来源、镜像只计一次、跨主题唯一分配、主题声明顺序无关、平台中立、
候选元数据不获证据权限、发高远球与后场高远的消歧，以及同输入同 fingerprint。
