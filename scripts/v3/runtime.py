"""Deterministic v3 shadow runtime builder and evidence-packet query."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from v3 import SCHEMA_VERSION
from v3.canonical import canonical_json, sha256_json
from v3.publication import validate_publication


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA = ROOT / "schemas" / "v3" / "runtime.sql"


def _runtime_fingerprint(publication: dict[str, Any]) -> str:
    return sha256_json(
        {
            "runtime_schema_version": SCHEMA_VERSION,
            "publication_fingerprint": publication["publication_fingerprint"],
            "sources": publication["sources"],
            "teaching_events": publication["teaching_events"],
            "semantic_claims": publication["semantic_claims"],
        }
    )


def build_runtime(
    publication: dict[str, Any], output_path: Path, schema_path: Path = DEFAULT_SCHEMA
) -> dict[str, Any]:
    counts = validate_publication(publication)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    temporary.unlink()
    runtime_fingerprint = _runtime_fingerprint(publication)
    try:
        connection = sqlite3.connect(temporary)
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.executescript(schema_path.read_text(encoding="utf-8"))
            metadata = {
                "application_id": "badminton-skills-coach-v3-shadow-runtime",
                "schema_version": SCHEMA_VERSION,
                "publication_id": publication["publication_id"],
                "publication_fingerprint": publication["publication_fingerprint"],
                "runtime_fingerprint": runtime_fingerprint,
            }
            connection.executemany(
                "INSERT INTO metadata(key,value) VALUES (?,?)", sorted(metadata.items())
            )
            for source in publication["sources"]:
                connection.execute(
                    "INSERT INTO sources VALUES (?,?,?,?,?)",
                    (
                        source["source_id"],
                        source["platform"],
                        source["canonical_url"],
                        canonical_json(source["alternate_urls"]),
                        source["title"],
                    ),
                )
            for event in publication["teaching_events"]:
                connection.execute(
                    "INSERT INTO teaching_events VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        event["teaching_event_id"],
                        event["source_id"],
                        event["start_ms"],
                        event["end_ms"],
                        event["modality"],
                        event["evidence_boundary"],
                        event["evidence_text"],
                        event["visual_observation"],
                        event["viewing_value"],
                        event["watch_focus"],
                        event["formal_projection_sha256"],
                    ),
                )
            for claim in publication["semantic_claims"]:
                search_text = " ".join(
                    [
                        claim["topic"],
                        *claim["symptoms"],
                        *claim["applicability"],
                        claim["mechanism"],
                        claim["correction_direction"],
                        *claim["aliases"],
                    ]
                ).casefold()
                connection.execute(
                    "INSERT INTO semantic_claims VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        claim["claim_id"],
                        claim["topic"],
                        canonical_json(claim["symptoms"]),
                        canonical_json(claim["applicability"]),
                        claim["mechanism"],
                        claim["correction_direction"],
                        canonical_json(claim["exclusions"]),
                        claim["confidence"],
                        claim["training_method"],
                        search_text,
                    ),
                )
                connection.executemany(
                    "INSERT INTO claim_aliases VALUES (?,?)",
                    [(claim["claim_id"], alias) for alias in claim["aliases"]],
                )
                connection.executemany(
                    "INSERT INTO claim_supports VALUES (?,?)",
                    [
                        (claim["claim_id"], event_id)
                        for event_id in claim["support_event_ids"]
                    ],
                )
            connection.commit()
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("built runtime failed SQLite integrity check")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("built runtime has invalid foreign keys")
        finally:
            connection.close()
        os.replace(temporary, output_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        "schema_version": SCHEMA_VERSION,
        "publication_id": publication["publication_id"],
        "publication_fingerprint": publication["publication_fingerprint"],
        "runtime_fingerprint": runtime_fingerprint,
        "row_counts": counts,
    }


def runtime_metadata(path: Path) -> dict[str, str]:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return dict(connection.execute("SELECT key,value FROM metadata"))
    finally:
        connection.close()


def _claim_score(query: str, row: sqlite3.Row, aliases: list[str]) -> int:
    folded = query.casefold().strip()
    if not folded:
        return 0
    score = 0
    if row["topic"].casefold() in folded or folded in row["topic"].casefold():
        score += 8
    for alias in aliases:
        if alias.casefold() in folded or folded in alias.casefold():
            score += 6
    symptoms = json.loads(row["symptoms_json"])
    score += sum(4 for symptom in symptoms if symptom.casefold() in folded)
    terms = {term for term in re_split_query(folded) if len(term) >= 2}
    search_text = row["search_text"].casefold()
    matched_terms = {term for term in terms if term in search_text}
    if any(len(term) >= 4 for term in matched_terms) or len(matched_terms) >= 2:
        score += len(matched_terms)
    return score


def re_split_query(query: str) -> list[str]:
    current: list[str] = []
    current_kind = ""
    runs: list[tuple[str, str]] = []

    def flush() -> None:
        nonlocal current, current_kind
        if current:
            runs.append((current_kind, "".join(current)))
            current = []
            current_kind = ""

    for character in query:
        if "\u4e00" <= character <= "\u9fff":
            kind = "cjk"
        elif character.isalnum():
            kind = "alnum"
        else:
            flush()
            continue
        if current_kind and current_kind != kind:
            flush()
        if not current_kind:
            current_kind = kind
        current.append(character)
    flush()

    terms: list[str] = []
    for kind, run in runs:
        terms.append(run)
        if kind == "cjk" and len(run) > 3:
            terms.extend(run[index : index + 2] for index in range(len(run) - 1))
    return terms


def shadow_answer_packet(path: Path, query: str, limit: int = 5) -> dict[str, Any]:
    if limit < 1 or limit > 10:
        raise ValueError("shadow query limit must be between 1 and 10")
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        metadata = dict(connection.execute("SELECT key,value FROM metadata"))
        scored = []
        for row in connection.execute("SELECT * FROM semantic_claims ORDER BY claim_id"):
            aliases = [
                alias_row[0]
                for alias_row in connection.execute(
                    "SELECT alias FROM claim_aliases WHERE claim_id=? ORDER BY alias",
                    (row["claim_id"],),
                )
            ]
            score = _claim_score(query, row, aliases)
            if score > 0:
                scored.append((score, row, aliases))
        scored.sort(key=lambda item: (-item[0], item[1]["claim_id"]))
        selected = scored[:limit]
        evidence_ids = sorted(
            {
                support[0]
                for _, claim, _ in selected
                for support in connection.execute(
                    "SELECT teaching_event_id FROM claim_supports WHERE claim_id=?",
                    (claim["claim_id"],),
                )
            }
        )
        labels = {event_id: f"V{index + 1}" for index, event_id in enumerate(evidence_ids)}
        evidence = []
        for event_id in evidence_ids:
            row = connection.execute(
                """
                SELECT e.*,s.platform,s.canonical_url,s.alternate_urls_json,s.title
                FROM teaching_events e JOIN sources s USING(source_id)
                WHERE teaching_event_id=?
                """,
                (event_id,),
            ).fetchone()
            evidence.append(
                {
                    "label": labels[event_id],
                    "teaching_event_id": event_id,
                    "source_id": row["source_id"],
                    "title": row["title"],
                    "platform": row["platform"],
                    "canonical_url": row["canonical_url"],
                    "alternate_urls": json.loads(row["alternate_urls_json"]),
                    "start_ms": row["start_ms"],
                    "end_ms": row["end_ms"],
                    "modality": row["modality"],
                    "evidence_text": row["evidence_text"],
                    "visual_observation": row["visual_observation"],
                    "evidence_boundary": row["evidence_boundary"],
                    "viewing_value": row["viewing_value"],
                    "watch_focus": row["watch_focus"],
                }
            )
        claims = []
        for score, row, aliases in selected:
            supports = [
                labels[support[0]]
                for support in connection.execute(
                    "SELECT teaching_event_id FROM claim_supports WHERE claim_id=? ORDER BY teaching_event_id",
                    (row["claim_id"],),
                )
            ]
            claims.append(
                {
                    "claim_id": row["claim_id"],
                    "score": score,
                    "topic": row["topic"],
                    "symptoms": json.loads(row["symptoms_json"]),
                    "applicability": json.loads(row["applicability_json"]),
                    "mechanism": row["mechanism"],
                    "correction_direction": row["correction_direction"],
                    "exclusions": json.loads(row["exclusions_json"]),
                    "confidence": row["confidence"],
                    "training_method": row["training_method"],
                    "aliases": aliases,
                    "evidence_labels": supports,
                }
            )
        return {
            "runtime_version": "v3-shadow",
            "runtime_fingerprint": metadata["runtime_fingerprint"],
            "query": query,
            "claims": claims,
            "evidence": evidence,
            "evidence_gap": "" if claims else "没有匹配到已发布的 v3 主张。",
        }
    finally:
        connection.close()
