PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS review_events (
    event_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    action TEXT NOT NULL,
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    reviewer_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    base_fingerprint TEXT NOT NULL,
    payload_fingerprint TEXT NOT NULL,
    content_fingerprint TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
    supersedes_event_id TEXT REFERENCES review_events(event_id),
    human_confirmation INTEGER NOT NULL CHECK (human_confirmation IN (0, 1)),
    note TEXT NOT NULL DEFAULT '',
    UNIQUE (entity_type, entity_id, revision)
);

CREATE TABLE IF NOT EXISTS entity_heads (
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    state TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    last_event_id TEXT NOT NULL REFERENCES review_events(event_id),
    payload_fingerprint TEXT NOT NULL,
    content_fingerprint TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
    PRIMARY KEY (entity_type, entity_id)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS entity_dependencies (
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    dependency_type TEXT NOT NULL,
    dependency_id TEXT NOT NULL,
    bound_fingerprint TEXT NOT NULL,
    PRIMARY KEY (
        entity_type,
        entity_id,
        dependency_type,
        dependency_id
    ),
    FOREIGN KEY (entity_type, entity_id)
        REFERENCES entity_heads(entity_type, entity_id)
        ON DELETE CASCADE
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS drafts (
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    base_revision INTEGER NOT NULL CHECK (base_revision >= 0),
    draft_fingerprint TEXT NOT NULL,
    draft_json TEXT NOT NULL CHECK (json_valid(draft_json)),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (entity_type, entity_id)
) WITHOUT ROWID;

CREATE TRIGGER IF NOT EXISTS review_events_no_update
BEFORE UPDATE ON review_events
BEGIN
    SELECT RAISE(ABORT, 'review events are append-only');
END;

CREATE TRIGGER IF NOT EXISTS review_events_no_delete
BEFORE DELETE ON review_events
BEGIN
    SELECT RAISE(ABORT, 'review events are append-only');
END;
