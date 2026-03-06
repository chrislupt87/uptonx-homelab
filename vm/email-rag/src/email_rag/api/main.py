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
    SenderStats, Timeline, ClaimLog, Snapshot,
    UserFact, SuggestedQuestion, Anomaly,
)
from email_rag.analysis.claude_query import query_claude, query_local

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

    flagged = db.query(func.count(Email.id)).filter(Email.is_flagged == True).scalar()
    bulk = db.query(func.count(Email.id)).filter(Email.is_bulk == True).scalar()
    with_attachments = db.query(func.count(Email.id)).filter(Email.has_attachments == True).scalar()
    unread = db.query(func.count(Email.id)).filter(Email.is_read == False).scalar()

    fact_count = db.query(func.count(UserFact.id)).scalar()
    pending_questions = db.query(func.count(SuggestedQuestion.id)).filter(
        SuggestedQuestion.status == "pending"
    ).scalar()

    anomaly_count = db.query(func.count(Anomaly.id)).filter(Anomaly.status == "open").scalar()

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
        "flagged": flagged,
        "bulk": bulk,
        "with_attachments": with_attachments,
        "unread": unread,
        "ollama": ollama_status,
        "facts": fact_count,
        "pending_questions": pending_questions,
        "anomalies": anomaly_count,
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
    bulk: bool = Query(None),
    flagged_only: bool = Query(False),
    has_attachments: bool = Query(None),
    db: Session = Depends(get_db),
):
    """List emails with optional metadata filters."""
    q = db.query(Email).order_by(Email.sent_at.desc().nullslast())
    if corpus:
        q = q.filter(Email.corpus == corpus)
    if priority_only:
        q = q.filter(Email.subject_priority == True)
    if bulk is not None:
        q = q.filter(Email.is_bulk == bulk)
    if flagged_only:
        q = q.filter(Email.is_flagged == True)
    if has_attachments is not None:
        q = q.filter(Email.has_attachments == has_attachments)
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
            "is_read": e.is_read,
            "is_flagged": e.is_flagged,
            "is_replied": e.is_replied,
            "gmail_labels": e.gmail_labels,
            "has_attachments": e.has_attachments,
            "attachment_count": e.attachment_count,
            "is_bulk": e.is_bulk,
            "importance": e.importance,
            "mail_client": e.mail_client,
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


@app.get("/api/models")
def list_models():
    """List available query models."""
    models = [{"id": "claude", "name": "Claude Sonnet 4.6", "type": "api"}]
    # Check workstation models
    for base in [
        os.environ.get("OLLAMA_GPU_BASE", "http://192.168.1.95:11434"),
        os.environ.get("OLLAMA_BASE", "http://localhost:11434"),
    ]:
        try:
            import httpx
            r = httpx.get(f"{base}/api/tags", timeout=3)
            if r.status_code == 200:
                for m in r.json().get("models", []):
                    name = m["name"]
                    # Skip embedding models
                    if "embed" in name or "nomic" in name:
                        continue
                    if not any(x["id"] == name for x in models):
                        size = m.get("details", {}).get("parameter_size", "")
                        models.append({
                            "id": name,
                            "name": f"{name} ({size})",
                            "type": "local",
                        })
                break  # Only use first reachable endpoint
        except Exception:
            continue
    return models


@app.post("/api/query")
def ask_question(payload: dict):
    """Ask a question using Claude or local model RAG."""
    question = payload.get("question", "")
    if not question:
        return {"error": "No question provided"}

    model = payload.get("model", "claude")
    if model == "claude":
        return query_claude(question)
    else:
        return query_local(question, model=model)


## -- Anomalies --

@app.get("/api/anomalies")
def list_anomalies(
    severity: str = Query(None),
    anomaly_type: str = Query(None),
    status: str = Query("open"),
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
):
    """List detected anomalies."""
    q = db.query(Anomaly).order_by(
        text("CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END"),
        Anomaly.created_at.desc(),
    )
    if severity:
        q = q.filter(Anomaly.severity == severity)
    if anomaly_type:
        q = q.filter(Anomaly.anomaly_type == anomaly_type)
    if status:
        q = q.filter(Anomaly.status == status)
    return [
        {
            "id": a.id,
            "thread_id": a.thread_id,
            "email_id": a.email_id,
            "type": a.anomaly_type,
            "severity": a.severity,
            "title": a.title,
            "detail": a.detail,
            "status": a.status,
            "created_at": str(a.created_at),
        }
        for a in q.limit(limit).all()
    ]


@app.post("/api/anomalies/{anomaly_id}/dismiss")
def dismiss_anomaly(anomaly_id: int, db: Session = Depends(get_db)):
    """Dismiss an anomaly."""
    a = db.query(Anomaly).filter(Anomaly.id == anomaly_id).first()
    if not a:
        return {"error": "Anomaly not found"}
    a.status = "dismissed"
    db.commit()
    return {"id": a.id, "status": "dismissed"}


## -- Facts CRUD --

@app.get("/api/facts")
def list_facts(category: str = Query(None), db: Session = Depends(get_db)):
    """List user facts with optional category filter."""
    q = db.query(UserFact).order_by(UserFact.created_at.desc())
    if category:
        q = q.filter(UserFact.category == category)
    return [
        {
            "id": f.id,
            "category": f.category,
            "subject": f.subject,
            "content": f.content,
            "created_at": str(f.created_at),
            "updated_at": str(f.updated_at),
        }
        for f in q.all()
    ]


@app.post("/api/facts")
def create_fact(payload: dict, db: Session = Depends(get_db)):
    """Create a user fact."""
    fact = UserFact(
        category=payload.get("category", "context"),
        subject=payload.get("subject", ""),
        content=payload.get("content", ""),
    )
    db.add(fact)
    db.commit()
    db.refresh(fact)
    return {"id": fact.id, "category": fact.category, "subject": fact.subject, "content": fact.content}


@app.put("/api/facts/{fact_id}")
def update_fact(fact_id: int, payload: dict, db: Session = Depends(get_db)):
    """Update a user fact."""
    fact = db.query(UserFact).filter(UserFact.id == fact_id).first()
    if not fact:
        return {"error": "Fact not found"}
    if "category" in payload:
        fact.category = payload["category"]
    if "subject" in payload:
        fact.subject = payload["subject"]
    if "content" in payload:
        fact.content = payload["content"]
    db.commit()
    return {"id": fact.id, "category": fact.category, "subject": fact.subject, "content": fact.content}


@app.delete("/api/facts/{fact_id}")
def delete_fact(fact_id: int, db: Session = Depends(get_db)):
    """Delete a user fact."""
    fact = db.query(UserFact).filter(UserFact.id == fact_id).first()
    if not fact:
        return {"error": "Fact not found"}
    db.delete(fact)
    db.commit()
    return {"deleted": fact_id}


## -- Questions --

@app.get("/api/questions")
def list_questions(
    status: str = Query(None),
    limit: int = Query(20, le=100),
    db: Session = Depends(get_db),
):
    """List suggested questions."""
    q = db.query(SuggestedQuestion).order_by(SuggestedQuestion.created_at.desc())
    if status:
        q = q.filter(SuggestedQuestion.status == status)
    return [
        {
            "id": sq.id,
            "question_text": sq.question_text,
            "context": sq.context,
            "source_type": sq.source_type,
            "source_email_ids": sq.source_email_ids,
            "status": sq.status,
            "suggested_answer": sq.suggested_answer,
            "suggested_category": sq.suggested_category,
            "suggested_subject": sq.suggested_subject,
            "answer_text": sq.answer_text,
            "created_at": str(sq.created_at),
            "answered_at": str(sq.answered_at) if sq.answered_at else None,
        }
        for sq in q.limit(limit).all()
    ]


@app.post("/api/questions/{question_id}/confirm")
def confirm_question(question_id: int, payload: dict = None, db: Session = Depends(get_db)):
    """Confirm AI-suggested answer, optionally with edits. Always saves as fact."""
    sq = db.query(SuggestedQuestion).filter(SuggestedQuestion.id == question_id).first()
    if not sq:
        return {"error": "Question not found"}

    payload = payload or {}
    answer = payload.get("answer", sq.suggested_answer or "")
    category = payload.get("category", sq.suggested_category or "context")
    subject = payload.get("subject", sq.suggested_subject or "")

    sq.answer_text = answer
    sq.status = "answered"
    sq.answered_at = func.now()

    fact = UserFact(category=category, subject=subject, content=answer)
    db.add(fact)
    db.flush()

    db.commit()
    return {"id": sq.id, "status": "answered", "fact_id": fact.id}


@app.post("/api/questions/{question_id}/answer")
def answer_question(question_id: int, payload: dict, db: Session = Depends(get_db)):
    """Answer a suggested question, optionally saving as a user fact."""
    sq = db.query(SuggestedQuestion).filter(SuggestedQuestion.id == question_id).first()
    if not sq:
        return {"error": "Question not found"}

    sq.answer_text = payload.get("answer", "")
    sq.status = "answered"
    sq.answered_at = func.now()
    db.flush()

    result = {"id": sq.id, "status": "answered"}

    if payload.get("save_as_fact"):
        fact = UserFact(
            category=payload.get("category", "context"),
            subject=payload.get("subject", ""),
            content=payload.get("answer", ""),
        )
        db.add(fact)
        db.flush()
        result["fact_id"] = fact.id

    db.commit()
    return result


@app.post("/api/questions/{question_id}/dismiss")
def dismiss_question(question_id: int, db: Session = Depends(get_db)):
    """Dismiss a suggested question."""
    sq = db.query(SuggestedQuestion).filter(SuggestedQuestion.id == question_id).first()
    if not sq:
        return {"error": "Question not found"}
    sq.status = "dismissed"
    db.commit()
    return {"id": sq.id, "status": "dismissed"}


@app.get("/", response_class=HTMLResponse)
def serve_ui():
    """Serve the web UI."""
    index_path = UI_DIR / "index.html"
    if index_path.exists():
        return index_path.read_text()
    return "<h1>Email RAG</h1><p>UI not found</p>"
