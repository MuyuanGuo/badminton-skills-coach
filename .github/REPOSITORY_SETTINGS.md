# Repository settings contract

The following GitHub-hosted controls are part of the architecture but cannot be
enforced from repository files alone:

- About description: `Evidence-backed badminton coaching Skill for Codex with timestamped public-video sources.`
- Website: `https://muyuanguo.github.io/badminton-skills-coach/`
- Topics: `badminton`, `codex-skill`, `evidence-retrieval`, `knowledge-base`, `chinese`.
- Default branch: `main`; do not advertise `develop` as the source of stable facts.
- Protect `main` and `develop`: require pull requests, the `validate` check,
  conversation resolution, no force-push, and no deletion.
- Require the `branch-policy` check on `main`. Normal feature, data,
  documentation, and CI pull requests target `develop`; only `release/*` and
  emergency `hotfix/*` branches (including the equivalent `codex/` prefixes)
  may target `main`, and they must originate in this repository.
- Keep the `Propose main to develop sync` workflow enabled with permission to
  create pull requests. Every successful validation of a `main` push must create
  or update the `automation/sync-main-to-develop` PR and approve the native
  approval-required `pull_request` validation for that exact synchronization
  head. Build that head from current `develop`, merge the validated `main` SHA,
  and only then refresh development metadata so strict branch protection never
  requires a second update-and-validate cycle. Do not dispatch a second
  validation for the same head. Because `develop` requires a validated PR with
  admin enforcement, its merge push must not rerun the full matrix; `main` keeps
  exact-SHA push validation for releases.
- Protect release tags matching `v*`: only maintainers may create them; tags must
  be cryptographically signed. Keep GitHub's registered signing key aligned with
  the public key in `.github/release-signers`; never commit the private key.
- Protect the `release` environment: required reviewer, deployment limited to
  protected tags, and no self-review.
- Keep artifact attestations enabled and immutable releases enforced by the
  release workflow.

Apply `.github/labels.yml` with the repository's label-sync mechanism. Review
these settings before every stable release and record exceptions in the release
notes.
