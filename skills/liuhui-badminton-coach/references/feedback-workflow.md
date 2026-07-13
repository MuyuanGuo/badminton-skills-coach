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

Tell the user what was recorded in plain language. If the result is `needs_clarification`, ask only about the unknown or contradictory reference. Never say that feedback has already changed retrieval or the knowledge base.

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

Allowed decisions are `accepted`, `rejected`, and `needs_clarification`. Acceptance only marks a record as eligible for a future promotion step. It must not directly alter retrieval weights, evidence notes, or evaluation ground truth.

## GitHub feedback

Use the repository's Skill feedback issue form. Ask users to paste video IDs or Douyin links, not only local `V` labels.

Export an issue body, then import it into the same local review queue:

```bash
python3 scripts/feedback.py import-github \
  --body-file /path/to/issue-body.md \
  --source-url https://github.com/OWNER/REPO/issues/NUMBER
```

Treat user preference as evidence about usefulness, not proof that a coaching claim is true. Verify the source video before promoting any global change.
