-- Anomaly detection table
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
