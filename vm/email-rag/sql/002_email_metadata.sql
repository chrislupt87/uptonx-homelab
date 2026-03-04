-- Migration: add email metadata columns
-- Run: psql -U email_rag_user -d email_rag -f sql/002_email_metadata.sql

ALTER TABLE emails ADD COLUMN IF NOT EXISTS is_read BOOLEAN;
ALTER TABLE emails ADD COLUMN IF NOT EXISTS is_flagged BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE emails ADD COLUMN IF NOT EXISTS is_replied BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE emails ADD COLUMN IF NOT EXISTS gmail_labels TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE emails ADD COLUMN IF NOT EXISTS gmail_thread_id TEXT;
ALTER TABLE emails ADD COLUMN IF NOT EXISTS gmail_message_id TEXT;
ALTER TABLE emails ADD COLUMN IF NOT EXISTS has_attachments BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE emails ADD COLUMN IF NOT EXISTS attachment_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE emails ADD COLUMN IF NOT EXISTS is_bulk BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE emails ADD COLUMN IF NOT EXISTS importance TEXT;
ALTER TABLE emails ADD COLUMN IF NOT EXISTS mail_client TEXT;

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_emails_is_read ON emails(is_read) WHERE is_read IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_emails_is_flagged ON emails(is_flagged) WHERE is_flagged = TRUE;
CREATE INDEX IF NOT EXISTS idx_emails_gmail_thread_id ON emails(gmail_thread_id) WHERE gmail_thread_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_emails_is_bulk ON emails(is_bulk) WHERE is_bulk = TRUE;
CREATE INDEX IF NOT EXISTS idx_emails_has_attachments ON emails(has_attachments) WHERE has_attachments = TRUE;
CREATE INDEX IF NOT EXISTS idx_emails_gmail_labels ON emails USING GIN(gmail_labels);
