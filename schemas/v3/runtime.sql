PRAGMA foreign_keys = ON;
PRAGMA user_version = 3;

CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
) WITHOUT ROWID;
CREATE TABLE sources (
    source_id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    alternate_urls_json TEXT NOT NULL CHECK (json_valid(alternate_urls_json)),
    title TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE teaching_events (
    teaching_event_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    start_ms INTEGER NOT NULL CHECK (start_ms >= 0),
    end_ms INTEGER NOT NULL CHECK (end_ms > start_ms),
    modality TEXT NOT NULL CHECK (modality IN ('language', 'visual', 'multimodal')),
    evidence_boundary TEXT NOT NULL,
    evidence_text TEXT NOT NULL,
    visual_observation TEXT NOT NULL,
    viewing_value TEXT NOT NULL,
    watch_focus TEXT NOT NULL,
    formal_projection_sha256 TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE semantic_claims (
    claim_id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    symptoms_json TEXT NOT NULL CHECK (json_valid(symptoms_json)),
    applicability_json TEXT NOT NULL CHECK (json_valid(applicability_json)),
    mechanism TEXT NOT NULL,
    correction_direction TEXT NOT NULL,
    exclusions_json TEXT NOT NULL CHECK (json_valid(exclusions_json)),
    confidence TEXT NOT NULL CHECK (confidence IN ('low', 'medium', 'high')),
    training_method TEXT NOT NULL,
    search_text TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE claim_aliases (
    claim_id TEXT NOT NULL REFERENCES semantic_claims(claim_id),
    alias TEXT NOT NULL,
    PRIMARY KEY (claim_id, alias)
) WITHOUT ROWID;

CREATE TABLE claim_supports (
    claim_id TEXT NOT NULL REFERENCES semantic_claims(claim_id),
    teaching_event_id TEXT NOT NULL REFERENCES teaching_events(teaching_event_id),
    PRIMARY KEY (claim_id, teaching_event_id)
) WITHOUT ROWID;
