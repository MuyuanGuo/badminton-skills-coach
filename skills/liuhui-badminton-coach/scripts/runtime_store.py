#!/usr/bin/env python3
"""Read-only, lazy access to the packaged SQLite runtime evidence store."""

from __future__ import annotations

import json
import sqlite3
import weakref
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


STORE_SCHEMA_VERSION = 2


class SQLiteJsonSequence(Sequence):
    """A deterministic JSON row sequence that never retains decoded rows."""

    def __init__(
        self,
        connection,
        table,
        *,
        id_column=None,
        lookup_table=None,
    ):
        self._connection = connection
        self._table = table
        self._id_column = id_column
        self._lookup_table = lookup_table or table
        self._decoded_rows = None
        self._length = None

    def __len__(self):
        if self._length is None:
            self._length = int(
                self._connection.execute(
                    f"SELECT COUNT(*) FROM {self._table}"
                ).fetchone()[0]
            )
        return self._length

    @staticmethod
    def _decode(row):
        if row is None:
            raise IndexError("runtime-store row does not exist")
        return json.loads(row[0])

    def __iter__(self):
        cursor = self._connection.execute(
            f"SELECT payload FROM {self._table} ORDER BY position"
        )
        return (self._decode(row) for row in cursor)

    def __getitem__(self, index):
        if isinstance(index, slice):
            start, stop, step = index.indices(len(self))
            if step != 1:
                return [self[item] for item in range(start, stop, step)]
            if stop <= start:
                return []
            rows = self._connection.execute(
                f"SELECT payload FROM {self._table} "
                "WHERE position >= ? AND position < ? ORDER BY position",
                (start, stop),
            )
            return [self._decode(row) for row in rows]
        if index < 0:
            index += len(self)
        if index < 0 or index >= len(self):
            raise IndexError(index)
        return self._decode(
            self._connection.execute(
                f"SELECT payload FROM {self._table} WHERE position = ?",
                (index,),
            ).fetchone()
        )

    def get(self, item_id, default=None, *, full=True):
        if not self._id_column:
            raise TypeError("this runtime-store sequence has no stable ID")
        table = self._lookup_table if full else self._table
        row = self._connection.execute(
            f"SELECT payload FROM {table} WHERE {self._id_column} = ?",
            (str(item_id),),
        ).fetchone()
        return default if row is None else self._decode(row)

    def get_many(self, item_ids, *, full=True):
        if not self._id_column:
            raise TypeError("this runtime-store sequence has no stable ID")
        ordered_ids = list(dict.fromkeys(str(item) for item in item_ids))
        if not ordered_ids:
            return []
        found: dict[str, Any] = {}
        table = self._lookup_table if full else self._table
        # Stay below SQLite's conservative cross-platform parameter limit.
        for offset in range(0, len(ordered_ids), 900):
            batch = ordered_ids[offset : offset + 900]
            placeholders = ",".join("?" for _ in batch)
            rows = self._connection.execute(
                f"SELECT {self._id_column}, payload FROM {table} "
                f"WHERE {self._id_column} IN ({placeholders})",
                batch,
            )
            found.update((str(item_id), json.loads(payload)) for item_id, payload in rows)
        return [found[item_id] for item_id in ordered_ids if item_id in found]

    def get_many_positions(self, indexes):
        ordered_indexes = list(dict.fromkeys(int(index) for index in indexes))
        if not ordered_indexes:
            return {}
        found: dict[int, Any] = {}
        # Stay below SQLite's conservative cross-platform parameter limit.
        for offset in range(0, len(ordered_indexes), 900):
            batch = ordered_indexes[offset : offset + 900]
            placeholders = ",".join("?" for _ in batch)
            rows = self._connection.execute(
                f"SELECT position, payload FROM {self._table} "
                f"WHERE position IN ({placeholders})",
                batch,
            )
            found.update(
                (int(position), json.loads(payload))
                for position, payload in rows
            )
        return found


class SQLiteIdMapping(Mapping):
    """A no-cache ID view so large decoded videos remain request-local."""

    def __init__(self, sequence, item_ids, *, full=True):
        self._sequence = sequence
        self._item_ids = tuple(dict.fromkeys(str(item) for item in item_ids))
        self._id_set = frozenset(self._item_ids)
        self._full = full

    def __getitem__(self, key):
        if str(key) not in self._id_set:
            raise KeyError(key)
        value = self._sequence.get(str(key), full=self._full)
        if value is None:
            raise KeyError(key)
        return value

    def get(self, key, default=None):
        if str(key) not in self._id_set:
            return default
        return self._sequence.get(str(key), default, full=self._full)

    def __iter__(self):
        return iter(self._item_ids)

    def __len__(self):
        return len(self._item_ids)


class SQLiteKnowledgeSequence(SQLiteJsonSequence):
    """Hydrate transcript fields only for knowledge rows actually requested."""

    def __init__(self, connection, transcript_payloads):
        super().__init__(connection, "knowledge_videos", id_column="video_id")
        self._transcript_payloads = transcript_payloads

    def _hydrate(self, video):
        transcript = self._transcript_payloads.get(video["video_id"], {})
        return {**video, **transcript}

    def __iter__(self):
        return (self._hydrate(video) for video in super().__iter__())

    def __getitem__(self, index):
        value = super().__getitem__(index)
        if isinstance(index, slice):
            return [self._hydrate(video) for video in value]
        return self._hydrate(value)

    def get(self, item_id, default=None, *, full=True):
        video = super().get(item_id, default, full=False)
        if video is default or not full:
            return video
        return self._hydrate(video)

    def get_many(self, item_ids, *, full=True):
        videos = super().get_many(item_ids, full=False)
        if not full:
            return videos
        return [self._hydrate(video) for video in videos]


class SQLiteMetadata(Mapping):
    def __init__(self, connection, table, *, virtual=None):
        self._connection = connection
        self._table = table
        self._virtual = dict(virtual or {})
        self._cache = {}
        self._keys = None

    def __getitem__(self, key):
        if key in self._virtual:
            value = self._virtual[key]
            return value() if callable(value) else value
        if key not in self._cache:
            row = self._connection.execute(
                f"SELECT value FROM {self._table} WHERE key = ?", (str(key),)
            ).fetchone()
            if row is None:
                raise KeyError(key)
            self._cache[key] = json.loads(row[0])
        return self._cache[key]

    def __iter__(self):
        if self._keys is None:
            self._keys = [
                row[0]
                for row in self._connection.execute(
                    f"SELECT key FROM {self._table} ORDER BY key"
                )
            ]
        return iter([*self._keys, *sorted(self._virtual)])

    def __len__(self):
        return sum(1 for _ in self)

    def __contains__(self, key):
        if key in self._virtual:
            return True
        return self._connection.execute(
            f"SELECT 1 FROM {self._table} WHERE key = ?", (str(key),)
        ).fetchone() is not None


class SQLiteChunkIndex(SQLiteMetadata):
    def __init__(self, store):
        self._store = store
        super().__init__(
            store.connection,
            "chunk_metadata",
            virtual={
                "chunks": store.chunks,
                "ngram_vocabulary": self._all_ngrams,
                "ngram_postings": self._all_postings,
            },
        )

    def _all_ngrams(self):
        return [
            row[0]
            for row in self._store.connection.execute(
                "SELECT gram FROM chunk_ngram_postings ORDER BY gram"
            )
        ]

    def _all_postings(self):
        return [
            row[0]
            for row in self._store.connection.execute(
                "SELECT payload FROM chunk_ngram_postings ORDER BY gram"
            )
        ]

    def lookup_ngram_postings(self, grams):
        return self._store.lookup_postings("chunk_ngram_postings", grams)


class SQLiteRetrievalIndex(SQLiteMetadata):
    def __init__(self, store):
        self._store = store
        super().__init__(
            store.connection,
            "retrieval_metadata",
            virtual={
                "videos": store.retrieval_videos,
                "chunk_index": store.chunk_index,
                "ngram_vocabulary": self._all_ngrams,
                "ngram_postings": self._all_postings,
            },
        )

    def _all_ngrams(self):
        return [
            row[0]
            for row in self._store.connection.execute(
                "SELECT gram FROM video_ngram_postings ORDER BY gram"
            )
        ]

    def _all_postings(self):
        return [
            row[0]
            for row in self._store.connection.execute(
                "SELECT payload FROM video_ngram_postings ORDER BY gram"
            )
        ]

    def lookup_ngram_postings(self, grams):
        return self._store.lookup_postings("video_ngram_postings", grams)


class RuntimeStore:
    def __init__(self, path):
        self.path = Path(path)
        uri = f"file:{self.path.resolve().as_posix()}?mode=ro&immutable=1"
        self.connection = sqlite3.connect(uri, uri=True, check_same_thread=False)
        self._connection_finalizer = weakref.finalize(
            self, self.connection.close
        )
        schema_version = int(
            self.connection.execute("PRAGMA user_version").fetchone()[0]
        )
        if schema_version != STORE_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported runtime-store schema {schema_version}; "
                f"expected {STORE_SCHEMA_VERSION}"
            )
        self.transcript_payloads = SQLiteJsonSequence(
            self.connection,
            "transcript_payloads",
            id_column="video_id",
        )
        self.knowledge_videos = SQLiteKnowledgeSequence(
            self.connection, self.transcript_payloads
        )
        self.search_videos = SQLiteJsonSequence(
            self.connection,
            "search_videos",
            id_column="video_id",
        )
        self.retrieval_videos = SQLiteJsonSequence(
            self.connection, "retrieval_videos", id_column="video_id"
        )
        self.chunks = SQLiteJsonSequence(self.connection, "chunks")
        self.chunk_index = SQLiteChunkIndex(self)
        self.knowledge = SQLiteMetadata(
            self.connection,
            "knowledge_metadata",
            virtual={
                "videos": self.knowledge_videos,
                "search_videos": self.search_videos,
            },
        )
        self.retrieval_index = SQLiteRetrievalIndex(self)

    def close(self):
        """Close the backing database; safe to call more than once."""

        self._connection_finalizer()

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        self.close()

    def lookup_postings(self, table, grams):
        ordered = list(dict.fromkeys(str(gram) for gram in grams))
        if not ordered:
            return {}
        found: dict[str, str] = {}
        for offset in range(0, len(ordered), 900):
            batch = ordered[offset : offset + 900]
            placeholders = ",".join("?" for _ in batch)
            rows = self.connection.execute(
                f"SELECT gram, payload FROM {table} "
                f"WHERE gram IN ({placeholders})",
                batch,
            )
            found.update((gram, payload) for gram, payload in rows)
        return found


def video_map(knowledge, video_ids=None, *, full=True):
    """Return only requested videos when the backing sequence supports it."""

    videos = (
        knowledge["videos"]
        if full
        else knowledge.get("search_videos", knowledge["videos"])
    )
    if video_ids is not None and isinstance(videos, SQLiteJsonSequence):
        return SQLiteIdMapping(videos, video_ids, full=full)
    if video_ids is not None and hasattr(videos, "get_many"):
        selected = videos.get_many(video_ids, full=full)
    else:
        requested = None if video_ids is None else set(video_ids)
        selected = (
            video
            for video in videos
            if requested is None or video["video_id"] in requested
        )
    return {video["video_id"]: video for video in selected}
