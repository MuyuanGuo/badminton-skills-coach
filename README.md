# Badminton Skills Coach

[![Validate knowledge pipeline](https://github.com/MuyuanGuo/badminton-skills-coach/actions/workflows/validate.yml/badge.svg)](https://github.com/MuyuanGuo/badminton-skills-coach/actions/workflows/validate.yml)

Build an evidence-backed badminton coaching knowledge base from authorized
teaching videos, then expose it through a reusable Codex Skill.

## Current Scope

- Indexed 470 public Douyin video links from `刘辉羽毛球`
- Classified 405 teaching candidates
- Selected and processed a representative 25-video pilot
- Generated timestamped transcripts locally with `faster-whisper`
- Built a structured pilot knowledge base and Draw.io mind map
- Created and validated the `liuhui-badminton-coach` Codex Skill

## Repository Layout

```text
data/knowledge/       Structured teaching knowledge
data/*.csv|json       Video indexes and pilot manifests
output/               Draw.io maps and evaluation results
scripts/              Collection, transcription, classification, and QA tools
skills/               Reusable Codex Skill
```

Raw videos, audio, transcripts, temporary CDN URLs, local model environments,
and generated spreadsheets are intentionally excluded from Git.

## Quick Checks

```bash
python3 scripts/evaluate_liuhui_skill.py
python3 skills/liuhui-badminton-coach/scripts/search_knowledge.py \
  "被动后场来不及架拍怎么办"
```

## Skill

Install `skills/liuhui-badminton-coach` into your personal Codex skills
directory, then invoke:

```text
$liuhui-badminton-coach 我在被动后场总是来不及架拍，应该怎么调整？
```

The Skill provides evidence-backed coaching rather than impersonating or
claiming endorsement by the original instructor.

## Content Notice

This project is intended for personal study and private knowledge management.
Respect platform terms, copyright, course licenses, and instructor rights.
