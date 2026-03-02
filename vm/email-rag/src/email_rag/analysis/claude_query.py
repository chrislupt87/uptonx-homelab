"""Claude query — claude-sonnet-4-6 for interactive UI queries."""

import json
import os

import anthropic
import httpx
from sqlalchemy.orm import Session

from email_rag.db.schema import SessionLocal, Snippet, Email, Finding

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OLLAMA_BASE = os.environ.get("OLLAMA_BASE", "http://localhost:11434")
EMBED_MODEL = "snowflake-arctic-embed2"


def get_embedding(text: str) -> list[float]:
    resp = httpx.post(
        f"{OLLAMA_BASE}/api/embed",
        json={"model": EMBED_MODEL, "input": text},
        timeout=60.0,
    )
    resp.raise_for_status()
    return resp.json()["embeddings"][0]


def search_snippets(query: str, db: Session, limit: int = 10) -> list[dict]:
    """Vector search for relevant email snippets."""
    query_embedding = get_embedding(query)

    results = (
        db.query(Snippet, Email)
        .join(Email, Snippet.email_id == Email.id)
        .order_by(Snippet.embedding.cosine_distance(query_embedding))
        .limit(limit)
        .all()
    )

    return [
        {
            "content": s.content,
            "from": e.from_addr,
            "to": e.to_addrs,
            "subject": e.subject,
            "date": str(e.sent_at) if e.sent_at else None,
            "raw_id": s.raw_id,
            "corpus": e.corpus,
            "priority": e.subject_priority,
        }
        for s, e in results
    ]


def get_recent_findings(db: Session, limit: int = 5) -> list[dict]:
    """Get recent findings for context."""
    findings = (
        db.query(Finding)
        .order_by(Finding.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "title": f.title,
            "summary": f.summary,
            "grounding": f.grounding,
            "type": f.finding_type,
        }
        for f in findings
    ]


def query_claude(question: str) -> dict:
    """Answer a question using Claude with RAG context."""
    if not ANTHROPIC_API_KEY:
        return {"answer": "ANTHROPIC_API_KEY not configured", "sources": []}

    db: Session = SessionLocal()

    try:
        snippets = search_snippets(question, db)
        findings = get_recent_findings(db)

        context = "## Relevant Email Excerpts\n\n"
        for i, s in enumerate(snippets, 1):
            context += (
                f"### Source {i} (raw_id: {s['raw_id']})\n"
                f"From: {s['from']} | To: {s['to']} | Date: {s['date']}\n"
                f"Subject: {s['subject']}\n"
                f"Priority: {s['priority']} | Corpus: {s['corpus']}\n\n"
                f"{s['content']}\n\n"
            )

        if findings:
            context += "## Recent Analysis Findings\n\n"
            for f in findings:
                context += f"- [{f['grounding']}] {f['title']}: {f['summary']}\n"

        system_prompt = (
            "You are an email intelligence analyst. Answer questions based ONLY on "
            "the provided email excerpts and findings. Always cite source raw_ids. "
            "Classify your confidence: grounded (directly from emails), inferred "
            "(reasonable conclusion), or speculative (possible but uncertain). "
            "If you cannot answer from the provided context, say so."
        )

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-sonnet-4-6-20250514",
            max_tokens=2048,
            system=system_prompt,
            messages=[
                {"role": "user", "content": f"{context}\n\n## Question\n{question}"}
            ],
        )

        answer = response.content[0].text
        sources = [s["raw_id"] for s in snippets]

        return {"answer": answer, "sources": sources}

    finally:
        db.close()
