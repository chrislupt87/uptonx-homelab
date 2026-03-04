"""Deep analysis — qwen2.5:72b batch processing for findings."""

import json
import os
import httpx
from sqlalchemy.orm import Session
from tqdm import tqdm

from email_rag.db.schema import SessionLocal, Email, Finding, ClaimLog, UserFact, SuggestedQuestion

OLLAMA_BASE = os.environ.get("OLLAMA_BASE", "http://localhost:11434")
OLLAMA_GPU_BASE = os.environ.get("OLLAMA_GPU_BASE", "http://192.168.1.95:11434")
DEEP_MODEL = os.environ.get("DEEP_MODEL", "dolphin3:8b")

VALID_FINDING_TYPES = {"pattern", "contradiction", "timeline_gap", "behavioral"}
VALID_GROUNDINGS = {"grounded", "inferred", "speculative"}
VALID_CLAIM_TYPES = {"factual", "promise", "opinion"}

ANALYSIS_PROMPT = """Analyze this email thread and extract:
1. Key claims or assertions made by each party
2. Any contradictions with known facts
3. Timeline events with dates
4. Behavioral patterns (tone shifts, evasion, promises)
5. Questions about unknowns — people, places, or gaps that need clarification

For each finding, classify the grounding as ONE of: grounded, inferred, speculative.
For each finding type, pick ONE of: pattern, contradiction, timeline_gap, behavioral.
For each claim type, pick ONE of: factual, promise, opinion.
For each question, classify source_type as ONE of: entity (unknown person/place), gap (missing timeline info), analysis (deeper insight needed).
{background_knowledge}
Email thread:
{thread_text}

Respond in JSON format:
{{
    "claims": [
        {{"text": "...", "speaker": "...", "type": "factual", "confidence": 0.8}}
    ],
    "findings": [
        {{"title": "...", "summary": "...", "type": "pattern", "grounding": "grounded", "confidence": 0.8}}
    ],
    "questions": [
        {{"question": "...", "context": "Why this matters", "source_type": "entity"}}
    ]
}}"""


def sanitize_enum(value: str, valid_set: set, default: str) -> str:
    """Pick a valid enum value from possibly malformed LLM output."""
    if not value or not isinstance(value, str):
        return default
    value = value.strip().lower()
    if value in valid_set:
        return value
    # Model may have returned "pattern|contradiction" — pick first valid one
    for part in value.replace("|", ",").replace("/", ",").split(","):
        part = part.strip()
        if part in valid_set:
            return part
    return default


def ollama_generate(prompt: str, model: str = DEEP_MODEL) -> str:
    """Generate text with Ollama GPU (workstation) with CPU fallback."""
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
                timeout=600.0,
            )
            resp.raise_for_status()
            return resp.json()["response"]
        except Exception:
            continue
    raise RuntimeError("All Ollama endpoints failed for generation")


def _get_background_knowledge(db: Session) -> str:
    """Build background knowledge section from user facts."""
    facts = db.query(UserFact).order_by(UserFact.category, UserFact.subject).all()
    if not facts:
        return ""
    lines = ["\nBackground knowledge (use this to inform your analysis):"]
    for f in facts:
        lines.append(f"- {f.subject} ({f.category}): {f.content}")
    return "\n".join(lines) + "\n"


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

    def _email_header(em):
        lines = [
            f"From: {em.from_addr}",
            f"To: {', '.join(em.to_addrs or [])}",
            f"Date: {em.sent_at}",
            f"Subject: {em.subject}",
            f"Read: {em.is_read} | Flagged: {em.is_flagged} | Replied: {em.is_replied}",
        ]
        if em.gmail_labels:
            lines.append(f"Labels: {', '.join(em.gmail_labels)}")
        lines.append(
            f"Attachments: {em.attachment_count} | Bulk: {em.is_bulk} | Importance: {em.importance or 'unknown'}"
        )
        return "\n".join(lines)

    thread_text = "\n\n---\n\n".join(
        f"{_email_header(em)}\n\n{em.body_text or ''}"
        for em in emails
    )

    raw_ids = [em.raw_id for em in emails]

    background_knowledge = _get_background_knowledge(db)

    try:
        response = ollama_generate(
            ANALYSIS_PROMPT.format(
                thread_text=thread_text[:8000],
                background_knowledge=background_knowledge,
            )
        )
        # Try to parse JSON from the response
        json_start = response.find("{")
        json_end = response.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            result = json.loads(response[json_start:json_end])
        else:
            return

        # Store claims
        for claim_data in result.get("claims", []):
            if not isinstance(claim_data, dict) or "text" not in claim_data:
                continue
            claim = ClaimLog(
                raw_id=raw_ids[0],
                email_id=emails[0].id,
                claim_text=claim_data["text"],
                claim_type=sanitize_enum(claim_data.get("type"), VALID_CLAIM_TYPES, "factual"),
                speaker=claim_data.get("speaker"),
                confidence=min(max(float(claim_data.get("confidence", 0.5)), 0.0), 1.0),
            )
            db.add(claim)

        # Store findings
        for finding_data in result.get("findings", []):
            if not isinstance(finding_data, dict) or "title" not in finding_data:
                continue
            finding = Finding(
                title=finding_data["title"][:500],
                summary=(finding_data.get("summary") or "")[:2000],
                finding_type=sanitize_enum(finding_data.get("type"), VALID_FINDING_TYPES, "pattern"),
                grounding=sanitize_enum(finding_data.get("grounding"), VALID_GROUNDINGS, "inferred"),
                supporting_email_ids=raw_ids,
                confidence=min(max(float(finding_data.get("confidence", 0.5)), 0.0), 1.0),
                model_used=DEEP_MODEL,
            )
            db.add(finding)

        # Store questions (dedup against existing pending)
        existing_questions = set(
            q[0] for q in db.query(SuggestedQuestion.question_text)
            .filter(SuggestedQuestion.status == "pending")
            .all()
        )
        for q_data in result.get("questions", []):
            if not isinstance(q_data, dict) or "question" not in q_data:
                continue
            q_text = q_data["question"].strip()
            if not q_text or q_text in existing_questions:
                continue
            valid_source_types = {"entity", "gap", "analysis"}
            source_type = q_data.get("source_type", "analysis")
            if source_type not in valid_source_types:
                source_type = "analysis"
            sq = SuggestedQuestion(
                question_text=q_text,
                context=q_data.get("context"),
                source_type=source_type,
                source_email_ids=raw_ids,
                status="pending",
            )
            db.add(sq)
            existing_questions.add(q_text)

    except Exception as e:
        print(f"Analysis error for thread {thread_id}: {e}")
        db.rollback()


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

        # Skip threads that already have findings (resume support)
        already_done = set()
        existing = db.query(Finding.supporting_email_ids).all()
        for (email_ids,) in existing:
            if isinstance(email_ids, list) and email_ids:
                # Find which thread this belongs to
                em = db.query(Email).filter(Email.raw_id == email_ids[0]).first()
                if em and em.thread_id:
                    already_done.add(em.thread_id)

        remaining = [tid for tid in thread_ids if tid not in already_done]
        print(f"Deep analysis: {len(remaining)} remaining ({len(already_done)} already done)")

        for tid in tqdm(remaining, desc="Deep analysis"):
            analyze_thread(tid, db)
            db.commit()

        print("Deep analysis complete")
    finally:
        db.close()
