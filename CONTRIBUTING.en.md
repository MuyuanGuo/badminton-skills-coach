# Contributing

[中文](CONTRIBUTING.md)

Badminton Skills Coach accepts changes that are verifiable, narrowly scoped,
and respectful of privacy and third-party rights.

## Before opening a pull request

1. Open an issue first for a large behavior or data change.
2. Branch from `develop`. Feature, data, documentation, and CI pull requests all
   target `develop`. Only `release/*` release branches and emergency `hotfix/*`
   branches may target `main`, always through a pull request. Every successfully
   validated `main` update automatically opens a back-merge pull request to
   `develop`; do not leave that synchronization outstanding.
3. Never commit original media, raw transcript directories, temporary URLs,
   cookies, credentials, private conversations, or local feedback queues.
4. Preserve canonical public source links and never claim endorsement by Liu
   Hui or a source publisher.

## Validation

Run the smallest affected deterministic gates first, then the complete gate for
shared runtime or generated-artifact changes:

```bash
python3 scripts/run_ci_tests.py fast --workers 2
python3 scripts/run_ci_tests.py compatibility --workers 2
python3 scripts/run_ci_tests.py context --shard-index 0 --shard-count 1
python3 scripts/run_ci_tests.py artifacts
python3 scripts/collect_evaluation_results.py \
  --workers 2 \
  --output /tmp/bsc-evaluations.json \
  --timings-output /tmp/bsc-evaluation-timings.json
python3 scripts/generate_evaluation_report.py --check --evaluations /tmp/bsc-evaluations.json
python3 scripts/benchmark_runtime.py
python3 scripts/validate_project.py
```

Every trigger runs the complete fast group on Python 3.12 and the
architecture-critical compatibility subset on Python 3.10. This avoids
repeating the complete fast group on both versions after a pull request is
merged. Core evaluations use two isolated subprocesses and print per-suite
temporary timings without adding wall-clock data to the deterministic report.
Artifact validation runs only for packaged inputs and artifact-test changes.

The full matrix runs once on the pull request for normal changes and automated
back-merges. The synchronization workflow approves the native `pull_request`
run created by `github-actions[bot]` instead of dispatching a second run for the
same SHA. It builds the synchronization head from current `develop` and merges
the validated `main` SHA before refreshing metadata, so strict branch protection
does not require another update. Protected `develop` requires that `validate`
result, so its merge push does not repeat the matrix. `main` keeps push
validation because releases bind to the exact merged SHA.

When the repository is stored in iCloud Drive, enable Keep Downloaded for the
whole checkout. Move the working copy to a non-synced developer directory if
`dataless` conflict copies or Git lock copies recur.

Install maintenance dependencies only from hash-locked files:

```bash
.venv/bin/pip install --require-hashes -r requirements-transcription.txt
.venv/bin/pip install --require-hashes -r requirements-dev.txt
```

Answer-quality changes additionally require an unseen forward test and, when
comparing `main` with `develop`, the blinded paired evaluation documented in
the Chinese guide. Do not copy holdout answers into runtime rules or priors.

After branching from a fully validated `develop`, first synchronize stable metadata,
the bilingual READMEs, website install links, Issue templates, and the versioned quality
baseline:

```bash
python3 scripts/prepare_stable_release.py
```

Before tagging a release, regenerate and validate the critical release answers:

```bash
python3 scripts/generate_release_answer_results.py
python3 scripts/validate_live_generation_results.py
```

The snapshot binds the complete and answer-semantic runtime fingerprints, pins
the trusted renderer and full-context auditor by SHA-256, and must reproduce
every answer byte for byte while passing the current final-answer audit.

## Pull request description

Explain the motivation, affected runtime/data paths, tests actually run, and
whether the change touches third-party material or privacy-sensitive data.
