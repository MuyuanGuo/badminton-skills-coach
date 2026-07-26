#!/usr/bin/env python3
"""Clarification-state and multi-turn answer contracts."""

import hashlib
import json

def canonical_json_digest(payload):
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def clarification_state_digest(state):
    unsigned = {
        key: value for key, value in state.items() if key != "state_digest"
    }
    return canonical_json_digest(unsigned)


def validate_clarification_state(previous_context, diagnostic_rules):
    if not isinstance(previous_context, dict):
        raise ValueError("continue_from must contain a context JSON object")
    state = previous_context.get("clarification_state")
    if not isinstance(state, dict):
        raise ValueError("continue_from does not contain clarification_state")
    if state.get("schema_version") != CLARIFICATION_STATE_SCHEMA_VERSION:
        raise ValueError("unsupported clarification_state schema_version")
    required = {
        "original_query",
        "effective_query",
        "turns",
        "resolved_answers",
        "pending_question_ids",
        "pending_requests",
        "state_digest",
    }
    if required - set(state):
        raise ValueError("clarification_state is missing required fields")
    if clarification_state_digest(state) != state["state_digest"]:
        raise ValueError("clarification_state digest mismatch")
    if previous_context.get("query") != state["effective_query"]:
        raise ValueError("continue_from query does not match clarification_state")
    requests = previous_context.get("clarification_decision", {}).get(
        "clarification_requests", []
    )
    if not isinstance(requests, list):
        raise ValueError("continue_from clarification requests are invalid")
    request_ids = [item.get("question_id") for item in requests]
    if any(not item for item in request_ids) or len(request_ids) != len(
        set(request_ids)
    ):
        raise ValueError("continue_from clarification request IDs are invalid")
    if request_ids != state["pending_question_ids"]:
        raise ValueError("clarification_state is stale for this context")
    if requests != state["pending_requests"]:
        raise ValueError("clarification_state request semantics are stale")
    if not all(
        isinstance(state.get(field), str) and state[field].strip()
        for field in ("original_query", "effective_query")
    ):
        raise ValueError("clarification_state queries are invalid")
    if not isinstance(state["resolved_answers"], list):
        raise ValueError("clarification_state resolved answers are invalid")
    if not isinstance(state["turns"], list) or not state["turns"]:
        raise ValueError("clarification_state turns are invalid")
    max_turns = diagnostic_rules.get("max_clarification_turns", 8)
    if len(state["turns"]) >= max_turns:
        raise ValueError("maximum clarification turns reached")
    return state, {item["question_id"]: item for item in requests}


def normalize_clarification_answers(payload):
    if payload is None:
        return None
    if isinstance(payload, dict) and "answers" in payload:
        payload = payload["answers"]
    if isinstance(payload, dict):
        items = [
            {"question_id": question_id, "answer": answer}
            for question_id, answer in payload.items()
        ]
    elif isinstance(payload, list):
        items = payload
    else:
        raise ValueError("clarification_answers must be an object or answer list")
    normalized = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("each clarification answer must be an object")
        question_id = item.get("question_id")
        answer = item.get("answer")
        if not isinstance(question_id, str) or not question_id.strip():
            raise ValueError("clarification answer has no question_id")
        if question_id in seen:
            raise ValueError(f"duplicate clarification answer: {question_id}")
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError(f"empty clarification answer: {question_id}")
        seen.add(question_id)
        normalized.append(
            {"question_id": question_id, "answer": answer.strip()}
        )
    if not normalized:
        raise ValueError("clarification_answers cannot be empty")
    return normalized


def answer_resolves_request(search_module, answer, request, explicit_binding):
    normalized = search_module.normalize(answer)
    inconclusive = {
        search_module.normalize(item)
        for item in ("不知道", "不清楚", "没注意", "没有注意", "无法判断")
    }
    if not normalized or normalized in inconclusive:
        return False
    if explicit_binding:
        return True
    cues = request.get("answer_cues", [])
    return any(search_module.normalize(cue) in normalized for cue in cues)


def resolve_continuation(
    search_module,
    raw_reply,
    previous_context,
    clarification_answers,
    diagnostic_rules,
):
    if not isinstance(raw_reply, str) or not raw_reply.strip():
        raise ValueError("clarification reply cannot be empty")
    state, requests_by_id = validate_clarification_state(
        previous_context, diagnostic_rules
    )
    pending_ids = state["pending_question_ids"]
    if not pending_ids:
        raise ValueError("continue_from has no pending clarification questions")
    answers = normalize_clarification_answers(clarification_answers)
    explicit_binding = answers is not None
    if answers is None:
        if len(pending_ids) != 1:
            raise ValueError(
                "multiple clarification questions require structured answers"
            )
        answers = [{"question_id": pending_ids[0], "answer": raw_reply.strip()}]
    unknown_ids = {
        item["question_id"] for item in answers
    } - set(pending_ids)
    if unknown_ids:
        raise ValueError(
            "unknown or stale clarification question IDs: "
            + ", ".join(sorted(unknown_ids))
        )
    turn_number = len(state["turns"]) + 1
    resolved = []
    for item in answers:
        request = requests_by_id[item["question_id"]]
        if not answer_resolves_request(
            search_module, item["answer"], request, explicit_binding
        ):
            raise ValueError(
                f'clarification reply does not resolve {item["question_id"]}'
            )
        resolved.append(
            {
                **item,
                "question": request["question"],
                "query_label": request["query_label"],
                "unknown_type": request["unknown_type"],
                "turn": turn_number,
            }
        )
    all_resolved = [*state["resolved_answers"], *resolved]
    effective_query = state["original_query"] + "".join(
        f'\n补充说明（{item["query_label"]}）：{item["answer"]}'
        for item in all_resolved
    )
    return effective_query, {
        "original_query": state["original_query"],
        "turns": [
            *state["turns"],
            {
                "turn": turn_number,
                "role": "user",
                "kind": "clarification_reply",
                "text": raw_reply.strip(),
                "answered_question_ids": [
                    item["question_id"] for item in resolved
                ],
            },
        ],
        "resolved_answers": all_resolved,
    }

def build_clarification_state(context, continuation=None):
    if continuation is None:
        state = {
            "schema_version": CLARIFICATION_STATE_SCHEMA_VERSION,
            "original_query": context["query"],
            "effective_query": context["query"],
            "turns": [
                {
                    "turn": 1,
                    "role": "user",
                    "kind": "original_query",
                    "text": context["query"],
                    "answered_question_ids": [],
                }
            ],
            "resolved_answers": [],
            "pending_question_ids": [],
            "pending_requests": [],
        }
    else:
        state = {
            "schema_version": CLARIFICATION_STATE_SCHEMA_VERSION,
            **continuation,
            "effective_query": context["query"],
            "pending_question_ids": [],
            "pending_requests": [],
        }
    state["pending_question_ids"] = [
        item["question_id"]
        for item in context["clarification_decision"][
            "clarification_requests"
        ]
    ]
    state["pending_requests"] = context["clarification_decision"][
        "clarification_requests"
    ]
    state["state_digest"] = clarification_state_digest(state)
    return state


def build_answer_turn_contract(context):
    state = context["clarification_state"]
    evidence_state = {
        "selected_videos": [
            {
                "label": item.get("label"),
                "evidence_id": str(
                    item.get("evidence_id", item.get("video_id", ""))
                ),
                "canonical_url": item.get("canonical_url") or item.get("url"),
            }
            for item in context.get("selected_videos", [])
        ],
        "claim_evidence": [
            {
                "claim_id": item.get("claim_id"),
                "kind": item.get("kind"),
                "status": item.get("status"),
                "eligible_video_labels": item.get(
                    "eligible_video_labels", []
                ),
                "confidence_ceiling": item.get("confidence_ceiling", "none"),
                "evidence": [
                    {
                        "label": evidence.get("label"),
                        "evidence_id": str(evidence.get("evidence_id", "")),
                        "directness": evidence.get("directness"),
                        "scope": evidence.get("scope"),
                    }
                    for evidence in item.get("evidence", [])
                ],
            }
            for item in context.get("claim_evidence_map", [])
        ],
    }
    return {
        "schema_version": ANSWER_TURN_CONTRACT_SCHEMA_VERSION,
        "original_query": state["original_query"],
        "effective_query": state["effective_query"],
        "turn_number": len(state["turns"]),
        "resolved_clarifications": state["resolved_answers"],
        "pending_clarifications": state["pending_requests"],
        "resolved_question_ids_must_not_be_reasked": [
            item["question_id"] for item in state["resolved_answers"]
        ],
        "evidence_state": evidence_state,
        "evidence_state_digest": canonical_json_digest(evidence_state),
    }
