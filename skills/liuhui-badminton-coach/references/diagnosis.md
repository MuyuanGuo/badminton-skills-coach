# Diagnostic Answer Workflow

Read the diagnostic fields before composing.

- Treat `observed_symptoms` and `clarification_observations` as user reports, not independently observed movement.
- Preserve `user_hypotheses` as proposals. `conditional` means a source supports a possible mechanism, not that it caused this user's error.
- Present `supported_mechanisms` as ordered checks with observable distinctions, not a generic list of causes.
- Cover every evidenced `material_branch` until clarified.
- With `answer_conditionally`, answer supported scope now. Put returned text questions in `为了让答案更完整，你还可以补充`; they are optional and must not block the answer.
- Use only each claim's mapped labels and stay below its confidence ceiling.

Separate three layers: reported symptom, proposed explanation, and source-supported mechanisms. Never claim one unique physical cause from limited text, but do not request or imply analysis of a user's action video.

State the actual failure first. For competing hypotheses, explain what user-reported observation favors each branch and what remains unresolved. A deterministic coverage pass does not prove that the diagnosis is semantically correct.
