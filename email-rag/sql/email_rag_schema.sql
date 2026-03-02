-- email_rag_schema.sql — Phase 1 Foundation
-- Complete DDL for 3-layer forensic email intelligence schema
-- Requires: PostgreSQL 16+, pgvector extension

BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

--------------------------------------------------------------------------------
-- LAYER 1: Raw Evidence (immutable)
--------------------------------------------------------------------------------

CREATE TABLE raw_messages (
    id          TEXT PRIMARY KEY,          -- SHA-256 hex of raw RFC822 content
    raw_content TEXT NOT NULL,
    source_file TEXT,                      -- original .eml filename (NULL for Gmail)
    store       TEXT NOT NULL CHECK (store IN ('rolling', 'archive')),
    imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    size_bytes  INTEGER
);

-- Immutability trigger: block all updates
CREATE OR REPLACE FUNCTION raw_messages_immutable()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'raw_messages is immutable — updates are not allowed';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_raw_messages_immutable
    BEFORE UPDATE ON raw_messages
    FOR EACH ROW
    EXECUTE FUNCTION raw_messages_immutable();

--------------------------------------------------------------------------------
-- LAYER 3: Snapshots (no FK deps, referenced by findings)
--------------------------------------------------------------------------------

CREATE TABLE snapshots (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata    JSONB
);

--------------------------------------------------------------------------------
-- LAYER 2: Parsed Emails
--------------------------------------------------------------------------------

CREATE TABLE emails (
    id                SERIAL PRIMARY KEY,
    raw_id            TEXT NOT NULL REFERENCES raw_messages(id),
    message_id        TEXT,               -- Message-ID header
    thread_id         TEXT,               -- assigned by thread reconstruction
    in_reply_to       TEXT,               -- In-Reply-To header
    references_header TEXT,               -- References header (space-delimited)
    from_addr         TEXT,
    to_addrs          TEXT[],
    cc_addrs          TEXT[],
    bcc_addrs         TEXT[],
    subject           TEXT,
    date_sent         TIMESTAMPTZ,
    body_text         TEXT,
    body_html         TEXT,
    store             TEXT NOT NULL CHECK (store IN ('rolling', 'archive')),
    corpus            TEXT NOT NULL CHECK (corpus IN ('sent', 'subject', 'other')),
    subject_priority  BOOLEAN NOT NULL DEFAULT FALSE,
    -- Gmail-specific metadata (NULL for .eml imports)
    gmail_labels      TEXT[],
    gmail_read        BOOLEAN,
    gmail_starred     BOOLEAN,
    gmail_importance  TEXT,

    UNIQUE (raw_id, store)
);

CREATE INDEX idx_emails_raw_id ON emails(raw_id);
CREATE INDEX idx_emails_thread_id ON emails(thread_id);
CREATE INDEX idx_emails_from_addr ON emails(from_addr);
CREATE INDEX idx_emails_date_sent ON emails(date_sent);
CREATE INDEX idx_emails_corpus ON emails(corpus);
CREATE INDEX idx_emails_subject_priority ON emails(subject_priority);
CREATE INDEX idx_emails_to_addrs ON emails USING GIN(to_addrs);
CREATE INDEX idx_emails_cc_addrs ON emails USING GIN(cc_addrs);

--------------------------------------------------------------------------------
-- LAYER 2: Snippets (chunks with vector embeddings)
--------------------------------------------------------------------------------

CREATE TABLE snippets (
    id          SERIAL PRIMARY KEY,
    email_id    INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
    raw_id      TEXT NOT NULL REFERENCES raw_messages(id),
    chunk_index INTEGER NOT NULL,         -- ordering within the email
    content     TEXT NOT NULL,
    embedding   vector(1024),             -- NULL in Phase 1; snowflake-arctic-embed2
    store       TEXT NOT NULL CHECK (store IN ('rolling', 'archive')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- HNSW index for archive (static data, better recall)
CREATE INDEX idx_snippets_embedding_archive
    ON snippets USING hnsw (embedding vector_cosine_ops)
    WHERE store = 'archive';

-- IVFFlat index for rolling (needs REINDEX after bulk loads)
-- Note: IVFFlat requires data to exist; create after initial load
-- CREATE INDEX idx_snippets_embedding_rolling
--     ON snippets USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)
--     WHERE store = 'rolling';

--------------------------------------------------------------------------------
-- LAYER 2: Entities
--------------------------------------------------------------------------------

CREATE TABLE entities (
    id          SERIAL PRIMARY KEY,
    email_id    INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
    raw_id      TEXT NOT NULL REFERENCES raw_messages(id),
    entity_type TEXT NOT NULL,            -- person, place, promise, boundary, financial, legal
    name        TEXT NOT NULL,
    context     TEXT,                      -- surrounding text snippet
    confidence  REAL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_entities_type ON entities(entity_type);
CREATE INDEX idx_entities_email_id ON entities(email_id);

--------------------------------------------------------------------------------
-- LAYER 2: Claims Log
--------------------------------------------------------------------------------

CREATE TABLE claims_log (
    id                   SERIAL PRIMARY KEY,
    claim_text           TEXT NOT NULL,
    claim_embedding      vector(1024),    -- for semantic contradiction search
    source               TEXT NOT NULL,    -- email_id ref or 'known_facts_seed'
    source_email_id      INTEGER REFERENCES emails(id) ON DELETE SET NULL,
    date_of_claim        TIMESTAMPTZ,
    verified             BOOLEAN,
    contradicts_claim_ids JSONB,          -- array of claim IDs
    metadata             JSONB,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_claims_log_source ON claims_log(source);
CREATE INDEX idx_claims_log_verified ON claims_log(verified);
CREATE INDEX idx_claims_log_embedding
    ON claims_log USING hnsw (claim_embedding vector_cosine_ops);

--------------------------------------------------------------------------------
-- LAYER 2: Timeline
--------------------------------------------------------------------------------

CREATE TABLE timeline (
    id          SERIAL PRIMARY KEY,
    email_id    INTEGER REFERENCES emails(id) ON DELETE SET NULL,
    event_date  TIMESTAMPTZ NOT NULL,
    event_type  TEXT NOT NULL,
    summary     TEXT NOT NULL,
    participants TEXT[],
    source      TEXT,                     -- how this was derived
    confidence  REAL,
    metadata    JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_timeline_date ON timeline(event_date);
CREATE INDEX idx_timeline_type ON timeline(event_type);

--------------------------------------------------------------------------------
-- LAYER 2: Sender Stats (materialized)
--------------------------------------------------------------------------------

CREATE TABLE sender_stats (
    from_addr       TEXT PRIMARY KEY,
    total_count     INTEGER NOT NULL DEFAULT 0,
    sent_count      INTEGER NOT NULL DEFAULT 0,
    subject_count   INTEGER NOT NULL DEFAULT 0,
    other_count     INTEGER NOT NULL DEFAULT 0,
    priority_count  INTEGER NOT NULL DEFAULT 0,
    first_seen      TIMESTAMPTZ,
    last_seen       TIMESTAMPTZ,
    refreshed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Refresh function: truncate and rebuild from emails
CREATE OR REPLACE FUNCTION refresh_sender_stats()
RETURNS VOID AS $$
BEGIN
    TRUNCATE sender_stats;
    INSERT INTO sender_stats (
        from_addr, total_count, sent_count, subject_count,
        other_count, priority_count, first_seen, last_seen, refreshed_at
    )
    SELECT
        from_addr,
        COUNT(*)                                        AS total_count,
        COUNT(*) FILTER (WHERE corpus = 'sent')         AS sent_count,
        COUNT(*) FILTER (WHERE corpus = 'subject')      AS subject_count,
        COUNT(*) FILTER (WHERE corpus = 'other')        AS other_count,
        COUNT(*) FILTER (WHERE subject_priority = TRUE)  AS priority_count,
        MIN(date_sent)                                  AS first_seen,
        MAX(date_sent)                                  AS last_seen,
        NOW()                                           AS refreshed_at
    FROM emails
    WHERE from_addr IS NOT NULL
    GROUP BY from_addr;
END;
$$ LANGUAGE plpgsql;

--------------------------------------------------------------------------------
-- LAYER 2: Review Queue
--------------------------------------------------------------------------------

CREATE TABLE review_queue (
    id          SERIAL PRIMARY KEY,
    email_id    INTEGER REFERENCES emails(id) ON DELETE CASCADE,
    raw_id      TEXT REFERENCES raw_messages(id),
    reason      TEXT NOT NULL,            -- parse_error, flagged, contradiction, etc.
    details     TEXT,
    resolved    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

CREATE INDEX idx_review_queue_resolved ON review_queue(resolved);

--------------------------------------------------------------------------------
-- LAYER 3: Findings (AI outputs with mandatory citations)
--------------------------------------------------------------------------------

CREATE TABLE findings (
    id                      SERIAL PRIMARY KEY,
    snapshot_id             INTEGER REFERENCES snapshots(id) ON DELETE SET NULL,
    title                   TEXT NOT NULL,
    body                    TEXT NOT NULL,
    supporting_email_ids    JSONB NOT NULL CHECK (jsonb_array_length(supporting_email_ids) > 0),
    grounding               TEXT NOT NULL CHECK (grounding IN ('grounded', 'inferred', 'speculative')),
    contradicts_finding_ids JSONB,        -- array of finding IDs
    inference_score_detail  JSONB,
    tags                    TEXT[],
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_findings_snapshot ON findings(snapshot_id);
CREATE INDEX idx_findings_grounding ON findings(grounding);

COMMIT;
