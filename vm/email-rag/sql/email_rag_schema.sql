-- email-rag schema
-- Layer 1: raw_messages (immutable, SHA-256 as ID)
-- Layer 2: emails, snippets, entities, claims_log, timeline, sender_stats, review_queue
-- Layer 3: findings, snapshots

CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================
-- LAYER 1: RAW MESSAGES — immutable, never updated after insert
-- ============================================================
CREATE TABLE IF NOT EXISTS raw_messages (
    id              TEXT PRIMARY KEY,  -- SHA-256 of raw content
    source          TEXT NOT NULL,     -- gmail, icloud
    corpus          TEXT NOT NULL,     -- sent, subject
    store           TEXT NOT NULL,     -- rolling, archive
    raw_content     TEXT NOT NULL,
    raw_headers     JSONB,
    file_path       TEXT,
    imported_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    subject_priority BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_raw_messages_source ON raw_messages(source);
CREATE INDEX IF NOT EXISTS idx_raw_messages_corpus ON raw_messages(corpus);
CREATE INDEX IF NOT EXISTS idx_raw_messages_store ON raw_messages(store);
CREATE INDEX IF NOT EXISTS idx_raw_messages_imported_at ON raw_messages(imported_at);

-- ============================================================
-- LAYER 2: STRUCTURED DATA — every row links to Layer 1
-- ============================================================

CREATE TABLE IF NOT EXISTS emails (
    id              BIGSERIAL PRIMARY KEY,
    raw_id          TEXT NOT NULL REFERENCES raw_messages(id),
    message_id      TEXT,
    in_reply_to     TEXT,
    thread_id       TEXT,
    from_addr       TEXT NOT NULL,
    to_addrs        TEXT[] NOT NULL DEFAULT '{}',
    cc_addrs        TEXT[] NOT NULL DEFAULT '{}',
    subject         TEXT,
    body_text       TEXT,
    sent_at         TIMESTAMPTZ,
    corpus          TEXT NOT NULL,
    store           TEXT NOT NULL,
    subject_priority BOOLEAN NOT NULL DEFAULT FALSE,
    processed       BOOLEAN NOT NULL DEFAULT FALSE,
    processed_at    TIMESTAMPTZ,
    is_read         BOOLEAN,
    is_flagged      BOOLEAN NOT NULL DEFAULT FALSE,
    is_replied      BOOLEAN NOT NULL DEFAULT FALSE,
    gmail_labels    TEXT[] NOT NULL DEFAULT '{}',
    gmail_thread_id TEXT,
    gmail_message_id TEXT,
    has_attachments BOOLEAN NOT NULL DEFAULT FALSE,
    attachment_count INTEGER NOT NULL DEFAULT 0,
    is_bulk         BOOLEAN NOT NULL DEFAULT FALSE,
    importance      TEXT,
    mail_client     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_emails_raw_id ON emails(raw_id);
CREATE INDEX IF NOT EXISTS idx_emails_thread_id ON emails(thread_id);
CREATE INDEX IF NOT EXISTS idx_emails_from_addr ON emails(from_addr);
CREATE INDEX IF NOT EXISTS idx_emails_sent_at ON emails(sent_at);
CREATE INDEX IF NOT EXISTS idx_emails_corpus ON emails(corpus);
CREATE INDEX IF NOT EXISTS idx_emails_store ON emails(store);
CREATE INDEX IF NOT EXISTS idx_emails_subject_priority ON emails(subject_priority) WHERE subject_priority = TRUE;
CREATE INDEX IF NOT EXISTS idx_emails_is_read ON emails(is_read) WHERE is_read IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_emails_is_flagged ON emails(is_flagged) WHERE is_flagged = TRUE;
CREATE INDEX IF NOT EXISTS idx_emails_gmail_thread_id ON emails(gmail_thread_id) WHERE gmail_thread_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_emails_is_bulk ON emails(is_bulk) WHERE is_bulk = TRUE;
CREATE INDEX IF NOT EXISTS idx_emails_has_attachments ON emails(has_attachments) WHERE has_attachments = TRUE;
CREATE INDEX IF NOT EXISTS idx_emails_gmail_labels ON emails USING GIN(gmail_labels);

CREATE TABLE IF NOT EXISTS snippets (
    id              BIGSERIAL PRIMARY KEY,
    raw_id          TEXT NOT NULL REFERENCES raw_messages(id),
    email_id        BIGINT REFERENCES emails(id),
    content         TEXT NOT NULL,
    embedding       vector(1024),
    store           TEXT NOT NULL,
    chunk_index     INTEGER NOT NULL DEFAULT 0,
    token_count     INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_snippets_raw_id ON snippets(raw_id);
CREATE INDEX IF NOT EXISTS idx_snippets_email_id ON snippets(email_id);
CREATE INDEX IF NOT EXISTS idx_snippets_store ON snippets(store);

CREATE TABLE IF NOT EXISTS entities (
    id              BIGSERIAL PRIMARY KEY,
    raw_id          TEXT NOT NULL REFERENCES raw_messages(id),
    email_id        BIGINT REFERENCES emails(id),
    entity_type     TEXT NOT NULL,
    entity_value    TEXT NOT NULL,
    confidence      REAL,
    context         TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_entities_raw_id ON entities(raw_id);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_value ON entities(entity_value);

CREATE TABLE IF NOT EXISTS claims_log (
    id              BIGSERIAL PRIMARY KEY,
    raw_id          TEXT NOT NULL REFERENCES raw_messages(id),
    email_id        BIGINT REFERENCES emails(id),
    claim_text      TEXT NOT NULL,
    claim_embedding vector(1024),
    claim_type      TEXT,
    speaker         TEXT,
    confidence      REAL,
    contradicts_claim_ids BIGINT[] DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_claims_raw_id ON claims_log(raw_id);
CREATE INDEX IF NOT EXISTS idx_claims_speaker ON claims_log(speaker);

CREATE TABLE IF NOT EXISTS timeline (
    id              BIGSERIAL PRIMARY KEY,
    raw_id          TEXT NOT NULL REFERENCES raw_messages(id),
    email_id        BIGINT REFERENCES emails(id),
    event_date      TIMESTAMPTZ,
    event_type      TEXT NOT NULL,
    description     TEXT NOT NULL,
    participants    TEXT[],
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_timeline_raw_id ON timeline(raw_id);
CREATE INDEX IF NOT EXISTS idx_timeline_event_date ON timeline(event_date);

CREATE TABLE IF NOT EXISTS sender_stats (
    id              BIGSERIAL PRIMARY KEY,
    email_address   TEXT NOT NULL UNIQUE,
    display_name    TEXT,
    total_messages  INTEGER NOT NULL DEFAULT 0,
    first_seen      TIMESTAMPTZ,
    last_seen       TIMESTAMPTZ,
    avg_response_time_hours REAL,
    top_topics      JSONB,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sender_stats_email ON sender_stats(email_address);

CREATE TABLE IF NOT EXISTS review_queue (
    id              BIGSERIAL PRIMARY KEY,
    raw_id          TEXT NOT NULL REFERENCES raw_messages(id),
    email_id        BIGINT REFERENCES emails(id),
    reason          TEXT NOT NULL,
    priority        INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'pending',
    reviewed_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_review_queue_status ON review_queue(status);
CREATE INDEX IF NOT EXISTS idx_review_queue_priority ON review_queue(priority DESC);

-- ============================================================
-- LAYER 3: FINDINGS — must cite Layer 1 email IDs
-- ============================================================

CREATE TABLE IF NOT EXISTS findings (
    id              BIGSERIAL PRIMARY KEY,
    title           TEXT NOT NULL,
    summary         TEXT NOT NULL,
    detail          TEXT,
    finding_type    TEXT NOT NULL,
    grounding       TEXT NOT NULL CHECK (grounding IN ('grounded', 'inferred', 'speculative')),
    supporting_email_ids JSONB NOT NULL,
    inference_score_detail JSONB,
    contradicts_finding_ids JSONB DEFAULT '[]',
    confidence      REAL,
    model_used      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_findings_type ON findings(finding_type);
CREATE INDEX IF NOT EXISTS idx_findings_grounding ON findings(grounding);
CREATE INDEX IF NOT EXISTS idx_findings_created_at ON findings(created_at);

CREATE TABLE IF NOT EXISTS snapshots (
    id              BIGSERIAL PRIMARY KEY,
    snapshot_type   TEXT NOT NULL,
    summary         TEXT NOT NULL,
    findings_ids    BIGINT[] DEFAULT '{}',
    stats           JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- ANOMALIES
-- ============================================================

CREATE TABLE IF NOT EXISTS anomalies (
    id              BIGSERIAL PRIMARY KEY,
    thread_id       TEXT,
    email_id        BIGINT REFERENCES emails(id),
    anomaly_type    TEXT NOT NULL,
    severity        TEXT NOT NULL DEFAULT 'medium',
    title           TEXT NOT NULL,
    detail          TEXT,
    status          TEXT NOT NULL DEFAULT 'open',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_anomalies_severity ON anomalies(severity);
CREATE INDEX IF NOT EXISTS idx_anomalies_type ON anomalies(anomaly_type);
CREATE INDEX IF NOT EXISTS idx_anomalies_status ON anomalies(status);
CREATE INDEX IF NOT EXISTS idx_anomalies_thread_id ON anomalies(thread_id);

-- ============================================================
-- USER FACTS & SUGGESTED QUESTIONS
-- ============================================================

CREATE TABLE IF NOT EXISTS user_facts (
    id              BIGSERIAL PRIMARY KEY,
    category        TEXT NOT NULL,
    subject         TEXT NOT NULL,
    content         TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_facts_category ON user_facts(category);

CREATE TABLE IF NOT EXISTS suggested_questions (
    id              BIGSERIAL PRIMARY KEY,
    question_text   TEXT NOT NULL,
    context         TEXT,
    source_type     TEXT NOT NULL,
    source_email_ids JSONB,
    status          TEXT NOT NULL DEFAULT 'pending',
    suggested_answer TEXT,
    suggested_category TEXT,
    suggested_subject TEXT,
    answer_text     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    answered_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_suggested_questions_status ON suggested_questions(status);
CREATE INDEX IF NOT EXISTS idx_suggested_questions_source_type ON suggested_questions(source_type);

-- ============================================================
-- VECTOR INDEXES
-- ============================================================

-- HNSW on snippets.embedding for archive store
CREATE INDEX IF NOT EXISTS idx_snippets_embedding_archive_hnsw
    ON snippets USING hnsw (embedding vector_cosine_ops)
    WHERE store = 'archive';

-- IVFFlat on snippets.embedding for rolling store
CREATE INDEX IF NOT EXISTS idx_snippets_embedding_rolling_ivfflat
    ON snippets USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100)
    WHERE store = 'rolling';

-- HNSW on claims_log.claim_embedding for contradiction search
CREATE INDEX IF NOT EXISTS idx_claims_embedding_hnsw
    ON claims_log USING hnsw (claim_embedding vector_cosine_ops);

-- ============================================================
-- RULES ENFORCEMENT
-- ============================================================

-- raw_messages immutability trigger
CREATE OR REPLACE FUNCTION prevent_raw_message_update()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'raw_messages is immutable: updates are not allowed';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_raw_messages_immutable ON raw_messages;
CREATE TRIGGER trg_raw_messages_immutable
    BEFORE UPDATE ON raw_messages
    FOR EACH ROW
    EXECUTE FUNCTION prevent_raw_message_update();

-- findings must cite supporting emails
CREATE OR REPLACE FUNCTION validate_finding_citations()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.supporting_email_ids IS NULL OR
       NEW.supporting_email_ids = '[]'::jsonb OR
       jsonb_array_length(NEW.supporting_email_ids) = 0 THEN
        RAISE EXCEPTION 'No receipts, no claims: findings must cite at least one email ID';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_findings_citations ON findings;
CREATE TRIGGER trg_findings_citations
    BEFORE INSERT OR UPDATE ON findings
    FOR EACH ROW
    EXECUTE FUNCTION validate_finding_citations();
