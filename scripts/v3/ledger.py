"""Append-only review ledger with rebuildable current-state projections."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from v3 import SCHEMA_VERSION
from v3.canonical import canonical_json, sha256_json
from v3.state import entity_types, resolve_transition


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA = ROOT / "schemas" / "v3" / "review-ledger.sql"
ACTIVE_DEPENDENCY_STATES = {"source_verified", "domain_approved", "published"}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _require_sha256(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _require_nonempty(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def _coverage_is_complete(intervals: Any, duration_ms: int) -> bool:
    if not isinstance(intervals, list) or duration_ms < 0:
        return False
    if duration_ms == 0:
        return intervals == [] or intervals == [{"start_ms": 0, "end_ms": 0}]
    normalized: list[tuple[int, int]] = []
    for interval in intervals:
        if not isinstance(interval, dict):
            return False
        start = interval.get("start_ms")
        end = interval.get("end_ms")
        if not isinstance(start, int) or not isinstance(end, int):
            return False
        if start < 0 or end <= start or end > duration_ms:
            return False
        normalized.append((start, end))
    if not normalized:
        return False
    normalized.sort()
    covered_until = 0
    for start, end in normalized:
        if start > covered_until:
            return False
        covered_until = max(covered_until, end)
    return covered_until >= duration_ms


class ReviewLedger:
    """Private ledger. Formal decisions append; only projections and drafts mutate."""

    def __init__(self, path: Path, schema_path: Path = DEFAULT_SCHEMA):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA busy_timeout=5000")
        self.connection.executescript(schema_path.read_text(encoding="utf-8"))
        self.connection.execute(
            "INSERT OR IGNORE INTO metadata(key,value) VALUES (?,?)",
            ("schema_version", SCHEMA_VERSION),
        )
        self.connection.execute(
            "INSERT OR IGNORE INTO metadata(key,value) VALUES (?,?)",
            ("application_id", "badminton-skills-coach-v3-review-ledger"),
        )
        metadata = dict(self.connection.execute("SELECT key,value FROM metadata"))
        if metadata.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(
                "ledger schema version mismatch: "
                f"{metadata.get('schema_version')!r} != {SCHEMA_VERSION!r}"
            )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "ReviewLedger":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @staticmethod
    def _payload_parts(payload: dict[str, Any]) -> tuple[str, str]:
        if not isinstance(payload.get("content"), dict):
            raise ValueError("event payload requires a content object")
        payload_fingerprint = sha256_json(payload)
        content_fingerprint = sha256_json(payload["content"])
        supplied = payload.get("content_fingerprint")
        if supplied is not None and supplied != content_fingerprint:
            raise ValueError("supplied content fingerprint does not match content")
        return payload_fingerprint, content_fingerprint

    @staticmethod
    def _dependencies(payload: dict[str, Any]) -> list[dict[str, str]]:
        raw = payload.get("dependencies", [])
        if not isinstance(raw, list):
            raise ValueError("dependencies must be a list")
        dependencies: list[dict[str, str]] = []
        identities: set[tuple[str, str]] = set()
        for dependency in raw:
            if not isinstance(dependency, dict):
                raise ValueError("every dependency must be an object")
            if set(dependency) != {"entity_type", "entity_id", "fingerprint"}:
                raise ValueError("dependency fields must be exact")
            dependency_type = _require_nonempty(
                dependency.get("entity_type"), "dependency entity type"
            )
            dependency_id = _require_nonempty(
                dependency.get("entity_id"), "dependency entity id"
            )
            fingerprint = _require_sha256(
                dependency.get("fingerprint"), "dependency fingerprint"
            )
            if dependency_type not in entity_types():
                raise ValueError(f"unsupported dependency type: {dependency_type}")
            identity = (dependency_type, dependency_id)
            if identity in identities:
                raise ValueError(f"duplicate dependency: {identity}")
            identities.add(identity)
            dependencies.append(
                {
                    "entity_type": dependency_type,
                    "entity_id": dependency_id,
                    "fingerprint": fingerprint,
                }
            )
        dependencies.sort(key=lambda item: (item["entity_type"], item["entity_id"]))
        return dependencies

    def head(self, entity_type: str, entity_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM entity_heads WHERE entity_type=? AND entity_id=?",
            (entity_type, entity_id),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["payload"] = json.loads(result.pop("payload_json"))
        return result

    def heads(self, entity_type: str | None = None) -> list[dict[str, Any]]:
        if entity_type is None:
            rows = self.connection.execute(
                "SELECT * FROM entity_heads ORDER BY entity_type,entity_id"
            )
        else:
            rows = self.connection.execute(
                "SELECT * FROM entity_heads WHERE entity_type=? ORDER BY entity_id",
                (entity_type,),
            )
        results = []
        for row in rows:
            result = dict(row)
            result["payload"] = json.loads(result.pop("payload_json"))
            results.append(result)
        return results

    def events(
        self, entity_type: str | None = None, entity_id: str | None = None
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM review_events"
        parameters: list[str] = []
        clauses: list[str] = []
        if entity_type is not None:
            clauses.append("entity_type=?")
            parameters.append(entity_type)
        if entity_id is not None:
            clauses.append("entity_id=?")
            parameters.append(entity_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY rowid"
        results = []
        for row in self.connection.execute(query, parameters):
            result = dict(row)
            result["payload"] = json.loads(result.pop("payload_json"))
            result["human_confirmation"] = bool(result["human_confirmation"])
            results.append(result)
        return results

    def _dependency_head(self, dependency: dict[str, str]) -> dict[str, Any]:
        head = self.head(dependency["entity_type"], dependency["entity_id"])
        if head is None:
            raise ValueError(
                "missing dependency: "
                f"{dependency['entity_type']}:{dependency['entity_id']}"
            )
        if head["content_fingerprint"] != dependency["fingerprint"]:
            raise ValueError(
                "stale dependency fingerprint: "
                f"{dependency['entity_type']}:{dependency['entity_id']}"
            )
        if head["state"] not in ACTIVE_DEPENDENCY_STATES:
            raise ValueError(
                "dependency is not formally verified: "
                f"{dependency['entity_type']}:{dependency['entity_id']}"
            )
        return head

    def _validate_transcript_verification(self, payload: dict[str, Any]) -> None:
        content = payload["content"]
        _require_nonempty(content.get("source_id"), "transcript source id")
        _require_sha256(content.get("media_sha256"), "media_sha256")
        _require_sha256(content.get("raw_asr_sha256"), "raw_asr_sha256")
        projection_sha = _require_sha256(
            content.get("formal_projection_sha256"), "formal_projection_sha256"
        )
        duration_ms = content.get("duration_ms")
        segments = content.get("segments")
        if not isinstance(duration_ms, int) or duration_ms < 0:
            raise ValueError("transcript duration_ms must be non-negative")
        if not isinstance(segments, list):
            raise ValueError("formal transcript segments must be a list")
        projection = {
            "source_id": content["source_id"],
            "media_sha256": content["media_sha256"],
            "raw_asr_sha256": content["raw_asr_sha256"],
            "duration_ms": duration_ms,
            "segments": segments,
        }
        if sha256_json(projection) != projection_sha:
            raise ValueError("formal transcript projection fingerprint mismatch")
        previous_end = 0
        seen_segments: set[str] = set()
        for segment in segments:
            if not isinstance(segment, dict):
                raise ValueError("formal transcript segment must be an object")
            segment_id = _require_nonempty(segment.get("segment_id"), "segment id")
            if segment_id in seen_segments:
                raise ValueError(f"duplicate formal transcript segment: {segment_id}")
            seen_segments.add(segment_id)
            start = segment.get("start_ms")
            end = segment.get("end_ms")
            _require_nonempty(segment.get("text"), "formal transcript text")
            if not isinstance(start, int) or not isinstance(end, int):
                raise ValueError("formal transcript times must be integers")
            if start < previous_end or end <= start or end > duration_ms:
                raise ValueError("formal transcript segments overlap or exceed media")
            previous_end = end
        attestation = payload.get("attestation")
        if not isinstance(attestation, dict):
            raise ValueError("transcript source verification requires attestation")
        required_true = (
            "full_media_reviewed",
            "segments_complete",
            "missing_speech_resolved",
            "false_positive_speech_resolved",
            "timing_resolved",
        )
        if any(attestation.get(name) is not True for name in required_true):
            raise ValueError("all transcript completeness confirmations are required")
        if not _coverage_is_complete(attestation.get("playback_coverage"), duration_ms):
            raise ValueError("playback coverage does not cover the complete media")
        if not segments and attestation.get("no_usable_speech_confirmed") is not True:
            raise ValueError("zero-segment transcript requires no-speech confirmation")
        if attestation.get("review_basis") not in {"local_media", "source_page"}:
            raise ValueError("transcript review basis must identify the reviewed media")

    def _validate_teaching_event(self, payload: dict[str, Any]) -> None:
        content = payload["content"]
        _require_nonempty(content.get("source_id"), "teaching event source id")
        _require_nonempty(content.get("evidence_boundary"), "evidence boundary")
        modality = content.get("modality")
        if modality not in {"language", "visual", "multimodal"}:
            raise ValueError("unsupported teaching event modality")
        start = content.get("start_ms")
        end = content.get("end_ms")
        if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start:
            raise ValueError("teaching event requires a valid time range")
        evidence_window = content.get("evidence_window")
        if not isinstance(evidence_window, dict):
            raise ValueError("teaching event requires an evidence window")
        dependencies = self._dependencies(payload)
        transcript_dependencies = [
            dependency
            for dependency in dependencies
            if dependency["entity_type"] == "transcript"
        ]
        if modality in {"language", "multimodal"}:
            if len(transcript_dependencies) != 1:
                raise ValueError("language evidence requires exactly one transcript")
            transcript_head = self._dependency_head(transcript_dependencies[0])
            transcript = transcript_head["payload"]["content"]
            segment_ids = evidence_window.get("segment_ids")
            if not isinstance(segment_ids, list) or not segment_ids:
                raise ValueError("language evidence requires transcript segment ids")
            selected = [
                segment
                for segment in transcript["segments"]
                if segment["segment_id"] in segment_ids
            ]
            if len(selected) != len(set(segment_ids)):
                raise ValueError("language evidence references missing transcript segments")
            selected.sort(key=lambda segment: (segment["start_ms"], segment["end_ms"]))
            expected_text = " ".join(segment["text"].strip() for segment in selected)
            if evidence_window.get("text") != expected_text:
                raise ValueError("language evidence text must match the formal transcript")
            if start > selected[0]["start_ms"] or end < selected[-1]["end_ms"]:
                raise ValueError("teaching event time range must contain its segments")
            if content.get("formal_projection_sha256") != transcript.get(
                "formal_projection_sha256"
            ):
                raise ValueError("teaching event is bound to the wrong transcript projection")
        if modality in {"visual", "multimodal"}:
            _require_nonempty(
                evidence_window.get("visual_observation"), "visual observation"
            )

    def _validate_semantic_claim(self, payload: dict[str, Any]) -> None:
        content = payload["content"]
        for field in ("topic", "mechanism", "correction_direction"):
            _require_nonempty(content.get(field), f"claim {field}")
        for field in ("symptoms", "applicability", "exclusions"):
            value = content.get(field)
            if not isinstance(value, list) or not value:
                raise ValueError(f"claim {field} must be a non-empty list")
            if any(not isinstance(item, str) or not item.strip() for item in value):
                raise ValueError(f"claim {field} contains an empty value")
        if content.get("confidence") not in {"low", "medium", "high"}:
            raise ValueError("claim confidence must be low, medium, or high")
        support_ids = content.get("support_event_ids")
        if not isinstance(support_ids, list) or not support_ids:
            raise ValueError("claim requires at least one supporting teaching event")
        if len(set(support_ids)) != len(support_ids):
            raise ValueError("claim support event ids must be unique")
        dependencies = self._dependencies(payload)
        event_dependencies = [
            dependency
            for dependency in dependencies
            if dependency["entity_type"] == "teaching_event"
        ]
        if sorted(support_ids) != sorted(
            dependency["entity_id"] for dependency in event_dependencies
        ):
            raise ValueError("claim supports and teaching-event dependencies differ")
        for dependency in event_dependencies:
            self._dependency_head(dependency)

    def _validate_action_payload(
        self,
        entity_type: str,
        action: str,
        payload: dict[str, Any],
        current_head: dict[str, Any] | None,
        content_fingerprint: str,
    ) -> None:
        dependencies = self._dependencies(payload)
        if action not in {"invalidate", "register_raw", "create_candidate"}:
            for dependency in dependencies:
                self._dependency_head(dependency)
        if action == "source_verify" and entity_type == "transcript":
            self._validate_transcript_verification(payload)
        elif action == "source_verify" and entity_type == "teaching_event":
            self._validate_teaching_event(payload)
        elif entity_type == "semantic_claim" and action in {
            "source_verify",
            "domain_approve",
            "publish",
        }:
            self._validate_semantic_claim(payload)
        if action in {"domain_approve", "publish"}:
            if current_head is None or current_head["content_fingerprint"] != content_fingerprint:
                raise ValueError(
                    f"{action} cannot silently change previously verified content"
                )

    def append_event(
        self,
        *,
        entity_type: str,
        entity_id: str,
        action: str,
        reviewer_id: str,
        human_confirmation: bool,
        payload: dict[str, Any],
        expected_revision: int,
        expected_base_fingerprint: str,
        occurred_at: str | None = None,
        note: str = "",
    ) -> dict[str, Any]:
        _require_nonempty(entity_id, "entity id")
        if not isinstance(expected_revision, int) or expected_revision < 0:
            raise ValueError("expected revision must be a non-negative integer")
        if not isinstance(expected_base_fingerprint, str):
            raise ValueError("expected base fingerprint must be a string")
        timestamp = occurred_at or utc_now()
        if not _UTC_TIMESTAMP.fullmatch(timestamp):
            raise ValueError("occurred_at must be an ISO-8601 UTC timestamp")
        payload_fingerprint, content_fingerprint = self._payload_parts(payload)
        payload_json = canonical_json(payload)

        self.connection.execute("BEGIN IMMEDIATE")
        try:
            current = self.head(entity_type, entity_id)
            current_state = current["state"] if current else "missing"
            current_revision = int(current["revision"]) if current else 0
            current_fingerprint = current["content_fingerprint"] if current else ""
            if current_revision != expected_revision:
                raise ValueError(
                    f"stale revision for {entity_type}:{entity_id}: "
                    f"expected {expected_revision}, current {current_revision}"
                )
            if current_fingerprint != expected_base_fingerprint:
                raise ValueError(
                    f"stale base fingerprint for {entity_type}:{entity_id}"
                )
            transition = resolve_transition(
                entity_type,
                current_state,
                action,
                reviewer_id,
                human_confirmation,
            )
            self._validate_action_payload(
                entity_type,
                action,
                payload,
                current,
                content_fingerprint,
            )
            revision = current_revision + 1
            supersedes = current["last_event_id"] if current else None
            event_body = {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "action": action,
                "from_state": transition.from_state,
                "to_state": transition.to_state,
                "reviewer_id": reviewer_id,
                "occurred_at": timestamp,
                "revision": revision,
                "base_fingerprint": current_fingerprint,
                "payload_fingerprint": payload_fingerprint,
                "content_fingerprint": content_fingerprint,
                "supersedes_event_id": supersedes,
                "human_confirmation": bool(human_confirmation),
                "note": note,
            }
            event_id = f"review_{sha256_json(event_body)}"
            self.connection.execute(
                """
                INSERT INTO review_events(
                    event_id,entity_type,entity_id,action,from_state,to_state,
                    reviewer_id,occurred_at,revision,base_fingerprint,
                    payload_fingerprint,content_fingerprint,payload_json,
                    supersedes_event_id,human_confirmation,note
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    event_id,
                    entity_type,
                    entity_id,
                    action,
                    transition.from_state,
                    transition.to_state,
                    reviewer_id,
                    timestamp,
                    revision,
                    current_fingerprint,
                    payload_fingerprint,
                    content_fingerprint,
                    payload_json,
                    supersedes,
                    int(human_confirmation),
                    note,
                ),
            )
            self.connection.execute(
                """
                INSERT INTO entity_heads(
                    entity_type,entity_id,state,revision,last_event_id,
                    payload_fingerprint,content_fingerprint,payload_json
                ) VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(entity_type,entity_id) DO UPDATE SET
                    state=excluded.state,
                    revision=excluded.revision,
                    last_event_id=excluded.last_event_id,
                    payload_fingerprint=excluded.payload_fingerprint,
                    content_fingerprint=excluded.content_fingerprint,
                    payload_json=excluded.payload_json
                """,
                (
                    entity_type,
                    entity_id,
                    transition.to_state,
                    revision,
                    event_id,
                    payload_fingerprint,
                    content_fingerprint,
                    payload_json,
                ),
            )
            self.connection.execute(
                "DELETE FROM entity_dependencies WHERE entity_type=? AND entity_id=?",
                (entity_type, entity_id),
            )
            for dependency in self._dependencies(payload):
                self.connection.execute(
                    """
                    INSERT INTO entity_dependencies(
                        entity_type,entity_id,dependency_type,dependency_id,
                        bound_fingerprint
                    ) VALUES (?,?,?,?,?)
                    """,
                    (
                        entity_type,
                        entity_id,
                        dependency["entity_type"],
                        dependency["entity_id"],
                        dependency["fingerprint"],
                    ),
                )
            self.connection.execute(
                "DELETE FROM drafts WHERE entity_type=? AND entity_id=?",
                (entity_type, entity_id),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        result = dict(event_body)
        result["event_id"] = event_id
        result["payload"] = payload
        return result

    def save_draft(
        self,
        entity_type: str,
        entity_id: str,
        base_revision: int,
        draft: dict[str, Any],
        updated_at: str | None = None,
    ) -> dict[str, Any]:
        if entity_type not in entity_types():
            raise ValueError(f"unsupported entity type: {entity_type}")
        _require_nonempty(entity_id, "entity id")
        head = self.head(entity_type, entity_id)
        current_revision = int(head["revision"]) if head else 0
        if base_revision != current_revision:
            raise ValueError("draft base revision is stale")
        timestamp = updated_at or utc_now()
        if not _UTC_TIMESTAMP.fullmatch(timestamp):
            raise ValueError("updated_at must be an ISO-8601 UTC timestamp")
        fingerprint = sha256_json(draft)
        self.connection.execute(
            """
            INSERT INTO drafts(
                entity_type,entity_id,base_revision,draft_fingerprint,
                draft_json,updated_at
            ) VALUES (?,?,?,?,?,?)
            ON CONFLICT(entity_type,entity_id) DO UPDATE SET
                base_revision=excluded.base_revision,
                draft_fingerprint=excluded.draft_fingerprint,
                draft_json=excluded.draft_json,
                updated_at=excluded.updated_at
            """,
            (
                entity_type,
                entity_id,
                base_revision,
                fingerprint,
                canonical_json(draft),
                timestamp,
            ),
        )
        self.connection.commit()
        return {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "base_revision": base_revision,
            "draft_fingerprint": fingerprint,
            "draft": draft,
            "updated_at": timestamp,
        }

    def load_draft(self, entity_type: str, entity_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM drafts WHERE entity_type=? AND entity_id=?",
            (entity_type, entity_id),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["draft"] = json.loads(result.pop("draft_json"))
        return result

    def _dependency_is_stale(self, row: sqlite3.Row) -> bool:
        dependency = self.head(row["dependency_type"], row["dependency_id"])
        return (
            dependency is None
            or dependency["state"] not in ACTIVE_DEPENDENCY_STATES
            or dependency["content_fingerprint"] != row["bound_fingerprint"]
        )

    def propagate_stale(self, reason: str) -> list[str]:
        """Invalidate every formally reviewed entity with a stale dependency."""

        _require_nonempty(reason, "invalidation reason")
        invalidated: list[str] = []
        while True:
            target: dict[str, Any] | None = None
            for head in self.heads():
                rows = list(
                    self.connection.execute(
                        """
                        SELECT * FROM entity_dependencies
                        WHERE entity_type=? AND entity_id=?
                        ORDER BY dependency_type,dependency_id
                        """,
                        (head["entity_type"], head["entity_id"]),
                    )
                )
                if not rows or not any(self._dependency_is_stale(row) for row in rows):
                    continue
                try:
                    resolve_transition(
                        head["entity_type"],
                        head["state"],
                        "invalidate",
                        "system:dependency-invalidator",
                        False,
                    )
                except ValueError:
                    continue
                target = head
                break
            if target is None:
                break
            event = self.append_event(
                entity_type=target["entity_type"],
                entity_id=target["entity_id"],
                action="invalidate",
                reviewer_id="system:dependency-invalidator",
                human_confirmation=False,
                payload={
                    "content": {
                        "invalidated_content_fingerprint": target[
                            "content_fingerprint"
                        ],
                        "reason": reason,
                    },
                    "dependencies": [],
                },
                expected_revision=int(target["revision"]),
                expected_base_fingerprint=target["content_fingerprint"],
                note=reason,
            )
            invalidated.append(event["event_id"])
        return invalidated

    @staticmethod
    def _event_body(row: dict[str, Any]) -> dict[str, Any]:
        return {
            key: row[key]
            for key in (
                "entity_type",
                "entity_id",
                "action",
                "from_state",
                "to_state",
                "reviewer_id",
                "occurred_at",
                "revision",
                "base_fingerprint",
                "payload_fingerprint",
                "content_fingerprint",
                "supersedes_event_id",
                "human_confirmation",
                "note",
            )
        }

    def verify_integrity(self) -> dict[str, int]:
        integrity = self.connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError(f"SQLite integrity check failed: {integrity}")
        projected: dict[tuple[str, str], dict[str, Any]] = {}
        event_count = 0
        for raw_row in self.connection.execute("SELECT * FROM review_events ORDER BY rowid"):
            row = dict(raw_row)
            row["human_confirmation"] = bool(row["human_confirmation"])
            payload = json.loads(row["payload_json"])
            payload_fingerprint, content_fingerprint = self._payload_parts(payload)
            if payload_fingerprint != row["payload_fingerprint"]:
                raise ValueError(f"event payload fingerprint mismatch: {row['event_id']}")
            if content_fingerprint != row["content_fingerprint"]:
                raise ValueError(f"event content fingerprint mismatch: {row['event_id']}")
            if f"review_{sha256_json(self._event_body(row))}" != row["event_id"]:
                raise ValueError(f"event identity mismatch: {row['event_id']}")
            key = (row["entity_type"], row["entity_id"])
            previous = projected.get(key)
            state = previous["state"] if previous else "missing"
            revision = previous["revision"] if previous else 0
            fingerprint = previous["content_fingerprint"] if previous else ""
            last_event_id = previous["last_event_id"] if previous else None
            transition = resolve_transition(
                row["entity_type"],
                state,
                row["action"],
                row["reviewer_id"],
                row["human_confirmation"],
            )
            if row["from_state"] != state or row["to_state"] != transition.to_state:
                raise ValueError(f"event transition chain mismatch: {row['event_id']}")
            if row["revision"] != revision + 1:
                raise ValueError(f"event revision chain mismatch: {row['event_id']}")
            if row["base_fingerprint"] != fingerprint:
                raise ValueError(f"event base fingerprint mismatch: {row['event_id']}")
            if row["supersedes_event_id"] != last_event_id:
                raise ValueError(f"event supersession chain mismatch: {row['event_id']}")
            projected[key] = {
                "state": row["to_state"],
                "revision": row["revision"],
                "last_event_id": row["event_id"],
                "payload_fingerprint": row["payload_fingerprint"],
                "content_fingerprint": row["content_fingerprint"],
                "payload_json": row["payload_json"],
            }
            event_count += 1
        stored = {
            (row["entity_type"], row["entity_id"]): {
                key: row[key]
                for key in (
                    "state",
                    "revision",
                    "last_event_id",
                    "payload_fingerprint",
                    "content_fingerprint",
                    "payload_json",
                )
            }
            for row in self.connection.execute("SELECT * FROM entity_heads")
        }
        if projected != stored:
            raise ValueError("entity head projection does not match append-only events")
        projected_dependencies: set[tuple[str, str, str, str, str]] = set()
        for (entity_type, entity_id), head in projected.items():
            payload = json.loads(head["payload_json"])
            for dependency in self._dependencies(payload):
                projected_dependencies.add(
                    (
                        entity_type,
                        entity_id,
                        dependency["entity_type"],
                        dependency["entity_id"],
                        dependency["fingerprint"],
                    )
                )
        stored_dependencies = {
            tuple(row)
            for row in self.connection.execute(
                """
                SELECT entity_type,entity_id,dependency_type,dependency_id,
                       bound_fingerprint
                FROM entity_dependencies
                """
            )
        }
        if projected_dependencies != stored_dependencies:
            raise ValueError("dependency projection does not match current event payloads")
        return {
            "events": event_count,
            "entities": len(projected),
            "dependencies": len(projected_dependencies),
        }


def dependency_for(head: dict[str, Any]) -> dict[str, str]:
    return {
        "entity_type": head["entity_type"],
        "entity_id": head["entity_id"],
        "fingerprint": head["content_fingerprint"],
    }


def current_dependencies(
    ledger: ReviewLedger, identities: Iterable[tuple[str, str]]
) -> list[dict[str, str]]:
    dependencies = []
    for entity_type, entity_id in identities:
        head = ledger.head(entity_type, entity_id)
        if head is None:
            raise ValueError(f"missing dependency: {entity_type}:{entity_id}")
        dependencies.append(dependency_for(head))
    return sorted(
        dependencies, key=lambda item: (item["entity_type"], item["entity_id"])
    )
