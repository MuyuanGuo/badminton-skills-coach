<!-- README_PROFILE: main -->
# Badminton Skills Coach

[![Validate Skill artifacts](https://github.com/MuyuanGuo/badminton-skills-coach/actions/workflows/validate.yml/badge.svg)](https://github.com/MuyuanGuo/badminton-skills-coach/actions/workflows/validate.yml)
[![Latest release](https://img.shields.io/github/v/release/MuyuanGuo/badminton-skills-coach)](https://github.com/MuyuanGuo/badminton-skills-coach/releases/latest)
[![License: MIT](https://img.shields.io/badge/code%20license-MIT-2f766d.svg)](LICENSE)
[![Data & sources: separate terms](https://img.shields.io/badge/data%20%26%20sources-separate%20terms-6b5b95.svg)](LICENSE-DATA)

![Badminton Skills Coach：证据驱动的羽毛球视频知识库](.github/assets/social-preview.jpg)

把你的羽毛球问题说清楚一点，它会帮你拆解动作、步法、战术或训练问题，并给出有时间戳的视频证据和下一步练习。

Describe your badminton situation in plain language. The Skill helps you separate technique, footwork, tactics, and training issues, then points you to timestamped video evidence and practical next steps.

**2.1.4 稳定版**来自 `main` 和 [v2.1.4 Release](https://github.com/MuyuanGuo/badminton-skills-coach/releases/tag/v2.1.4)。本项目独立开发，不是刘辉本人，也不代表刘辉或任何视频发布者的认可或背书。

**Version 2.1.4 is the stable release** from `main` and [v2.1.4](https://github.com/MuyuanGuo/badminton-skills-coach/releases/tag/v2.1.4). This independent project is not authored, operated, endorsed, or approved by Liu Hui or any source publisher.

## 30 秒安装 / Install in 30 seconds

需要 Python 3.10 或更高版本；不需要 OpenAI API key，也不需要安装转写工具。

Requires Python 3.10 or newer. No OpenAI API key or transcription tooling is needed.

### macOS / Linux

~~~bash
base="https://github.com/MuyuanGuo/badminton-skills-coach/releases/download/v2.1.4"
curl --fail --show-error --location --retry 3 "$base/liuhui-badminton-coach-2.1.4.zip" -o "/tmp/liuhui-badminton-coach-2.1.4.zip"
curl --fail --show-error --location --retry 3 "$base/SHA256SUMS.txt" -o /tmp/SHA256SUMS.txt
curl --fail --show-error --location --retry 3 "$base/SBOM.cdx.json" -o /tmp/SBOM.cdx.json
(cd /tmp && shasum -a 256 -c SHA256SUMS.txt)
stage="$(mktemp -d)"
unzip -q "/tmp/liuhui-badminton-coach-2.1.4.zip" -d "$stage"
python3 "$stage/liuhui-badminton-coach/scripts/install.py"
python3 ~/.codex/skills/liuhui-badminton-coach/scripts/doctor.py
~~~

### Windows PowerShell

~~~powershell
$base = "https://github.com/MuyuanGuo/badminton-skills-coach/releases/download/v2.1.4"
Invoke-WebRequest "$base/liuhui-badminton-coach-2.1.4.zip" -OutFile "$env:TEMP/liuhui-badminton-coach-2.1.4.zip"
Invoke-WebRequest "$base/SHA256SUMS.txt" -OutFile "$env:TEMP/SHA256SUMS.txt"
Invoke-WebRequest "$base/SBOM.cdx.json" -OutFile "$env:TEMP/SBOM.cdx.json"
$expected = ((Select-String "liuhui-badminton-coach-2.1.4.zip" "$env:TEMP/SHA256SUMS.txt").Line -split '\s+')[0]
$actual = (Get-FileHash "$env:TEMP/liuhui-badminton-coach-2.1.4.zip" -Algorithm SHA256).Hash.ToLower()
if ($actual -ne $expected) { throw "SHA-256 mismatch" }
$stage = Join-Path $env:TEMP "liuhui-skill-install"; Expand-Archive "$env:TEMP/liuhui-badminton-coach-2.1.4.zip" $stage -Force
python "$stage/liuhui-badminton-coach/scripts/install.py"
python "$HOME/.codex/skills/liuhui-badminton-coach/scripts/doctor.py"
~~~

安装完成后重启 Codex。升级时重复以上步骤即可，安装器会先验证文件再原子替换旧版本。

Restart Codex after installation. To upgrade, repeat the same steps; the installer verifies the package before replacing the previous version.

## 直接这样问 / Ask like this

~~~text
$liuhui-badminton-coach 我是业余中级双打选手。
对手杀到反手身体附近时，我挡网经常冒高。
请帮我区分拍面、击球点和到位问题，并给一个有陪练、每次 20 分钟的训练方案。
~~~

~~~text
$liuhui-badminton-coach I am an intermediate recreational doubles player.
When a smash reaches my backhand hip, my block often sits up.
Help me separate racket-face, contact-point, and positioning problems, then give me a 20-minute partner drill.
~~~

问题里最好包含：你的水平、单打或双打、来球与场区、正反手、主动或被动、实际症状，以及你能独练还是有陪练。

Useful details include your level, singles or doubles, incoming shot and court area, forehand or backhand, active or defensive state, the symptom you see, and whether you train alone or with a partner.

## 它能帮你什么 / What it can help with

- **动作与步法 / Technique and footwork:** 握拍、击球点、发力顺序、网前、后场和移动衔接。 / Grip, contact point, kinetic sequence, net play, rear-court strokes, and movement transitions.
- **诊断 / Diagnosis:** 把“总下网”“总冒高”“回不到位”等症状拆成可以依次检查的假设。 / Turn symptoms such as repeated net errors, floating replies, or short clears into an ordered checklist of hypotheses.
- **战术 / Tactics:** 区分单打、双打、前后场角色和前三拍条件，不把不同场景混成一条建议。 / Keep singles, doubles, front–back roles, and first-three-shot conditions separate.
- **训练 / Practice:** 根据独练、陪练、教练和可用时间组织步骤、剂量与成功标准。 / Build drills, dosage, and success criteria around solo, partner, or coached practice.
- **视频证据 / Video evidence:** 给出稳定的 V1…Vn 标签、原始链接、可用时间戳和每条视频在答案中的用途。 / Provide stable V1…Vn labels, canonical links, usable timestamps, and the role each video plays in the answer.

## 为什么回答不是“搜到什么就贴什么” / Why answers are not a list of search hits

标题和关键词只负责找到候选视频，不能单独证明技术结论。视频必须通过来源、转写、证据质量、适用范围和去重门禁，才可能进入回答。

Titles and keywords only retrieve candidates; they do not prove a coaching claim. A video must pass provenance, transcription, evidence-quality, scope, and duplicate gates before it can appear in an answer.

一个简单问题通常只需要少量视频。复杂问题可以展示更多，但每个结论最多使用 1–3 条最强证据；不同子问题不会为了遵守一个虚构的“整篇三条”限制而被丢掉。

A simple question usually needs only a few videos. A multi-part question may show more, while each claim still uses at most one to three strong sources. Independent subproblems are not discarded to satisfy an artificial three-video limit for the whole answer.

没有你的连续动作视频时，Skill 会给出证据支持的排查顺序，但不会声称已经确认唯一原因。它不会做医学诊断、保证效果、冒充刘辉，或宣称得到来源发布者认可。

Without footage of your movement, the Skill can provide an evidence-backed diagnostic order, but it will not pretend to have confirmed one unique cause. It does not provide medical diagnosis, guarantee outcomes, impersonate Liu Hui, or claim source-publisher endorsement.

## 反馈、隐私与帮助 / Feedback, privacy, and help

回答末尾会给出适用于本次 V 标签的反馈格式。确认前，反馈只保存在你的机器上；公开反馈还需要脱敏、明确授权、来源复核和回归测试。

Each answer ends with a feedback format tied to that answer's V labels. Feedback stays on your machine until you confirm it. Public feedback additionally requires redaction, explicit permission, source re-verification, and regression tests.

- [提交回答反馈 / Submit answer feedback](https://github.com/MuyuanGuo/badminton-skills-coach/issues/new?template=skill-feedback.yml)
- [报告问题 / Report a bug](https://github.com/MuyuanGuo/badminton-skills-coach/issues/new?template=bug-report.yml)
- [项目网站 / Project website](https://muyuanguo.github.io/badminton-skills-coach/)

仓库不会发布原始媒体、临时 Cookie、平台凭据、模型缓存或用户本地反馈。软件与原创文档使用 [MIT License](LICENSE)；第三方视频、音频、标题、创作者名称、缩略图和转写不属于该授权，详见 [数据与来源材料声明 / Data and source-material terms](LICENSE-DATA) 与 [NOTICE](NOTICE)。

The repository does not publish raw media, temporary cookies, platform credentials, model caches, or local user feedback. Software and original documentation use the [MIT License](LICENSE). Third-party video, audio, titles, creator names, thumbnails, and transcripts are outside that grant; see [Data and source-material terms](LICENSE-DATA) and [NOTICE](NOTICE).

## 分支状态 / Branch status

- `main` 是稳定发布来源；当前稳定版为 `v2.1.4`。
- `main` is the stable release source; the current stable version is `v2.1.4`.
- 开发与工程说明位于 [`develop`](https://github.com/MuyuanGuo/badminton-skills-coach/tree/develop)；贡献规范见 [CONTRIBUTING.md](CONTRIBUTING.md)。
- Engineering and development documentation lives on [`develop`](https://github.com/MuyuanGuo/badminton-skills-coach/tree/develop); see [CONTRIBUTING.md](CONTRIBUTING.md) to contribute.
