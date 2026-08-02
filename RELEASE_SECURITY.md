# Release integrity and provenance

Formal Badminton Skills Coach releases publish a deterministic Skill archive together with three complementary integrity signals:

- `SHA256SUMS.txt` contains the SHA-256 digest of the installable ZIP and its CycloneDX SBOM.
- `SBOM.cdx.json` lists every file inside the archive with a SHA-256 digest, records the source repository, version, archive digest, and source commit, and enumerates the fully pinned optional transcription environment as optional PyPI components.
- GitHub Actions creates a signed artifact attestation that binds the archive and SBOM to the repository, workflow, commit, and tag that produced them.

These signals establish origin and detect tampering. They do not claim that the software is free of defects or that third-party teaching content is covered by the repository's MIT license.

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
`LICENSE` and `NOTICE`, sorts files, normalizes archive timestamps and permissions,
and validates the completed ZIP. Unexpected or missing Skill files stop packaging.
`scripts/generate_release_sbom.py` hashes the exact files in that ZIP rather than
describing the working tree indirectly.

The release workflow runs the deterministic project validation gate and then requires
fresh model-generated answers for every critical answer case. Those answers must be
bound to the current Skill runtime, pass the final-answer audit, and carry passing
scores from a reviewer independent of the generator. Only then does the workflow
package the Skill, generate the SBOM, sign the archive/SBOM relationship with GitHub
Artifact Attestations, and upload the assets to the matching tag.
