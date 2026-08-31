# ADR 0001: v3 evidence authority and atomic cutover

- Status: accepted
- Date: 2026-08-31
- Decision owner: product owner
- Specification: `docs/spec-v3.zh-CN.md`

## Context

The stable v2 Skill has useful deterministic retrieval and answer controls, but
its legacy ASR, evidence atoms, and quality cases cannot prove that every answer
claim was checked against the complete original video. The v3 refactor needs a
stronger evidence chain without silently changing the currently released Skill.

## Decision

1. A formal transcript requires an explicit decision for every ASR segment and
   a separate attestation that the complete corresponding media was played and
   checked for missing speech, false positives, and timing errors.
2. Full formal transcripts stay in the Git-ignored private maintenance plane.
   The public publication contains only approved semantic claims, claim-scoped
   minimal evidence windows, source identity, and non-personal review hashes.
3. The six pilot topics are evaluated independently in shadow mode, but switch
   to v3 together only after every topic passes. Uncovered topics continue to
   use the complete v2 path; one claim may never mix v2 and v3 evidence.
4. Automated systems may create candidates and propagate stale state. They may
   not perform source verification, domain approval, or publication approval.

## Consequences

- M1 and M2 artifacts are shadow-only and explicitly `switch_eligible: false`.
- Changing source media, transcript text, or timing invalidates all dependents.
- A sanitized, fingerprinted publication is the only input to the v3 runtime.
- Any future change to these semantics requires another ADR and explicit product
  review; an ordinary refactor PR is insufficient.
