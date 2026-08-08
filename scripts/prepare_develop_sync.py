#!/usr/bin/env python3
"""Convert a stable main checkout into the next development branch state."""

import json
import re
from pathlib import Path

from project_artifacts import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
VERSION_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
FEEDBACK_RULES_PATHS = (
    Path("config/feedback_rules.json"),
    Path("skills/liuhui-badminton-coach/references/feedback-rules.json"),
)
ISSUE_TEMPLATE_PATHS = (
    Path(".github/ISSUE_TEMPLATE/bug-report.yml"),
    Path(".github/ISSUE_TEMPLATE/question.yml"),
    Path(".github/ISSUE_TEMPLATE/skill-feedback.yml"),
)


def next_patch_development_version(stable_version):
    match = VERSION_PATTERN.fullmatch(stable_version)
    if not match:
        raise ValueError("Stable version must use MAJOR.MINOR.PATCH")
    major, minor, patch = (int(part) for part in match.groups())
    return f"{major}.{minor}.{patch + 1}-dev.1"


def replace_line(text, predicate, replacement, label):
    lines = text.splitlines()
    matches = [index for index, line in enumerate(lines) if predicate(line)]
    if len(matches) != 1:
        raise ValueError(f"Expected one {label} line, found {len(matches)}")
    lines[matches[0]] = replacement
    return "\n".join(lines) + "\n"


def replace_once(text, old, new, label):
    if text.count(old) != 1:
        raise ValueError(f"Expected one {label} marker, found {text.count(old)}")
    return text.replace(old, new, 1)


def development_readme_zh(text, stable_version, development_version):
    text = replace_line(
        text,
        lambda line: line.startswith("**") and "稳定版**通过 GitHub" in line,
        (
            "你正在查看 `develop` 分支；当前开发版本是 "
            f"**{development_version}**，发布状态为 **unreleased**。"
            "稳定安装仍来自 `main` 与 "
            f"[v{stable_version}](https://github.com/MuyuanGuo/"
            f"badminton-skills-coach/releases/tag/v{stable_version})。"
            "本项目独立开发，不是刘辉本人，也不代表刘辉或视频发布者的观点与背书。"
        ),
        "Chinese release banner",
    )
    text = replace_once(
        text,
        f"## {stable_version} 带来了什么",
        (
            f"## 当前开发版（{development_version}）\n\n"
            f"本分支在稳定版 {stable_version} 基础上汇总尚未发布的数据、运行时与工程改动；"
            "以下内容描述当前开发树，不表示已经存在对应的稳定安装包。"
        ),
        "Chinese release heading",
    )
    marker = "## 分支与发布\n"
    if marker not in text:
        raise ValueError("Chinese branch status section is missing")
    prefix = text.split(marker, 1)[0]
    return prefix + marker + (
        "\n"
        "- 当前分支：`develop`\n"
        f"- 当前开发版本：`{development_version}`\n"
        "- 发布状态：`unreleased`\n"
        f"- 稳定版：`main` / `v{stable_version}`\n"
        f"- 正式安装包：[v{stable_version}](https://github.com/MuyuanGuo/"
        f"badminton-skills-coach/releases/tag/v{stable_version})\n"
        "- `main` 是稳定发布来源；`develop` 是集成分支。"
        "两个分支使用同一套可验证事实和治理标准，但 README 与版本元数据必须反映各自状态。\n"
    )


def development_readme_en(text, stable_version, development_version):
    text = replace_line(
        text,
        lambda line: line.startswith("**Version ") and "stable release**" in line,
        (
            "You are viewing the `develop` branch; the current development version is "
            f"**{development_version}** and its release status is **unreleased**. "
            "Stable installs remain on `main` and "
            f"[v{stable_version}](https://github.com/MuyuanGuo/"
            f"badminton-skills-coach/releases/tag/v{stable_version}). "
            "This independent project is not authored, operated, endorsed, or approved "
            "by Liu Hui or the source publishers."
        ),
        "English release banner",
    )
    text = replace_once(
        text,
        f"## What changed in {stable_version}",
        (
            f"## Current development build ({development_version})\n\n"
            f"This branch collects unreleased data, runtime, and engineering changes on "
            f"top of stable {stable_version}. It describes the development tree, not an "
            "already available stable package."
        ),
        "English release heading",
    )
    marker = "- Stable release: `main` / `v"
    if marker not in text:
        raise ValueError("English branch status section is missing")
    prefix = text.split(marker, 1)[0]
    return prefix + (
        "- Current branch: `develop`\n"
        f"- Current development version: `{development_version}`\n"
        "- Release status: `unreleased`\n"
        f"- Stable release: `main` / `v{stable_version}`\n"
        f"- Installable package: [v{stable_version}](https://github.com/MuyuanGuo/"
        f"badminton-skills-coach/releases/tag/v{stable_version})\n\n"
        "`main` is the stable release source and `develop` is the integration branch. "
        "Both use the same evidence and governance standards, while their README and "
        "version metadata must reflect their distinct states.\n"
    )


def prepare_develop_sync(root=ROOT):
    root = Path(root)
    source_path = root / FEEDBACK_RULES_PATHS[0]
    original_metadata = json.loads(source_path.read_text(encoding="utf-8"))
    stable_version = original_metadata.get("stable_version", "")
    if original_metadata.get("channel") != "stable":
        raise ValueError("Develop sync must start from a stable-channel main checkout")
    if original_metadata.get("skill_version") != stable_version:
        raise ValueError("Stable main metadata must use one identical Skill version")
    development_version = next_patch_development_version(stable_version)

    for relative in FEEDBACK_RULES_PATHS:
        path = root / relative
        current_text = path.read_text(encoding="utf-8")
        current = json.loads(current_text)
        if current != original_metadata:
            raise ValueError(f"Version metadata is out of sync before update: {relative}")
        updated_text = replace_once(
            current_text,
            f'"skill_version": "{stable_version}"',
            f'"skill_version": "{development_version}"',
            f"Skill version in {relative}",
        )
        updated_text = replace_once(
            updated_text,
            '"channel": "stable"',
            '"channel": "development"',
            f"release channel in {relative}",
        )
        atomic_write_text(path, updated_text)

    readme_zh = root / "README.md"
    atomic_write_text(
        readme_zh,
        development_readme_zh(
            readme_zh.read_text(encoding="utf-8"),
            stable_version,
            development_version,
        ),
    )
    readme_en = root / "README.en.md"
    atomic_write_text(
        readme_en,
        development_readme_en(
            readme_en.read_text(encoding="utf-8"),
            stable_version,
            development_version,
        ),
    )

    for relative in ISSUE_TEMPLATE_PATHS:
        path = root / relative
        text = path.read_text(encoding="utf-8")
        if stable_version not in text:
            raise ValueError(f"Issue template version is stale before update: {relative}")
        atomic_write_text(path, text.replace(stable_version, development_version))

    return {
        "channel": "development",
        "skill_version": development_version,
        "stable_version": stable_version,
    }


def main():
    try:
        result = prepare_develop_sync()
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
