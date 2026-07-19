# Answer Workflow Reference

Read this file for complex answers, learning paths, practice plans, feedback handling, or retrieval debugging. `SKILL.md` remains authoritative if anything conflicts.

## Context Interpretation

Start from `scripts/prepare_answer_context.py`, not an improvised keyword search.

- Preserve the user's original wording, literal symptom, exclusions, discipline, court position, stroke side, level, and desired output.
- For `split_multi_issue`, answer every query unit separately before merging repeated conclusions and videos.
- For `topic_first_systematic`, use `topic_navigation.matches`, `learning_path`, and focused evidence together. The topic map itself is not proof.
- For `literal_symptom_first`, distinguish evidence that directly covers the symptom from related mechanisms. Do not declare one cause without the user's movement video.
- For `boundary_first`, state the boundary before any relevant coaching material.
- Ask one concise clarification only when different answers would be materially correct under different scenarios. Otherwise state the assumption.

## Text And Video Modes

### `text_primary`

Explain every supported tactical principle, decision rule, condition, exception, and training implication in text. Videos demonstrate rallies, choices, consequences, and the original lesson.

### `balanced`

Explain purpose, timing, force or movement logic, common errors, cues, and practice methods. Videos carry continuity, rhythm, spatial relationships, and pressured variations.

### `video_primary`

Still give purpose, a small set of reliable observation points, common errors, and self-checks. Let video carry grip shape, racket-face change, posture, relative position, and trajectory. Do not claim that prose fully teaches those visual details.

## Finalist Semantics

`selected_videos` is the citation allowlist. Each item already contains a stable label, role, canonical URL, selection reasons, matched query units, teaching note, and query-matched transcript evidence.

- `core` directly supports the complete question or one complete split query unit under exact requested conditions.
- `supporting` covers a component, generic mechanism, reviewed evidence lead, or retrieval expansion. It cannot silently inherit conditions absent from the source.
- `concept_match: exact_question` may support the complete question. `exact_query_unit` supports only its matched split unit. `component_support`, `reviewed_support`, and `expanded_support` support only their evidenced component or mechanism.
- `constraint_match` records every explicit condition. `exact` matches the requested scope. `partial_support`, `mixed_support`, `incidental_support`, and `unspecified_support` are auxiliary only; `conflict` is rejected.
- Follow `claim_scope_policy` literally: `exact_question_scope`, `exact_query_unit_scope_only`, or `component_or_generic_support_only_not_full_question_proof`.
- The selector distinguishes stroke side, shot family, net-shot variant, court zone, singles/doubles, serve role and trajectory, active/passive state, attack/defense phase, and shot direction.
- `actor_context.target_actor` identifies whether the requested advice targets the user or partner, and `question_interpretation.constraints` describes only that target's action. `opponent_constraints`, `partner_constraints`, and other non-target actor constraints remain stated conditions, not hard matches against the target's technique. Use `derived_player_constraints` and `derived_search_terms` only for configured user responses such as receiving an opponent's serve or defending an opponent's shot.
- Court-zone constraints describe where the player executes the stroke. A target phrase such as `吊网前`, `推后场`, or `打到底线` does not by itself place the player in that target zone.
- Actor and goal wording remains scoped: `对方主动`, `对手推球`, or `争取主动` cannot prove that the player is executing the requested active stroke or push.
- Reviewed evidence signals are generated from the maintained answer-quality registry. They may rank an already compatible candidate or admit it as limited support; they never override a scenario conflict, exclusion, safety boundary, or source-readiness check.
- `title` may use a reviewed teaching-topic override when the public source title mixes teaching with product promotion. This changes presentation only; claims still require the original teaching note or transcript evidence.
- The default policy admits at most 12 exact sources plus 4 supporting sources. `selection_truncated: false` means every source remaining after these policy quotas is present; it does not prove semantic completeness.
- `selection_truncated: true` means rerun with a larger `--max-videos` only for a genuinely exhaustive survey. Do not silently claim completeness.
- `rejected_candidates` records deterministic conflicts, evidence failures, and quota exclusions in debug mode. Never cite it.

## Answer Construction

Use the following order, omitting only sections that truly do not apply:

1. **直接回答**: answer the actual question and identify the situation.
2. **文字解释**: synthesize all distinct supported points; do not copy transcripts line by line.
3. **适用边界**: state conditions that change the advice.
4. **核心视频与观看重点**: strongest one to three videos, with reason, observation target, timestamp when available, video ID, and canonical URL.
5. **完整相关视频**: every other selected worthwhile video, grouped by subtopic when long. Reuse labels and do not repeat URLs.
6. **置信边界**: separate source-backed facts, reasonable synthesis, and what requires watching the source or the user's own video.

One claim may cite at most three strongest sources. A video URL appears once in the answer. A `V` label maps to one video for that answer turn and is never recycled for another video.

## Systematic Learning

For a topic map or learning-order request, include:

1. Top category and subtopic.
2. Three to five stages from positioning to pressured use.
3. One observable goal per stage.
4. One to three selected evidence videos per stage where useful.
5. Two or three focused next questions.
6. The boundary between topic navigation and direct evidence.

Avoid a giant encyclopedia. Start with the nearest branch and a compact path.

## Practice Plans

Use `practice-plan-template.md` and the returned `topic_navigation.practice_adaptation`.

- Respect stated level, singles/doubles use, solo/partner/coach setup, handedness, session length, and pain boundary.
- If duration is absent, use 15 minutes. Warm-up, isolated cue, pressured or decision drill, and self-check minutes must sum to the total.
- Add a three-day correction focus, a two-week progression, observable success criteria, evidence-backed common errors, and stop/review signals.
- Keep volume conservative and never promise fixed-date improvement.

## Feedback-Guided Answers

Feedback changes ranking, presentation, question interpretation, or source re-check priority; it never replaces source evidence.

- `missing_content`: cover every distinct supported conclusion.
- `too_vague`: add decisions and observable cues.
- `hard_to_apply`: add executable steps and self-checks.
- `scenario_mismatch`: state or ask for the condition that changes the answer.
- `question_misunderstood`: restate the intended question and rerun the full context command.
- `incorrect_claim`, `transcript_error`, `video_misinterpreted`, or `citation_mismatch`: re-fetch the named source, prefer corroboration, and do not accept the correction as fact without evidence.

Local feedback affects future answers only after the user confirms the parsed record and it is marked accepted. Public feedback additionally requires sanitized consent, a real GitHub Issue, API verification, deduplication, source-integrity checks, regression tests, and release promotion. This is a safety and integrity gate, not coaching-expert approval.

## Retrieval Debugging

Use lower-level commands only to diagnose a failed or disputed context:

```bash
python3 scripts/search_knowledge.py "问题" --plan-only
python3 scripts/search_knowledge.py "问题" --manifest-limit 20
python3 scripts/search_knowledge.py "问题" --video-id VIDEO_ID
python3 scripts/prepare_answer_context.py "问题" --include-rejected
```

An exhaustive manifest proves only that configured retrieval channels were not truncated. It does not prove semantic completeness. Do not expose n-gram hashes or full debug payloads in a coaching answer.

## Citation Form

Use the selected label and canonical source once:

```text
V1｜视频标题（视频 ID：1234567890123456789）
观看重点：……
关键片段：00:23-00:38
https://www.douyin.com/video/1234567890123456789
```

If a public link fails, preserve the title and video ID. The textual answer must remain useful without link access.
