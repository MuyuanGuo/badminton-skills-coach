# Badminton Skills Coach

[![Validate Skill artifacts](https://github.com/MuyuanGuo/badminton-skills-coach/actions/workflows/validate.yml/badge.svg)](https://github.com/MuyuanGuo/badminton-skills-coach/actions/workflows/validate.yml)
[![Latest release](https://img.shields.io/github/v/release/MuyuanGuo/badminton-skills-coach)](https://github.com/MuyuanGuo/badminton-skills-coach/releases/latest)
[![License: MIT](https://img.shields.io/badge/code%20license-MIT-2f766d.svg)](LICENSE)
[![数据与来源条款](https://img.shields.io/badge/data%20%26%20sources-separate%20terms-6b5b95.svg)](LICENSE-DATA)

![Badminton Skills Coach：证据驱动的羽毛球视频知识库](.github/assets/social-preview.jpg)

面向 Codex 的证据型羽毛球教练 Skill。你描述真实的技术、步法、战术、器材或训练问题，它会从已处理的抖音和 B 站教学资料中给出诊断、训练建议、值得观看的视频、时间戳和证据边界。

[安装 2.1.1](#安装稳定版) · [怎样提问](#怎样提问效果最好) · [项目网站](https://muyuanguo.github.io/badminton-skills-coach/) · [提交回答反馈](https://github.com/MuyuanGuo/badminton-skills-coach/issues/new?template=skill-feedback.yml) · [English](README.en.md)

**2.1.1 稳定版**通过 GitHub `main` 分支和 [v2.1.1 Release](https://github.com/MuyuanGuo/badminton-skills-coach/releases/tag/v2.1.1) 提供；后续开发继续在 `develop`。本项目独立开发，不是刘辉本人，也不代表刘辉或视频发布者的观点与背书。

## 30 秒开始使用

安装并重启 Codex 后，直接说出你的场景：

~~~text
$liuhui-badminton-coach 我是业余中级双打选手。
对手杀到反手身体附近时，我挡网经常冒高。
请帮我区分拍面、击球点和到位问题，并给一个有陪练、每次 20 分钟的训练方案。
~~~

Skill 会先恢复谁在做什么、来球与目标动作是什么，再区分“来源明确说了什么”和“还需要看你的动作视频才能确认什么”。回答中的视频会带稳定 V 标签、evidence_id、规范链接和可用时间戳。

## 2.1.1 带来了什么

- 同时使用抖音与 B 站知识库，覆盖技术动作、全场步法、单双打战术、网前小技术、发接发、装备与训练。
- 只让通过来源、转写、证据质量和去重门禁的视频进入回答；标题和关键词只负责召回，不能单独证明技术结论。
- 783 条主证据优先回答，175 条受限补充证据只在命中实际时间戳窗口时补足概念、条件、训练或器材信息。
- 多问题回答不再被误解为“整篇最多 3 个视频”：每个结论最多 3 条最强证据，独立子问题或实质场景分支可以展示更多；简单问题不会为了凑数增加重复视频。
- 本地反馈默认只保存在用户机器，确认前不会影响个性化；公开反馈还需要脱敏、明确授权、来源复核和回归测试。
- 回答模型只读取紧凑 answer packet，完整上下文用于最终审计，两者由 SHA-256 绑定。
- 运行时审核先验与 `data/evaluation/answer_quality_cases.json` 分离；评测脚本默认以无先验模式报告检索质量，避免用评测金标准反哺指标。
- 51.7 MiB 只读 SQLite 证据存储按需读取映射、序列和 chunk，避免在冷启动时同时常驻多份完整 JSON 投影；Linux 冷启动 RSS 受 128 MiB 硬预算约束。
- Python 3.10/3.12 使用同一套哈希锁定维护依赖，生成物、SQLite 逻辑内容和 canary 哈希跨环境保持可复现。
- 发布答案改由受信任 renderer 为关键案例确定性重建，绑定完整/回答语义双运行时指纹，并在 tag 工作流中逐例复现和重跑完整上下文审计。

## 当前知识与质量基线

| 指标 | 当前值 | 说明 |
| --- | ---: | --- |
| 已处理公开视频 | 1247 | 完整来源目录，不等于全部可回答内容 |
| B 站完整来源目录 | 767 | 599 条回答就绪、168 条策略排除或质量隔离、0 条待处理 |
| 可用于回答的教学视频 | 958 | 只有 ready 内容进入证据池 |
| 主证据 / 受限补充证据 | 783 / 175 | 主证据优先；补充证据只使用命中的时间戳窗口 |
| 转写证据 | 765 | 7,744/7,744 条转写证据包含时间戳 |
| 受限时间戳窗口证据 | 174 | 1,816 条已提交窗口；标题不得作为结论证据 |
| 视觉复核兜底 | 19 | 语音不足时使用已审核视觉摘要 |
| 回答质量黄金用例 | 57/57 | 覆盖文字、边界、视频和禁用结论 |
| 查询理解 | 143/143 | 结构化意图回归集 |
| 语言变体稳健性 | 30/30 | 5 类问题、15 个基础案例 |
| 硬负例误选 | 0 | 当前回归集共 194 个硬负例 |
| 当前运行时自动生成审计 | 3/3 | renderer 字节级复现，完整上下文逐例通过 |
| 公共反馈信号 | 0 | 反馈闭环已就绪，但不虚构真实用户数据 |

这些数字描述当前受控语料和评测集，不表示所有自然语言问题都已经验证。具体回答仍以当轮证据和置信边界为准。

## 安装稳定版

日常使用需要 Python 3.10 或更高版本，不需要 OpenAI API key，也不需要安装转写依赖。

~~~bash
curl --fail --show-error --location --retry 3 https://github.com/MuyuanGuo/badminton-skills-coach/releases/download/v2.1.1/liuhui-badminton-coach-2.1.1.zip \
  -o /tmp/liuhui-badminton-coach-2.1.1.zip
curl --fail --show-error --location --retry 3 https://github.com/MuyuanGuo/badminton-skills-coach/releases/download/v2.1.1/SHA256SUMS.txt \
  -o /tmp/SHA256SUMS.txt
curl --fail --show-error --location --retry 3 https://github.com/MuyuanGuo/badminton-skills-coach/releases/download/v2.1.1/SBOM.cdx.json \
  -o /tmp/SBOM.cdx.json
(cd /tmp && shasum -a 256 -c SHA256SUMS.txt)
install_dir="$(mktemp -d)"
unzip -q /tmp/liuhui-badminton-coach-2.1.1.zip -d "$install_dir"
python3 "$install_dir/liuhui-badminton-coach/scripts/install.py"
~~~

安装后检查：

~~~bash
python3 ~/.codex/skills/liuhui-badminton-coach/scripts/doctor.py
~~~

然后重启 Codex。升级时可以重复安装命令；安装器会验证文件，并以新版本替换 Skill。

Windows PowerShell 使用同一发布物和 SHA-256：

~~~powershell
$v = "2.1.1"; $base = "https://github.com/MuyuanGuo/badminton-skills-coach/releases/download/v$v"
Invoke-WebRequest "$base/liuhui-badminton-coach-$v.zip" -OutFile "$env:TEMP/liuhui-badminton-coach-$v.zip"
Invoke-WebRequest "$base/SHA256SUMS.txt" -OutFile "$env:TEMP/SHA256SUMS.txt"
$expected = ((Select-String "liuhui-badminton-coach-$v.zip" "$env:TEMP/SHA256SUMS.txt").Line -split '\s+')[0]
$actual = (Get-FileHash "$env:TEMP/liuhui-badminton-coach-$v.zip" -Algorithm SHA256).Hash.ToLower()
if ($actual -ne $expected) { throw "SHA-256 mismatch" }
$stage = Join-Path $env:TEMP "liuhui-skill-install"; Expand-Archive "$env:TEMP/liuhui-badminton-coach-$v.zip" $stage -Force
python "$stage/liuhui-badminton-coach/scripts/install.py"
~~~

## 怎样提问效果最好

推荐提供：

- 你的水平，以及单打还是双打。
- 来球、场区、正反手、主动或被动状态。
- 你当前怎样处理，实际出现了什么症状。
- 想改善的动作、战术或结果。
- 是否能独练、有陪练或教练、每次可用多久。

例如：

~~~text
我单打反手后场被动，来不及正常架拍，回球总不到底线。
请区分判断慢、到位晚和发力问题，并给我能独练的步骤。
~~~

~~~text
双打接发时我习惯正手握拍，反手区容易顶不住。
请说明握拍转换、站位和前三拍选择，并给对应视频。
~~~

没有你的连续动作视频时，Skill 可以给证据支持的排查顺序，但不会声称已经确认唯一原因。它不用于医学诊断、效果保证、泛化购物推荐，也不会冒充刘辉或宣称得到其认可。

## 视频为什么有时超过 3 条

“1–3 条”是单个结论的证据上限，不是整篇回答的总上限。一个简单问题通常只需要少量视频；复杂问题如果包含不同动作、单双打分支、技术与步法两个独立子问题，或需要主证据与受限补充证据承担不同作用，就可能展示更多。

回答只展示最终 answer packet 中的视频，每条恰好一次，并按用途连续编号为 V1…Vn。内容簇去重、逐结论证据门和整篇 16 条候选硬上限会阻止重复或失控扩张。

## 反馈与隐私

回答末尾会给出适用于当前标签的反馈格式，例如：

~~~text
V2 最有价值；V4 不相关；第 2 点结论不对；
回答漏了“被动情况下如何处理”；
你理解错了，我真正问的是“单打杀上网”。
~~~

明确反馈会先进入本地待确认队列。只有在你确认解析无误后，它才会影响本地个性化。记录器保留回答当时的精确标签映射；旧回答即使使用 V2、V3、V5 这样的稀疏标签，也不会被偷偷重编号或错绑到其他视频。

若愿意公开分享，请使用 [Skill feedback Issue 模板](https://github.com/MuyuanGuo/badminton-skills-coach/issues/new?template=skill-feedback.yml)。只有经过脱敏、授权、来源复核和回归测试的信号才可能进入公开 Skill；用户反馈不会直接变成羽毛球技术事实。

## 来源与边界

仓库不发布原始媒体、原始转写目录、临时 Cookie、平台凭据、模型缓存或用户本地反馈。安装包只含运行所需的派生索引和可定位证据数据。软件与原创文档使用 [MIT License](LICENSE)；第三方视频、音频、标题、创作者名称、缩略图和转写不属于该授权，详见 [数据与来源材料声明](LICENSE-DATA) 和 [NOTICE](NOTICE)。

维护批处理默认只下载、转写和验证，不会自动 commit 或 push；需要发布时显式使用 `--commit --push`，且只允许提交生成物白名单。

### 新数据怎样进入回答

~~~mermaid
flowchart LR
    B["来源准入与媒体校验"] --> C["可解码媒体"]
    C --> D["确定性ASR"]
    D --> P["转写配方、ASR质量、来源安全与重复硬门禁"]
    P --> E["结构化知识库（含隔离审计记录）"]
    E --> A["回答资格分层：primary / supplemental / none"]
    A --> S["只读 SQLite 运行时证据存储"]
    S --> F["45秒 chunk-first + 受限窗口检索"]
    F --> R["回答 packet 与最终审计"]
~~~

新增转写不会写入模型权重或成为 Codex 的会话记忆。原始 `.json`、`.srt` 或 `.txt` 文件单独存在不会改变回答。完整通过的记录成为 `primary`；有直接教学窗口但元数据或适用范围需要收窄的记录成为 `supplemental`。来源、安全、转写质量或重复门禁失败时，系统保留审计状态并保持 `answer_eligibility: none`；只有生成级一致性门禁失败时，才回滚本轮生成产物。

维护者恢复未完成的 B 站流水线只使用一个入口：

~~~bash
python3 scripts/run_bilibili_update_pipeline.py --install
~~~

运行时边界与模块加载约束见 [ARCHITECTURE.md](ARCHITECTURE.md)。维护和贡献说明见 [CONTRIBUTING.md](CONTRIBUTING.md)（[English](CONTRIBUTING.en.md)），发布校验、签名标签和 SBOM 说明见 [RELEASE_SECURITY.md](RELEASE_SECURITY.md)。所有分支的说明都必须与该分支实际代码一致，不把未发布设计写成现有能力。

## 分支与发布

- 稳定版：`main` / `v2.1.1`
- 正式安装包：[v2.1.1](https://github.com/MuyuanGuo/badminton-skills-coach/releases/tag/v2.1.1)
- `main` 是稳定发布来源；`develop` 是集成分支。两个分支使用同一套可验证事实和治理标准，但 README 与版本元数据必须反映各自状态。
