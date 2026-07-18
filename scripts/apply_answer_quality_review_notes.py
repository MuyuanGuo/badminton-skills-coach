#!/usr/bin/env python3
import argparse
import copy
import json
import os
import re
import tempfile
from pathlib import Path

from evaluate_answer_quality import (
    DATE_PATTERN,
    DEFAULT_CASES_PATH,
    DEFAULT_RULES_PATH,
    KNOWLEDGE_PATH,
    load_json,
    ready_video_ids,
    validate_registry,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MARKDOWN_PATH = ROOT / "output" / "answer_quality_review_queue.md"
CASE_SECTION_PATTERN = re.compile(
    r"^## (?P<case_id>AQ\d{3}) ·.*?(?=^## AQ\d{3} ·|\Z)",
    re.MULTILINE | re.DOTALL,
)
REVIEW_BLOCK_PATTERN = re.compile(
    r"^### Review notes\s*$.*?^```json\s*$\n(?P<payload>.*?)^```\s*$",
    re.MULTILINE | re.DOTALL,
)
REVIEW_HEADING_PATTERN = re.compile(r"^### Review notes\s*$", re.MULTILINE)
VIDEO_ID_PATTERN = re.compile(r"\d{18,20}")
REVIEW_FIELDS = {
    "maintainer_decision",
    "maintainer_reviewer",
    "maintainer_reviewed_at",
    "primary_video_ids",
    "required_video_ids",
    "irrelevant_video_ids",
    "required_text_points",
    "required_boundary_points",
    "forbidden_claims",
    "notes",
}


class ReviewApplicationError(ValueError):
    pass


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
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def extract_review_blocks(markdown_text):
    blocks = {}
    for section_match in CASE_SECTION_PATTERN.finditer(markdown_text):
        case_id = section_match.group("case_id")
        if case_id in blocks:
            raise ReviewApplicationError(f"Duplicate review section: {case_id}")
        block_match = REVIEW_BLOCK_PATTERN.search(section_match.group(0))
        if block_match:
            blocks[case_id] = block_match.group("payload").strip()
            continue

        # Migrate queues produced by the short-lived legacy format that emitted
        # a bare JSON object without a fenced block.
        heading_match = REVIEW_HEADING_PATTERN.search(section_match.group(0))
        legacy_body = (
            section_match.group(0)[heading_match.end() :].strip()
            if heading_match
            else ""
        )
        if legacy_body.startswith("{"):
            try:
                _, end = json.JSONDecoder().raw_decode(legacy_body)
            except json.JSONDecodeError:
                end = 0
            if end and not legacy_body[end:].strip():
                blocks[case_id] = legacy_body[:end]
                continue
        raise ReviewApplicationError(f"Missing structured Review notes: {case_id}")
    return blocks


def review_data_from_case(case):
    review = case["review"]
    gold = case["gold"]
    status = review["status"]
    maintainer_decision = review.get(
        "maintainer_decision", "approved" if status != "draft" else "pending"
    )
    return {
        "maintainer_decision": maintainer_decision,
        "maintainer_reviewer": review.get("maintainer_reviewer", ""),
        "maintainer_reviewed_at": review.get("reviewed_at", ""),
        "primary_video_ids": gold["primary_video_ids"],
        "required_video_ids": gold["required_video_ids"],
        "irrelevant_video_ids": gold["irrelevant_video_ids"],
        "required_text_points": [
            {
                "description": point["description"],
                "acceptable_terms": point["acceptable_terms"],
                "evidence_video_ids": point["evidence_video_ids"],
            }
            for point in gold["required_text_points"]
        ],
        "required_boundary_points": [
            {
                "description": point["description"],
                "acceptable_terms": point["acceptable_terms"],
            }
            for point in gold["required_boundary_points"]
        ],
        "forbidden_claims": gold["forbidden_claims"],
        "notes": review.get("notes", ""),
    }


def render_review_payload(payload):
    return (
        "请只编辑下面 JSON 中的值；视频填写 18-20 位 ID，日期使用 `YYYY-MM-DD`。\n\n"
        "```json\n"
        f"{payload.strip()}\n"
        "```"
    )


def render_review_block(case):
    payload = json.dumps(
        review_data_from_case(case), ensure_ascii=False, indent=2
    )
    return render_review_payload(payload)


def normalized_string_list(value, field, case_id, allow_empty=True):
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ReviewApplicationError(f"{case_id} {field} must be a string list")
    normalized = list(dict.fromkeys(item.strip() for item in value))
    if len(normalized) != len(value):
        raise ReviewApplicationError(f"{case_id} {field} contains duplicates")
    if not allow_empty and not normalized:
        raise ReviewApplicationError(f"{case_id} {field} cannot be empty")
    return normalized


def normalized_video_ids(value, field, case_id, ready_ids):
    video_ids = normalized_string_list(value, field, case_id)
    invalid = [video_id for video_id in video_ids if not VIDEO_ID_PATTERN.fullmatch(video_id)]
    if invalid:
        raise ReviewApplicationError(
            f"{case_id} {field} contains invalid video IDs: {', '.join(invalid)}"
        )
    unavailable = sorted(set(video_ids) - ready_ids)
    if unavailable:
        raise ReviewApplicationError(
            f"{case_id} {field} references non-ready videos: {', '.join(unavailable)}"
        )
    return video_ids


def normalized_points(value, field, case_id, ready_ids, boundary=False):
    expected_fields = {"description", "acceptable_terms"}
    if not boundary:
        expected_fields.add("evidence_video_ids")
    if not isinstance(value, list):
        raise ReviewApplicationError(f"{case_id} {field} must be a list")
    points = []
    for index, point in enumerate(value, start=1):
        if not isinstance(point, dict) or set(point) != expected_fields:
            raise ReviewApplicationError(
                f"{case_id} {field}[{index}] has an invalid schema"
            )
        description = str(point["description"]).strip()
        if not description:
            raise ReviewApplicationError(
                f"{case_id} {field}[{index}] needs a description"
            )
        acceptable_terms = normalized_string_list(
            point["acceptable_terms"],
            f"{field}[{index}].acceptable_terms",
            case_id,
            allow_empty=False,
        )
        normalized = {
            "point_id": f"{case_id}-{'B' if boundary else 'P'}{index}",
            "description": description,
            "acceptable_terms": acceptable_terms,
        }
        if not boundary:
            normalized["evidence_video_ids"] = normalized_video_ids(
                point["evidence_video_ids"],
                f"{field}[{index}].evidence_video_ids",
                case_id,
                ready_ids,
            )
            if not normalized["evidence_video_ids"]:
                raise ReviewApplicationError(
                    f"{case_id} {field}[{index}] needs video evidence"
                )
        points.append(normalized)
    return points


def apply_review_data(case, data, rules, ready_ids, all_video_ids=None):
    case_id = case["case_id"]
    if not isinstance(data, dict) or set(data) != REVIEW_FIELDS:
        raise ReviewApplicationError(f"{case_id} Review notes schema is invalid")
    maintainer_decision = data["maintainer_decision"]
    if maintainer_decision not in rules["maintainer_decisions"]:
        raise ReviewApplicationError(f"{case_id} has an invalid maintainer decision")
    for field in [
        "maintainer_reviewer",
        "maintainer_reviewed_at",
        "notes",
    ]:
        if not isinstance(data[field], str):
            raise ReviewApplicationError(f"{case_id} {field} must be a string")

    primary_ids = normalized_video_ids(
        data["primary_video_ids"], "primary_video_ids", case_id, ready_ids
    )
    required_ids = normalized_video_ids(
        data["required_video_ids"], "required_video_ids", case_id, ready_ids
    )
    irrelevant_ids = normalized_video_ids(
        data["irrelevant_video_ids"],
        "irrelevant_video_ids",
        case_id,
        all_video_ids or ready_ids,
    )
    if not set(primary_ids).issubset(required_ids):
        raise ReviewApplicationError(
            f"{case_id} primary videos must also be required videos"
        )
    if set(required_ids) & set(irrelevant_ids):
        raise ReviewApplicationError(
            f"{case_id} cannot keep and exclude the same video"
        )

    text_points = normalized_points(
        data["required_text_points"],
        "required_text_points",
        case_id,
        ready_ids,
    )
    boundary_points = normalized_points(
        data["required_boundary_points"],
        "required_boundary_points",
        case_id,
        ready_ids,
        boundary=True,
    )
    evidence_ids = {
        video_id
        for point in text_points
        for video_id in point["evidence_video_ids"]
    }
    if not evidence_ids.issubset(required_ids):
        raise ReviewApplicationError(
            f"{case_id} text-point evidence must be included in required_video_ids"
        )
    forbidden_claims = normalized_string_list(
        data["forbidden_claims"], "forbidden_claims", case_id
    )

    maintainer = data["maintainer_reviewer"].strip()
    maintained_at = data["maintainer_reviewed_at"].strip()
    notes = data["notes"].strip()
    if maintainer_decision in {"approved", "rejected"}:
        if not maintainer or not DATE_PATTERN.fullmatch(maintained_at):
            raise ReviewApplicationError(
                f"{case_id} decided maintainer review needs reviewer and YYYY-MM-DD date"
            )
    if maintainer_decision == "approved":
        if not (text_points or boundary_points):
            raise ReviewApplicationError(
                f"{case_id} approved review needs text or boundary points"
            )
        if case["case_type"] != "evidence_boundary" and not required_ids:
            raise ReviewApplicationError(
                f"{case_id} approved coaching case needs required video evidence"
            )
    review = {
        "status": "draft",
        "maintainer_decision": maintainer_decision,
        "notes": notes,
    }
    if maintainer_decision in {"approved", "rejected"}:
        review["maintainer_reviewer"] = maintainer
        review["reviewed_at"] = maintained_at
    if maintainer_decision == "approved":
        review["status"] = "maintainer_reviewed"
    case["review"] = review
    case["gold"] = {
        "primary_video_ids": primary_ids,
        "required_video_ids": required_ids,
        "irrelevant_video_ids": irrelevant_ids,
        "required_text_points": text_points,
        "required_boundary_points": boundary_points,
        "forbidden_claims": forbidden_claims,
    }


def apply_review_markdown(
    markdown_text, registry, rules, ready_ids, all_video_ids=None
):
    blocks = extract_review_blocks(markdown_text)
    case_ids = [case["case_id"] for case in registry["cases"]]
    missing = sorted(set(case_ids) - set(blocks))
    unknown = sorted(set(blocks) - set(case_ids))
    if missing or unknown:
        raise ReviewApplicationError(
            "Review queue and registry differ; "
            f"missing={missing or 'none'}, unknown={unknown or 'none'}"
        )
    updated = copy.deepcopy(registry)
    for case in updated["cases"]:
        try:
            data = json.loads(blocks[case["case_id"]])
        except json.JSONDecodeError as error:
            raise ReviewApplicationError(
                f"{case['case_id']} Review notes contain invalid JSON: {error.msg}"
            ) from error
        apply_review_data(
            case, data, rules, ready_ids, all_video_ids=all_video_ids
        )
    validate_registry(
        updated,
        rules,
        ready_ids,
        minimum_cases=len(case_ids),
        all_video_ids=all_video_ids,
    )
    return updated


def main():
    parser = argparse.ArgumentParser(
        description="Validate and atomically apply structured answer-quality reviews."
    )
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN_PATH)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES_PATH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    registry = load_json(args.cases)
    rules = load_json(args.rules)
    knowledge = load_json(KNOWLEDGE_PATH)
    ready_ids = ready_video_ids(knowledge)
    all_video_ids = {video["video_id"] for video in knowledge["videos"]}
    try:
        updated = apply_review_markdown(
            args.markdown.read_text(encoding="utf-8"),
            registry,
            rules,
            ready_ids,
            all_video_ids=all_video_ids,
        )
    except (OSError, KeyError, TypeError, ReviewApplicationError) as error:
        raise SystemExit(str(error)) from error
    counts = {}
    for case in updated["cases"]:
        status = case["review"]["status"]
        counts[status] = counts.get(status, 0) + 1
    result = {"validated_cases": len(updated["cases"]), "status_counts": counts}
    if not args.dry_run:
        atomic_write_json(args.cases, updated)
        result["written"] = str(args.cases)
    else:
        result["written"] = None
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
