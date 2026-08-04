# Repository settings contract

The following GitHub-hosted controls are part of the architecture but cannot be
enforced from repository files alone:

- About description: `Evidence-backed badminton coaching Skill for Codex with timestamped public-video sources.`
- Website: `https://muyuanguo.github.io/badminton-skills-coach/`
- Topics: `badminton`, `codex-skill`, `evidence-retrieval`, `knowledge-base`, `chinese`.
- Default branch: `main`; do not advertise `develop` as the source of stable facts.
- Protect `main` and `develop`: require pull requests, the `validate` check,
  conversation resolution, no force-push, and no deletion.
- Protect release tags matching `v*`: only maintainers may create them; tags must
  be cryptographically signed.
- Protect the `release` environment: required reviewer, deployment limited to
  protected tags, and no self-review.
- Keep artifact attestations enabled and immutable releases enforced by the
  release workflow.

Apply `.github/labels.yml` with the repository's label-sync mechanism. Review
these settings before every stable release and record exceptions in the release
notes.
