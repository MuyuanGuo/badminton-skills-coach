#!/usr/bin/env python3
"""Build the deterministic, read-only SQLite store shipped with the Skill."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_PATH = ROOT / "data" / "knowledge" / "douyin_knowledge_base.json"
RETRIEVAL_INDEX_PATH = ROOT / "data" / "knowledge" / "retrieval_index.json"
OUTPUT_PATH = (
    ROOT
    / "skills"
    / "liuhui-badminton-coach"
    / "references"
    / "runtime-store.sqlite3"
)
STORE_SCHEMA_VERSION = 2
APPLICATION_ID = 0x4C484243  # "LHBC"


def canonical_json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def insert_metadata(connection, table, payload, excluded=()):
    rows = [
        (key, canonical_json(value))
        for key, value in payload.items()
        if key not in set(excluded)
    ]
    connection.executemany(
        f"INSERT INTO {table}(key, value) VALUES (?, ?)", sorted(rows)
    )


def create_schema(connection):
    connection.executescript(
        """
        PRAGMA page_size = 4096;
        PRAGMA journal_mode = OFF;
        PRAGMA synchronous = OFF;
        PRAGMA temp_store = MEMORY;
        PRAGMA locking_mode = EXCLUSIVE;
        CREATE TABLE store_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
        CREATE TABLE knowledge_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
        CREATE TABLE retrieval_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
        CREATE TABLE chunk_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
        CREATE TABLE knowledge_videos (
            position INTEGER PRIMARY KEY,
            video_id TEXT NOT NULL UNIQUE,
            payload TEXT NOT NULL
        );
        CREATE TABLE transcript_payloads (
            position INTEGER PRIMARY KEY,
            video_id TEXT NOT NULL UNIQUE,
            payload TEXT NOT NULL
        );
        CREATE TABLE search_videos (
            position INTEGER PRIMARY KEY,
            video_id TEXT NOT NULL UNIQUE,
            payload TEXT NOT NULL
        );
        CREATE TABLE retrieval_videos (
            position INTEGER PRIMARY KEY,
            video_id TEXT NOT NULL UNIQUE,
            payload TEXT NOT NULL
        );
        CREATE TABLE chunks (
            position INTEGER PRIMARY KEY,
            payload TEXT NOT NULL
        );
        CREATE TABLE video_ngram_postings (
            gram TEXT PRIMARY KEY,
            payload TEXT NOT NULL
        ) WITHOUT ROWID;
        CREATE TABLE chunk_ngram_postings (
            gram TEXT PRIMARY KEY,
            payload TEXT NOT NULL
        ) WITHOUT ROWID;
        """
    )
    connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
    connection.execute(f"PRAGMA user_version = {STORE_SCHEMA_VERSION}")


def build_store(knowledge_path, retrieval_index_path, output_path):
    knowledge_path = Path(knowledge_path)
    retrieval_index_path = Path(retrieval_index_path)
    output_path = Path(output_path)
    knowledge = json.loads(knowledge_path.read_text(encoding="utf-8"))
    retrieval = json.loads(retrieval_index_path.read_text(encoding="utf-8"))
    chunk_index = retrieval.get("chunk_index") or {}
    chunk_sources = set(
        (chunk_index.get("config") or {}).get("source_allowlist")
        or ["bilibili_video"]
    )

    transcript_fields = {
        "transcript_segments",
        "transcript_segments_json",
    }

    def knowledge_projection(video):
        return {
            key: value
            for key, value in video.items()
            if key not in transcript_fields
        }

    def transcript_projection(video):
        return {
            key: video[key]
            for key in transcript_fields
            if key in video
        }

    def search_projection(video):
        projection = {
            key: value
            for key, value in video.items()
            if key
            not in {
                "transcript_segments",
                "transcript_segments_json",
                "quality",
                "origin_verification",
                "classification",
                "automatic_admission",
            }
        }
        if video.get("source_type") not in chunk_sources:
            segments = video.get("transcript_segments")
            if segments is None and video.get("transcript_segments_json"):
                segments = json.loads(video["transcript_segments_json"])
            projection["_runtime_search_transcript"] = "".join(
                str(segment.get("text") or "") for segment in (segments or [])
            )
        return projection

    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.", suffix=".tmp", dir=output_path.parent
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        connection = sqlite3.connect(temporary_path)
        try:
            create_schema(connection)
            store_metadata = {
                "schema_version": STORE_SCHEMA_VERSION,
                "knowledge_sha256": sha256(knowledge_path),
                "retrieval_index_sha256": sha256(retrieval_index_path),
                "knowledge_video_count": len(knowledge["videos"]),
                "transcript_payload_count": sum(
                    bool(transcript_projection(video))
                    for video in knowledge["videos"]
                ),
                "retrieval_video_count": len(retrieval["videos"]),
                "chunk_count": len(chunk_index.get("chunks", [])),
            }
            insert_metadata(connection, "store_metadata", store_metadata)
            insert_metadata(connection, "knowledge_metadata", knowledge, {"videos"})
            insert_metadata(
                connection,
                "retrieval_metadata",
                retrieval,
                {"videos", "ngram_vocabulary", "ngram_postings", "chunk_index"},
            )
            insert_metadata(
                connection,
                "chunk_metadata",
                chunk_index,
                {"chunks", "ngram_vocabulary", "ngram_postings"},
            )
            connection.executemany(
                "INSERT INTO knowledge_videos(position, video_id, payload) VALUES (?, ?, ?)",
                [
                    (
                        index,
                        video["video_id"],
                        canonical_json(knowledge_projection(video)),
                    )
                    for index, video in enumerate(knowledge["videos"])
                ],
            )
            connection.executemany(
                "INSERT INTO transcript_payloads(position, video_id, payload) VALUES (?, ?, ?)",
                [
                    (index, video["video_id"], canonical_json(payload))
                    for index, video in enumerate(knowledge["videos"])
                    if (payload := transcript_projection(video))
                ],
            )
            connection.executemany(
                "INSERT INTO search_videos(position, video_id, payload) VALUES (?, ?, ?)",
                [
                    (index, video["video_id"], canonical_json(search_projection(video)))
                    for index, video in enumerate(knowledge["videos"])
                ],
            )
            connection.executemany(
                "INSERT INTO retrieval_videos(position, video_id, payload) VALUES (?, ?, ?)",
                [
                    (index, video["video_id"], canonical_json(video))
                    for index, video in enumerate(retrieval["videos"])
                ],
            )
            connection.executemany(
                "INSERT INTO chunks(position, payload) VALUES (?, ?)",
                [
                    (index, canonical_json(chunk))
                    for index, chunk in enumerate(chunk_index.get("chunks", []))
                ],
            )
            connection.executemany(
                "INSERT INTO video_ngram_postings(gram, payload) VALUES (?, ?)",
                list(
                    zip(
                        retrieval.get("ngram_vocabulary", []),
                        retrieval.get("ngram_postings", []),
                    )
                ),
            )
            connection.executemany(
                "INSERT INTO chunk_ngram_postings(gram, payload) VALUES (?, ?)",
                list(
                    zip(
                        chunk_index.get("ngram_vocabulary", []),
                        chunk_index.get("ngram_postings", []),
                    )
                ),
            )
            connection.commit()
            connection.execute("VACUUM")
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise ValueError(f"runtime store integrity check failed: {integrity}")
        finally:
            connection.close()
        os.replace(temporary_path, output_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return {
        "output": str(output_path),
        "sha256": sha256(output_path),
        "bytes": output_path.stat().st_size,
        "knowledge_videos": len(knowledge["videos"]),
        "retrieval_videos": len(retrieval["videos"]),
        "chunks": len(chunk_index.get("chunks", [])),
    }


def check_store(knowledge_path, retrieval_index_path, output_path):
    output_path = Path(output_path)
    if not output_path.exists():
        raise ValueError(f"runtime store missing: {output_path}")
    uri = f"file:{output_path.resolve().as_posix()}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    try:
        metadata = dict(
            connection.execute("SELECT key, value FROM store_metadata")
        )
        expected = {
            "schema_version": STORE_SCHEMA_VERSION,
            "knowledge_sha256": sha256(knowledge_path),
            "retrieval_index_sha256": sha256(retrieval_index_path),
        }
        for key, value in expected.items():
            actual = json.loads(metadata.get(key, "null"))
            if actual != value:
                raise ValueError(
                    f"runtime store {key} is stale: expected {value!r}, got {actual!r}"
                )
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError(f"runtime store integrity check failed: {integrity}")
    finally:
        connection.close()
    return {"output": str(output_path), "sha256": sha256(output_path), "status": "ok"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--knowledge", type=Path, default=KNOWLEDGE_PATH)
    parser.add_argument("--retrieval-index", type=Path, default=RETRIEVAL_INDEX_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        result = (
            check_store(args.knowledge, args.retrieval_index, args.output)
            if args.check
            else build_store(args.knowledge, args.retrieval_index, args.output)
        )
    except (OSError, ValueError, sqlite3.DatabaseError) as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
