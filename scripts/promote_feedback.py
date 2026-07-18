#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised on Windows only
    fcntl = None


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
GITHUB_REPOSITORY = "MuyuanGuo/badminton-skills-coach"
GITHUB_ISSUE_PATTERN = re.compile(
    r"^https://github\.com/MuyuanGuo/badminton-skills-coach/issues/([1-9]\d*)/?$"
)


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


def json_bytes(payload):
    return (
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")


def atomic_write_bytes(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def atomic_write_bundle(writes, replace_func=None):
    replace = replace_func or os.replace
    originals = {}
    staged = {}
    replaced = []
    try:
        for raw_path, content in writes.items():
            path = Path(raw_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            originals[path] = path.read_bytes() if path.exists() else None
            handle, temporary_name = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
            )
            with os.fdopen(handle, "wb") as file:
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
            staged[path] = Path(temporary_name)

        for path, temporary_path in staged.items():
            replace(str(temporary_path), str(path))
            replaced.append(path)
    except Exception:
        for path in reversed(replaced):
            original = originals[path]
            if original is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write_bytes(path, original)
        raise
    finally:
        for temporary_path in staged.values():
            temporary_path.unlink(missing_ok=True)


@contextmanager
def exclusive_promotion_lock(lock_path):
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        else:  # pragma: no cover - exercised on Windows only
            import msvcrt

            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write("0")
                lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            else:  # pragma: no cover - exercised on Windows only
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


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
    if feedback.get("status") == "superseded" or feedback.get("superseded_by"):
        raise ValueError("Superseded feedback revisions cannot be promoted")
    if feedback.get("status") != "accepted":
        raise ValueError("Feedback must be accepted before promotion")
    if feedback.get("source", {}).get("type") != "github_issue":
        raise ValueError("Only feedback imported from a public GitHub issue can be promoted")
    source_reference = feedback.get("source", {}).get("reference", "")
    issue_match = GITHUB_ISSUE_PATTERN.fullmatch(source_reference)
    if not issue_match:
        raise ValueError(
            "Promoted feedback must use an issue from " + GITHUB_REPOSITORY
        )
    verification = feedback.get("source", {}).get("verification", {})
    if (
        verification.get("method") != "github_api"
        or verification.get("repository") != GITHUB_REPOSITORY
        or verification.get("issue_number") != int(issue_match.group(1))
        or not verification.get("node_id")
        or not verification.get("verified_at")
        or not re.fullmatch(r"[0-9a-f]{64}", verification.get("body_sha256", ""))
    ):
        raise ValueError("GitHub issue source has not been verified through the API")
    promotion_verification = feedback.get("source", {}).get(
        "promotion_verification", {}
    )
    if (
        promotion_verification.get("method") != "github_api"
        or promotion_verification.get("repository") != GITHUB_REPOSITORY
        or promotion_verification.get("issue_number") != int(issue_match.group(1))
        or promotion_verification.get("node_id") != verification.get("node_id")
        or promotion_verification.get("body_sha256")
        != verification.get("body_sha256")
        or not promotion_verification.get("matches_imported_body")
        or not promotion_verification.get("verified_at")
    ):
        raise ValueError(
            "GitHub issue must be reverified through the API after maintainer review"
        )
    if not public_query.strip():
        raise ValueError("A sanitized public query is required")
    if len(evidence_note.strip()) < 8:
        raise ValueError("Evidence note is too short to document human verification")
    review_history = feedback.get("review_history", [])
    if not review_history or review_history[-1].get("decision") != "accepted":
        raise ValueError("The latest maintainer review decision must be accepted")
    try:
        reviewed_at = datetime.fromisoformat(
            review_history[-1]["reviewed_at"].replace("Z", "+00:00")
        )
        reverified_at = datetime.fromisoformat(
            promotion_verification["verified_at"].replace("Z", "+00:00")
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Feedback review or reverification timestamp is invalid") from error
    if reverified_at < reviewed_at:
        raise ValueError(
            "GitHub issue must be reverified through the API after maintainer review"
        )

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
    intended_query = str(signals.get("intended_query") or "").strip() or None
    source_issue_video_ids = unique(signals.get("source_issue_video_ids", []))
    source_issue_types = {
        "transcript_error",
        "video_misinterpreted",
        "citation_mismatch",
    }
    if "question_misunderstood" in answer_issue_types and not intended_query:
        raise ValueError("Question-misunderstanding feedback needs an intended query")
    if source_issue_types.intersection(answer_issue_types) and not source_issue_video_ids:
        raise ValueError("Source-quality feedback needs at least one source video ID")
    positive_ids = set(helpful_ids) | set(missing_ids)
    conflicts = positive_ids & set(irrelevant_ids)
    if conflicts:
        raise ValueError(
            "The same video cannot be promoted as both positive and irrelevant: "
            + ", ".join(sorted(conflicts))
        )
    referenced_ids = positive_ids | set(irrelevant_ids) | set(source_issue_video_ids)
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
        "intended_query": intended_query,
        "source_issue_video_ids": source_issue_video_ids,
        "source_issue_node_id": promotion_verification["node_id"],
        "source_updated_at": promotion_verification.get("source_updated_at"),
        "source_reverified_at": promotion_verification["verified_at"],
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
    replace_existing=False,
):
    queue_dir = Path(queue_dir or default_feedback_dir())
    feedback_path = queue_dir / "queue" / f"{feedback_id}.json"
    if not feedback_path.exists():
        raise ValueError(f"Feedback record not found: {feedback_id}")
    signals_path = Path(signals_path)
    skill_signals_path = Path(skill_signals_path)
    evaluation_path = Path(evaluation_path)
    readme_path = Path(readme_path) if readme_path else None
    lock_key = hashlib.sha256(
        str(signals_path.resolve()).encode("utf-8")
    ).hexdigest()[:20]
    lock_path = (
        Path(tempfile.gettempdir())
        / "liuhui-feedback-promotion"
        / f"{lock_key}.lock"
    )

    with exclusive_promotion_lock(lock_path):
        feedback = load_json(feedback_path)
        knowledge = load_json(KNOWLEDGE_PATH)
        signals_payload = load_json(signals_path)
        evaluation_payload = load_json(evaluation_path)
        values = validate_feedback_for_promotion(
            feedback,
            knowledge,
            public_query,
            evidence_note,
        )
        existing_by_feedback = next(
            (
                signal
                for signal in signals_payload["signals"]
                if signal["source_feedback_id"] == feedback_id
            ),
            None,
        )
        source_reference = feedback["source"]["reference"].rstrip("/")
        existing_by_source = [
            signal
            for signal in signals_payload["signals"]
            if signal.get("source_reference", "").rstrip("/") == source_reference
        ]
        if len(existing_by_source) > 1:
            raise ValueError("Public feedback signals contain duplicate GitHub sources")
        existing_source = existing_by_source[0] if existing_by_source else None
        existing = existing_by_feedback or existing_source
        same_revision = existing and (
            existing.get("source_body_sha256")
            == feedback["source"]["verification"]["body_sha256"]
        )
        if existing and same_revision:
            if not dry_run and feedback.get("promotion_status") != "promoted":
                feedback["promotion_status"] = "promoted"
                feedback["promotion"] = {
                    "signal_id": existing["signal_id"],
                    "public_query": existing["public_query"],
                    "promoted_by": existing["promoted_by"],
                    "promoted_at": existing["promoted_at"],
                }
                feedback["updated_at"] = utc_now()
                atomic_write_json(feedback_path, feedback)
            return {
                "status": "already_promoted",
                "signal": existing,
                "feedback_id": feedback_id,
            }
        if existing_source and not same_revision and not replace_existing:
            raise ValueError(
                "This GitHub issue already has a promoted older revision; "
                "use --replace-existing after reviewing the new revision"
            )
        promoted_at = utc_now()
        signal_id = (
            existing_source["signal_id"]
            if existing_source and replace_existing
            else build_signal_id(feedback_id, public_query)
        )
        signal = {
            "signal_id": signal_id,
            "source_feedback_id": feedback_id,
            "source_type": "github_issue",
            "source_reference": feedback["source"]["reference"],
            "source_body_sha256": feedback["source"]["verification"][
                "body_sha256"
            ],
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
            "expected_intended_query": signal["intended_query"],
            "expected_source_issue_video_ids": signal["source_issue_video_ids"],
        }
        result = {
            "status": (
                "dry_run"
                if dry_run
                else "replaced"
                if existing_source and replace_existing
                else "promoted"
            ),
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

        if existing_source and replace_existing:
            signals_payload["signals"] = [
                item
                for item in signals_payload["signals"]
                if item["signal_id"] != existing_source["signal_id"]
            ]
            evaluation_payload["cases"] = [
                item
                for item in evaluation_payload["cases"]
                if item["case_id"] != existing_source["signal_id"]
            ]
        signals_payload["signals"].append(signal)
        signals_payload["signals"].sort(key=lambda item: item["signal_id"])
        signals_payload["updated_at"] = promoted_at
        evaluation_payload["cases"].append(evaluation_case)
        evaluation_payload["cases"].sort(key=lambda item: item["case_id"])

        writes = {
            signals_path: json_bytes(signals_payload),
            skill_signals_path: json_bytes(signals_payload),
            evaluation_path: json_bytes(evaluation_payload),
        }
        if readme_path:
            readme_updated = updated_readme_feedback_count(
                readme_path.read_text(encoding="utf-8"),
                len(signals_payload["signals"]),
            )
            writes[readme_path] = readme_updated.encode("utf-8")
        atomic_write_bundle(writes)

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
    parser.add_argument(
        "--replace-existing",
        action="store_true",
        help="Replace the older promoted revision from the same GitHub issue.",
    )
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
            replace_existing=args.replace_existing,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
