# Feedback Workflow

Use this workflow only for answers produced with this Skill and for explicit user feedback about those answers.

## Before sending an answer

1. Assign every confirmed worthwhile video exactly one stable label: `V1`, `V2`, and so on.
2. Keep the same label when a core video appears again in the complete related-video list.
3. Order labels by answer usefulness, not by raw retrieval rank.
4. Keep the question and mapping in task context. Do not persist the user's question merely because an answer was generated.

End the answer with one short optional feedback example that uses only labels present in that answer:

```text
反馈示例：V1 最有价值；V2 不相关；文字漏了“被动情况下如何处理”。
```

Do not imply that unselected videos are irrelevant.

## When the user gives feedback

Only after the user explicitly gives feedback, save the prior question, exact label mapping, and user's words in one operation:

```bash
python3 scripts/feedback.py record \
  --question "用户原问题" \
  --mode balanced \
  --video V1=VIDEO_ID \
  --video V2=VIDEO_ID \
  --core-video V1 \
  --feedback "用户的原始反馈"
```

For a previously persisted answer context, use `scripts/feedback.py submit --answer-id ANSWER_ID` instead.

Tell the user what was recorded in plain language. If the result is `needs_clarification`, ask only about the unknown or contradictory reference. Otherwise ask the user to reply `确认用于本地个性化` before accepting it. Never say that pending feedback has changed retrieval.

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

## Human review

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

- Accepted `local` feedback becomes available to future searches that use the same local feedback directory. It can adjust bounded video ranking and answer presentation, but never source evidence or coaching facts.
- Accepted `github_issue` feedback is still not public Skill data. It must pass the promotion step below.
- Rejected, pending, contradictory, or unparsed feedback never affects an answer.

Disable local personalization for one search with:

```bash
python3 scripts/search_knowledge.py "用户问题" --no-local-personalization
```

## GitHub feedback

Use the repository's Skill feedback issue form. Ask users to paste video IDs or Douyin links, not only local `V` labels.

To share an accepted local record, first ask the user to provide or approve a sanitized public version of the question. After separate public-sharing consent, generate a GitHub Issue body:

```bash
python3 scripts/feedback.py export-github \
  --feedback-id FEEDBACK_ID \
  --public-question "脱敏后的代表性问题" \
  --confirm-public \
  --output /path/to/issue-body.md
```

The export contains only the sanitized question, video IDs and links, parsed issue types, version, and privacy confirmation. It does not include the original question or raw feedback. It also does not upload anything: show the returned submission URL and Issue body to the user, and wait for the user to submit it. Do not mark it as uploaded until a real public Issue URL exists.

After a public Issue exists, import its body into the same local review queue:

```bash
python3 scripts/feedback.py import-github \
  --body-file /path/to/issue-body.md \
  --source-url https://github.com/OWNER/REPO/issues/NUMBER
```

Treat user preference as evidence about usefulness, not proof that a coaching claim is true. Verify the source video before promoting any global change.

After accepting an imported GitHub record, perform a dry run with a sanitized public query and a human evidence note:

```bash
python3 /path/to/repository/scripts/promote_feedback.py \
  --feedback-id FEEDBACK_ID \
  --public-query "脱敏后的代表性问题" \
  --evidence-note "已回看相关公开视频并核对适用边界" \
  --promoted-by MAINTAINER \
  --dry-run
```

Remove `--dry-run` only after inspecting the preview. Promotion writes a minimal public signal to `config/feedback_signals.json`, syncs the Skill reference, and adds a regression case. It excludes the original question and raw feedback.

Then run:

```bash
python3 scripts/evaluate_feedback_signals.py
python3 scripts/evaluate_retrieval.py
python3 scripts/validate_project.py
```

Commit a promoted signal only when all evaluations pass. The source must be a public GitHub Issue; a local export or `share_upstream` flag is not sufficient by itself.
