"""MCP server — exposes email-rag database to Claude Code / Claude Desktop."""

import re
from collections import defaultdict
from datetime import datetime

from mcp.server.fastmcp import FastMCP
from sqlalchemy import func
from sqlalchemy.orm import Session

from email_rag.db.schema import (
    SessionLocal, Email, Finding, ClaimLog, Timeline,
    UserFact, SuggestedQuestion, Anomaly, Snippet,
)
from email_rag.analysis.claude_query import search_snippets

mcp = FastMCP("email-rag")

# ---------------------------------------------------------------------------
# Anti-speak decoder
# ---------------------------------------------------------------------------

# Layer 1: Negation flips (don't→do, never→always, nothing→something)
NEGATION_FLIPS = [
    (r"\bI don[\u2019']?t\b", "I do"),
    (r"\bi don[\u2019']?t\b", "I do"),
    (r"\bYou don[\u2019']?t\b", "You do"),
    (r"\byou don[\u2019']?t\b", "you do"),
    (r"\bhe don[\u2019']?t\b", "he does"),
    (r"\bshe don[\u2019']?t\b", "she does"),
    (r"\bthey don[\u2019']?t\b", "they do"),
    (r"\bwe don[\u2019']?t\b", "we do"),
    (r"\bdon[\u2019']?t\b", "do"),
    (r"\bdidn[\u2019']?t\b", "did"),
    (r"\bwon[\u2019']?t\b", "will"),
    (r"\bcan[\u2019']?t\b", "can"),
    (r"\bcouldn[\u2019']?t\b", "could"),
    (r"\bwouldn[\u2019']?t\b", "would"),
    (r"\bshouldn[\u2019']?t\b", "should"),
    (r"\bisn[\u2019']?t\b", "is"),
    (r"\baren[\u2019']?t\b", "are"),
    (r"\bwasn[\u2019']?t\b", "was"),
    (r"\bweren[\u2019']?t\b", "were"),
    (r"\bhaven[\u2019']?t\b", "have"),
    (r"\bhasn[\u2019']?t\b", "has"),
    (r"\bain[\u2019']?t\b", "am/is"),
    (r"\bnever\b", "ALWAYS"),
    (r"\bnobody\b", "SOMEBODY"),
    (r"\bno one\b", "SOMEONE"),
    (r"\bnothing\b", "SOMETHING"),
    (r"\bnowhere\b", "SOMEWHERE"),
    (r"\bnot really\b", "REALLY"),
    (r"\bnot even\b", "EVEN"),
    (r"\bnot\b", ""),
    (r"\bno\b(?!\w)", "YES"),
]

# Layer 2: Antonym swaps — bidirectional (honest↔dishonest, real↔fake, etc.)
ANTONYM_PAIRS = [
    ("honest", "dishonest"),
    ("honesty", "dishonesty"),
    ("real", "fake"),
    ("open", "secretive"),
    ("direct", "evasive"),
    ("truth", "lies"),
    ("true", "false"),
    ("trust", "distrust"),
    ("safe", "unsafe"),
    ("safety", "danger"),
    ("respect", "disrespect"),
    ("innocent", "guilty"),
    ("love", "hate"),
    ("care", "indifference"),
    ("friend", "enemy"),
    ("help", "harm"),
    ("straight", "crooked"),
    ("proof", "no proof"),
    ("loyal", "disloyal"),
    ("loyalty", "disloyalty"),
    ("faithful", "unfaithful"),
    ("clean", "dirty"),
    ("kind", "cruel"),
    ("gentle", "aggressive"),
    ("calm", "volatile"),
    ("stable", "unstable"),
    ("sane", "insane"),
    ("rational", "irrational"),
    ("reasonable", "unreasonable"),
    ("transparent", "opaque"),
    ("secure", "insecure"),
]
# Build bidirectional swap dict (word → opposite)
ANTONYM_MAP = {}
for a, b in ANTONYM_PAIRS:
    ANTONYM_MAP[a] = b.upper()
    ANTONYM_MAP[b] = a.upper()

# Layer 3: Projection swaps (you→I when in accusatory context)
PROJECTION_MARKERS = [
    r"\byou (did|are|were|have|had|always|keep|kept|made|started|caused)",
    r"\byour (dishonesty|lies|secrets|fault|game|actions|behavior|bullshit|bs|crap|shit|garbage)",
    r"\byou'?re the one",
    r"\byou (twisted|reversed|flipped|spun|switched)",
    r"\byou doing .+ behind my back",
]


def decode_negations(text: str) -> str:
    """Layer 1: Flip negations."""
    result = text
    for pat, repl in NEGATION_FLIPS:
        result = re.sub(pat, repl, result, flags=re.IGNORECASE)
    return re.sub(r"  +", " ", result)


def decode_antonyms(text: str) -> str:
    """Layer 2: Swap words for their antonyms (bidirectional, simultaneous)."""
    # Build one regex that matches all antonym words at once
    all_words = sorted(ANTONYM_MAP.keys(), key=len, reverse=True)
    pattern = r"\b(" + "|".join(re.escape(w) for w in all_words) + r")\b"

    def _swap(m):
        word = m.group(0).lower()
        repl = ANTONYM_MAP.get(word, m.group(0))
        return repl

    return re.sub(pattern, _swap, text, flags=re.IGNORECASE)


def decode_projection(text: str) -> str:
    """Layer 3: Flag projection — 'you did X' likely means 'I did X'."""
    flags = []
    for pat in PROJECTION_MARKERS:
        matches = re.findall(pat, text, re.IGNORECASE)
        if matches:
            flags.append(pat)
    if flags:
        # Swap you→I, your→my, you're→I'm in accusatory sentences
        result = text
        result = re.sub(r"\bYou are\b", "I AM", result)
        result = re.sub(r"\byou are\b", "I am", result)
        result = re.sub(r"\bYou'?re\b", "I'M", result)
        result = re.sub(r"\byou'?re\b", "I'm", result)
        result = re.sub(r"\bYou were\b", "I WAS", result)
        result = re.sub(r"\byou were\b", "I was", result)
        result = re.sub(r"\bYou did\b", "I DID", result)
        result = re.sub(r"\byou did\b", "I did", result)
        result = re.sub(r"\bYou have\b", "I HAVE", result)
        result = re.sub(r"\byou have\b", "I have", result)
        result = re.sub(r"\bYou\b", "I", result)
        result = re.sub(r"\byou\b", "I", result)
        result = re.sub(r"\bYour\b", "MY", result)
        result = re.sub(r"\byour\b", "my", result)
        return result
    return text


def decode_antispeak(text: str, layers: str = "all") -> str:
    """Full anti-speak decoder. Layers: negation, antonym, projection, or all."""
    result = text
    if layers in ("all", "negation"):
        result = decode_negations(result)
    if layers in ("all", "antonym"):
        result = decode_antonyms(result)
    if layers in ("all", "projection"):
        result = decode_projection(result)
    return result


def _extract_own_text(body: str) -> str:
    """Strip quoted replies to get just the sender's own words."""
    lines = (body or "").strip().split("\n")
    own = []
    for line in lines:
        s = line.strip()
        if s.startswith(">"):
            break
        if "On " in s and "wrote:" in s:
            break
        if s == "Best Regards,":
            break
        own.append(line)
    return "\n".join(own).strip()


def _normalize_subject(subj: str) -> str:
    """Strip Re:/Fwd: prefixes for thread grouping."""
    if not subj:
        return ""
    return re.sub(r"^(Re|Fwd|Fw|RE|FWD|FW)\s*:\s*", "", subj, flags=re.IGNORECASE).strip().lower()


def _fmt_email(em: Email, include_body: bool = False, antispeak: bool = False) -> str:
    """Format an email for display."""
    date = em.sent_at.strftime("%Y-%m-%d %H:%M") if em.sent_at else "?"
    parts = [
        f"From: {em.from_addr}",
        f"To: {', '.join(em.to_addrs or [])}",
        f"Date: {date}",
        f"Subject: {em.subject or '(none)'}",
    ]
    if include_body:
        body = em.body_text or ""
        own = _extract_own_text(body)
        parts.append(f"\n{own}")
        if antispeak and own:
            decoded = decode_antispeak(own)
            if decoded != own:
                parts.append(f"\n--- ANTI-SPEAK DECODED ---\n{decoded}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def search_emails(
    query: str = "",
    sender: str = "",
    subject: str = "",
    start_date: str = "",
    end_date: str = "",
    limit: int = 20,
    include_body: bool = True,
    antispeak: bool = False,
) -> str:
    """Search emails by sender, subject, date range, or free text.

    Args:
        query: Free text to search in body/subject
        sender: Filter by sender email (partial match)
        subject: Filter by subject (partial match)
        start_date: Start date YYYY-MM-DD
        end_date: End date YYYY-MM-DD
        limit: Max results (default 20)
        include_body: Include email body text
        antispeak: Show anti-speak decoded version alongside original
    """
    db = SessionLocal()
    try:
        q = db.query(Email).order_by(Email.sent_at.asc().nullslast())
        if sender:
            q = q.filter(Email.from_addr.ilike(f"%{sender}%"))
        if subject:
            q = q.filter(Email.subject.ilike(f"%{subject}%"))
        if start_date:
            q = q.filter(Email.sent_at >= start_date)
        if end_date:
            q = q.filter(Email.sent_at <= end_date + " 23:59:59")
        if query:
            q = q.filter(
                Email.body_text.ilike(f"%{query}%")
                | Email.subject.ilike(f"%{query}%")
            )
        results = q.limit(limit).all()
        if not results:
            return "No emails found."
        lines = [f"Found {len(results)} emails:\n"]
        for em in results:
            lines.append("=" * 60)
            lines.append(_fmt_email(em, include_body=include_body, antispeak=antispeak))
        return "\n".join(lines)
    finally:
        db.close()


@mcp.tool()
def get_thread(subject: str, antispeak: bool = False) -> str:
    """Get all emails in a conversation thread by subject.

    Uses normalized subject matching (strips Re:/Fwd: prefixes).

    Args:
        subject: Subject to match (partial OK)
        antispeak: Show anti-speak decoded version for each message
    """
    db = SessionLocal()
    try:
        all_emails = (
            db.query(Email)
            .filter(Email.subject.ilike(f"%{subject}%"))
            .order_by(Email.sent_at.asc().nullslast())
            .all()
        )
        # Group by normalized subject
        groups = defaultdict(list)
        for em in all_emails:
            key = _normalize_subject(em.subject)
            groups[key].append(em)

        if not groups:
            return f"No threads found matching '{subject}'."

        lines = []
        for subj_key, emails in groups.items():
            lines.append(f"=== Thread: {subj_key} ({len(emails)} messages) ===\n")
            for em in emails:
                lines.append("-" * 50)
                lines.append(_fmt_email(em, include_body=True, antispeak=antispeak))
                lines.append("")
        return "\n".join(lines)
    finally:
        db.close()


@mcp.tool()
def decode_text(text: str, layers: str = "all") -> str:
    """Decode anti-speak in arbitrary text. Three layers of inversion detection.

    Args:
        text: Text to decode
        layers: Which layers to apply — "negation", "antonym", "projection", or "all"
    """
    lines = [f"ORIGINAL:\n{text}\n"]
    if layers == "all":
        neg = decode_negations(text)
        if neg != text:
            lines.append(f"NEGATION FLIPS:\n{neg}\n")
        ant = decode_antonyms(text)
        if ant != text:
            lines.append(f"ANTONYM SWAPS:\n{ant}\n")
        proj = decode_projection(text)
        if proj != text:
            lines.append(f"PROJECTION SWAPS:\n{proj}\n")
        full = decode_antispeak(text, "all")
        lines.append(f"FULL DECODE:\n{full}")
    else:
        decoded = decode_antispeak(text, layers)
        lines.append(f"DECODED ({layers}):\n{decoded}")
    return "\n".join(lines)


@mcp.tool()
def get_cody_emails(
    start_date: str = "",
    end_date: str = "",
    antispeak: bool = True,
    limit: int = 50,
) -> str:
    """Get Cody's emails (b.yourself1@hotmail.com) with anti-speak decoding.

    Args:
        start_date: Start date YYYY-MM-DD
        end_date: End date YYYY-MM-DD
        antispeak: Decode anti-speak (default True)
        limit: Max results
    """
    return search_emails(
        sender="b.yourself1",
        start_date=start_date,
        end_date=end_date,
        include_body=True,
        antispeak=antispeak,
        limit=limit,
    )


@mcp.tool()
def semantic_search(query: str, limit: int = 10) -> str:
    """Vector similarity search across email snippets.

    Uses embeddings to find semantically similar content regardless of exact wording.

    Args:
        query: Natural language query
        limit: Max results (default 10)
    """
    db = SessionLocal()
    try:
        results = search_snippets(query, db, limit=limit)
        if not results:
            return "No matching snippets found."
        lines = [f"Found {len(results)} relevant snippets:\n"]
        for i, s in enumerate(results, 1):
            lines.append(f"--- Result {i} ---")
            lines.append(f"From: {s['from']} | Date: {s['date']} | Subject: {s['subject']}")
            lines.append(s["content"])
            lines.append("")
        return "\n".join(lines)
    finally:
        db.close()


@mcp.tool()
def get_findings(
    finding_type: str = "",
    grounding: str = "",
    limit: int = 30,
) -> str:
    """Get analysis findings (patterns, contradictions, behavioral, timeline_gap).

    Args:
        finding_type: Filter by type: pattern, contradiction, timeline_gap, behavioral
        grounding: Filter by grounding: grounded, inferred, speculative
        limit: Max results
    """
    db = SessionLocal()
    try:
        q = db.query(Finding).order_by(Finding.confidence.desc().nullslast())
        if finding_type:
            q = q.filter(Finding.finding_type == finding_type)
        if grounding:
            q = q.filter(Finding.grounding == grounding)
        results = q.limit(limit).all()
        if not results:
            return "No findings found."
        lines = [f"Found {len(results)} findings:\n"]
        for f in results:
            lines.append(f"[{f.finding_type}|{f.grounding}|conf={f.confidence:.1f}] {f.title}")
            lines.append(f"  {f.summary}")
            lines.append("")
        return "\n".join(lines)
    finally:
        db.close()


@mcp.tool()
def get_claims(speaker: str = "", claim_type: str = "", limit: int = 30) -> str:
    """Get extracted claims from emails.

    Args:
        speaker: Filter by speaker name
        claim_type: Filter by type: factual, promise, opinion
        limit: Max results
    """
    db = SessionLocal()
    try:
        q = db.query(ClaimLog).order_by(ClaimLog.confidence.desc().nullslast())
        if speaker:
            q = q.filter(ClaimLog.speaker.ilike(f"%{speaker}%"))
        if claim_type:
            q = q.filter(ClaimLog.claim_type == claim_type)
        results = q.limit(limit).all()
        if not results:
            return "No claims found."
        lines = [f"Found {len(results)} claims:\n"]
        for c in results:
            lines.append(f"[{c.claim_type}|conf={c.confidence:.1f}] {c.speaker}: {c.claim_text}")
        return "\n".join(lines)
    finally:
        db.close()


@mcp.tool()
def get_timeline(
    start_date: str = "",
    end_date: str = "",
    event_type: str = "",
    limit: int = 50,
) -> str:
    """Get timeline of real-world events extracted from emails.

    Args:
        start_date: Start date YYYY-MM-DD
        end_date: End date YYYY-MM-DD
        event_type: Filter by type: visit, birthday, court, incident, trip, appointment, milestone
        limit: Max results
    """
    db = SessionLocal()
    try:
        q = db.query(Timeline).order_by(Timeline.event_date.asc().nullslast())
        if start_date:
            q = q.filter(Timeline.event_date >= start_date)
        if end_date:
            q = q.filter(Timeline.event_date <= end_date + " 23:59:59")
        if event_type:
            q = q.filter(Timeline.event_type == event_type)
        results = q.limit(limit).all()
        if not results:
            return "No timeline events found."
        lines = [f"Found {len(results)} events:\n"]
        for t in results:
            date = t.event_date.strftime("%Y-%m-%d") if t.event_date else "?"
            who = ", ".join(t.participants or [])
            lines.append(f"{date} [{t.event_type}] {t.description} ({who})")
        return "\n".join(lines)
    finally:
        db.close()


@mcp.tool()
def get_facts() -> str:
    """Get all stored background knowledge / user facts."""
    db = SessionLocal()
    try:
        facts = db.query(UserFact).order_by(UserFact.category, UserFact.subject).all()
        if not facts:
            return "No facts stored."
        lines = [f"{len(facts)} facts:\n"]
        current_cat = None
        for f in facts:
            if f.category != current_cat:
                current_cat = f.category
                lines.append(f"\n## {current_cat}")
            lines.append(f"  [{f.id}] {f.subject}: {f.content}")
        return "\n".join(lines)
    finally:
        db.close()


@mcp.tool()
def add_fact(category: str, subject: str, content: str) -> str:
    """Add a new background knowledge fact.

    Args:
        category: Category (person, relationship, place, event, context)
        subject: Short label
        content: The fact content
    """
    db = SessionLocal()
    try:
        fact = UserFact(category=category, subject=subject, content=content)
        db.add(fact)
        db.commit()
        db.refresh(fact)
        return f"Fact #{fact.id} added: [{category}] {subject}: {content}"
    finally:
        db.close()


@mcp.tool()
def get_anomalies(severity: str = "", anomaly_type: str = "", limit: int = 30) -> str:
    """Get detected anomalies (tampering, forwarding, header issues, patterns).

    Args:
        severity: Filter by severity: high, medium, low
        anomaly_type: Filter by type
        limit: Max results
    """
    db = SessionLocal()
    try:
        q = db.query(Anomaly).filter(Anomaly.status == "open").order_by(Anomaly.created_at.desc())
        if severity:
            q = q.filter(Anomaly.severity == severity)
        if anomaly_type:
            q = q.filter(Anomaly.anomaly_type == anomaly_type)
        results = q.limit(limit).all()
        if not results:
            return "No open anomalies found."
        lines = [f"Found {len(results)} anomalies:\n"]
        for a in results:
            lines.append(f"[{a.severity}|{a.anomaly_type}] {a.title}")
            if a.detail:
                lines.append(f"  {a.detail[:200]}")
            lines.append("")
        return "\n".join(lines)
    finally:
        db.close()


@mcp.tool()
def get_questions(status: str = "pending", limit: int = 20) -> str:
    """Get AI-suggested questions that need human answers.

    Args:
        status: Filter by status: pending, answered, dismissed
        limit: Max results
    """
    db = SessionLocal()
    try:
        q = db.query(SuggestedQuestion).order_by(SuggestedQuestion.created_at.desc())
        if status:
            q = q.filter(SuggestedQuestion.status == status)
        results = q.limit(limit).all()
        if not results:
            return f"No {status} questions."
        lines = [f"Found {len(results)} {status} questions:\n"]
        for sq in results:
            lines.append(f"[{sq.id}|{sq.source_type}] {sq.question_text}")
            if sq.context:
                lines.append(f"  Context: {sq.context[:150]}")
            if sq.suggested_answer:
                lines.append(f"  Suggested: {sq.suggested_answer[:150]}")
            lines.append("")
        return "\n".join(lines)
    finally:
        db.close()


@mcp.tool()
def get_stats() -> str:
    """Get database statistics — email counts, findings, claims, etc."""
    db = SessionLocal()
    try:
        email_count = db.query(func.count(Email.id)).scalar()
        cody_count = db.query(func.count(Email.id)).filter(
            Email.from_addr.ilike("%b.yourself1%")
        ).scalar()
        chris_count = db.query(func.count(Email.id)).filter(
            Email.from_addr.ilike("%claurenceu%")
        ).scalar()
        finding_count = db.query(func.count(Finding.id)).scalar()
        claim_count = db.query(func.count(ClaimLog.id)).scalar()
        timeline_count = db.query(func.count(Timeline.id)).scalar()
        fact_count = db.query(func.count(UserFact.id)).scalar()
        anomaly_count = db.query(func.count(Anomaly.id)).filter(
            Anomaly.status == "open"
        ).scalar()
        pending_q = db.query(func.count(SuggestedQuestion.id)).filter(
            SuggestedQuestion.status == "pending"
        ).scalar()

        return (
            f"Emails: {email_count} total ({chris_count} Chris, {cody_count} Cody)\n"
            f"Findings: {finding_count}\n"
            f"Claims: {claim_count}\n"
            f"Timeline events: {timeline_count}\n"
            f"Facts: {fact_count}\n"
            f"Open anomalies: {anomaly_count}\n"
            f"Pending questions: {pending_q}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    mcp.run(transport="stdio")
