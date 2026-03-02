"""FastAPI application — email-rag API."""

import os
from pathlib import Path

from fastapi import FastAPI, Depends, Query
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from email_rag.db.schema import (
    get_db, Email, RawMessage, Snippet, Finding,
    SenderStats, Timeline, ClaimLog, Snapshot
)
from email_rag.analysis.claude_query import query_claude

app = FastAPI(title="Email RAG", version="1.0.0")

UI_DIR = Path(__file__).parent.parent / "ui"


@app.get("/api/stats")
def get_stats(db: Session = Depends(get_db)):
    """Dashboard statistics."""
    raw_count = db.query(func.count(RawMessage.id)).scalar()
    email_count = db.query(func.count(Email.id)).scalar()
    snippet_count = db.query(func.count(Snippet.id)).scalar()
    finding_count = db.query(func.count(Finding.id)).scalar()
    claim_count = db.query(func.count(ClaimLog.id)).scalar()

    processed = db.query(func.count(Email.id)).filter(Email.processed == True).scalar()
    priority = db.query(func.count(Email.id)).filter(Email.subject_priority == True).scalar()

    rolling = db.query(func.count(RawMessage.id)).filter(RawMessage.store == "rolling").scalar()
    archive = db.query(func.count(RawMessage.id)).filter(RawMessage.store == "archive").scalar()

    # Ollama status
    ollama_status = "unknown"
    try:
        import httpx
        r = httpx.get(f"{os.environ.get('OLLAMA_BASE', 'http://localhost:11434')}/api/version", timeout=3)
        if r.status_code == 200:
            ollama_status = f"v{r.json().get('version', '?')}"
    except Exception:
        ollama_status = "offline"

    return {
        "raw_messages": raw_count,
        "emails": email_count,
        "snippets": snippet_count,
        "findings": finding_count,
        "claims": claim_count,
        "processed": processed,
        "subject_priority": priority,
        "rolling": rolling,
        "archive": archive,
        "ollama": ollama_status,
    }


@app.get("/api/findings")
def get_findings(
    limit: int = Query(20, le=100),
    grounding: str = Query(None),
    db: Session = Depends(get_db),
):
    """List findings."""
    q = db.query(Finding).order_by(Finding.created_at.desc())
    if grounding:
        q = q.filter(Finding.grounding == grounding)
    results = q.limit(limit).all()
    return [
        {
            "id": f.id,
            "title": f.title,
            "summary": f.summary,
            "type": f.finding_type,
            "grounding": f.grounding,
            "confidence": f.confidence,
            "model": f.model_used,
            "created_at": str(f.created_at),
            "supporting_emails": f.supporting_email_ids,
        }
        for f in results
    ]


@app.get("/api/emails")
def get_emails(
    limit: int = Query(50, le=200),
    corpus: str = Query(None),
    priority_only: bool = Query(False),
    db: Session = Depends(get_db),
):
    """List emails."""
    q = db.query(Email).order_by(Email.sent_at.desc().nullslast())
    if corpus:
        q = q.filter(Email.corpus == corpus)
    if priority_only:
        q = q.filter(Email.subject_priority == True)
    results = q.limit(limit).all()
    return [
        {
            "id": e.id,
            "from": e.from_addr,
            "to": e.to_addrs,
            "subject": e.subject,
            "date": str(e.sent_at) if e.sent_at else None,
            "corpus": e.corpus,
            "store": e.store,
            "priority": e.subject_priority,
            "thread_id": e.thread_id,
        }
        for e in results
    ]


@app.get("/api/timeline")
def get_timeline(limit: int = Query(50, le=200), db: Session = Depends(get_db)):
    """Get timeline events."""
    events = db.query(Timeline).order_by(Timeline.event_date.desc().nullslast()).limit(limit).all()
    return [
        {
            "id": t.id,
            "date": str(t.event_date) if t.event_date else None,
            "type": t.event_type,
            "description": t.description,
            "participants": t.participants,
        }
        for t in events
    ]


@app.post("/api/query")
def ask_question(payload: dict):
    """Ask a question using Claude RAG."""
    question = payload.get("question", "")
    if not question:
        return {"error": "No question provided"}
    return query_claude(question)


@app.get("/", response_class=HTMLResponse)
def serve_ui():
    """Serve the web UI."""
    index_path = UI_DIR / "index.html"
    if index_path.exists():
        return index_path.read_text()
    return "<h1>Email RAG</h1><p>UI not found</p>"
