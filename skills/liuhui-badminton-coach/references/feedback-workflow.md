# Feedback Workflow

Use this workflow only for answers produced with this Skill and for explicit user feedback about those answers.

## Before sending an answer

1. Assign every confirmed worthwhile video exactly one stable label: `V1`, `V2`, and so on.
2. Keep the same label when a core video appears again in the complete related-video list.
3. Order labels by answer usefulness, not by raw retrieval rank.
4. Keep the question and mapping in task context. Do not persist the user's question merely because an answer was generated.

End every answer with the exact `answer_contract.feedback_prompt`, which uses only labels present in that answer and parser-covered wording:

```text
反馈可直接回复：V1 最有价值；V2 不相关；第 2 点结论不对；回答漏了“被动情况下如何处理”；你理解错了，我真正问的是“……”。
```

For a misunderstood question, ask the user to state the correction explicitly, for example `你理解错了，我真正问的是“接发战术和接发握拍两个问题”`. For a transcript, interpretation, or citation problem, require the relevant `V` label, for example `V2 转写错了，原视频说的是……`.

Do not imply that unselected videos are irrelevant.

## When the user gives feedback

Only after the user explicitly gives feedback, save the prior question, exact answer text, exact label mapping, and user's words in one operation. The answer text and mapping are covered by one integrity digest:

```bash
python3 scripts/feedback.py record \
  --question "用户原问题" \
  --answer-file /path/to/exact-answer.md \
  --mode balanced \
  --video V1=VIDEO_ID \
  --video V2=VIDEO_ID \
  --core-video V1 \
  --feedback "用户的原始反馈"
```

For a previously persisted answer context, use `scripts/feedback.py submit --answer-id ANSWER_ID` instead. An answer ID is also its turn ID: labels from one answer must never be resolved against another answer's mapping. The stored mapping digest is checked before feedback is parsed.

Tell the user what was recorded in plain language. If the result is `needs_clarification`, ask only about the unknown, contradictory, comparative, or unresolved mixed-sentiment reference, the corrected intent after a misunderstood question, or the target video for a source-quality problem. Otherwise ask the user to reply `确认用于本地个性化` before accepting it. Never say that pending feedback has changed retrieval.

After explicit confirmation, accept the local record:

```bash
python3 scripts/feedback.py review \
  --feedback-id FEEDBACK_ID \
  --decision accepted \
  --reviewer local-user \
  --note "用户已确认解析结果用于本地个性化"
```

If the user declines or does not confirm, leave it pending. Do not infer consent from silence.

The default local queue is:

```text
${CODEX_HOME:-~/.codex}/feedback/liuhui-badminton-coach/
```

Set `LIUHUI_FEEDBACK_DIR` to override it. Local records are not uploaded automatically.

## Local confirmation and public safety review

List pending records:

```bash
python3 scripts/feedback.py list --status pending_review
```

Inspect one record:

```bash
python3 scripts/feedback.py show --feedback-id FEEDBACK_ID
```

Record a decision:

```bash
python3 scripts/feedback.py review \
  --feedback-id FEEDBACK_ID \
  --decision accepted \
  --note "已核对问题、视频和来源证据"
```

Allowed decisions are `accepted`, `rejected`, and `needs_clarification`.

- Accepted `local` feedback becomes available to future searches that use the same local feedback directory. It can adjust bounded video ranking and answer presentation, trigger a corrected-query replan, or flag named videos for evidence recheck, but never replace source evidence or coaching facts.
- Accepted `github_issue` feedback is still not public Skill data. It must pass the promotion step below.
- Rejected, pending, contradictory, or unparsed feedback never affects an answer.

Disable local personalization for one search with:

```bash
python3 scripts/search_knowledge.py "用户问题" --no-local-personalization
```

## GitHub feedback

Use the exported Issue body as the primary path. If the repository's Skill feedback form is visible on the default branch, users may fill it directly. Require a sanitized original question, sanitized complete answer or exact error excerpt, and a concrete error or omission. Ask users to paste video IDs or Douyin links, not only local `V` labels.

To share an accepted local record, first ask the user to provide or approve a sanitized public version of the question. After separate public-sharing consent, generate a GitHub Issue body:

```bash
python3 scripts/feedback.py export-github \
  --feedback-id FEEDBACK_ID \
  --public-question "脱敏后的代表性问题" \
  --public-answer-excerpt "脱敏后的完整回答或出错原句及必要上下文" \
  --public-intended-query "脱敏后的真实意图（仅问题理解错误时需要）" \
  --confirm-public \
  --output /path/to/issue-body.md
```

The export contains only the separately approved sanitized question, sanitized answer excerpt, video IDs and links, parsed issue types, version, and privacy confirmation. It does not include the original local question, original answer, or raw feedback. It also does not upload anything: show the returned submission URL and Issue body to the user, and wait for the user to submit it. Do not mark it as uploaded until a real public Issue URL exists.

After a public Issue exists in the canonical repository, fetch and import it through the GitHub API:

```bash
python3 scripts/feedback.py import-github \
  --fetch-url https://github.com/MuyuanGuo/badminton-skills-coach/issues/NUMBER
```

This records the canonical repository, issue number, node ID, source update time, and body hash. A manual `--body-file` import can still be reviewed locally, but it is unverified and cannot be promoted into public Skill data.

Treat user feedback as evidence about usefulness, question interpretation, or a possible source defect, not proof that a coaching claim is true. Question corrections must carry a sanitized intended query; transcript, video-interpretation, and citation corrections must name the affected video. Recheck the stored source before promoting any global change.

After accepting an imported GitHub record, re-fetch the exact Issue. This must happen after the latest maintainer safety and source-integrity review; if the body changed, the old record is superseded and the new revision must be reviewed from the beginning:

```bash
python3 scripts/feedback.py reverify-github \
  --feedback-id FEEDBACK_ID
```

Then perform a dry run with a sanitized public query and a source-check note:

```bash
python3 /path/to/repository/scripts/promote_feedback.py \
  --feedback-id FEEDBACK_ID \
  --public-query "脱敏后的代表性问题" \
  --evidence-note "已回看相关公开视频并核对适用边界" \
  --promoted-by MAINTAINER \
  --dry-run
```

Remove `--dry-run` only after inspecting the preview. Promotion uses an exclusive lock and an all-files write with rollback on ordinary write failures. It deduplicates by canonical GitHub Issue, writes a minimal public signal to `config/feedback_signals.json`, syncs the Skill reference, and adds a regression case. It excludes the original question and raw feedback. If a reviewed new Issue revision intentionally replaces an older promoted revision, use `--replace-existing`; otherwise replacement is blocked.

Then run:

```bash
python3 scripts/evaluate_feedback_signals.py
python3 scripts/evaluate_retrieval.py
python3 scripts/validate_project.py
```

Commit a promoted signal only when all evaluations pass. The source must be a GitHub-API-verified Issue in `MuyuanGuo/badminton-skills-coach`; a manual import, local export, or `share_upstream` flag is not sufficient by itself.
