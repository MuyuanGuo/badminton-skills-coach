# v3 证据重构实施手册

- 状态：M1 已实现；M2 首条真实纵切已进入 shadow 评测
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
| v3 正式转写 | 0 |

这些数字描述 2026-08-31 本机私有输入快照的可用性，不代表审核通过率或回答质量。
公开 CI 校验其内容指纹、统计一致性和 959 条公共来源身份覆盖；只有持有私有输入的维护机
才能用 `--check-local-inputs` 逐文件重建并比较可用性状态。

## 3. M2 真实纵切候选

默认纵切使用公开视频 `7589749293205363633`。选择它是因为本地同时存在原视频和
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

审核顺序固定为：

1. 填写稳定审核者身份并开始人工审核；
2. 对每个 ASR 片段选择保留、接受建议、人工改写或删除误识别；
3. 补录完整播放时发现的漏句，并调整时间边界；
4. 从头到尾自然播放原视频，完成四项独立完整性确认；
5. 确认正式转写；
6. 从正式转写窗口建立并核对 teaching event；
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

真实纵切只有在产品所有者完成原视频核对后才能越过 M2 的领域质量门；自动测试使用的
`fixture-reviewer` 和合成主张只存在于临时目录，不进入仓库 publication。
