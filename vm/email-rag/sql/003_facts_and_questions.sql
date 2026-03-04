-- Migration 003: User facts and suggested questions
-- User facts: background knowledge injected into RAG + analysis context
-- Suggested questions: system-generated questions from analysis gaps

CREATE TABLE IF NOT EXISTS user_facts (
    id              BIGSERIAL PRIMARY KEY,
    category        TEXT NOT NULL,          -- person, relationship, place, event, context
    subject         TEXT NOT NULL,          -- Short label ("Cody")
    content         TEXT NOT NULL,          -- Full description ("My son, age 5")
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_facts_category ON user_facts(category);

CREATE TABLE IF NOT EXISTS suggested_questions (
    id              BIGSERIAL PRIMARY KEY,
    question_text   TEXT NOT NULL,
    context         TEXT,                   -- Why this matters
    source_type     TEXT NOT NULL,          -- analysis, entity, gap
    source_email_ids JSONB,                -- Which emails triggered it
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending, answered, dismissed
    answer_text     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    answered_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_suggested_questions_status ON suggested_questions(status);
CREATE INDEX IF NOT EXISTS idx_suggested_questions_source_type ON suggested_questions(source_type);
