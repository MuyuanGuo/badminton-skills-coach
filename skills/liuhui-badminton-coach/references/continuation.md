# Clarification Continuation

Treat a clarification reply as a continuation of the preserved original problem. Pass the complete raw reply with `--continue-from` and the exact prior context. With several pending questions, supply a JSON object keyed by stable `question_id`; allow partial answers.

Reject empty replies, unknown/duplicate IDs, modified state, or a free-text reply that cannot resolve the sole pending question. Never copy prior selected videos, labels, claims, or evidence mappings into the new turn; rerun retrieval and selection.

Use `answer_turn_contract.original_query` for final audit. Treat `effective_query` only as retrieval input. Acknowledge resolved answers, never re-ask resolved IDs, and retain every pending question with its purpose.

Treat clarification observations as user-reported. They may prioritize a source-backed branch but do not independently prove a unique physical cause.
