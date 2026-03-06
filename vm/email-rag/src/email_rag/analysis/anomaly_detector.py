"""Anomaly detector — scans emails for header inconsistencies, reply chain gaps, and hidden text."""

import email as email_mod
import re
import unicodedata
from collections import defaultdict
from datetime import timedelta

import click
from sqlalchemy.orm import Session

from email_rag.db.schema import SessionLocal, Email, RawMessage, Anomaly


# Zero-width and invisible Unicode characters
INVISIBLE_CHARS = {
    '\u200b': 'ZERO WIDTH SPACE',
    '\u200c': 'ZERO WIDTH NON-JOINER',
    '\u200d': 'ZERO WIDTH JOINER',
    '\u200e': 'LEFT-TO-RIGHT MARK',
    '\u200f': 'RIGHT-TO-LEFT MARK',
    '\u2060': 'WORD JOINER',
    '\u2061': 'FUNCTION APPLICATION',
    '\u2062': 'INVISIBLE TIMES',
    '\u2063': 'INVISIBLE SEPARATOR',
    '\u2064': 'INVISIBLE PLUS',
    '\ufeff': 'ZERO WIDTH NO-BREAK SPACE (BOM)',
    '\u00ad': 'SOFT HYPHEN',
    '\u034f': 'COMBINING GRAPHEME JOINER',
    '\u061c': 'ARABIC LETTER MARK',
    '\u180e': 'MONGOLIAN VOWEL SEPARATOR',
}

# Common homoglyph substitutions (Latin lookalikes from Cyrillic, Greek, etc.)
HOMOGLYPHS = {
    '\u0410': ('A', 'CYRILLIC A'),
    '\u0412': ('B', 'CYRILLIC VE'),
    '\u0421': ('C', 'CYRILLIC ES'),
    '\u0415': ('E', 'CYRILLIC IE'),
    '\u041d': ('H', 'CYRILLIC EN'),
    '\u041a': ('K', 'CYRILLIC KA'),
    '\u041c': ('M', 'CYRILLIC EM'),
    '\u041e': ('O', 'CYRILLIC O'),
    '\u0420': ('P', 'CYRILLIC ER'),
    '\u0422': ('T', 'CYRILLIC TE'),
    '\u0425': ('X', 'CYRILLIC HA'),
    '\u0430': ('a', 'CYRILLIC a'),
    '\u0435': ('e', 'CYRILLIC ie'),
    '\u043e': ('o', 'CYRILLIC o'),
    '\u0440': ('p', 'CYRILLIC er'),
    '\u0441': ('c', 'CYRILLIC es'),
    '\u0443': ('y', 'CYRILLIC u'),
    '\u0445': ('x', 'CYRILLIC ha'),
}


def _extract_domain(addr: str) -> str:
    """Extract domain from email address."""
    if not addr:
        return ""
    match = re.search(r'@([\w.-]+)', addr)
    return match.group(1).lower() if match else ""


def _parse_received_chain(raw_content: str) -> list[dict]:
    """Parse Received headers into structured data."""
    msg = email_mod.message_from_string(raw_content)
    received = msg.get_all("Received", [])
    chain = []
    for r in received:
        entry = {"raw": r.strip()}
        # Try to extract "from X" and "by Y"
        from_match = re.search(r'from\s+([\w.-]+)', r)
        by_match = re.search(r'by\s+([\w.-]+)', r)
        if from_match:
            entry["from"] = from_match.group(1)
        if by_match:
            entry["by"] = by_match.group(1)
        chain.append(entry)
    return chain


def detect_header_anomalies(em: Email, raw_content: str) -> list[dict]:
    """Check for header inconsistencies."""
    anomalies = []
    msg = email_mod.message_from_string(raw_content)

    # 1. From vs Return-Path mismatch
    from_addr = em.from_addr or ""
    return_path = msg.get("Return-Path", "")
    if return_path:
        rp_clean = return_path.strip("<>").lower()
        from_clean = from_addr.lower()
        if rp_clean and from_clean and rp_clean != from_clean:
            from_domain = _extract_domain(from_clean)
            rp_domain = _extract_domain(rp_clean)
            if from_domain != rp_domain:
                anomalies.append({
                    "type": "header_mismatch",
                    "severity": "high",
                    "title": "From/Return-Path domain mismatch",
                    "detail": f"From: {from_addr} but Return-Path: {return_path}. "
                              f"Different domains suggest possible spoofing or forwarding.",
                })

    # 2. Message-ID domain vs From domain
    message_id = msg.get("Message-ID", "")
    if message_id and from_addr:
        mid_domain = _extract_domain(message_id)
        from_domain = _extract_domain(from_addr)
        if mid_domain and from_domain and mid_domain != from_domain:
            # Common for webmail/services, only flag if suspicious
            known_services = {"google.com", "googlemail.com", "outlook.com", "icloud.com",
                              "mail.gmail.com", "smtp.gmail.com", "amazonses.com",
                              "hotmail.com", "live.com", "msn.com"}
            # Microsoft uses outlook.com infra for hotmail/live/msn
            ms_domains = {"hotmail.com", "live.com", "msn.com", "outlook.com"}
            is_ms_routing = from_domain in ms_domains and "outlook.com" in mid_domain
            if mid_domain not in known_services and not is_ms_routing:
                anomalies.append({
                    "type": "header_mismatch",
                    "severity": "medium",
                    "title": "Message-ID domain doesn't match sender",
                    "detail": f"From domain: {from_domain}, Message-ID domain: {mid_domain}. "
                              f"May indicate forwarding, relay, or spoofing.",
                })

    # 3. Authentication results (SPF/DKIM/DMARC failures)
    auth_results = msg.get("Authentication-Results", "")
    if auth_results:
        if "spf=fail" in auth_results.lower() or "spf=softfail" in auth_results.lower():
            anomalies.append({
                "type": "auth_failure",
                "severity": "high",
                "title": "SPF authentication failed",
                "detail": f"SPF check failed for this message. {auth_results[:200]}",
            })
        if "dkim=fail" in auth_results.lower():
            anomalies.append({
                "type": "auth_failure",
                "severity": "high",
                "title": "DKIM signature failed",
                "detail": f"DKIM verification failed — message may have been altered in transit. {auth_results[:200]}",
            })
        if "dmarc=fail" in auth_results.lower():
            anomalies.append({
                "type": "auth_failure",
                "severity": "high",
                "title": "DMARC policy failed",
                "detail": f"DMARC check failed. {auth_results[:200]}",
            })

    # 4. Unusual X-Mailer / User-Agent
    x_mailer = msg.get("X-Mailer", "") or msg.get("User-Agent", "")
    if x_mailer:
        suspicious_patterns = ["python", "php", "curl", "wget", "postfix", "sendmail"]
        for pat in suspicious_patterns:
            if pat in x_mailer.lower():
                anomalies.append({
                    "type": "suspicious_client",
                    "severity": "medium",
                    "title": f"Unusual mail client: {x_mailer[:80]}",
                    "detail": f"Message sent using {x_mailer}, which is typically a scripting/server tool, not a personal mail client.",
                })
                break

    # 5. Date header far from Received timestamp
    date_header = msg.get("Date", "")
    if date_header and em.sent_at:
        try:
            from email.utils import parsedate_to_datetime
            header_dt = parsedate_to_datetime(date_header)
            diff = abs((em.sent_at.replace(tzinfo=None) - header_dt.replace(tzinfo=None)).total_seconds())
            if diff > 86400:  # More than 24 hours off
                anomalies.append({
                    "type": "timestamp_anomaly",
                    "severity": "medium",
                    "title": "Date header significantly differs from delivery time",
                    "detail": f"Date header: {date_header}, delivery around: {em.sent_at}. "
                              f"Difference: {diff/3600:.1f} hours. Could indicate delayed delivery or clock manipulation.",
                })
        except Exception:
            pass

    return anomalies


def detect_reply_chain_anomalies(thread_emails: list[Email], all_message_ids: set) -> list[dict]:
    """Check for reply chain inconsistencies within a thread."""
    anomalies = []

    if len(thread_emails) < 2:
        return anomalies

    # Sort by sent_at
    sorted_emails = sorted(thread_emails, key=lambda e: e.sent_at or e.created_at)

    # 1. Missing In-Reply-To targets
    for em in sorted_emails:
        if em.in_reply_to and em.in_reply_to not in all_message_ids:
            anomalies.append({
                "type": "missing_reference",
                "severity": "high",
                "title": "Reply references missing message",
                "detail": f"Email from {em.from_addr} ({em.sent_at}) replies to Message-ID "
                          f"{em.in_reply_to[:60]} which doesn't exist in the corpus. "
                          f"A message in this thread may have been deleted or withheld.",
                "email_id": em.id,
            })

    # 2. Timestamp ordering anomalies
    for i in range(1, len(sorted_emails)):
        prev = sorted_emails[i - 1]
        curr = sorted_emails[i]
        if prev.sent_at and curr.sent_at:
            # Reply sent BEFORE the message it replies to
            if curr.in_reply_to and curr.in_reply_to == prev.message_id:
                if curr.sent_at < prev.sent_at:
                    anomalies.append({
                        "type": "timestamp_anomaly",
                        "severity": "high",
                        "title": "Reply timestamp precedes original",
                        "detail": f"Reply from {curr.from_addr} ({curr.sent_at}) was sent "
                                  f"BEFORE the message it replies to from {prev.from_addr} ({prev.sent_at}). "
                                  f"Timestamps may have been manipulated.",
                        "email_id": curr.id,
                    })

    # 3. Large gaps in conversation
    for i in range(1, len(sorted_emails)):
        prev = sorted_emails[i - 1]
        curr = sorted_emails[i]
        if prev.sent_at and curr.sent_at:
            gap = curr.sent_at - prev.sent_at
            if gap > timedelta(days=30):
                anomalies.append({
                    "type": "conversation_gap",
                    "severity": "low",
                    "title": f"Large gap in thread ({gap.days} days)",
                    "detail": f"Gap between {prev.from_addr} ({prev.sent_at}) and "
                              f"{curr.from_addr} ({curr.sent_at}). "
                              f"Messages may be missing from the thread.",
                    "email_id": curr.id,
                })

    # 4. Subject line changes mid-thread (beyond Re:/Fwd: prefixes)
    base_subjects = set()
    for em in sorted_emails:
        subj = (em.subject or "").strip()
        # Strip Re:/Fwd: prefixes
        clean = re.sub(r'^(Re|Fwd|Fw)\s*:\s*', '', subj, flags=re.IGNORECASE).strip()
        if clean:
            base_subjects.add(clean.lower())
    if len(base_subjects) > 1:
        anomalies.append({
            "type": "subject_change",
            "severity": "low",
            "title": "Subject line changed within thread",
            "detail": f"Thread contains {len(base_subjects)} different subjects: "
                      f"{', '.join(list(base_subjects)[:3])}. May indicate topic shift or thread hijacking.",
        })

    # 5. Unexpected participant (someone new enters mid-thread)
    initial_participants = set()
    if sorted_emails:
        first = sorted_emails[0]
        initial_participants.add(first.from_addr.lower())
        initial_participants.update(a.lower() for a in (first.to_addrs or []))
        initial_participants.update(a.lower() for a in (first.cc_addrs or []))

    for em in sorted_emails[1:]:
        sender = em.from_addr.lower()
        if sender not in initial_participants and initial_participants:
            anomalies.append({
                "type": "new_participant",
                "severity": "medium",
                "title": f"New participant entered thread: {em.from_addr}",
                "detail": f"{em.from_addr} was not in the original message participants "
                          f"but sent a message on {em.sent_at}. "
                          f"Original participants: {', '.join(list(initial_participants)[:5])}",
                "email_id": em.id,
            })
            initial_participants.add(sender)

    return anomalies


def detect_hidden_text(em: Email, raw_content: str) -> list[dict]:
    """Scan for hidden, coded, or obfuscated text."""
    anomalies = []
    body = em.body_text or ""

    # 1. Zero-width / invisible characters
    found_invisible = {}
    for char, name in INVISIBLE_CHARS.items():
        count = body.count(char)
        if count > 0:
            found_invisible[name] = count
    # Also check raw content (catches HTML-level hiding)
    for char, name in INVISIBLE_CHARS.items():
        count = raw_content.count(char)
        if count > found_invisible.get(name, 0):
            found_invisible[name] = count
    if found_invisible:
        # BOM chars are extremely common in Outlook/Hotmail emails — only flag
        # if there are non-BOM invisible chars, or BOM count is suspiciously high
        bom_count = found_invisible.get('ZERO WIDTH NO-BREAK SPACE (BOM)', 0)
        non_bom = {k: v for k, v in found_invisible.items() if k != 'ZERO WIDTH NO-BREAK SPACE (BOM)'}
        should_flag = bool(non_bom) or bom_count > 20
        if should_flag:
            total = sum(found_invisible.values())
            details = ", ".join(f"{name}: {count}" for name, count in found_invisible.items())
            anomalies.append({
                "type": "hidden_text",
                "severity": "high",
                "title": f"Invisible characters detected ({total} total)",
                "detail": f"Found invisible Unicode characters that could hide text: {details}. "
                          f"These characters are invisible but can carry information or disrupt text processing.",
            })

    # 2. Homoglyph characters (Cyrillic/Greek lookalikes in otherwise Latin text)
    found_homoglyphs = {}
    for char, (looks_like, name) in HOMOGLYPHS.items():
        if char in body:
            found_homoglyphs[char] = (looks_like, name, body.count(char))
    if found_homoglyphs:
        details = ", ".join(
            f"'{looks_like}' replaced by {name} ({count}x)"
            for char, (looks_like, name, count) in found_homoglyphs.items()
        )
        anomalies.append({
            "type": "hidden_text",
            "severity": "high",
            "title": "Homoglyph character substitution detected",
            "detail": f"Characters that look like Latin letters but are from other scripts: {details}. "
                      f"This can be used to bypass text filters or embed hidden meaning.",
        })

    # 3. Base64 encoded strings in body text
    b64_pattern = re.findall(r'(?<!\w)[A-Za-z0-9+/]{20,}={0,2}(?!\w)', body)
    if b64_pattern:
        # Filter out common non-base64 (URLs, etc.)
        suspicious_b64 = [b for b in b64_pattern if not any(
            x in b for x in ['http', 'www', 'gmail', 'yahoo', 'outlook']
        )]
        if suspicious_b64:
            import base64
            decoded_samples = []
            for s in suspicious_b64[:3]:
                try:
                    decoded = base64.b64decode(s).decode('utf-8', errors='replace')
                    if any(c.isalpha() for c in decoded):
                        decoded_samples.append(f"'{s[:30]}...' → '{decoded[:50]}'")
                except Exception:
                    pass
            if decoded_samples:
                anomalies.append({
                    "type": "encoded_content",
                    "severity": "medium",
                    "title": f"Base64 encoded text in body ({len(suspicious_b64)} strings)",
                    "detail": f"Decoded samples: {'; '.join(decoded_samples)}",
                })

    # 4. HTML comments or hidden elements in raw content
    html_comments = re.findall(r'<!--(.*?)-->', raw_content, re.DOTALL)
    meaningful_comments = [c.strip() for c in html_comments if len(c.strip()) > 10
                           and not c.strip().startswith('[if')]
    if meaningful_comments:
        preview = "; ".join(c[:80] for c in meaningful_comments[:3])
        anomalies.append({
            "type": "hidden_text",
            "severity": "medium",
            "title": f"HTML comments with content ({len(meaningful_comments)} found)",
            "detail": f"Hidden HTML comments: {preview}",
        })

    # 5. Display:none or visibility:hidden CSS hiding text
    hidden_css = re.findall(
        r'(?:display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0|color\s*:\s*(?:white|#fff(?:fff)?|rgb\(255))[^"]*"[^>]*>([^<]+)',
        raw_content, re.IGNORECASE
    )
    if hidden_css:
        anomalies.append({
            "type": "hidden_text",
            "severity": "high",
            "title": "CSS-hidden text detected",
            "detail": f"Text hidden via CSS (display:none, visibility:hidden, or invisible color): "
                      f"{'; '.join(h[:60] for h in hidden_css[:3])}",
        })

    # 6. Unusual Unicode categories (private use, tags, etc.)
    unusual_chars = {}
    for char in body:
        cat = unicodedata.category(char)
        if cat.startswith('Co'):  # Private use
            name = f"U+{ord(char):04X} (private use)"
            unusual_chars[name] = unusual_chars.get(name, 0) + 1
        elif cat == 'Cf' and char not in INVISIBLE_CHARS:  # Format chars not already caught
            name = unicodedata.name(char, f"U+{ord(char):04X}")
            unusual_chars[name] = unusual_chars.get(name, 0) + 1
    if unusual_chars:
        details = ", ".join(f"{name}: {count}" for name, count in unusual_chars.items())
        anomalies.append({
            "type": "hidden_text",
            "severity": "medium",
            "title": "Unusual Unicode characters detected",
            "detail": f"Found non-standard Unicode: {details}",
        })

    return anomalies


def detect_x_mailer_changes(thread_emails: list[Email], raw_contents: dict[str, str]) -> list[dict]:
    """Detect when someone switches mail clients within a thread."""
    anomalies = []
    sender_clients = defaultdict(set)

    for em in thread_emails:
        raw = raw_contents.get(em.raw_id, "")
        if not raw:
            continue
        msg = email_mod.message_from_string(raw)
        client = msg.get("X-Mailer", "") or msg.get("User-Agent", "")
        if client:
            sender_clients[em.from_addr.lower()].add(client.strip())

    for sender, clients in sender_clients.items():
        if len(clients) > 1:
            anomalies.append({
                "type": "client_change",
                "severity": "low",
                "title": f"Mail client changed for {sender}",
                "detail": f"{sender} used {len(clients)} different mail clients in this thread: "
                          f"{', '.join(c[:50] for c in clients)}. "
                          f"Could indicate multiple people using one account or device switching.",
            })

    return anomalies


def run_anomaly_detection():
    """Scan all priority threads for anomalies."""
    db: Session = SessionLocal()

    try:
        # Build set of all known Message-IDs for reference checking
        all_message_ids = set(
            mid[0] for mid in db.query(Email.message_id).filter(Email.message_id.isnot(None)).all()
        )

        # Get priority threads
        priority_threads = (
            db.query(Email.thread_id)
            .filter(Email.subject_priority == True, Email.thread_id.isnot(None))
            .distinct()
            .all()
        )
        thread_ids = [t[0] for t in priority_threads]

        # Check which threads already have anomalies (resume support)
        existing_threads = set(
            t[0] for t in db.query(Anomaly.thread_id).filter(Anomaly.thread_id.isnot(None)).distinct().all()
        )
        remaining = [tid for tid in thread_ids if tid not in existing_threads]
        click.echo(f"Anomaly detection: {len(remaining)} threads to scan ({len(existing_threads)} already done)")

        total_found = 0

        for tid in remaining:
            thread_emails = (
                db.query(Email)
                .filter(Email.thread_id == tid)
                .order_by(Email.sent_at.asc().nullslast())
                .all()
            )
            if not thread_emails:
                continue

            # Fetch raw content for the thread
            raw_ids = [em.raw_id for em in thread_emails]
            raw_rows = db.query(RawMessage.id, RawMessage.raw_content).filter(
                RawMessage.id.in_(raw_ids)
            ).all()
            raw_contents = {r[0]: r[1] for r in raw_rows}

            thread_anomalies = []

            # Per-email checks
            for em in thread_emails:
                raw = raw_contents.get(em.raw_id, "")
                if raw:
                    thread_anomalies.extend(
                        {**a, "email_id": em.id} for a in detect_header_anomalies(em, raw)
                    )
                    thread_anomalies.extend(
                        {**a, "email_id": em.id} for a in detect_hidden_text(em, raw)
                    )

            # Thread-level checks
            thread_anomalies.extend(detect_reply_chain_anomalies(thread_emails, all_message_ids))
            thread_anomalies.extend(detect_x_mailer_changes(thread_emails, raw_contents))

            # Store anomalies
            for a_data in thread_anomalies:
                anomaly = Anomaly(
                    thread_id=tid,
                    email_id=a_data.get("email_id"),
                    anomaly_type=a_data["type"],
                    severity=a_data.get("severity", "medium"),
                    title=a_data["title"][:500],
                    detail=a_data.get("detail", "")[:4000],
                )
                db.add(anomaly)
                total_found += 1

            db.commit()

        click.echo(f"Anomaly detection complete: {total_found} anomalies found")
    finally:
        db.close()
