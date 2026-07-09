# Badminton Skills Coach

[![Validate knowledge pipeline](https://github.com/MuyuanGuo/badminton-skills-coach/actions/workflows/validate.yml/badge.svg)](https://github.com/MuyuanGuo/badminton-skills-coach/actions/workflows/validate.yml)

Badminton Skills Coach is a private-study knowledge project that turns public
badminton teaching videos from Douyin creator `刘辉羽毛球` into an
evidence-backed Codex Skill.

The goal is not to imitate the creator or claim endorsement. The goal is to
make a structured, searchable coaching reference that answers technique
questions with source videos, timestamps, and clear confidence boundaries.

## Current Status

As of the latest checked-in knowledge base:

- Indexed 470 public Douyin video links from `刘辉羽毛球`
- Classified 405 candidate teaching videos
- Processed 218 videos into the full Douyin knowledge base
- Marked 186 full-knowledge videos as ready for evidence-backed retrieval
- Marked 32 full-knowledge videos as requiring visual review because speech
  evidence is sparse
- Created and validated the `liuhui-badminton-coach` Codex Skill from the
  curated 25-video pilot set
- Added an automated batch runner for downloading, transcribing, validating,
  committing, and pushing processed batches

Raw video/audio files, full transcripts, temporary CDN URLs, model caches, and
local environments are intentionally excluded from Git.

## How This Skill Was Built

The project started as a small pilot: collect representative videos, classify
them by badminton topic, transcribe the teaching audio, extract timestamped
evidence, and package the result as a Codex Skill.

The workflow then expanded into a repeatable pipeline:

1. Collect Douyin video metadata for `刘辉羽毛球`.
2. Remove advertisements and non-teaching content.
3. Classify teaching candidates into badminton topics such as rear-court
   technique, footwork, shot quality, power generation, doubles tactics, and
   correction drills.
4. Extract media URLs from authenticated browser sessions.
5. Download media locally into ignored raw-data folders.
6. Transcribe Chinese speech with `faster-whisper`.
7. Convert transcripts into timestamped teaching evidence.
8. Build a structured JSON knowledge base.
9. Evaluate retrieval quality with deterministic test prompts.
10. Package the knowledge base and retrieval helper as a reusable Codex Skill.

The full Douyin knowledge base combines curated pilot notes with automatically
extracted evidence. Automatically extracted entries are useful for retrieval,
but answers should still respect the confidence field and avoid overclaiming
when a video needs visual review.

The checked-in Codex Skill currently bundles the curated 25-video pilot
knowledge base. The larger Douyin knowledge base is maintained in
`data/knowledge/douyin_knowledge_base.json` and can be promoted into the skill
when you are ready to distribute the expanded version.

## What The Skill Does

The skill lives in:

```text
skills/liuhui-badminton-coach/
```

When installed into Codex, it can help answer questions like:

```text
$liuhui-badminton-coach 我被动后场总是来不及架拍，应该怎么调整？
```

The skill is designed to:

- Retrieve relevant teaching entries from the bundled pilot knowledge base
- Cite source Douyin video URLs and timestamp ranges
- Separate diagnosis, principle, correction cues, and drills
- Prefer curated or transcript-backed evidence
- Avoid pretending to be 刘辉 or implying official endorsement
- Ask for user video/context when evidence is insufficient

## Technology Stack

Core language and tooling:

- Python 3 for pipeline scripts, JSON processing, validation, and retrieval
- Node.js for Douyin catalog classification helpers
- Git and GitHub Actions for versioning and validation
- Codex Skills for packaging the coaching workflow

Media and transcription:

- `faster-whisper` for local Chinese ASR transcription
- Local browser-assisted extraction for authenticated Douyin media playback URLs
- Local-only raw media and transcript storage

Knowledge and evaluation:

- JSON knowledge base under `data/knowledge/`
- Deterministic keyword retrieval via `search_knowledge.py`
- Validation via `scripts/validate_project.py`
- Retrieval evaluation via `scripts/evaluate_liuhui_skill.py`

Visual planning:

- Draw.io output for the original pilot knowledge map

## Repository Layout

```text
data/
  douyin_video_index.*             Public video index exports
  douyin_teaching_filtered.json    Filtered teaching candidates
  processing/douyin_queue.json     Batch-processing queue and statuses
  knowledge/
    douyin_knowledge_base.json     Current structured Douyin knowledge base
    pilot_teaching_notes.json      Curated pilot notes

scripts/
  classify_douyin_catalog.mjs      Topic classification helper
  check_douyin_updates.py          Detect newly observed homepage videos
  douyin_profile_snapshot_dom.js   Browser-page snapshot collector
  init_douyin_queue.py             Queue initialization
  monitor_douyin_updates.py        Update-monitor orchestration
  process_douyin_ready_batch.py    Automated batch processor
  batch_transcribe_directory.py    Directory transcription runner
  build_douyin_knowledge.py        Knowledge-base builder
  validate_project.py              Repository validation
  evaluate_liuhui_skill.py         Retrieval evaluation

skills/
  liuhui-badminton-coach/
    SKILL.md                       Skill instructions
    references/knowledge-base.json Skill-bundled pilot reference data
    scripts/search_knowledge.py    Local retrieval helper

output/
  liuhui-pilot-knowledge-map.drawio
  liuhui-skill-retrieval-evaluation.json
```

Ignored local-only folders:

```text
data/raw_videos/
data/transcripts/
data/tmp/
.venv/
```

## Setup For Local Development

Clone the repository:

```bash
git clone https://github.com/MuyuanGuo/badminton-skills-coach.git
cd badminton-skills-coach
```

Create a Python virtual environment:

```bash
python3 -m venv .venv
.venv/bin/pip install faster-whisper
```

Run validation:

```bash
python3 scripts/validate_project.py
python3 scripts/evaluate_liuhui_skill.py
```

Try retrieval directly:

```bash
python3 skills/liuhui-badminton-coach/scripts/search_knowledge.py \
  "被动后场来不及架拍怎么办"
```

## Install The Skill In Codex

Copy the skill directory into your personal Codex skills directory:

```bash
mkdir -p ~/.codex/skills
cp -R skills/liuhui-badminton-coach ~/.codex/skills/liuhui-badminton-coach
```

Then invoke it in Codex:

```text
$liuhui-badminton-coach 如何改正杀球发力分散的问题？
```

The skill reads its bundled pilot knowledge base and uses
`scripts/search_knowledge.py` to retrieve supporting entries.

## Continue Processing More Douyin Videos

### Detect New Homepage Videos

Use `scripts/check_douyin_updates.py` as the safe entrypoint for update
monitoring. It compares a newly observed Douyin profile snapshot with the local
index, classifies any new videos, and writes a report. By default it does not
modify the repository.

The browser-side snapshot collector is:

```text
scripts/douyin_profile_snapshot_dom.js
```

Run it inside an authenticated browser page that is already open on the
`刘辉羽毛球` Douyin profile. It defines:

```javascript
await window.__collectDouyinProfileSnapshot({ scrollRounds: 8 })
```

Save the returned JSON to:

```text
data/tmp/douyin_profile_latest.json
```

The input should be a JSON file with either a top-level `videos` list, `items`
list, or a raw list. Each item should include at least a video ID or URL, plus
title text when available:

```json
{
  "videos": [
    {
      "video_id": "1234567890",
      "url": "https://www.douyin.com/video/1234567890",
      "title": "后场被动架拍调整 #羽毛球教学 #刘辉羽毛球",
      "raw_text": "后场被动架拍调整 #羽毛球教学 #刘辉羽毛球"
    }
  ]
}
```

Run a dry check:

```bash
python3 scripts/check_douyin_updates.py \
  --input data/tmp/douyin_profile_latest.json
```

The script writes `output/douyin-update-report.json` with counts and classified
new candidates:

- `teaching`: new videos that look like teaching content
- `review`: new videos that mix teaching signals with promotion signals
- `excluded`: new videos that look like ads, equipment-only posts, or non-teaching content

After reviewing the report, apply safe teaching additions to the local index and
processing queue:

```bash
python3 scripts/check_douyin_updates.py \
  --input data/tmp/douyin_profile_latest.json \
  --apply
```

This updates:

- `data/douyin_video_index.json`
- `data/douyin_teaching_filtered.json`
- `data/processing/douyin_queue.json`

It does not download, transcribe, or update the skill by itself. That separation
keeps monitoring safe: finding new videos and processing media remain two
auditable steps.

### Run The Monitor

`scripts/monitor_douyin_updates.py` wraps the update check and optional
repository actions:

```bash
python3 scripts/monitor_douyin_updates.py \
  --snapshot data/tmp/douyin_profile_latest.json \
  --validate
```

To apply new teaching candidates, validate, commit, and push:

```bash
python3 scripts/monitor_douyin_updates.py \
  --snapshot data/tmp/douyin_profile_latest.json \
  --apply \
  --validate \
  --commit \
  --push
```

The monitor writes ignored runtime files:

```text
output/douyin-update-report.json
output/douyin-monitor-state.json
```

If you have a separate command that refreshes the snapshot, pass it with
`--snapshot-command`:

```bash
python3 scripts/monitor_douyin_updates.py \
  --snapshot data/tmp/douyin_profile_latest.json \
  --snapshot-command ./your_snapshot_exporter.sh \
  --apply \
  --validate
```

This makes the monitoring layer independent from the browser mechanism. The
current Codex workflow can provide the snapshot from an already-authenticated
in-app browser; a future local setup can replace it with Playwright, Chrome
remote debugging, or another authenticated exporter.

### Process Queued Videos

The queue file is:

```text
data/processing/douyin_queue.json
```

Typical statuses are:

- `pending`: candidate video is waiting for media extraction
- `media_ready`: media URL and local target path have been prepared
- `transcribed`: transcript exists and knowledge base can include it
- `extraction_failed`: browser/media extraction failed
- `transcription_failed`: transcription failed

After media URLs have been extracted into `data/tmp/<batch>/`, process a batch
with:

```bash
python3 scripts/process_douyin_ready_batch.py batch-018
```

The batch runner will:

1. Check available disk space.
2. Download each media file with its generated curl config.
3. Transcribe all media files in the batch.
4. Update the processing queue.
5. Rebuild `data/knowledge/douyin_knowledge_base.json`.
6. Delete raw media from the batch folder.
7. Run validation and retrieval evaluation.
8. Commit and push the changed structured artifacts.

The runner deliberately does not store raw media or transcripts in Git.

### Suggested Monitoring Loop

For a semi-automatic monitor, run these steps on a schedule:

1. Export the latest visible `刘辉羽毛球` homepage items to
   `data/tmp/douyin_profile_latest.json` using the browser snapshot collector.
2. Run `scripts/monitor_douyin_updates.py` without `--apply`.
3. Review `output/douyin-update-report.json`.
4. Rerun the monitor with `--apply` if the new teaching candidates look correct.
5. Use the existing batch media extraction and
   `scripts/process_douyin_ready_batch.py` pipeline to process the new queue
   items.

The update check is intentionally outside the skill runtime. The skill stays
fast and deterministic, while Douyin monitoring can handle browser login,
platform changes, and occasional manual review.

## Promote The Full Knowledge Base Into The Skill

By default, the checked-in skill references the curated 25-video pilot set, and
`scripts/validate_project.py` enforces that pilot sync.

If you want a local expanded skill that uses the full Douyin knowledge base,
copy the generated full knowledge base into the skill reference file:

```bash
cp data/knowledge/douyin_knowledge_base.json \
  skills/liuhui-badminton-coach/references/knowledge-base.json
```

Then update `scripts/validate_project.py` to validate against
`data/knowledge/douyin_knowledge_base.json` instead of
`data/knowledge/pilot_knowledge_base.json`, and run:

```bash
python3 scripts/validate_project.py
python3 scripts/evaluate_liuhui_skill.py
```

## GitHub Actions

The repository includes a validation workflow:

```text
.github/workflows/validate.yml
```

On push, it compiles Python sources, validates repository artifacts, and runs
retrieval evaluation. The status badge at the top of this README reflects the
latest workflow result.

## Data And Copyright Boundaries

This repository is for personal study and private knowledge management.

Please respect platform terms, copyright, course licenses, and instructor
rights. Do not redistribute downloaded videos, paid course material, private
live-stream clips, or full transcripts without permission.

The checked-in artifacts are intentionally limited to metadata, structured
notes, references, and skill code. Source video links remain attributed to
Douyin pages, and answers generated from the skill should cite the original
video URL and timestamp whenever possible.

## Limitations

- Automatic speech recognition may mishear badminton terminology.
- Some videos rely heavily on visual demonstration and are marked
  `needs_visual_review`.
- Retrieval is deterministic keyword matching, not semantic vector search.
- The skill is a study aid, not a replacement for a qualified coach.
- The skill must not impersonate 刘辉 or suggest official endorsement.

## Quick Commands

```bash
python3 scripts/validate_project.py
python3 scripts/evaluate_liuhui_skill.py
python3 skills/liuhui-badminton-coach/scripts/search_knowledge.py "后场被动怎么架拍"
```
