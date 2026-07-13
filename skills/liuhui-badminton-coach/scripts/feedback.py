#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
REFERENCES = SKILL_ROOT / "references"
KNOWLEDGE_PATH = REFERENCES / "knowledge-base.json"
RULES_PATH = REFERENCES / "feedback-rules.json"
VIDEO_REF_PATTERN = re.compile(r"(?:[Vv]\s*0*(\d+)|视频\s*0*(\d+))")
VIDEO_ID_PATTERN = re.compile(r"(?<!\d)(\d{18,20})(?!\d)")
CLAUSE_SPLIT_PATTERN = re.compile(r"[，,；;。!！？?\n]+|[.](?=\s|$)")
ISSUE_HEADING_PATTERN = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def default_queue_dir():
    override = os.environ.get("LIUHUI_FEEDBACK_DIR")
    if override:
        return Path(override).expanduser()
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    return codex_home / "feedback" / "liuhui-badminton-coach"


def load_json(path):
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def load_resources():
    return load_json(KNOWLEDGE_PATH), load_json(RULES_PATH)


def atomic_write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def make_record_id(prefix, seed):
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha256(f"{seed}|{utc_now()}".encode("utf-8")).hexdigest()[:8]
    return f"{prefix}-{timestamp}-{digest}"


def normalize_ref(number):
    return f"V{int(number)}"


def ref_sort_key(reference):
    return int(reference[1:])


def unique_in_order(items):
    return list(dict.fromkeys(items))


def extract_video_refs(text):
    references = []
    for match in VIDEO_REF_PATTERN.finditer(text or ""):
        references.append(normalize_ref(match.group(1) or match.group(2)))
    return unique_in_order(references)


def extract_video_ids(text):
    return unique_in_order(VIDEO_ID_PATTERN.findall(text or ""))


def parse_video_spec(spec):
    if "=" not in spec:
        raise ValueError(f"Video mapping must use V1=VIDEO_ID: {spec}")
    reference, video_id = (part.strip() for part in spec.split("=", 1))
    matched = re.fullmatch(r"[Vv]\s*0*(\d+)", reference)
    if not matched:
        raise ValueError(f"Invalid video reference: {reference}")
    if not re.fullmatch(r"\d{18,20}", video_id):
        raise ValueError(f"Invalid Douyin video ID: {video_id}")
    return normalize_ref(matched.group(1)), video_id


def validate_video_mappings(video_specs, core_refs, knowledge):
    mappings = [parse_video_spec(spec) for spec in video_specs]
    references = [reference for reference, _ in mappings]
    video_ids = [video_id for _, video_id in mappings]
    if len(references) != len(set(references)):
        raise ValueError("Video references must be unique")
    if len(video_ids) != len(set(video_ids)):
        raise ValueError("The same video ID cannot receive multiple references")
    expected = [f"V{index}" for index in range(1, len(mappings) + 1)]
    if sorted(references, key=ref_sort_key) != expected:
        raise ValueError("Video references must be contiguous and start at V1")

    ready_videos = {
        video["video_id"]: video
        for video in knowledge["videos"]
        if video["processing_status"] == "ready"
    }
    missing_ids = [video_id for video_id in video_ids if video_id not in ready_videos]
    if missing_ids:
        raise ValueError(
            "Answer video mappings must reference ready knowledge videos: "
            + ", ".join(missing_ids)
        )

    normalized_core_refs = unique_in_order(
        normalize_ref(reference[1:]) if reference.upper().startswith("V") else reference
        for reference in core_refs
    )
    unknown_core_refs = sorted(set(normalized_core_refs) - set(references))
    if unknown_core_refs:
        raise ValueError(
            "Core video references are missing from the answer mapping: "
            + ", ".join(unknown_core_refs)
        )

    return [
        {
            "ref": reference,
            "video_id": video_id,
            "title": ready_videos[video_id]["title"],
            "url": ready_videos[video_id]["url"],
            "core": reference in normalized_core_refs,
        }
        for reference, video_id in sorted(mappings, key=lambda item: ref_sort_key(item[0]))
    ]


def knowledge_version(knowledge):
    latest_ready = next(
        (video for video in knowledge["videos"] if video["processing_status"] == "ready"),
        None,
    )
    return {
        "updated_at": knowledge["updated_at"],
        "latest_ready_video_id": latest_ready["video_id"] if latest_ready else None,
        "ready_video_count": sum(
            video["processing_status"] == "ready" for video in knowledge["videos"]
        ),
    }


def build_feedback_hint(videos):
    references = [video["ref"] for video in videos]
    if len(references) >= 2:
        return (
            f"反馈：{references[0]} 最有价值；{references[-1]} 不相关；"
            "文字漏了‘……’。"
        )
    if references:
        return f"反馈：{references[0]} 最有价值；文字漏了‘……’。"
    return "反馈：文字漏了‘……’，或者回答理解错了我的问题。"


def create_answer_context(
    question,
    video_specs,
    core_refs=None,
    answer_mode=None,
    user_context=None,
    queue_dir=None,
):
    knowledge, rules = load_resources()
    videos = validate_video_mappings(video_specs, core_refs or [], knowledge)
    created_at = utc_now()
    answer_id = make_record_id(
        "A", f"{question}|{'|'.join(video['video_id'] for video in videos)}"
    )
    payload = {
        "schema_version": rules["version"],
        "answer_id": answer_id,
        "created_at": created_at,
        "skill_version": rules["skill_version"],
        "channel": rules["channel"],
        "question": question.strip(),
        "user_context": unique_in_order(user_context or []),
        "answer_mode": answer_mode,
        "knowledge_version": knowledge_version(knowledge),
        "videos": videos,
    }
    target_dir = Path(queue_dir or default_queue_dir())
    atomic_write_json(target_dir / "answers" / f"{answer_id}.json", payload)
    return {
        **payload,
        "feedback_hint": build_feedback_hint(videos),
    }


def cue_in_text(text, cues):
    lowered = text.lower()
    return any(cue.lower() in lowered for cue in cues)


def parse_feedback_text(feedback_text, answer, rules):
    ref_to_id = {video["ref"]: video["video_id"] for video in answer["videos"]}
    id_to_ref = {video_id: reference for reference, video_id in ref_to_id.items()}
    all_refs = set(extract_video_refs(feedback_text))
    unknown_refs = sorted(all_refs - set(ref_to_id), key=ref_sort_key)
    helpful_refs = []
    irrelevant_refs = []
    missing_video_ids = []

    for clause in filter(None, (part.strip() for part in CLAUSE_SPLIT_PATTERN.split(feedback_text))):
        refs = extract_video_refs(clause)
        direct_ids = extract_video_ids(clause)
        is_negative = cue_in_text(clause, rules["negative_video_cues"])
        is_positive = cue_in_text(clause, rules["positive_video_cues"])
        is_missing = cue_in_text(clause, rules["missing_video_cues"])

        known_refs = [reference for reference in refs if reference in ref_to_id]
        if is_negative:
            irrelevant_refs.extend(known_refs)
        elif is_positive:
            helpful_refs.extend(known_refs)

        for video_id in direct_ids:
            if video_id in id_to_ref:
                if is_negative:
                    irrelevant_refs.append(id_to_ref[video_id])
                elif is_positive:
                    helpful_refs.append(id_to_ref[video_id])
            elif is_missing or is_positive:
                missing_video_ids.append(video_id)

        if is_missing:
            missing_video_ids.extend(
                video_id for video_id in direct_ids if video_id not in id_to_ref
            )

    helpful_refs = sorted(set(helpful_refs), key=ref_sort_key)
    irrelevant_refs = sorted(set(irrelevant_refs), key=ref_sort_key)
    conflicts = sorted(set(helpful_refs) & set(irrelevant_refs), key=ref_sort_key)
    missing_video_ids = unique_in_order(missing_video_ids)

    text_issue_types = [
        issue_type
        for issue_type, cues in rules["text_issue_cues"].items()
        if cue_in_text(feedback_text, cues)
    ]
    outcome = None
    for outcome_name in [
        "misunderstood",
        "unresolved",
        "understood_need_video",
        "directly_applicable",
    ]:
        if cue_in_text(feedback_text, rules["outcome_cues"].get(outcome_name, [])):
            outcome = outcome_name
            break

    warnings = []
    if unknown_refs:
        warnings.append("unknown_video_refs:" + ",".join(unknown_refs))
    if conflicts:
        warnings.append("conflicting_video_refs:" + ",".join(conflicts))

    signals = {
        "helpful_video_refs": helpful_refs,
        "helpful_video_ids": [ref_to_id[reference] for reference in helpful_refs],
        "irrelevant_video_refs": irrelevant_refs,
        "irrelevant_video_ids": [ref_to_id[reference] for reference in irrelevant_refs],
        "missing_video_ids": missing_video_ids,
        "text_issue_types": text_issue_types,
        "outcome": outcome,
    }
    actionable = any(
        [
            helpful_refs,
            irrelevant_refs,
            missing_video_ids,
            text_issue_types,
            outcome,
        ]
    )
    if not actionable:
        warnings.append("no_actionable_signal")

    return {
        "signals": signals,
        "parser_warnings": warnings,
        "status": "needs_clarification" if warnings else "pending_review",
    }


def load_answer(answer_id, queue_dir):
    path = Path(queue_dir) / "answers" / f"{answer_id}.json"
    if not path.exists():
        raise ValueError(f"Answer context not found: {answer_id}")
    return load_json(path)


def submit_feedback(
    answer_id,
    feedback_text,
    share_upstream=False,
    queue_dir=None,
):
    target_dir = Path(queue_dir or default_queue_dir())
    answer = load_answer(answer_id, target_dir)
    _, rules = load_resources()
    parsed = parse_feedback_text(feedback_text, answer, rules)
    feedback_id = make_record_id("F", f"{answer_id}|{feedback_text}")
    payload = {
        "schema_version": rules["version"],
        "feedback_id": feedback_id,
        "status": parsed["status"],
        "created_at": utc_now(),
        "updated_at": None,
        "source": {"type": "local", "reference": None},
        "answer_id": answer_id,
        "skill_version": answer["skill_version"],
        "channel": answer["channel"],
        "question": answer["question"],
        "user_context": answer["user_context"],
        "answer_mode": answer["answer_mode"],
        "knowledge_version": answer["knowledge_version"],
        "presented_videos": answer["videos"],
        "signals": parsed["signals"],
        "raw_feedback": feedback_text.strip(),
        "share_upstream": bool(share_upstream),
        "parser_warnings": parsed["parser_warnings"],
        "review_history": [],
        "promotion_status": "not_promoted",
    }
    atomic_write_json(target_dir / "queue" / f"{feedback_id}.json", payload)
    return payload


def record_feedback(
    question,
    video_specs,
    feedback_text,
    core_refs=None,
    answer_mode=None,
    user_context=None,
    share_upstream=False,
    queue_dir=None,
):
    answer = create_answer_context(
        question=question,
        video_specs=video_specs,
        core_refs=core_refs,
        answer_mode=answer_mode,
        user_context=user_context,
        queue_dir=queue_dir,
    )
    return submit_feedback(
        answer_id=answer["answer_id"],
        feedback_text=feedback_text,
        share_upstream=share_upstream,
        queue_dir=queue_dir,
    )


def list_feedback(queue_dir=None, statuses=None):
    target_dir = Path(queue_dir or default_queue_dir())
    items = []
    for path in sorted((target_dir / "queue").glob("*.json")):
        payload = load_json(path)
        if statuses and payload["status"] not in statuses:
            continue
        items.append(
            {
                "feedback_id": payload["feedback_id"],
                "status": payload["status"],
                "created_at": payload["created_at"],
                "source": payload["source"],
                "question": payload["question"],
                "signals": payload["signals"],
                "parser_warnings": payload["parser_warnings"],
            }
        )
    return {"count": len(items), "items": items}


def show_feedback(feedback_id, queue_dir=None):
    target_dir = Path(queue_dir or default_queue_dir())
    path = target_dir / "queue" / f"{feedback_id}.json"
    if not path.exists():
        raise ValueError(f"Feedback record not found: {feedback_id}")
    return load_json(path)


def review_feedback(feedback_id, decision, note, reviewer, queue_dir=None):
    target_dir = Path(queue_dir or default_queue_dir())
    _, rules = load_resources()
    if decision not in rules["review_decisions"]:
        raise ValueError(f"Unsupported review decision: {decision}")
    if not note.strip():
        raise ValueError("A review note is required")
    payload = show_feedback(feedback_id, target_dir)
    reviewed_at = utc_now()
    payload["status"] = decision
    payload["updated_at"] = reviewed_at
    payload["review_history"].append(
        {
            "decision": decision,
            "note": note.strip(),
            "reviewer": reviewer.strip() or "local-maintainer",
            "reviewed_at": reviewed_at,
        }
    )
    atomic_write_json(target_dir / "queue" / f"{feedback_id}.json", payload)
    return {
        **payload,
        "next_action": (
            "eligible_for_future_promotion_after_evidence_review"
            if decision == "accepted"
            else "no_automatic_retrieval_change"
        ),
    }


def parse_issue_sections(body):
    matches = list(ISSUE_HEADING_PATTERN.finditer(body))
    sections = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections[match.group(1).strip()] = body[start:end].strip()
    return sections


def normalize_issue_value(value):
    value = (value or "").strip()
    return "" if value in {"_No response_", "无", "没有", "N/A"} else value


def import_github_issue(body, source_url, queue_dir=None):
    target_dir = Path(queue_dir or default_queue_dir())
    knowledge, rules = load_resources()
    sections = {
        heading: normalize_issue_value(value)
        for heading, value in parse_issue_sections(body).items()
    }
    question = sections.get("用户问题", "")
    if not question:
        raise ValueError("GitHub issue is missing the 用户问题 section")

    helpful_ids = extract_video_ids(sections.get("最有价值的视频", ""))
    irrelevant_ids = extract_video_ids(sections.get("明确不相关的视频", ""))
    missing_ids = extract_video_ids(sections.get("遗漏的视频", ""))
    text_issue_value = sections.get("文字回答问题", "")
    issue_labels = {
        "文字内容有遗漏": "missing_content",
        "存在错误结论": "incorrect_claim",
        "过于笼统": "too_vague",
        "过于冗长": "too_verbose",
        "难以执行": "hard_to_apply",
        "不适合提问场景": "scenario_mismatch",
    }
    text_issue_types = [
        issue_type
        for label, issue_type in issue_labels.items()
        if label in text_issue_value
    ]
    known_ids = {video["video_id"] for video in knowledge["videos"]}
    unknown_labeled_ids = unique_in_order(
        video_id
        for video_id in helpful_ids + irrelevant_ids
        if video_id not in known_ids
    )
    warnings = (
        ["unknown_labeled_video_ids:" + ",".join(unknown_labeled_ids)]
        if unknown_labeled_ids
        else []
    )
    actionable = any([helpful_ids, irrelevant_ids, missing_ids, text_issue_types])
    if not actionable:
        warnings.append("no_actionable_signal")

    feedback_id = make_record_id("G", f"{source_url}|{question}")
    payload = {
        "schema_version": rules["version"],
        "feedback_id": feedback_id,
        "status": "needs_clarification" if warnings else "pending_review",
        "created_at": utc_now(),
        "updated_at": None,
        "source": {"type": "github_issue", "reference": source_url},
        "answer_id": sections.get("回答编号") or None,
        "skill_version": sections.get("版本信息") or "unknown",
        "channel": "unknown",
        "question": question,
        "user_context": [],
        "answer_mode": None,
        "knowledge_version": knowledge_version(knowledge),
        "presented_videos": [],
        "signals": {
            "helpful_video_refs": [],
            "helpful_video_ids": helpful_ids,
            "irrelevant_video_refs": [],
            "irrelevant_video_ids": irrelevant_ids,
            "missing_video_ids": missing_ids,
            "text_issue_types": text_issue_types,
            "outcome": None,
        },
        "raw_feedback": sections.get("补充说明", ""),
        "share_upstream": True,
        "parser_warnings": warnings,
        "review_history": [],
        "promotion_status": "not_promoted",
    }
    atomic_write_json(target_dir / "queue" / f"{feedback_id}.json", payload)
    return payload


def print_json(payload):
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def build_parser():
    parser = argparse.ArgumentParser(
        description="Record and review feedback for the Liu Hui badminton Skill."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser(
        "create-answer", help="Persist a question and its stable V1...Vn video mapping."
    )
    create.add_argument("--question", required=True)
    create.add_argument("--video", action="append", default=[], help="V1=VIDEO_ID")
    create.add_argument("--core-video", action="append", default=[], help="V1")
    create.add_argument("--mode")
    create.add_argument("--user-context", action="append", default=[])
    create.add_argument("--queue-dir", type=Path)

    record = subparsers.add_parser(
        "record",
        help="Persist an answer mapping and explicit feedback in one operation.",
    )
    record.add_argument("--question", required=True)
    record.add_argument("--video", action="append", default=[], help="V1=VIDEO_ID")
    record.add_argument("--core-video", action="append", default=[], help="V1")
    record.add_argument("--mode")
    record.add_argument("--user-context", action="append", default=[])
    record.add_argument("--feedback", required=True)
    record.add_argument("--share-upstream", action="store_true")
    record.add_argument("--queue-dir", type=Path)

    submit = subparsers.add_parser(
        "submit", help="Parse natural-language feedback into the local review queue."
    )
    submit.add_argument("--answer-id", required=True)
    submit.add_argument("--feedback", required=True)
    submit.add_argument("--share-upstream", action="store_true")
    submit.add_argument("--queue-dir", type=Path)

    list_command = subparsers.add_parser("list", help="List queued feedback.")
    list_command.add_argument("--status", action="append")
    list_command.add_argument("--queue-dir", type=Path)

    show = subparsers.add_parser("show", help="Show one feedback record.")
    show.add_argument("--feedback-id", required=True)
    show.add_argument("--queue-dir", type=Path)

    review = subparsers.add_parser(
        "review", help="Record a human accept, reject, or clarification decision."
    )
    review.add_argument("--feedback-id", required=True)
    review.add_argument(
        "--decision", required=True, choices=["accepted", "rejected", "needs_clarification"]
    )
    review.add_argument("--note", required=True)
    review.add_argument("--reviewer", default="local-maintainer")
    review.add_argument("--queue-dir", type=Path)

    import_issue = subparsers.add_parser(
        "import-github", help="Import an exported GitHub feedback issue body."
    )
    import_issue.add_argument("--body-file", type=Path, required=True)
    import_issue.add_argument("--source-url", required=True)
    import_issue.add_argument("--queue-dir", type=Path)

    return parser


def main():
    args = build_parser().parse_args()
    try:
        if args.command == "create-answer":
            result = create_answer_context(
                question=args.question,
                video_specs=args.video,
                core_refs=args.core_video,
                answer_mode=args.mode,
                user_context=args.user_context,
                queue_dir=args.queue_dir,
            )
        elif args.command == "record":
            result = record_feedback(
                question=args.question,
                video_specs=args.video,
                feedback_text=args.feedback,
                core_refs=args.core_video,
                answer_mode=args.mode,
                user_context=args.user_context,
                share_upstream=args.share_upstream,
                queue_dir=args.queue_dir,
            )
        elif args.command == "submit":
            result = submit_feedback(
                answer_id=args.answer_id,
                feedback_text=args.feedback,
                share_upstream=args.share_upstream,
                queue_dir=args.queue_dir,
            )
        elif args.command == "list":
            result = list_feedback(queue_dir=args.queue_dir, statuses=args.status)
        elif args.command == "show":
            result = show_feedback(args.feedback_id, queue_dir=args.queue_dir)
        elif args.command == "review":
            result = review_feedback(
                feedback_id=args.feedback_id,
                decision=args.decision,
                note=args.note,
                reviewer=args.reviewer,
                queue_dir=args.queue_dir,
            )
        else:
            result = import_github_issue(
                body=args.body_file.read_text(encoding="utf-8"),
                source_url=args.source_url,
                queue_dir=args.queue_dir,
            )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        raise SystemExit(str(error)) from error
    print_json(result)


if __name__ == "__main__":
    main()
