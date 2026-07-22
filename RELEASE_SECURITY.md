# Release integrity and provenance

Formal Badminton Skills Coach releases publish a deterministic Skill archive together with three complementary integrity signals:

- `SHA256SUMS.txt` contains the SHA-256 digest of the installable ZIP and its CycloneDX SBOM.
- `SBOM.cdx.json` lists every file inside the archive with a SHA-256 digest and records the source repository, version, archive digest, and source commit.
- GitHub Actions creates a signed artifact attestation that binds the archive and SBOM to the repository, workflow, commit, and tag that produced them.

These signals establish origin and detect tampering. They do not claim that the software is free of defects or that third-party teaching content is covered by the repository's MIT license.

## Verify downloaded files

Download all assets from the same Release, then run:

```bash
shasum -a 256 -c SHA256SUMS.txt
```

To verify the GitHub build attestation and its signed CycloneDX predicate:

```bash
gh attestation verify liuhui-badminton-coach-v1.3.0.zip \
  --repo MuyuanGuo/badminton-skills-coach \
  --predicate-type https://cyclonedx.org/bom
```

To inspect the verified predicate as JSON, add `--format json`:

```bash
gh attestation verify liuhui-badminton-coach-v1.3.0.zip \
  --repo MuyuanGuo/badminton-skills-coach \
  --predicate-type https://cyclonedx.org/bom \
  --format json
```

Replace `v1.3.0` with the version being downloaded. Older releases created before this workflow may provide checksums without a GitHub attestation.

## Reproducible package construction

`scripts/package_skill_release.py` sorts files, normalizes archive timestamps and permissions, excludes local caches, and validates the completed ZIP. `scripts/generate_release_sbom.py` hashes the exact files in that ZIP rather than describing the working tree indirectly.

The release workflow runs the project validation gate before packaging, generates the SBOM, signs the archive/SBOM relationship with GitHub Artifact Attestations, and uploads the resulting assets to the matching tag.
