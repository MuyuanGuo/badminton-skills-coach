# Evidence Scope Guide

Read this file only for `claim_evidence_fallback` composition or retrieval diagnosis. In `reviewed_atoms_closed` mode, the packet's reviewed atoms already define the allowed claims and conditions.

## Named Stroke Variants

Preserve active/passive, singles/doubles, forehand/backhand, level, and court-position distinctions. Treat `挑球`, `过渡球`, `挡杀/接杀`, named smash variants (`普通杀球`, `普通反手杀球`, `反手转圈杀`, `反手跳杀`, `点杀`, `跳杀`, `重杀`, `快杀`, `遁地炮`, `定杀`, `轻杀`, `劈杀`, `霸王杀`), and named drop variants (`普通吊球`, `劈吊`, `滑板`) as distinct actions or variants. When the user names one, require direct support instead of an incidental mention, broad same-side source, or generic tactics.

Do not use ordinary-smash, heavy-smash, or jump-smash evidence to prove point-smash mechanics. Phrases such as `高点杀球`, `点杀一样的效果`, and `把点杀得很尖` do not name the point-smash technique. Separate ordinary backhand smash, spinning backhand smash, and backhand jump smash. A multi-technique source supports only its matching segment, and an advanced source must retain prerequisites.

Do not use ordinary-smash, point-smash, ground-cannon, backhand-jump-smash, or generic jump-training evidence to prove forehand jump-smash mechanics unless a source directly connects the component to jump smash. Condition advanced, female-athlete, or continuous-attack sources rather than presenting them as universal beginner instructions.

For fast smash, separate its small, quick framework from heavy-smash mechanics and condition fast jump-smash evidence on continuous attack. Use only `遁地炮` as the canonical ground-cannon name; accept `顿地炮`, `蹲地炮`, and `dun地炮` only as input errors, correct them once, and never repeat them as valid names. Classify `遁地炮` as a non-jumping heavy-smash subtype and, by landing depth, a long smash whose landing point is farther back than a steep jump smash. Natural brief loss of ground contact from pushing and weight transfer is not a jump. Generic heavy-smash evidence cannot prove `遁地炮` footwork or timing, and a title, incidental mention, or ability ranking cannot prove the complete action.

For stationary smash, say when a source supports only a comparison and not the complete action. For light smash, use tactical evidence about reduced pace, maintained downward pressure, and next-shot connection without inventing hand mechanics.

Do not let `劈吊` prove `劈杀`, or `劈杀` prove `劈吊`; a multi-technique source supports each only through its matching segment. Do not use ordinary-drop evidence for a slice drop, a slice-drop source for a reverse-slice slide drop, or a source saying one smash contains a slicing component as slide-drop technique evidence.

## Named Tactical And Movement Scopes

Treat `平高球`, `假挑真放`, `动态低架`, far-net subtypes, and `杀上网` as named scopes. For `平高球`, separate outgoing-stroke evidence from receiving or intercepting an opponent's flat clear, and state when only force-mode and visual-demo evidence exists. For `假挑真放`, reject a demonstration promising later teaching as mechanism evidence. Do not substitute `升框架` or generic dynamic force for `动态低架`.

Treat bare `远网` as ambiguous among flat-slice far net, middle far-net splitting, defensive far-net-to-push, and far-net drop; explain branches before details. Separate `杀上网` from generic smash and generic net footwork, retaining singles/doubles and partner-coverage conditions. Preserve `杀球 -> 上网` as the same named sequence when connectors, question words, or symptoms such as `来不及` occur between the actions. Keep the symptom for diagnosis and do not retrieve unrelated generic late-contact evidence.

Treat `压球` and similar downward-pressure wording as context-dependent. Distinguish rear-court smash pressure from forecourt or midcourt interception, state returned ambiguity before coaching, and require direct court-zone support when the user names a zone.

When `inferred_target_action` identifies a late forecourt-reception symptom, treat the net shot or drop as the incoming condition and coach the returned forward-start or up-net movement. Require direct movement evidence; a rear-court passive stroke, a video matching only `来不及`, or a smash-to-net sequence does not support this question.

A requested-action fallback may restore a positioning or team-coverage source only when every explicit constraint has direct scope support. A source matching only `站位` cannot bypass a condition such as defense.

## Actors And Roles

Use `actor_context.target_actor` to identify whether advice targets the user or partner. Resolve `他/她` through returned actor context, never by assuming an opponent. Preserve `event_chain` actor order: distinguish the player's prior action, opponent response, and requested player action. An intervening actor must not erase a named sequence.

Treat `target_action_query` as the requested action and `target_condition_query` as that actor's prior state or symptom. A condition such as weak backhand is not the requested stroke when the user asks about positioning. When `target_action_backreferences_condition` is true, a generic request such as `怎么改` inherits only configured actions from the prior clause. Opponent and partner constraints remain conditions, not target actions. Apply hard evidence scope from `question_interpretation.constraints`; use returned derived constraints and requested-action scopes only as specified by the packet.

Do not treat an action performed only by a coach, partner, opponent, wall-feed setup, or shuttle machine as the user's requested technique. Broad categories such as `发球与接发` or `网前技术` are navigation metadata, not proof of every role or sub-technique. A role-unspecified source supports only a separately requested generic component and never a serve/receive claim when role wording is absent, suppressed, or contradictory.
