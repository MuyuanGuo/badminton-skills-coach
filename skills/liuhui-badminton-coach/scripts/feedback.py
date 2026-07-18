#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import shutil
import ssl
import subprocess
import tempfile
import urllib.error
import urllib.request
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
GITHUB_ISSUE_URL = "https://github.com/MuyuanGuo/badminton-skills-coach/issues/new"
GITHUB_REPOSITORY = "MuyuanGuo/badminton-skills-coach"
GITHUB_ISSUE_PATTERN = re.compile(
    r"^https://github\.com/MuyuanGuo/badminton-skills-coach/issues/([1-9]\d*)/?$"
)
INTENDED_QUERY_PATTERN = re.compile(
    r"(?:我(?:真正)?问的是|我的(?:真实)?问题是|应该理解为|你应该回答的是)"
    r"\s*[：:，,]?\s*(.+?)(?:[。！？!\n]|$)",
    re.IGNORECASE,
)
SOURCE_ISSUE_TYPES = {
    "transcript_error",
    "video_misinterpreted",
    "citation_mismatch",
}


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


def atomic_write_json_bundle(payloads):
    originals = {}
    staged = {}
    replaced = []
    try:
        for raw_path, payload in payloads.items():
            path = Path(raw_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            originals[path] = path.read_bytes() if path.exists() else None
            handle, temporary_name = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
            )
            with os.fdopen(handle, "w", encoding="utf-8") as file:
                json.dump(payload, file, ensure_ascii=False, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            staged[path] = Path(temporary_name)
        for path, temporary_path in staged.items():
            os.replace(temporary_path, path)
            replaced.append(path)
    except Exception:
        for path in reversed(replaced):
            original = originals[path]
            if original is None:
                path.unlink(missing_ok=True)
            else:
                handle, temporary_name = tempfile.mkstemp(
                    prefix=f".{path.name}.", suffix=".rollback", dir=path.parent
                )
                with os.fdopen(handle, "wb") as file:
                    file.write(original)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(temporary_name, path)
        raise
    finally:
        for temporary_path in staged.values():
            temporary_path.unlink(missing_ok=True)


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


def answer_context_sha256(question, videos):
    canonical = {
        "question": question.strip(),
        "videos": [
            {"ref": video["ref"], "video_id": video["video_id"]}
            for video in videos
        ],
    }
    serialized = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


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
        "turn_id": answer_id,
        "context_sha256": answer_context_sha256(question, videos),
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


def extract_intended_query(text):
    matched = INTENDED_QUERY_PATTERN.search(text or "")
    return matched.group(1).strip(" ，,；;：:") if matched else ""


def contains_video_pointer(text):
    return bool(extract_video_refs(text) or extract_video_ids(text))


def contrast_pattern(separators):
    parts = []
    for separator in sorted(separators, key=len, reverse=True):
        escaped = re.escape(separator)
        if separator.isascii() and separator.isalpha():
            parts.append(rf"\b{escaped}\b")
        elif separator == "但":
            parts.append(r"(?<!不)但")
        else:
            parts.append(escaped)
    return re.compile(r"\s*(?:" + "|".join(parts) + r")\s*", re.IGNORECASE)


def split_feedback_clauses(feedback_text, rules):
    clauses = []
    separator_pattern = contrast_pattern(rules.get("contrast_separators", []))
    hard_clauses = filter(
        None, (part.strip() for part in CLAUSE_SPLIT_PATTERN.split(feedback_text or ""))
    )
    for clause in hard_clauses:
        contrast_parts = [part.strip() for part in separator_pattern.split(clause)]
        contrast_parts = [part for part in contrast_parts if part]
        if len(contrast_parts) > 1 and all(
            contains_video_pointer(part) for part in contrast_parts
        ):
            clauses.extend(contrast_parts)
        else:
            clauses.append(clause)
    return clauses


def parse_feedback_text(feedback_text, answer, rules):
    ref_to_id = {video["ref"]: video["video_id"] for video in answer["videos"]}
    id_to_ref = {video_id: reference for reference, video_id in ref_to_id.items()}
    all_refs = set(extract_video_refs(feedback_text))
    unknown_refs = sorted(all_refs - set(ref_to_id), key=ref_sort_key)
    helpful_refs = []
    irrelevant_refs = []
    missing_video_ids = []
    warnings = []
    clause_assignments = []

    for clause in split_feedback_clauses(feedback_text, rules):
        refs = extract_video_refs(clause)
        direct_ids = extract_video_ids(clause)
        is_negative = cue_in_text(clause, rules["negative_video_cues"])
        is_positive = cue_in_text(clause, rules["positive_video_cues"])
        is_missing = cue_in_text(clause, rules["missing_video_cues"])

        known_refs = [reference for reference in refs if reference in ref_to_id]
        presented_direct_refs = [
            id_to_ref[video_id] for video_id in direct_ids if video_id in id_to_ref
        ]
        labeled_refs = unique_in_order(known_refs + presented_direct_refs)
        is_comparative = cue_in_text(
            clause, rules.get("comparative_video_cues", [])
        ) and len(labeled_refs) >= 2
        is_mixed = is_negative and is_positive

        if is_comparative:
            polarity = "comparative"
            warnings.append("comparative_video_clause:" + ",".join(labeled_refs))
        elif is_mixed:
            polarity = "mixed"
            warnings.append("mixed_video_sentiment_clause:" + ",".join(labeled_refs))
        elif is_negative:
            polarity = "negative"
            irrelevant_refs.extend(known_refs)
        elif is_positive:
            polarity = "positive"
            helpful_refs.extend(known_refs)
        else:
            polarity = "none"

        for video_id in direct_ids:
            if video_id in id_to_ref:
                if polarity == "negative":
                    irrelevant_refs.append(id_to_ref[video_id])
                elif polarity == "positive":
                    helpful_refs.append(id_to_ref[video_id])
            elif is_missing or is_positive:
                missing_video_ids.append(video_id)
            elif is_negative:
                warnings.append("unpresented_negative_video_id:" + video_id)

        if is_missing:
            missing_video_ids.extend(
                video_id for video_id in direct_ids if video_id not in id_to_ref
            )

        clause_assignments.append(
            {
                "text": clause,
                "video_refs": refs,
                "video_ids": direct_ids,
                "polarity": polarity,
                "missing_video": is_missing,
            }
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
    intended_query = extract_intended_query(feedback_text)
    source_issue_refs = []
    source_issue_ids = []
    for assignment in clause_assignments:
        matched_source_types = [
            issue_type
            for issue_type in SOURCE_ISSUE_TYPES
            if issue_type in text_issue_types
            and cue_in_text(assignment["text"], rules["text_issue_cues"][issue_type])
        ]
        assignment["source_issue_types"] = sorted(matched_source_types)
        if not matched_source_types:
            continue
        known_refs = [
            reference
            for reference in assignment["video_refs"]
            if reference in ref_to_id
        ]
        source_issue_refs.extend(known_refs)
        source_issue_ids.extend(ref_to_id[reference] for reference in known_refs)
        source_issue_ids.extend(assignment["video_ids"])
    source_issue_refs = sorted(set(source_issue_refs), key=ref_sort_key)
    source_issue_ids = unique_in_order(source_issue_ids)
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

    if unknown_refs:
        warnings.append("unknown_video_refs:" + ",".join(unknown_refs))
    if conflicts:
        warnings.append("conflicting_video_refs:" + ",".join(conflicts))
    if "question_misunderstood" in text_issue_types and not intended_query:
        warnings.append("missing_intended_query")
    if SOURCE_ISSUE_TYPES.intersection(text_issue_types) and not source_issue_ids:
        warnings.append("missing_source_issue_video")

    signals = {
        "helpful_video_refs": helpful_refs,
        "helpful_video_ids": [ref_to_id[reference] for reference in helpful_refs],
        "irrelevant_video_refs": irrelevant_refs,
        "irrelevant_video_ids": [ref_to_id[reference] for reference in irrelevant_refs],
        "missing_video_ids": missing_video_ids,
        "text_issue_types": text_issue_types,
        "intended_query": intended_query or None,
        "source_issue_video_refs": source_issue_refs,
        "source_issue_video_ids": source_issue_ids,
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
        "clause_assignments": clause_assignments,
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
    turn_id = answer.get("turn_id", answer_id)
    if turn_id != answer_id:
        raise ValueError("Answer context turn ID does not match its answer ID")
    expected_digest = answer_context_sha256(answer["question"], answer["videos"])
    stored_digest = answer.get("context_sha256")
    if stored_digest and stored_digest != expected_digest:
        raise ValueError("Answer context mapping failed its integrity check")
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
        "turn_id": turn_id,
        "answer_context_sha256": stored_digest or expected_digest,
        "skill_version": answer["skill_version"],
        "channel": answer["channel"],
        "question": answer["question"],
        "user_context": answer["user_context"],
        "answer_mode": answer["answer_mode"],
        "knowledge_version": answer["knowledge_version"],
        "presented_videos": answer["videos"],
        "signals": parsed["signals"],
        "clause_assignments": parsed["clause_assignments"],
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
    if payload.get("status") == "superseded" or payload.get("superseded_by"):
        raise ValueError("Superseded feedback revisions cannot be reviewed")
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
    payload.get("source", {}).pop("promotion_verification", None)
    atomic_write_json(target_dir / "queue" / f"{feedback_id}.json", payload)
    return {
        **payload,
        "next_action": (
            "eligible_for_future_promotion_after_evidence_review"
            if decision == "accepted"
            else "no_automatic_retrieval_change"
        ),
    }


def github_video_lines(video_ids):
    if not video_ids:
        return "无"
    return "\n".join(
        f"- https://www.douyin.com/video/{video_id} (`{video_id}`)"
        for video_id in video_ids
    )


def body_sha256(body):
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def github_ssl_context():
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def fetch_with_curl(api_url, headers):
    if not shutil.which("curl"):
        raise ValueError("GitHub TLS verification failed and curl is unavailable")

    def escaped(value):
        return str(value).replace("\\", "\\\\").replace('"', '\\"')

    config_lines = [
        f'url = "{escaped(api_url)}"',
        "fail",
        "silent",
        "show-error",
        "location",
        "max-time = 20",
    ]
    config_lines.extend(
        f'header = "{escaped(name)}: {escaped(value)}"'
        for name, value in headers.items()
    )
    result = subprocess.run(
        ["curl", "--config", "-"],
        input="\n".join(config_lines) + "\n",
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise ValueError("GitHub issue lookup failed via curl: " + result.stderr.strip())
    return result.stdout.encode("utf-8")


def fetch_github_issue(issue_url, token=None, opener=None):
    match = GITHUB_ISSUE_PATTERN.fullmatch(issue_url.strip())
    if not match:
        raise ValueError(
            "GitHub feedback must use an issue from " + GITHUB_REPOSITORY
        )
    issue_number = int(match.group(1))
    api_url = (
        f"https://api.github.com/repos/{GITHUB_REPOSITORY}/issues/{issue_number}"
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "liuhui-badminton-coach-feedback",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    github_token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"
    request = urllib.request.Request(api_url, headers=headers)
    try:
        if opener:
            with opener(request, timeout=20) as response:
                response_body = response.read()
        else:
            with urllib.request.urlopen(
                request,
                timeout=20,
                context=github_ssl_context(),
            ) as response:
                response_body = response.read()
    except urllib.error.HTTPError as error:
        raise ValueError(
            f"GitHub issue lookup failed with HTTP {error.code}"
        ) from error
    except urllib.error.URLError as error:
        if not opener and isinstance(error.reason, ssl.SSLCertVerificationError):
            response_body = fetch_with_curl(api_url, headers)
        else:
            raise ValueError(f"GitHub issue lookup failed: {error.reason}") from error
    try:
        issue = json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("GitHub issue API returned invalid JSON") from error

    canonical_url = issue_url.strip().rstrip("/")
    if issue.get("html_url", "").rstrip("/") != canonical_url:
        raise ValueError("GitHub API response does not match the requested issue")
    if "pull_request" in issue:
        raise ValueError("Pull requests cannot be imported as Skill feedback")
    body = issue.get("body") or ""
    if not body.strip():
        raise ValueError("GitHub feedback issue body is empty")
    verification = {
        "method": "github_api",
        "repository": GITHUB_REPOSITORY,
        "issue_number": issue_number,
        "node_id": issue.get("node_id"),
        "state": issue.get("state"),
        "source_updated_at": issue.get("updated_at"),
        "body_sha256": body_sha256(body),
        "verified_at": utc_now(),
    }
    return body, verification


def export_github_feedback(
    feedback_id,
    public_question,
    public_intended_query=None,
    confirm_public=False,
    queue_dir=None,
):
    if not confirm_public:
        raise ValueError("Explicit --confirm-public consent is required")
    if not public_question.strip():
        raise ValueError("A sanitized public question is required")
    target_dir = Path(queue_dir or default_queue_dir())
    payload = show_feedback(feedback_id, target_dir)
    if payload.get("status") != "accepted":
        raise ValueError("Only accepted local feedback can be exported to GitHub")
    if payload.get("source", {}).get("type") != "local":
        raise ValueError("Only local feedback records can be exported")

    issue_labels = {
        "missing_content": "文字内容有遗漏",
        "incorrect_claim": "存在错误结论",
        "too_vague": "过于笼统",
        "too_verbose": "过于冗长",
        "hard_to_apply": "难以执行",
        "scenario_mismatch": "不适合提问场景",
        "question_misunderstood": "问题理解错误",
        "transcript_error": "视频转写错误",
        "video_misinterpreted": "视频含义解释错误",
        "citation_mismatch": "引用与结论不匹配",
    }
    signals = payload["signals"]
    issue_types = [
        issue_labels[issue_type]
        for issue_type in signals.get("text_issue_types", [])
        if issue_type in issue_labels
    ]
    sanitized_intended_query = (
        str(public_intended_query or "").strip() or public_question.strip()
        if "question_misunderstood" in signals.get("text_issue_types", [])
        else "无"
    )
    issue_body = f"""### 用户问题
{public_question.strip()}

### 用户真实意图
{sanitized_intended_query}

### 回答编号
{payload.get('answer_id') or '无'}

### 最有价值的视频
{github_video_lines(signals.get('helpful_video_ids', []))}

### 明确不相关的视频
{github_video_lines(signals.get('irrelevant_video_ids', []))}

### 遗漏的视频
{github_video_lines(signals.get('missing_video_ids', []))}

### 需重新核对的视频
{github_video_lines(signals.get('source_issue_video_ids', []))}

### 文字回答问题
{chr(10).join(f'- {label}' for label in issue_types) if issue_types else '没有明显问题'}

### 补充说明
本地反馈已脱敏导出；原始问题和原始反馈未包含在此正文中。

### 版本信息
{payload.get('skill_version', 'unknown')}

### 隐私确认
已确认此脱敏内容可以公开提交到 GitHub。
"""
    exported_at = utc_now()
    payload["share_upstream"] = True
    payload["updated_at"] = exported_at
    payload["github_export"] = {
        "exported_at": exported_at,
        "public_question": public_question.strip(),
        "uploaded": False,
    }
    atomic_write_json(target_dir / "queue" / f"{feedback_id}.json", payload)
    return {
        "feedback_id": feedback_id,
        "issue_title": f"[Skill Feedback] {public_question.strip()[:60]}",
        "issue_body": issue_body,
        "submit_url": GITHUB_ISSUE_URL,
        "uploaded": False,
        "privacy": {
            "raw_feedback_included": False,
            "original_question_included": False,
            "explicit_public_consent": True,
            "intended_query_was_explicitly_provided": bool(public_intended_query),
        },
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


def source_body_sha256(payload):
    source = payload.get("source", {})
    return source.get("body_sha256") or source.get("verification", {}).get(
        "body_sha256"
    )


def github_imports_for_source(target_dir, source_url):
    imports = []
    for path in (Path(target_dir) / "queue").glob("*.json"):
        payload = load_json(path)
        source = payload.get("source", {})
        if source.get("type") != "github_issue":
            continue
        if str(source.get("reference", "")).rstrip("/") == source_url.rstrip("/"):
            imports.append(payload)
    return sorted(
        imports,
        key=lambda item: (
            item.get("source", {}).get("revision_number", 1),
            item.get("created_at", ""),
        ),
    )


def github_feedback_id(source_url, body_hash, source_verification=None):
    source_identity = (source_verification or {}).get("node_id") or source_url
    digest = hashlib.sha256(
        f"{source_identity}|{body_hash}".encode("utf-8")
    ).hexdigest()[:16]
    return f"G-{digest}"


def import_github_issue(body, source_url, queue_dir=None, source_verification=None):
    target_dir = Path(queue_dir or default_queue_dir())
    source_url = source_url.strip().rstrip("/")
    knowledge, rules = load_resources()
    if source_verification:
        if source_verification.get("body_sha256") != body_sha256(body):
            raise ValueError("GitHub verification hash does not match the imported body")
        match = GITHUB_ISSUE_PATTERN.fullmatch(source_url)
        if not match:
            raise ValueError("Verified feedback must use the canonical repository")
        if source_verification.get("method") != "github_api":
            raise ValueError("Verified feedback must come from the GitHub API")
        if source_verification.get("repository") != GITHUB_REPOSITORY:
            raise ValueError("Verified feedback repository does not match")
        if source_verification.get("issue_number") != int(match.group(1)):
            raise ValueError("Verified feedback issue number does not match")
    sections = {
        heading: normalize_issue_value(value)
        for heading, value in parse_issue_sections(body).items()
    }
    question = sections.get("用户问题", "")
    if not question:
        raise ValueError("GitHub issue is missing the 用户问题 section")

    body_hash = body_sha256(body)
    previous_imports = github_imports_for_source(target_dir, source_url)
    existing_revision = next(
        (
            payload
            for payload in previous_imports
            if source_body_sha256(payload) == body_hash
        ),
        None,
    )
    if existing_revision:
        return {**existing_revision, "import_status": "already_imported"}
    previous_revision = previous_imports[-1] if previous_imports else None

    helpful_ids = extract_video_ids(sections.get("最有价值的视频", ""))
    irrelevant_ids = extract_video_ids(sections.get("明确不相关的视频", ""))
    missing_ids = extract_video_ids(sections.get("遗漏的视频", ""))
    source_issue_ids = extract_video_ids(sections.get("需重新核对的视频", ""))
    intended_query = normalize_issue_value(sections.get("用户真实意图", ""))
    text_issue_value = sections.get("文字回答问题", "")
    issue_labels = {
        "文字内容有遗漏": "missing_content",
        "存在错误结论": "incorrect_claim",
        "过于笼统": "too_vague",
        "过于冗长": "too_verbose",
        "难以执行": "hard_to_apply",
        "不适合提问场景": "scenario_mismatch",
        "问题理解错误": "question_misunderstood",
        "视频转写错误": "transcript_error",
        "视频含义解释错误": "video_misinterpreted",
        "引用与结论不匹配": "citation_mismatch",
    }
    text_issue_types = [
        issue_type
        for label, issue_type in issue_labels.items()
        if label in text_issue_value
    ]
    known_ids = {video["video_id"] for video in knowledge["videos"]}
    unknown_labeled_ids = unique_in_order(
        video_id
        for video_id in helpful_ids + irrelevant_ids + source_issue_ids
        if video_id not in known_ids
    )
    warnings = (
        ["unknown_labeled_video_ids:" + ",".join(unknown_labeled_ids)]
        if unknown_labeled_ids
        else []
    )
    if "question_misunderstood" in text_issue_types and not intended_query:
        warnings.append("missing_intended_query")
    if SOURCE_ISSUE_TYPES.intersection(text_issue_types) and not source_issue_ids:
        warnings.append("missing_source_issue_video")
    actionable = any([helpful_ids, irrelevant_ids, missing_ids, text_issue_types])
    if not actionable:
        warnings.append("no_actionable_signal")

    feedback_id = github_feedback_id(source_url, body_hash, source_verification)
    revision_number = (
        previous_revision.get("source", {}).get("revision_number", 1) + 1
        if previous_revision
        else 1
    )
    payload = {
        "schema_version": rules["version"],
        "feedback_id": feedback_id,
        "status": "needs_clarification" if warnings else "pending_review",
        "created_at": utc_now(),
        "updated_at": None,
        "source": {
            "type": "github_issue",
            "reference": source_url,
            "body_sha256": body_hash,
            "revision_number": revision_number,
            "revision_of": previous_revision.get("feedback_id") if previous_revision else None,
            **(
                {"verification": source_verification}
                if source_verification
                else {}
            ),
        },
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
            "intended_query": intended_query or None,
            "source_issue_video_refs": [],
            "source_issue_video_ids": source_issue_ids,
            "outcome": None,
        },
        "raw_feedback": sections.get("补充说明", ""),
        "share_upstream": True,
        "parser_warnings": warnings,
        "review_history": [],
        "promotion_status": "not_promoted",
        "import_status": "imported",
    }
    target_path = target_dir / "queue" / f"{feedback_id}.json"
    if previous_revision:
        previous_revision["status"] = "superseded"
        previous_revision["superseded_by"] = feedback_id
        previous_revision["updated_at"] = utc_now()
        previous_path = (
            target_dir / "queue" / f"{previous_revision['feedback_id']}.json"
        )
        atomic_write_json_bundle(
            {previous_path: previous_revision, target_path: payload}
        )
    else:
        atomic_write_json(target_path, payload)
    return payload


def fetch_and_import_github_issue(issue_url, queue_dir=None, token=None, opener=None):
    body, verification = fetch_github_issue(
        issue_url,
        token=token,
        opener=opener,
    )
    return import_github_issue(
        body=body,
        source_url=issue_url.strip().rstrip("/"),
        queue_dir=queue_dir,
        source_verification=verification,
    )


def reverify_github_feedback(feedback_id, queue_dir=None, token=None, opener=None):
    target_dir = Path(queue_dir or default_queue_dir())
    payload = show_feedback(feedback_id, target_dir)
    source = payload.get("source", {})
    issue_url = str(source.get("reference", "")).rstrip("/")
    if source.get("type") != "github_issue" or not GITHUB_ISSUE_PATTERN.fullmatch(
        issue_url
    ):
        raise ValueError("Only canonical GitHub issue feedback can be reverified")
    if payload.get("status") == "superseded" or payload.get("superseded_by"):
        raise ValueError("Superseded feedback revisions cannot be reverified")

    body, verification = fetch_github_issue(
        issue_url,
        token=token,
        opener=opener,
    )
    imported_hash = source_body_sha256(payload)
    if verification["body_sha256"] != imported_hash:
        replacement = import_github_issue(
            body=body,
            source_url=issue_url,
            queue_dir=target_dir,
            source_verification=verification,
        )
        return {
            "source_reverification_status": "source_changed",
            "superseded_feedback_id": feedback_id,
            "replacement": replacement,
        }

    original_verification = source.get("verification", {})
    if original_verification.get("node_id") and (
        verification.get("node_id") != original_verification["node_id"]
    ):
        raise ValueError("GitHub issue node ID changed during reverification")
    source["promotion_verification"] = {
        **verification,
        "matches_imported_body": True,
    }
    payload["source"] = source
    payload["updated_at"] = utc_now()
    atomic_write_json(target_dir / "queue" / f"{feedback_id}.json", payload)
    return {**payload, "source_reverification_status": "unchanged"}


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
        "review", help="Record a user confirmation or maintainer review decision."
    )
    review.add_argument("--feedback-id", required=True)
    review.add_argument(
        "--decision", required=True, choices=["accepted", "rejected", "needs_clarification"]
    )
    review.add_argument("--note", required=True)
    review.add_argument("--reviewer", default="local-maintainer")
    review.add_argument("--queue-dir", type=Path)

    import_issue = subparsers.add_parser(
        "import-github", help="Import or fetch a GitHub feedback issue."
    )
    import_source = import_issue.add_mutually_exclusive_group(required=True)
    import_source.add_argument("--body-file", type=Path)
    import_source.add_argument("--fetch-url")
    import_issue.add_argument("--source-url")
    import_issue.add_argument("--queue-dir", type=Path)

    reverify_issue = subparsers.add_parser(
        "reverify-github",
        help="Re-fetch a GitHub issue and bind its current revision to promotion.",
    )
    reverify_issue.add_argument("--feedback-id", required=True)
    reverify_issue.add_argument("--queue-dir", type=Path)

    export_issue = subparsers.add_parser(
        "export-github",
        help="Create a sanitized GitHub issue body from accepted local feedback.",
    )
    export_issue.add_argument("--feedback-id", required=True)
    export_issue.add_argument("--public-question", required=True)
    export_issue.add_argument("--public-intended-query")
    export_issue.add_argument("--confirm-public", action="store_true")
    export_issue.add_argument("--output", type=Path)
    export_issue.add_argument("--queue-dir", type=Path)

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
        elif args.command == "export-github":
            result = export_github_feedback(
                feedback_id=args.feedback_id,
                public_question=args.public_question,
                public_intended_query=args.public_intended_query,
                confirm_public=args.confirm_public,
                queue_dir=args.queue_dir,
            )
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(result["issue_body"], encoding="utf-8")
                result["output"] = str(args.output)
        elif args.command == "reverify-github":
            result = reverify_github_feedback(
                feedback_id=args.feedback_id,
                queue_dir=args.queue_dir,
            )
        else:
            if args.fetch_url:
                result = fetch_and_import_github_issue(
                    issue_url=args.fetch_url,
                    queue_dir=args.queue_dir,
                )
            else:
                if not args.source_url:
                    raise ValueError("--source-url is required with --body-file")
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
