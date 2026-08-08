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
python3 scripts/run_ci_tests.py fast
python3 scripts/run_ci_tests.py context --shard-index 0 --shard-count 1
python3 scripts/run_ci_tests.py artifacts
python3 scripts/collect_evaluation_results.py --output /tmp/bsc-evaluations.json
python3 scripts/generate_evaluation_report.py --check --evaluations /tmp/bsc-evaluations.json
python3 scripts/benchmark_runtime.py
python3 scripts/validate_project.py
```

Install maintenance dependencies only from hash-locked files:

```bash
.venv/bin/pip install --require-hashes -r requirements-transcription.txt
.venv/bin/pip install --require-hashes -r requirements-dev.txt
```

Answer-quality changes additionally require an unseen forward test and, when
comparing `main` with `develop`, the blinded paired evaluation documented in
the Chinese guide. Do not copy holdout answers into runtime rules or priors.

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
