#!/usr/bin/env python3
"""Convert a validated development checkout into a stable release candidate."""

import copy
import json
import re
from pathlib import Path

from prepare_develop_sync import (
    FEEDBACK_RULES_PATHS,
    ISSUE_TEMPLATE_PATHS,
    replace_line,
    replace_once,
)
from project_artifacts import atomic_write_text
from readme_profiles import write_readme_profile


ROOT = Path(__file__).resolve().parents[1]
DEVELOPMENT_VERSION_PATTERN = re.compile(r"^(\d+\.\d+\.\d+)-dev\.\d+$")
DOCS_PATHS = (Path("docs/index.html"), Path("docs/en/index.html"))
BASELINES_PATH = Path("data/evaluation/evaluation_baselines.json")
REPORT_PATH = Path("data/evaluation/evaluation_report.json")


def release_version_from_development(development_version):
    match = DEVELOPMENT_VERSION_PATTERN.fullmatch(development_version)
    if not match:
        raise ValueError("Development version must use MAJOR.MINOR.PATCH-dev.N")
    return match.group(1)


def replace_all(text, old, new, label):
    count = text.count(old)
    if count < 1:
        raise ValueError(f"Expected at least one {label} marker")
    return text.replace(old, new)


def stable_readme_zh(text, previous_stable, development_version, release_version):
    text = replace_line(
        text,
        lambda line: line.startswith("你正在查看 `develop` 分支"),
        (
            f"**{release_version} 稳定版**通过 GitHub `main` 分支和 "
            f"[v{release_version} Release](https://github.com/MuyuanGuo/"
            f"badminton-skills-coach/releases/tag/v{release_version}) 提供；"
            "后续开发继续在 `develop`。本项目独立开发，不是刘辉本人，也不代表刘辉或"
            "视频发布者的观点与背书。"
        ),
        "Chinese development banner",
    )
    text = replace_once(
        text,
        (
            f"## 当前开发版（{development_version}）\n\n"
            f"本分支在稳定版 {previous_stable} 基础上汇总尚未发布的数据、运行时与工程改动；"
            "以下内容描述当前开发树，不表示已经存在对应的稳定安装包。"
        ),
        f"## {release_version} 带来了什么",
        "Chinese development release heading",
    )
    marker = "## 分支与发布\n"
    if marker not in text:
        raise ValueError("Chinese branch status section is missing")
    prefix = text.split(marker, 1)[0]
    text = prefix + marker + (
        "\n"
        f"- 稳定版：`main` / `v{release_version}`\n"
        f"- 正式安装包：[v{release_version}](https://github.com/MuyuanGuo/"
        f"badminton-skills-coach/releases/tag/v{release_version})\n"
        "- `main` 是稳定发布来源；`develop` 是集成分支。"
        "两个分支使用同一套可验证事实和治理标准，但 README 与版本元数据必须反映各自状态。\n"
    )
    return replace_all(
        text,
        previous_stable,
        release_version,
        "Chinese stable install version",
    )


def stable_readme_en(text, previous_stable, development_version, release_version):
    text = replace_line(
        text,
        lambda line: line.startswith("You are viewing the `develop` branch"),
        (
            f"**Version {release_version} is the stable release** on `main` and "
            f"[v{release_version}](https://github.com/MuyuanGuo/"
            f"badminton-skills-coach/releases/tag/v{release_version}); ongoing work "
            "continues on `develop`. This independent project is not authored, operated, "
            "endorsed, or approved by Liu Hui or the source publishers."
        ),
        "English development banner",
    )
    text = replace_once(
        text,
        (
            f"## Current development build ({development_version})\n\n"
            "This branch collects unreleased data, runtime, and engineering changes on "
            f"top of stable {previous_stable}. It describes the development tree, not an "
            "already available stable package."
        ),
        f"## What changed in {release_version}",
        "English development release heading",
    )
    marker = "- Current branch: `develop`\n"
    if marker not in text:
        raise ValueError("English branch status section is missing")
    prefix = text.split(marker, 1)[0]
    text = prefix + (
        f"- Stable release: `main` / `v{release_version}`\n"
        f"- Installable package: [v{release_version}](https://github.com/MuyuanGuo/"
        f"badminton-skills-coach/releases/tag/v{release_version})\n\n"
        "`main` is the stable release source and `develop` is the integration branch. "
        "Both use the same evidence and governance standards, while their README and "
        "version metadata must reflect their distinct states.\n"
    )
    return replace_all(
        text,
        previous_stable,
        release_version,
        "English stable install version",
    )


def promote_quality_baseline(root, previous_stable, development_version, release_version):
    baseline_path = root / BASELINES_PATH
    report_path = root / REPORT_PATH
    baselines = json.loads(baseline_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    previous_key = f"v{previous_stable}"
    release_key = f"v{release_version}"
    if release_key in baselines["baselines"]:
        raise ValueError(f"Quality baseline already exists: {release_key}")
    if report.get("development_version") != development_version:
        raise ValueError("Evaluation report does not match the development version")
    if report.get("baseline_version") != previous_key:
        raise ValueError("Evaluation report does not use the previous stable baseline")
    if report.get("summary", {}).get("status") != "pass":
        raise ValueError("Only a passing evaluation report may become a release baseline")

    comparisons = {
        item["metric"]: item for item in report.get("baseline_comparison", [])
    }
    promoted = copy.deepcopy(baselines["baselines"][previous_key])
    promoted["description"] = f"Stable release {release_key} quality floor"
    for metric, contract in promoted["metrics"].items():
        comparison = comparisons.get(metric)
        if comparison is None:
            raise ValueError(f"Evaluation report is missing baseline metric: {metric}")
        if "value" in contract:
            contract["value"] = comparison["current"]
    baselines["baselines"][release_key] = promoted
    atomic_write_text(
        baseline_path,
        json.dumps(baselines, ensure_ascii=False, indent=2) + "\n",
    )


def prepare_stable_release(root=ROOT):
    root = Path(root)
    source_path = root / FEEDBACK_RULES_PATHS[0]
    original_metadata = json.loads(source_path.read_text(encoding="utf-8"))
    development_version = original_metadata.get("skill_version", "")
    previous_stable = original_metadata.get("stable_version", "")
    release_version = release_version_from_development(development_version)
    if original_metadata.get("channel") != "development":
        raise ValueError("Stable release preparation must start from develop metadata")
    if not re.fullmatch(r"\d+\.\d+\.\d+", previous_stable):
        raise ValueError("Previous stable version must use MAJOR.MINOR.PATCH")
    if tuple(map(int, release_version.split("."))) <= tuple(
        map(int, previous_stable.split("."))
    ):
        raise ValueError("Release version must be newer than the previous stable version")

    promote_quality_baseline(
        root,
        previous_stable,
        development_version,
        release_version,
    )

    for relative in FEEDBACK_RULES_PATHS:
        path = root / relative
        current_text = path.read_text(encoding="utf-8")
        current = json.loads(current_text)
        if current != original_metadata:
            raise ValueError(f"Version metadata is out of sync before update: {relative}")
        updated_text = replace_once(
            current_text,
            f'"skill_version": "{development_version}"',
            f'"skill_version": "{release_version}"',
            f"Skill version in {relative}",
        )
        updated_text = replace_once(
            updated_text,
            '"channel": "development"',
            '"channel": "stable"',
            f"release channel in {relative}",
        )
        updated_text = replace_once(
            updated_text,
            f'"stable_version": "{previous_stable}"',
            f'"stable_version": "{release_version}"',
            f"stable version in {relative}",
        )
        atomic_write_text(path, updated_text)

    write_readme_profile(
        "main",
        root=root,
        stable_version=release_version,
        development_version=release_version,
    )
    readme_en = root / "README.en.md"
    atomic_write_text(
        readme_en,
        stable_readme_en(
            readme_en.read_text(encoding="utf-8"),
            previous_stable,
            development_version,
            release_version,
        ),
    )

    for relative in DOCS_PATHS:
        path = root / relative
        text = path.read_text(encoding="utf-8")
        atomic_write_text(
            path,
            replace_all(
                text,
                previous_stable,
                release_version,
                f"website install version in {relative}",
            ),
        )

    for relative in ISSUE_TEMPLATE_PATHS:
        path = root / relative
        text = path.read_text(encoding="utf-8")
        atomic_write_text(
            path,
            replace_all(
                text,
                development_version,
                release_version,
                f"Issue template version in {relative}",
            ),
        )

    return {
        "channel": "stable",
        "skill_version": release_version,
        "stable_version": release_version,
        "previous_stable_version": previous_stable,
    }


def main():
    try:
        result = prepare_stable_release()
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
