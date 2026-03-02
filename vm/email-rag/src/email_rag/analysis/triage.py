"""Triage — dolphin3:8b for fast email classification and embedding."""

import os
import httpx
from sqlalchemy.orm import Session
from tqdm import tqdm

from email_rag.db.schema import SessionLocal, Email, Snippet

OLLAMA_BASE = os.environ.get("OLLAMA_BASE", "http://localhost:11434")
EMBED_MODEL = "snowflake-arctic-embed2"
TRIAGE_MODEL = "dolphin3:8b"
CHUNK_SIZE = 512  # tokens approx


def get_embedding(text: str) -> list[float]:
    """Get embedding from Ollama."""
    resp = httpx.post(
        f"{OLLAMA_BASE}/api/embed",
        json={"model": EMBED_MODEL, "input": text},
        timeout=60.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["embeddings"][0]


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE) -> list[str]:
    """Split text into chunks by approximate token count."""
    words = text.split()
    chunks = []
    for i in range(0, len(words), chunk_size):
        chunk = " ".join(words[i : i + chunk_size])
        if chunk.strip():
            chunks.append(chunk)
    return chunks if chunks else [text[:100]]


def triage_emails():
    """Process unprocessed emails: chunk, embed, store snippets."""
    db: Session = SessionLocal()

    try:
        unprocessed = (
            db.query(Email)
            .filter(Email.processed == False)
            .order_by(Email.sent_at.asc().nullslast())
            .all()
        )

        if not unprocessed:
            print("No unprocessed emails found")
            return

        print(f"Processing {len(unprocessed)} emails")

        for em in tqdm(unprocessed, desc="Triage"):
            if not em.body_text:
                em.processed = True
                continue

            chunks = chunk_text(em.body_text)

            for i, chunk in enumerate(chunks):
                try:
                    embedding = get_embedding(chunk)
                    snippet = Snippet(
                        raw_id=em.raw_id,
                        email_id=em.id,
                        content=chunk,
                        embedding=embedding,
                        store=em.store,
                        chunk_index=i,
                        token_count=len(chunk.split()),
                    )
                    db.add(snippet)
                except Exception as e:
                    print(f"Embedding error for email {em.id} chunk {i}: {e}")

            em.processed = True

            if em.id % 50 == 0:
                db.commit()

        db.commit()
        print(f"Triage complete: {len(unprocessed)} emails processed")

    finally:
        db.close()
