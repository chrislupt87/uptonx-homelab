"""Query module — Claude API or local Ollama for interactive UI queries."""

import json
import os

import anthropic
import httpx
from sqlalchemy.orm import Session

from email_rag.db.schema import SessionLocal, Snippet, Email, Finding, UserFact

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OLLAMA_BASE = os.environ.get("OLLAMA_BASE", "http://localhost:11434")
OLLAMA_GPU_BASE = os.environ.get("OLLAMA_GPU_BASE", "http://192.168.1.95:11434")
EMBED_MODEL = "snowflake-arctic-embed2"
LOCAL_QUERY_MODEL = os.environ.get("LOCAL_QUERY_MODEL", "dolphin3:8b")


def get_embedding(text: str) -> list[float]:
    """Get embedding from GPU (workstation) with CPU fallback."""
    for base in [OLLAMA_GPU_BASE, OLLAMA_BASE]:
        try:
            resp = httpx.post(
                f"{base}/api/embed",
                json={"model": EMBED_MODEL, "input": text},
                timeout=30.0,
            )
            resp.raise_for_status()
            return resp.json()["embeddings"][0]
        except Exception:
            continue
    raise RuntimeError("All Ollama endpoints failed for embedding")


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
            "is_read": e.is_read,
            "is_flagged": e.is_flagged,
            "is_replied": e.is_replied,
            "gmail_labels": e.gmail_labels or [],
            "has_attachments": e.has_attachments,
            "attachment_count": e.attachment_count,
            "is_bulk": e.is_bulk,
            "importance": e.importance,
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


SYSTEM_PROMPT = (
    "You are an email intelligence analyst. Answer questions based ONLY on "
    "the provided email excerpts and findings. Always cite source raw_ids. "
    "Classify your confidence: grounded (directly from emails), inferred "
    "(reasonable conclusion), or speculative (possible but uncertain). "
    "If you cannot answer from the provided context, say so."
)


def get_user_facts(db: Session) -> list[dict]:
    """Load all user facts for context injection."""
    facts = db.query(UserFact).order_by(UserFact.category, UserFact.subject).all()
    return [
        {"category": f.category, "subject": f.subject, "content": f.content}
        for f in facts
    ]


def _build_context(snippets: list[dict], findings: list[dict], facts: list[dict] = None) -> str:
    """Build RAG context string from snippets, findings, and user facts."""
    context = ""

    if facts:
        context += "## Background Knowledge\n\n"
        for f in facts:
            context += f"- **{f['subject']}** ({f['category']}): {f['content']}\n"
        context += "\n"

    context += "## Relevant Email Excerpts\n\n"
    for i, s in enumerate(snippets, 1):
        labels = ", ".join(s.get("gmail_labels") or [])
        meta_parts = []
        if s.get("is_read") is not None:
            meta_parts.append(f"Read: {s['is_read']}")
        if s.get("is_flagged"):
            meta_parts.append("Flagged")
        if s.get("is_replied"):
            meta_parts.append("Replied")
        if s.get("has_attachments"):
            meta_parts.append(f"Attachments: {s.get('attachment_count', 0)}")
        if s.get("is_bulk"):
            meta_parts.append("Bulk")
        if s.get("importance"):
            meta_parts.append(f"Importance: {s['importance']}")
        meta_line = " | ".join(meta_parts) if meta_parts else ""

        context += (
            f"### Source {i} (raw_id: {s['raw_id']})\n"
            f"From: {s['from']} | To: {s['to']} | Date: {s['date']}\n"
            f"Subject: {s['subject']}\n"
            f"Priority: {s['priority']} | Corpus: {s['corpus']}\n"
        )
        if meta_line:
            context += f"{meta_line}\n"
        if labels:
            context += f"Labels: {labels}\n"
        context += f"\n{s['content']}\n\n"
    if findings:
        context += "## Recent Analysis Findings\n\n"
        for f in findings:
            context += f"- [{f['grounding']}] {f['title']}: {f['summary']}\n"
    return context


def query_claude(question: str) -> dict:
    """Answer a question using Claude with RAG context."""
    if not ANTHROPIC_API_KEY:
        return {"answer": "ANTHROPIC_API_KEY not configured", "sources": []}

    db: Session = SessionLocal()
    try:
        snippets = search_snippets(question, db)
        findings = get_recent_findings(db)
        facts = get_user_facts(db)
        context = _build_context(snippets, findings, facts)

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": f"{context}\n\n## Question\n{question}"}
            ],
        )

        return {
            "answer": response.content[0].text,
            "sources": [s["raw_id"] for s in snippets],
            "model": "claude-sonnet-4-6",
        }
    finally:
        db.close()


def query_local(question: str, model: str = None) -> dict:
    """Answer a question using a local Ollama model with RAG context."""
    model = model or LOCAL_QUERY_MODEL
    db: Session = SessionLocal()
    try:
        snippets = search_snippets(question, db)
        findings = get_recent_findings(db)
        facts = get_user_facts(db)
        context = _build_context(snippets, findings, facts)

        prompt = f"{SYSTEM_PROMPT}\n\n{context}\n\n## Question\n{question}"

        for base in [OLLAMA_GPU_BASE, OLLAMA_BASE]:
            try:
                resp = httpx.post(
                    f"{base}/api/generate",
                    json={
                        "model": model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": 0.3, "num_predict": 2048},
                    },
                    timeout=120.0,
                )
                resp.raise_for_status()
                return {
                    "answer": resp.json()["response"],
                    "sources": [s["raw_id"] for s in snippets],
                    "model": model,
                }
            except Exception:
                continue

        return {"answer": f"All Ollama endpoints failed for model {model}", "sources": []}
    finally:
        db.close()
