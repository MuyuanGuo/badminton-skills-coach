# Complex Answer Workflow

Read this file only for systematic learning paths or complex multi-issue answers. `SKILL.md` and the current packet remain authoritative.

A transcript file on disk is not answer evidence; never inspect raw transcripts to repair a missing claim. Surface the gap or rebuild the reviewed runtime artifacts.

## Multi-issue answers

Answer every `query_unit` against its own constraints and claim allowlist. Merge repeated conclusions only after each unit is covered. Never require one video to satisfy unrelated units. Preserve `matched_query_units` and the unit-level evidence status.

Use this order when applicable:

1. `直接回答`: one compact decision per unit.
2. `文字解释`: supported mechanisms, conditions, cues, and observable distinctions.
3. `适用边界`: material branches, exclusions, and unresolved gaps.
4. `核心视频与观看重点`: the 3–5 strongest labels from `core_videos`, with detailed viewing guidance.
5. `完整相关视频`: every remaining label from `complete_related_videos`, grouped by unit and never silently capped to the core shortlist.
6. `置信边界`: distinguish source facts, bounded synthesis, and required user video.

One claim may synthesize at most three strongest, source-distinct labels from `synthesis_videos`. This is a prose-density limit, not a related-video limit: sources present only in `complete_related_videos` must still be listed but cannot be borrowed to add technical claims. Reuse a video's assigned label and URL; never recycle a label for another video. Keep the answer useful without link access.

## Systematic learning

Use `topic_navigation` as navigation, not evidence. Provide:

1. the nearest category/subtopic;
2. three to five stages from positioning to pressured use;
3. one observable goal per stage;
4. selected evidence where useful;
5. two or three focused next questions;
6. the boundary between topic mapping and selected evidence.

Avoid an encyclopedia. Start from the nearest branch and a compact progression.

## Text/video allocation

- `text_primary`: explain decisions, conditions, exceptions, and training implications; use videos as original examples.
- `balanced`: explain timing, force/movement logic, errors, cues, and practice; use video for rhythm and space.
- `video_primary`: still give purpose, observation points, errors, and self-checks; let video carry visual shape and continuity.

Run `audit_answer.py` with the exact original question, unmodified context, packet, and final draft. Fix every violation without weakening the context.

## Closed structured draft

For diagnostic or multi-claim answers, render from the packet instead of writing free technical prose. The default renderer covers every claim. If selecting among authorized evidence, supply a JSON draft containing only:

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

Every packet claim must appear. Atom and window IDs must belong to that claim's directive. No block accepts a free-text field; unknown fields fail closed. Run `render_answer.py --packet answer-packet.json --draft draft.json > answer.md`, then pass that unmodified file to the auditor.

The claim draft does not control `delivery_contract`. The renderer appends every required `D` block itself. These blocks are atomic: a practice session, three-day progression, two-week progression, success criteria, tactical direction branch, diagnostic comparison, ordered checklist, source requirement, or evidence boundary must each render and pass its kind-specific semantic audit. A visible `[D…]` marker without the required internal structure fails audit.
