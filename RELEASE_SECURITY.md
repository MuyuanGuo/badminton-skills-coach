# Release integrity and provenance

Formal Badminton Skills Coach releases publish a deterministic Skill archive together with three complementary integrity signals:

- `SHA256SUMS.txt` contains the SHA-256 digest of the installable ZIP and its CycloneDX SBOM.
- `SBOM.cdx.json` lists every file inside the archive with a SHA-256 digest, records the source repository, version, archive digest, and source commit, and enumerates the fully pinned optional transcription environment as optional PyPI components.
- GitHub Actions creates a signed artifact attestation that binds the archive and SBOM to the repository, workflow, commit, and tag that produced them.

These signals establish origin and detect tampering. They do not claim that the software is free of defects or that third-party teaching content is covered by the repository's MIT license. The exact boundary is defined in [LICENSE-DATA](LICENSE-DATA).

## Verify downloaded files

Download all assets from the same Release, then run:

```bash
shasum -a 256 -c SHA256SUMS.txt
```

To verify the GitHub build attestation and its signed CycloneDX predicate:

```bash
gh attestation verify liuhui-badminton-coach-<version>.zip \
  --repo MuyuanGuo/badminton-skills-coach \
  --predicate-type https://cyclonedx.org/bom
```

To inspect the verified predicate as JSON, add `--format json`:

```bash
gh attestation verify liuhui-badminton-coach-<version>.zip \
  --repo MuyuanGuo/badminton-skills-coach \
  --predicate-type https://cyclonedx.org/bom \
  --format json
```

Replace `<version>` with the version being downloaded. Older releases created before this workflow may provide checksums without a GitHub attestation.

## Reproducible package construction

`scripts/package_skill_release.py` uses an explicit fail-closed file allowlist, includes
`LICENSE`, `LICENSE-DATA`, and `NOTICE`, sorts files, normalizes archive timestamps and permissions,
and validates the completed ZIP. Unexpected or missing Skill files stop packaging.
`scripts/generate_release_sbom.py` hashes the exact files in that ZIP rather than
describing the working tree indirectly.

The release workflow runs the deterministic project validation gate and then requires
fresh reproducible answers for every critical answer case. The committed snapshot
records both the complete Skill runtime fingerprint and the answer-semantic runtime
fingerprint, pins the trusted renderer and full-context auditor by path and SHA-256,
and stores a digest for every answer. At release time the workflow reconstructs every
answer from the current runtime, requires byte-for-byte renderer reproduction, and
reruns the final-answer audit against the complete context. Only then does the
workflow package the Skill, generate the SBOM, sign the archive/SBOM relationship
with GitHub Artifact Attestations, and upload the assets to the matching tag.

## GitHub-hosted enforcement

The release tag must be cryptographically signed; the workflow verifies it with
`git verify-tag`. The release job targets the protected `release` environment and
refuses to overwrite an existing release. Branch protection, protected tag rules,
environment reviewers, repository About text, topics, and label synchronization
must be configured in GitHub according to [.github/REPOSITORY_SETTINGS.md](.github/REPOSITORY_SETTINGS.md).

The transcription and development environments are installed with
`pip --require-hashes`. Faster-whisper model repositories and immutable revisions
are recorded in `config/transcription_models.json`; new transcripts record the
repository and revision in recipe schema 2. Historical schema-1 recipes are not
silently upgraded.
