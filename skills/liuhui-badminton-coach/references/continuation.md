# Clarification Continuation

Treat a clarification reply as a continuation of the preserved original problem. Pass the complete raw reply with `--continue-from` and the exact prior context. With several pending questions, supply a JSON object keyed by stable `question_id`; allow partial answers.

Reject empty replies, unknown/duplicate IDs, modified state, or a free-text reply that cannot resolve the sole pending question. Never copy prior selected videos, labels, claims, or evidence mappings into the new turn; rerun retrieval and selection.

Use `answer_turn_contract.original_query` for final audit. Keep `effective_query` as the auditable rendering of the original question, assistant-authored clarification labels, and user replies. Use `semantic_query` for intent, actor, constraint, retrieval, and diagnostic parsing; it contains only the original question and the user's reply text. Never treat `query_label`, question wording, or other assistant-authored metadata as a user-required evidence focus.

Bind a mechanism or branch continuation through the request's structured `evidence_focus`, not by copying its natural-language label into the machine query. Rerun retrieval and selection from the preserved original problem, use clarification observations to refine applicability, and keep the original user-authored hard focus. Acknowledge resolved answers, never re-ask resolved IDs, and retain every pending question with its purpose.

Treat clarification observations as user-reported. They may prioritize a source-backed branch but do not independently prove a unique physical cause.
