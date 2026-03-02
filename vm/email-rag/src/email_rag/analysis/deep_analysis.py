"""Deep analysis — dolphin3:70b batch processing for findings."""

import json
import os
import httpx
from sqlalchemy.orm import Session
from tqdm import tqdm

from email_rag.db.schema import SessionLocal, Email, Finding, ClaimLog

OLLAMA_BASE = os.environ.get("OLLAMA_BASE", "http://localhost:11434")
DEEP_MODEL = "qwen2.5:72b"

ANALYSIS_PROMPT = """Analyze this email thread and extract:
1. Key claims or assertions made by each party
2. Any contradictions with known facts
3. Timeline events with dates
4. Behavioral patterns (tone shifts, evasion, promises)

For each finding, classify as: grounded (directly stated), inferred (reasonable conclusion), or speculative (possible but uncertain).

Email thread:
{thread_text}

Respond in JSON format:
{{
    "claims": [
        {{"text": "...", "speaker": "...", "type": "factual|promise|opinion", "confidence": 0.0-1.0}}
    ],
    "findings": [
        {{"title": "...", "summary": "...", "type": "pattern|contradiction|timeline_gap|behavioral", "grounding": "grounded|inferred|speculative", "confidence": 0.0-1.0}}
    ],
    "timeline_events": [
        {{"date": "...", "type": "...", "description": "..."}}
    ]
}}"""


def ollama_generate(prompt: str, model: str = DEEP_MODEL) -> str:
    """Generate text with Ollama."""
    resp = httpx.post(
        f"{OLLAMA_BASE}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 2048},
        },
        timeout=600.0,
    )
    resp.raise_for_status()
    return resp.json()["response"]


def analyze_thread(thread_id: str, db: Session):
    """Run deep analysis on a single thread."""
    emails = (
        db.query(Email)
        .filter(Email.thread_id == thread_id)
        .order_by(Email.sent_at.asc().nullslast())
        .all()
    )

    if not emails:
        return

    thread_text = "\n\n---\n\n".join(
        f"From: {em.from_addr}\nTo: {', '.join(em.to_addrs or [])}\n"
        f"Date: {em.sent_at}\nSubject: {em.subject}\n\n{em.body_text or ''}"
        for em in emails
    )

    raw_ids = [em.raw_id for em in emails]

    try:
        response = ollama_generate(ANALYSIS_PROMPT.format(thread_text=thread_text[:8000]))
        # Try to parse JSON from the response
        json_start = response.find("{")
        json_end = response.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            result = json.loads(response[json_start:json_end])
        else:
            return

        # Store claims
        for claim_data in result.get("claims", []):
            claim = ClaimLog(
                raw_id=raw_ids[0],
                email_id=emails[0].id,
                claim_text=claim_data["text"],
                claim_type=claim_data.get("type", "factual"),
                speaker=claim_data.get("speaker"),
                confidence=claim_data.get("confidence", 0.5),
            )
            db.add(claim)

        # Store findings
        for finding_data in result.get("findings", []):
            finding = Finding(
                title=finding_data["title"],
                summary=finding_data["summary"],
                finding_type=finding_data.get("type", "pattern"),
                grounding=finding_data.get("grounding", "inferred"),
                supporting_email_ids=json.dumps(raw_ids),
                confidence=finding_data.get("confidence", 0.5),
                model_used=DEEP_MODEL,
            )
            db.add(finding)

    except Exception as e:
        print(f"Analysis error for thread {thread_id}: {e}")


def run_deep_analysis():
    """Run deep analysis on all threads with subject_priority emails."""
    db: Session = SessionLocal()

    try:
        # Get threads that have subject_priority emails
        priority_threads = (
            db.query(Email.thread_id)
            .filter(Email.subject_priority == True, Email.thread_id.isnot(None))
            .distinct()
            .all()
        )

        thread_ids = [t[0] for t in priority_threads]
        print(f"Running deep analysis on {len(thread_ids)} priority threads")

        for tid in tqdm(thread_ids, desc="Deep analysis"):
            analyze_thread(tid, db)
            db.commit()

        print("Deep analysis complete")
    finally:
        db.close()
