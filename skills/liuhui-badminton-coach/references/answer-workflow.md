# Complex Answer Workflow

Read this file only for systematic learning paths or complex multi-issue answers. `SKILL.md` and the current packet remain authoritative.

A transcript file on disk is not answer evidence; never inspect raw transcripts to repair a missing claim. Surface the gap or rebuild the reviewed runtime artifacts.

## Multi-issue answers

Answer every `query_unit` against its own constraints and claim allowlist. Merge repeated conclusions only after each unit is covered. Never require one video to satisfy unrelated units. Preserve `matched_query_units` and the unit-level evidence status.

Use this order when applicable:

1. `直接回答`: one compact decision per unit.
2. `文字解释`: supported mechanisms, conditions, cues, and observable distinctions.
3. `适用边界`: material branches, exclusions, and unresolved gaps.
4. `核心视频与观看重点`: the strongest labels from `core_videos`, with the packet's reason, viewing value, and focus.
5. `完整相关视频`: every remaining label from `complete_related_videos`, each with the same three-part viewing guidance; never output a bare title or link.
6. `置信边界`: distinguish source facts and bounded synthesis.
7. `为了让答案更完整，你还可以补充`: optional text context from pending clarifications, after the supported answer.

One claim may synthesize at most three strongest, source-distinct labels from `synthesis_videos`. This is an evidence-breadth limit, not a prose-length limit. Explain the supported conclusion, mechanism, observable distinction, and condition in coherent prose. Every source in `complete_related_videos` participated in synthesis and must be annotated; other semantically answerable candidates stay audit-only and must not be displayed merely to prove they were found. Reuse a video's assigned label and URL; never recycle a label for another video. Keep the answer useful without link access.

## Systematic learning

Use `topic_navigation` as navigation, not evidence. Provide:

1. the nearest category/subtopic;
2. the concepts, mechanisms, errors, and conditions that need separate evidence checks;
3. one source-supported distinction per branch;
4. selected evidence where useful;
5. two or three optional text questions at the end;
6. the boundary between topic mapping and selected evidence.

Avoid an encyclopedia. Start from the nearest branch and a compact evidence map.
Do not turn that map into session timing, repetitions, sets, frequency, success
rates, or a multi-day progression. If a selected source explicitly states a
practice cue, preserve its exact scope; otherwise return the training-evidence
boundary instead of inventing a learning plan.

## Text/video allocation

- `text_primary`: explain decisions, conditions, exceptions, and correction implications; use videos as original examples.
- `balanced`: explain timing, force/movement logic, errors, and source-supported cues; use video for rhythm and space.
- `video_primary`: still give purpose, observation points, errors, and source-supported checks; let video carry visual shape and continuity.

Run `audit_answer.py` with the exact original question, unmodified context, packet, and final draft. Fix every violation without weakening the context.

## Detailed packet-bound draft

For diagnostic or multi-claim answers, write detailed prose from the packet's authorized atoms and windows. Do not import generic badminton knowledge or use complete-list-only sources for claims. Preserve each claim's marker in the final draft so the auditor can verify coverage.

The deterministic renderer is useful as a completeness baseline. If selecting among authorized evidence for that baseline, supply a JSON draft containing only:

```json
{
  "schema_version": 1,
  "blocks": [
    {"type": "claim_atom", "claim_id": "Q1", "atom_id": "EA-..."},
    {"type": "claim_window", "claim_id": "Q2", "window_id": "W..."},
    {"type": "claim_gap", "claim_id": "H1"}
  ]
}
```

Every packet claim must appear. Atom and window IDs must belong to that claim's directive. No block accepts a free-text field; unknown fields fail closed. Render to `baseline-answer.md`, compare its coverage with the detailed draft, and audit the detailed draft.

The claim draft does not control `delivery_contract`. Required `D` blocks remain atomic: a tactical direction branch, diagnostic comparison, ordered checklist, source requirement, training-evidence boundary, or general evidence boundary must each appear and pass its kind-specific semantic audit. A visible `[D…]` marker without the required internal structure fails audit.
