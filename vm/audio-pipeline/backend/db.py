import sqlite3
import json
import os
from pathlib import Path
from datetime import datetime

DB_PATH = os.getenv("AUDIO_DB_PATH", "/data/audio_pipeline.db")


def get_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            file_size INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            analysis_json TEXT,
            params_json TEXT,
            processed_analysis_json TEXT,
            transcript_json TEXT,
            file_hashes_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC);
    """)
    conn.close()


def save_job(job_id, filename, file_size=None, analysis=None, file_hashes=None):
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO jobs (id, filename, file_size, analysis_json, file_hashes_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (job_id, filename, file_size,
         json.dumps(analysis) if analysis else None,
         json.dumps(file_hashes) if file_hashes else None)
    )
    conn.commit()
    conn.close()


def update_job_processing(job_id, params, processed_analysis):
    conn = get_db()
    conn.execute(
        "UPDATE jobs SET params_json = ?, processed_analysis_json = ? WHERE id = ?",
        (json.dumps(params), json.dumps(processed_analysis), job_id)
    )
    conn.commit()
    conn.close()


def update_job_transcript(job_id, transcript):
    conn = get_db()
    conn.execute(
        "UPDATE jobs SET transcript_json = ? WHERE id = ?",
        (json.dumps(transcript), job_id)
    )
    conn.commit()
    conn.close()


def get_job(job_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return _row_to_dict(row)


def list_jobs(limit=50, offset=0):
    conn = get_db()
    rows = conn.execute(
        "SELECT id, filename, file_size, created_at, "
        "CASE WHEN transcript_json IS NOT NULL THEN 1 ELSE 0 END as has_transcript, "
        "CASE WHEN processed_analysis_json IS NOT NULL THEN 1 ELSE 0 END as has_processing "
        "FROM jobs ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (limit, offset)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _row_to_dict(row):
    d = dict(row)
    for key in ['analysis_json', 'params_json', 'processed_analysis_json',
                'transcript_json', 'file_hashes_json']:
        short = key.replace('_json', '')
        if d.get(key):
            d[short] = json.loads(d[key])
        else:
            d[short] = None
        del d[key]
    return d
