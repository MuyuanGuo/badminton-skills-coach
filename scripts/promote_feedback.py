#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_PATH = ROOT / "data" / "knowledge" / "douyin_knowledge_base.json"
DEFAULT_SIGNALS_PATH = ROOT / "config" / "feedback_signals.json"
DEFAULT_SKILL_SIGNALS_PATH = (
    ROOT
    / "skills"
    / "liuhui-badminton-coach"
    / "references"
    / "feedback-signals.json"
)
DEFAULT_EVALUATION_PATH = (
    ROOT / "data" / "evaluation" / "feedback_relevance_cases.json"
)
DEFAULT_README_PATH = ROOT / "README.md"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def default_feedback_dir():
    override = os.environ.get("LIUHUI_FEEDBACK_DIR")
    if override:
        return Path(override).expanduser()
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    return codex_home / "feedback" / "liuhui-badminton-coach"


def load_json(path):
    with Path(path).open(encoding="utf-8") as file:
        return json.load(file)


def atomic_write_json(path, payload):
    path = Path(path)
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


def unique(items):
    return list(dict.fromkeys(items))


def build_signal_id(feedback_id, public_query):
    digest = hashlib.sha256(
        f"{feedback_id}|{public_query.strip()}".encode("utf-8")
    ).hexdigest()[:12]
    return f"P-{digest}"


def updated_readme_feedback_count(readme, promoted_count):
    note = "已通过公开来源、人工核证和回归测试"
    replacement = f"- 已晋升公共反馈信号：`{promoted_count}` 条（{note}）"
    updated, count = re.subn(
        r"^- 已晋升公共反馈信号：`\d+` 条（.*）$",
        replacement,
        readme,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise ValueError("README public feedback count line is missing or duplicated")
    return updated


def blocking_parser_warnings(feedback, ready_video_ids):
    blocking = []
    for warning in feedback.get("parser_warnings", []):
        if warning.startswith("unknown_labeled_video_ids:"):
            warning_ids = set(warning.split(":", 1)[1].split(","))
            if warning_ids.issubset(ready_video_ids):
                continue
        blocking.append(warning)
    return blocking


def validate_feedback_for_promotion(feedback, knowledge, public_query, evidence_note):
    if feedback.get("status") != "accepted":
        raise ValueError("Feedback must be accepted before promotion")
    if feedback.get("source", {}).get("type") != "github_issue":
        raise ValueError("Only feedback imported from a public GitHub issue can be promoted")
    source_reference = feedback.get("source", {}).get("reference", "")
    if not source_reference.startswith("https://github.com/"):
        raise ValueError("Promoted feedback must retain its public GitHub issue URL")
    if not public_query.strip():
        raise ValueError("A sanitized public query is required")
    if len(evidence_note.strip()) < 8:
        raise ValueError("Evidence note is too short to document human verification")
    review_history = feedback.get("review_history", [])
    if not review_history or review_history[-1].get("decision") != "accepted":
        raise ValueError("The latest human review decision must be accepted")

    ready_video_ids = {
        video["video_id"]
        for video in knowledge["videos"]
        if video["processing_status"] == "ready"
    }
    warnings = blocking_parser_warnings(feedback, ready_video_ids)
    if warnings:
        raise ValueError("Feedback still has blocking parser warnings: " + ", ".join(warnings))

    signals = feedback.get("signals", {})
    helpful_ids = unique(signals.get("helpful_video_ids", []))
    irrelevant_ids = unique(signals.get("irrelevant_video_ids", []))
    missing_ids = unique(signals.get("missing_video_ids", []))
    answer_issue_types = unique(signals.get("text_issue_types", []))
    positive_ids = set(helpful_ids) | set(missing_ids)
    conflicts = positive_ids & set(irrelevant_ids)
    if conflicts:
        raise ValueError(
            "The same video cannot be promoted as both positive and irrelevant: "
            + ", ".join(sorted(conflicts))
        )
    referenced_ids = positive_ids | set(irrelevant_ids)
    unavailable = sorted(referenced_ids - ready_video_ids)
    if unavailable:
        raise ValueError(
            "Promoted videos must already be ready in the knowledge base: "
            + ", ".join(unavailable)
        )
    if not referenced_ids and not answer_issue_types:
        raise ValueError("Feedback has no promotable relevance or answer-quality signal")
    return {
        "helpful_video_ids": helpful_ids,
        "irrelevant_video_ids": irrelevant_ids,
        "missing_video_ids": missing_ids,
        "answer_issue_types": answer_issue_types,
    }


def promote_feedback(
    feedback_id,
    public_query,
    evidence_note,
    promoted_by,
    queue_dir=None,
    signals_path=DEFAULT_SIGNALS_PATH,
    skill_signals_path=DEFAULT_SKILL_SIGNALS_PATH,
    evaluation_path=DEFAULT_EVALUATION_PATH,
    readme_path=None,
    dry_run=False,
):
    queue_dir = Path(queue_dir or default_feedback_dir())
    feedback_path = queue_dir / "queue" / f"{feedback_id}.json"
    if not feedback_path.exists():
        raise ValueError(f"Feedback record not found: {feedback_id}")
    feedback = load_json(feedback_path)
    knowledge = load_json(KNOWLEDGE_PATH)
    signals_payload = load_json(signals_path)
    evaluation_payload = load_json(evaluation_path)

    existing = next(
        (
            signal
            for signal in signals_payload["signals"]
            if signal["source_feedback_id"] == feedback_id
        ),
        None,
    )
    if existing:
        return {
            "status": "already_promoted",
            "signal": existing,
            "feedback_id": feedback_id,
        }

    values = validate_feedback_for_promotion(
        feedback,
        knowledge,
        public_query,
        evidence_note,
    )
    promoted_at = utc_now()
    signal_id = build_signal_id(feedback_id, public_query)
    signal = {
        "signal_id": signal_id,
        "source_feedback_id": feedback_id,
        "source_type": "github_issue",
        "source_reference": feedback["source"]["reference"],
        "public_query": public_query.strip(),
        **values,
        "evidence_note": evidence_note.strip(),
        "promoted_by": promoted_by.strip() or "maintainer",
        "promoted_at": promoted_at,
    }
    evaluation_case = {
        "case_id": signal_id,
        "query": signal["public_query"],
        "expected_positive_video_ids": unique(
            signal["helpful_video_ids"] + signal["missing_video_ids"]
        ),
        "expected_negative_video_ids": signal["irrelevant_video_ids"],
        "expected_answer_reminders": signal["answer_issue_types"],
    }
    result = {
        "status": "dry_run" if dry_run else "promoted",
        "signal": signal,
        "evaluation_case": evaluation_case,
        "privacy": {
            "raw_feedback_included": False,
            "original_question_included": False,
            "public_query_was_explicitly_provided": True,
        },
    }
    if dry_run:
        return result

    signals_payload["signals"].append(signal)
    signals_payload["signals"].sort(key=lambda item: item["signal_id"])
    signals_payload["updated_at"] = promoted_at
    evaluation_payload["cases"].append(evaluation_case)
    evaluation_payload["cases"].sort(key=lambda item: item["case_id"])

    readme_updated = None
    if readme_path:
        readme_path = Path(readme_path)
        readme_updated = updated_readme_feedback_count(
            readme_path.read_text(encoding="utf-8"),
            len(signals_payload["signals"]),
        )

    atomic_write_json(signals_path, signals_payload)
    atomic_write_json(skill_signals_path, signals_payload)
    atomic_write_json(evaluation_path, evaluation_payload)
    if readme_path:
        readme_path.write_text(readme_updated, encoding="utf-8")

    feedback["promotion_status"] = "promoted"
    feedback["promotion"] = {
        "signal_id": signal_id,
        "public_query": signal["public_query"],
        "promoted_by": signal["promoted_by"],
        "promoted_at": promoted_at,
    }
    feedback["updated_at"] = promoted_at
    atomic_write_json(feedback_path, feedback)
    return result


def build_parser():
    parser = argparse.ArgumentParser(
        description="Promote accepted GitHub feedback into public Skill signals and regression cases."
    )
    parser.add_argument("--feedback-id", required=True)
    parser.add_argument("--public-query", required=True)
    parser.add_argument("--evidence-note", required=True)
    parser.add_argument("--promoted-by", default="maintainer")
    parser.add_argument("--queue-dir", type=Path)
    parser.add_argument("--signals-path", type=Path, default=DEFAULT_SIGNALS_PATH)
    parser.add_argument(
        "--skill-signals-path", type=Path, default=DEFAULT_SKILL_SIGNALS_PATH
    )
    parser.add_argument(
        "--evaluation-path", type=Path, default=DEFAULT_EVALUATION_PATH
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main():
    args = build_parser().parse_args()
    uses_repository_outputs = all(
        path.resolve() == expected.resolve()
        for path, expected in [
            (args.signals_path, DEFAULT_SIGNALS_PATH),
            (args.skill_signals_path, DEFAULT_SKILL_SIGNALS_PATH),
            (args.evaluation_path, DEFAULT_EVALUATION_PATH),
        ]
    )
    try:
        result = promote_feedback(
            feedback_id=args.feedback_id,
            public_query=args.public_query,
            evidence_note=args.evidence_note,
            promoted_by=args.promoted_by,
            queue_dir=args.queue_dir,
            signals_path=args.signals_path,
            skill_signals_path=args.skill_signals_path,
            evaluation_path=args.evaluation_path,
            readme_path=(
                DEFAULT_README_PATH
                if uses_repository_outputs and not args.dry_run
                else None
            ),
            dry_run=args.dry_run,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
