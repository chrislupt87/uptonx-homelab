"""Forensic decoder — scans for hidden codes, patterns, reply chain tampering, and forwarding."""

import email as email_mod
import re
from collections import Counter
from datetime import timedelta
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from email_rag.db.schema import SessionLocal, Email, RawMessage, Anomaly


CODY_ADDRS = {"b.yourself1@hotmail.com"}
CHRIS_ADDRS = {"claurenceu@gmail.com"}
KNOWN_ADDRS = CODY_ADDRS | CHRIS_ADDRS


def extract_capital_pattern(text: str) -> dict:
    """Extract capital letters that appear mid-word or in unusual positions."""
    if not text:
        return {}

    results = {}

    # 1. Extract ALL capitals from body to see if they spell something
    all_caps = "".join(c for c in text if c.isupper())
    if len(all_caps) > 3:
        results["all_capitals"] = all_caps

    # 2. Mid-word capitals (camelCase-style in normal text)
    mid_caps = []
    words = text.split()
    for word in words:
        clean = re.sub(r'[^a-zA-Z]', '', word)
        if len(clean) > 1:
            for i, c in enumerate(clean[1:], 1):
                if c.isupper() and clean[i-1].islower():
                    mid_caps.append(word)
                    break
    if mid_caps:
        results["mid_word_capitals"] = mid_caps

    # 3. Words that are ALL CAPS (not common abbreviations)
    common_abbrev = {"I", "OK", "AM", "PM", "RE", "FW", "CC", "BCC", "PS",
                     "FYI", "ASAP", "LOL", "OMG", "WTF", "IMO", "BTW", "TBH"}
    all_cap_words = [w for w in words if w.isupper() and len(w) > 1
                     and w.strip(".,!?;:\"'()") not in common_abbrev
                     and any(c.isalpha() for c in w)]
    if all_cap_words:
        results["all_caps_words"] = all_cap_words
        # First letter of each all-caps word
        acro = "".join(w[0] for w in all_cap_words if w[0].isalpha())
        if len(acro) > 1:
            results["all_caps_acronym"] = acro

    # 4. First letter of each sentence
    sentences = re.split(r'[.!?]+\s+', text)
    sentence_initials = ""
    for s in sentences:
        s = s.strip()
        if s and s[0].isalpha():
            sentence_initials += s[0]
    if len(sentence_initials) > 2:
        results["sentence_acrostic"] = sentence_initials

    # 5. First letter of each line
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    line_initials = ""
    for l in lines:
        if l and l[0].isalpha():
            line_initials += l[0]
    if len(line_initials) > 2 and line_initials != sentence_initials:
        results["line_acrostic"] = line_initials

    return results


def detect_number_patterns(text: str) -> dict:
    """Look for patterns involving the number 3 and other numeric codes."""
    if not text:
        return {}

    results = {}

    # Count occurrences of digits
    digit_counts = Counter(c for c in text if c.isdigit())
    if digit_counts.get('3', 0) >= 3:
        results["three_count"] = digit_counts['3']

    # Groups of 3
    words = text.split()
    triple_patterns = []

    # Three-word repeated phrases
    for i in range(len(words) - 2):
        chunk = " ".join(words[i:i+3])
        # Check for 3 repeated items (e.g., "no no no", "... ... ...")
        if words[i] == words[i+1] == words[i+2]:
            triple_patterns.append(f"repeated x3: '{words[i]}'")

    # Three dots/periods not standard ellipsis
    ellipsis_count = len(re.findall(r'\.{3}', text))
    if ellipsis_count >= 3:
        results["triple_dots"] = ellipsis_count

    # Numbers divisible by 3 or containing 3
    numbers = re.findall(r'\b\d+\b', text)
    threes = [n for n in numbers if '3' in n or (n.isdigit() and int(n) % 3 == 0 and int(n) != 0)]
    if len(threes) >= 2:
        results["numbers_with_three"] = threes

    if triple_patterns:
        results["triple_patterns"] = triple_patterns

    return results


def detect_reverse_mirror(text: str) -> dict:
    """Look for reversed words, palindromes, and mirror patterns."""
    if not text:
        return {}

    results = {}
    words = re.findall(r'[a-zA-Z]+', text.lower())

    # 1. Words that are other words reversed
    word_set = set(words)
    reversed_pairs = []
    seen = set()
    for w in words:
        if len(w) > 3:
            rev = w[::-1]
            if rev in word_set and rev != w and (rev, w) not in seen:
                reversed_pairs.append((w, rev))
                seen.add((w, rev))
                seen.add((rev, w))
    if reversed_pairs:
        results["reverse_word_pairs"] = reversed_pairs

    # 2. Palindrome words (beyond common ones like "mom", "dad", "pop")
    common_palindromes = {"mom", "dad", "pop", "sis", "nun", "eye", "did", "pup",
                          "wow", "gag", "gig", "pep", "pip", "poop", "deed", "noon",
                          "toot", "peep", "sees", "level", "refer", "madam", "civic",
                          "radar", "kayak", "rotor"}
    unusual_palindromes = [w for w in set(words) if len(w) > 2
                           and w == w[::-1] and w not in common_palindromes]
    if unusual_palindromes:
        results["unusual_palindromes"] = unusual_palindromes

    # 3. Check if the entire body reversed spells something coherent
    # Just extract and report — let the user evaluate
    full_reversed = text.strip()[:200][::-1]
    results["reversed_preview"] = full_reversed

    # 4. Every Nth letter patterns (steganography)
    alpha_only = "".join(c.lower() for c in text if c.isalpha())
    for n in [2, 3, 5]:
        extracted = alpha_only[::n]
        if len(extracted) > 5:
            results[f"every_{n}th_letter"] = extracted[:100]

    return results


def detect_reply_chain_tampering(thread_emails: list[Email], raw_contents: dict) -> list[dict]:
    """Compare quoted text in replies against originals to find modifications."""
    anomalies = []

    if len(thread_emails) < 2:
        return anomalies

    # Build a map of email content by message_id
    content_by_mid = {}
    for em in thread_emails:
        if em.message_id and em.body_text:
            content_by_mid[em.message_id] = {
                "from": em.from_addr,
                "body": em.body_text,
                "date": em.sent_at,
            }

    # Sort by date
    sorted_emails = sorted(thread_emails, key=lambda e: e.sent_at or e.created_at)

    for em in sorted_emails:
        if not em.body_text or not em.in_reply_to:
            continue

        original = content_by_mid.get(em.in_reply_to)
        if not original:
            continue

        # Extract quoted sections from the reply
        # Common patterns: lines starting with ">" or "On ... wrote:" blocks
        body = em.body_text

        # Look for "On <date> <person> wrote:" pattern
        wrote_pattern = re.search(
            r'On .+?wrote:\s*\n(.*)',
            body, re.DOTALL | re.IGNORECASE
        )

        if not wrote_pattern:
            # Try ">" quoting
            quoted_lines = [line.lstrip('>').strip() for line in body.split('\n')
                           if line.strip().startswith('>')]
            if not quoted_lines:
                continue
            quoted_text = "\n".join(quoted_lines)
        else:
            quoted_text = wrote_pattern.group(1)

        # Clean up quoted text
        quoted_clean = re.sub(r'^[>\s]+', '', quoted_text, flags=re.MULTILINE).strip()
        original_clean = original["body"].strip()

        if not quoted_clean or not original_clean:
            continue

        # Compare using SequenceMatcher
        # Only flag if there's enough quoted text to compare
        if len(quoted_clean) < 20:
            continue

        ratio = SequenceMatcher(None, original_clean[:2000], quoted_clean[:2000]).ratio()

        # If similarity is moderate (quoted but changed) vs very high (faithful quote)
        if 0.3 < ratio < 0.85:
            # Find specific differences
            matcher = SequenceMatcher(None, original_clean[:2000], quoted_clean[:2000])
            changes = []
            for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                if tag in ('replace', 'delete', 'insert') and (i2 - i1 > 3 or j2 - j1 > 3):
                    orig_chunk = original_clean[i1:i2][:80]
                    quoted_chunk = quoted_clean[j1:j2][:80]
                    if tag == 'replace':
                        changes.append(f"CHANGED: '{orig_chunk}' -> '{quoted_chunk}'")
                    elif tag == 'delete':
                        changes.append(f"REMOVED: '{orig_chunk}'")
                    elif tag == 'insert':
                        changes.append(f"ADDED: '{quoted_chunk}'")

            if changes:
                anomalies.append({
                    "type": "reply_tampering",
                    "severity": "high",
                    "title": f"Quoted text differs from original ({ratio:.0%} match)",
                    "detail": (
                        f"Reply from {em.from_addr} ({em.sent_at}) quotes "
                        f"{original['from']}'s message but with modifications:\n"
                        + "\n".join(changes[:5])
                    ),
                    "email_id": em.id,
                })

    return anomalies


def detect_forwarding(thread_emails: list[Email], raw_contents: dict) -> list[dict]:
    """Detect emails forwarded to third parties or evidence of external sharing."""
    anomalies = []

    for em in thread_emails:
        raw = raw_contents.get(em.raw_id)
        if not raw:
            continue

        msg = email_mod.message_from_string(raw)
        body = em.body_text or ""
        from_addr = (em.from_addr or "").lower()
        to_addrs = set((a or "").lower() for a in (em.to_addrs or []))
        cc_addrs = set((a or "").lower() for a in (em.cc_addrs or []))
        all_recipients = to_addrs | cc_addrs

        # 1. Check for forwarded message indicators in body
        fwd_patterns = [
            r'---------- Forwarded message ----------',
            r'Begin forwarded message:',
            r'----- Forwarded Message -----',
            r'-------- Original Message --------',
            r'From:.*\nSent:.*\nTo:.*\nSubject:',  # Outlook forward format
        ]
        for pattern in fwd_patterns:
            match = re.search(pattern, body, re.IGNORECASE)
            if match:
                # Extract who it was forwarded to if visible
                fwd_to_match = re.search(r'To:\s*(.+?)(?:\n|$)', body[match.start():], re.IGNORECASE)
                fwd_to = fwd_to_match.group(1).strip() if fwd_to_match else "unknown"
                anomalies.append({
                    "type": "forwarded_message",
                    "severity": "high",
                    "title": f"Email contains forwarded message",
                    "detail": (
                        f"From: {em.from_addr} ({em.sent_at})\n"
                        f"Subject: {em.subject}\n"
                        f"Contains a forwarded message block. Forward recipient: {fwd_to}\n"
                        f"This means a prior conversation was shared with someone else."
                    ),
                    "email_id": em.id,
                })
                break

        # 2. Check for unknown third-party recipients
        third_parties = []
        for addr in all_recipients:
            if addr and addr not in KNOWN_ADDRS and addr.strip():
                third_parties.append(addr)
        if third_parties:
            anomalies.append({
                "type": "third_party_recipient",
                "severity": "medium",
                "title": f"Email sent to/CC'd unknown third party",
                "detail": (
                    f"From: {em.from_addr} ({em.sent_at})\n"
                    f"Subject: {em.subject}\n"
                    f"Third-party recipients: {', '.join(third_parties)}\n"
                    f"To: {', '.join(to_addrs)}\n"
                    f"CC: {', '.join(cc_addrs) if cc_addrs else 'none'}"
                ),
                "email_id": em.id,
            })

        # 3. Check raw headers for BCC evidence (some servers leak it)
        bcc_header = msg.get("Bcc", "") or msg.get("bcc", "")
        if bcc_header:
            anomalies.append({
                "type": "bcc_detected",
                "severity": "high",
                "title": f"BCC recipient detected in headers",
                "detail": (
                    f"From: {em.from_addr} ({em.sent_at})\n"
                    f"Subject: {em.subject}\n"
                    f"BCC: {bcc_header}\n"
                    f"BCC headers are normally stripped — this suggests the mail server "
                    f"or client leaked it, or the sender included it intentionally."
                ),
                "email_id": em.id,
            })

        # 4. Check X-Forwarded-To / X-Forwarded-For headers
        for hdr_name in ["X-Forwarded-To", "X-Forwarded-For", "X-Original-To",
                         "Delivered-To", "X-MS-Exchange-Organization-AutoForwarded-To"]:
            hdr_val = msg.get(hdr_name, "")
            if hdr_val:
                fwd_addrs = [a.strip().lower() for a in hdr_val.split(",")]
                unexpected = [a for a in fwd_addrs if a not in KNOWN_ADDRS and a]
                if unexpected:
                    anomalies.append({
                        "type": "header_forward",
                        "severity": "high",
                        "title": f"Forward detected via {hdr_name} header",
                        "detail": (
                            f"From: {em.from_addr} ({em.sent_at})\n"
                            f"Subject: {em.subject}\n"
                            f"{hdr_name}: {hdr_val}\n"
                            f"Unexpected addresses: {', '.join(unexpected)}"
                        ),
                        "email_id": em.id,
                    })

        # 5. Auto-forward rules — check for X-Auto-Response-Suppress or similar
        auto_fwd = msg.get("X-MS-Exchange-Organization-AutoForwarding", "")
        if auto_fwd:
            anomalies.append({
                "type": "auto_forward_rule",
                "severity": "high",
                "title": "Auto-forwarding rule detected",
                "detail": (
                    f"From: {em.from_addr} ({em.sent_at})\n"
                    f"Subject: {em.subject}\n"
                    f"Auto-forwarding header present: {auto_fwd}\n"
                    f"This suggests an automatic mail rule is forwarding emails."
                ),
                "email_id": em.id,
            })

    return anomalies


def detect_timestamp_anomalies(thread_emails: list[Email], raw_contents: dict) -> list[dict]:
    """Detect timestamp inconsistencies — replies before originals, timezone shifts, gaps."""
    anomalies = []

    if len(thread_emails) < 2:
        return anomalies

    sorted_emails = sorted(thread_emails, key=lambda e: e.sent_at or e.created_at)

    # Build message_id -> email map
    by_mid = {}
    for em in sorted_emails:
        if em.message_id:
            by_mid[em.message_id] = em

    for em in sorted_emails:
        # 1. Reply dated BEFORE the message it replies to
        if em.in_reply_to and em.sent_at:
            parent = by_mid.get(em.in_reply_to)
            if parent and parent.sent_at:
                if em.sent_at < parent.sent_at:
                    diff = parent.sent_at - em.sent_at
                    anomalies.append({
                        "type": "timestamp_anomaly",
                        "severity": "high",
                        "title": f"Reply dated BEFORE the message it replies to",
                        "detail": (
                            f"Reply from {em.from_addr} dated {em.sent_at}\n"
                            f"But replies to message from {parent.from_addr} dated {parent.sent_at}\n"
                            f"The reply is {diff} earlier than the original.\n"
                            f"This could indicate clock manipulation, timezone issues, or message tampering."
                        ),
                        "email_id": em.id,
                    })

        # 2. Check raw headers for Received chain — look for time travel
        raw = raw_contents.get(em.raw_id)
        if raw:
            msg = email_mod.message_from_string(raw)
            received_headers = msg.get_all("Received", [])
            if len(received_headers) >= 2:
                # Received headers are in reverse order (newest first)
                # Check for suspicious gaps or backwards times
                dates_in_chain = []
                for rh in received_headers:
                    date_match = re.search(r';\s*(.+)$', rh)
                    if date_match:
                        try:
                            from email.utils import parsedate_to_datetime
                            dt = parsedate_to_datetime(date_match.group(1).strip())
                            dates_in_chain.append(dt)
                        except Exception:
                            pass

                # Check for large delays in the Received chain (message held somewhere)
                for i in range(len(dates_in_chain) - 1):
                    # Remember: newest first, so dates_in_chain[i] should be >= dates_in_chain[i+1]
                    newer = dates_in_chain[i]
                    older = dates_in_chain[i + 1]
                    if newer < older:
                        anomalies.append({
                            "type": "timestamp_anomaly",
                            "severity": "medium",
                            "title": "Received chain has backwards timestamps",
                            "detail": (
                                f"Email from {em.from_addr} ({em.sent_at})\n"
                                f"Received header {i} ({newer}) is OLDER than header {i+1} ({older})\n"
                                f"This suggests message routing anomalies or header manipulation."
                            ),
                            "email_id": em.id,
                        })
                    elif (newer - older) > timedelta(hours=12):
                        delay = newer - older
                        anomalies.append({
                            "type": "delivery_delay",
                            "severity": "medium",
                            "title": f"Suspicious delivery delay ({delay})",
                            "detail": (
                                f"Email from {em.from_addr} ({em.sent_at})\n"
                                f"Subject: {em.subject}\n"
                                f"Message was held for {delay} between mail servers.\n"
                                f"Hop {i+1} -> {i}: {older} -> {newer}\n"
                                f"Long delays can indicate message queuing, filtering, or interception."
                            ),
                            "email_id": em.id,
                        })

    return anomalies


def detect_missing_replies(thread_emails: list[Email]) -> list[dict]:
    """Detect gaps in reply chains — references to messages not in our database."""
    anomalies = []

    known_mids = set()
    for em in thread_emails:
        if em.message_id:
            known_mids.add(em.message_id)

    for em in thread_emails:
        # Check In-Reply-To references a message we don't have
        if em.in_reply_to and em.in_reply_to not in known_mids:
            anomalies.append({
                "type": "missing_reply_parent",
                "severity": "medium",
                "title": "Reply references a message not in the thread",
                "detail": (
                    f"Email from {em.from_addr} ({em.sent_at})\n"
                    f"Subject: {em.subject}\n"
                    f"In-Reply-To: {em.in_reply_to}\n"
                    f"This message ID doesn't exist in our database.\n"
                    f"The original message may have been deleted, sent via a different channel, "
                    f"or this reply was crafted to appear as part of a conversation."
                ),
                "email_id": em.id,
            })

    return anomalies


def detect_subject_changes(thread_emails: list[Email]) -> list[dict]:
    """Detect subtle subject line modifications mid-thread."""
    anomalies = []

    if len(thread_emails) < 2:
        return anomalies

    sorted_emails = sorted(thread_emails, key=lambda e: e.sent_at or e.created_at)

    def normalize_subject(s):
        if not s:
            return ""
        # Strip Re:/Fwd:/FW: prefixes
        return re.sub(r'^(Re|Fwd|Fw|RE|FWD|FW)\s*:\s*', '', s, flags=re.IGNORECASE).strip()

    base_subject = normalize_subject(sorted_emails[0].subject)

    for em in sorted_emails[1:]:
        current = normalize_subject(em.subject)
        if not current or not base_subject:
            continue

        if current != base_subject:
            # Check how different it is
            ratio = SequenceMatcher(None, base_subject.lower(), current.lower()).ratio()
            if ratio > 0.3:  # Related but changed (not a completely different conversation)
                anomalies.append({
                    "type": "subject_changed",
                    "severity": "low" if ratio > 0.8 else "medium",
                    "title": f"Subject line modified mid-thread ({ratio:.0%} similar)",
                    "detail": (
                        f"From: {em.from_addr} ({em.sent_at})\n"
                        f"Original subject: \"{base_subject}\"\n"
                        f"Changed to: \"{current}\"\n"
                        f"Subtle subject changes can alter the context or hide the thread "
                        f"from searches."
                    ),
                    "email_id": em.id,
                })

    return anomalies


def detect_recipient_changes(thread_emails: list[Email]) -> list[dict]:
    """Detect when recipients are added or removed mid-thread."""
    anomalies = []

    if len(thread_emails) < 2:
        return anomalies

    sorted_emails = sorted(thread_emails, key=lambda e: e.sent_at or e.created_at)

    prev_recipients = None
    prev_email = None

    for em in sorted_emails:
        current_to = set((a or "").lower() for a in (em.to_addrs or []) if a)
        current_cc = set((a or "").lower() for a in (em.cc_addrs or []) if a)
        current_all = current_to | current_cc

        if prev_recipients is not None:
            added = current_all - prev_recipients
            removed = prev_recipients - current_all

            # Filter out the sender swapping to/from (normal in replies)
            sender = (em.from_addr or "").lower()
            prev_sender = (prev_email.from_addr or "").lower()
            added.discard(prev_sender)
            removed.discard(sender)

            if added:
                added_unknown = [a for a in added if a not in KNOWN_ADDRS]
                if added_unknown:
                    anomalies.append({
                        "type": "recipient_added",
                        "severity": "high",
                        "title": f"New recipient(s) added mid-thread",
                        "detail": (
                            f"From: {em.from_addr} ({em.sent_at})\n"
                            f"Subject: {em.subject}\n"
                            f"New recipients: {', '.join(added_unknown)}\n"
                            f"Previous message from {prev_email.from_addr} did not include them.\n"
                            f"Someone brought a third party into the conversation."
                        ),
                        "email_id": em.id,
                    })
                elif added:
                    anomalies.append({
                        "type": "recipient_added",
                        "severity": "low",
                        "title": f"Known recipient(s) re-added mid-thread",
                        "detail": (
                            f"From: {em.from_addr} ({em.sent_at})\n"
                            f"Re-added: {', '.join(added)}"
                        ),
                        "email_id": em.id,
                    })

            if removed:
                removed_known = [a for a in removed if a in KNOWN_ADDRS]
                if removed_known:
                    anomalies.append({
                        "type": "recipient_removed",
                        "severity": "medium",
                        "title": f"Known recipient(s) dropped mid-thread",
                        "detail": (
                            f"From: {em.from_addr} ({em.sent_at})\n"
                            f"Subject: {em.subject}\n"
                            f"Removed: {', '.join(removed_known)}\n"
                            f"Someone was dropped from the conversation — "
                            f"they may not see subsequent messages."
                        ),
                        "email_id": em.id,
                    })

        prev_recipients = current_all
        prev_email = em

    return anomalies


def detect_header_oddities(thread_emails: list[Email], raw_contents: dict) -> list[dict]:
    """Scan raw headers for unusual or suspicious entries."""
    anomalies = []

    for em in thread_emails:
        raw = raw_contents.get(em.raw_id)
        if not raw:
            continue

        msg = email_mod.message_from_string(raw)

        # 1. Check for spoofing indicators — mismatched From and Return-Path/Sender
        from_addr = (em.from_addr or "").lower()
        return_path = (msg.get("Return-Path", "") or "").strip("<>").lower()
        sender_header = (msg.get("Sender", "") or "").lower()

        if return_path and return_path != from_addr and "@" in return_path:
            # Extract just the email part
            rp_email = re.search(r'[\w.+-]+@[\w.-]+', return_path)
            from_email = re.search(r'[\w.+-]+@[\w.-]+', from_addr)
            if rp_email and from_email and rp_email.group() != from_email.group():
                anomalies.append({
                    "type": "header_mismatch",
                    "severity": "high",
                    "title": "From and Return-Path mismatch",
                    "detail": (
                        f"Email dated {em.sent_at}\n"
                        f"From: {from_addr}\n"
                        f"Return-Path: {return_path}\n"
                        f"These should match. A mismatch could indicate spoofing, "
                        f"mailing list forwarding, or sent-on-behalf."
                    ),
                    "email_id": em.id,
                })

        if sender_header and sender_header != from_addr and "@" in sender_header:
            anomalies.append({
                "type": "header_mismatch",
                "severity": "medium",
                "title": "Sender header differs from From",
                "detail": (
                    f"Email dated {em.sent_at}\n"
                    f"From: {from_addr}\n"
                    f"Sender: {sender_header}\n"
                    f"The Sender header indicates someone else actually dispatched this email."
                ),
                "email_id": em.id,
            })

        # 2. Check DKIM/SPF/DMARC results for failures
        auth_results = msg.get("Authentication-Results", "") or ""
        if auth_results:
            failures = []
            if "spf=fail" in auth_results.lower() or "spf=softfail" in auth_results.lower():
                failures.append("SPF failed")
            if "dkim=fail" in auth_results.lower():
                failures.append("DKIM failed")
            if "dmarc=fail" in auth_results.lower():
                failures.append("DMARC failed")
            if failures:
                anomalies.append({
                    "type": "auth_failure",
                    "severity": "high",
                    "title": f"Email authentication failures: {', '.join(failures)}",
                    "detail": (
                        f"From: {em.from_addr} ({em.sent_at})\n"
                        f"Subject: {em.subject}\n"
                        f"Authentication-Results: {auth_results[:500]}\n"
                        f"Failed checks suggest the email may not be from who it claims."
                    ),
                    "email_id": em.id,
                })

        # 3. Check for unusual X-Mailer or User-Agent changes within thread
        x_mailer = msg.get("X-Mailer", "") or msg.get("User-Agent", "") or ""
        if x_mailer:
            # Store for cross-thread comparison (handled at thread level below)
            em._x_mailer = x_mailer
        else:
            em._x_mailer = None

    # 4. Detect mail client changes within a thread from same sender
    by_sender = {}
    for em in thread_emails:
        addr = (em.from_addr or "").lower()
        mailer = getattr(em, '_x_mailer', None)
        if mailer:
            by_sender.setdefault(addr, []).append((em, mailer))

    for addr, entries in by_sender.items():
        if len(entries) < 2:
            continue
        mailers = set(m for _, m in entries)
        if len(mailers) > 1:
            details = "\n".join(f"  {em.sent_at}: {m}" for em, m in entries)
            anomalies.append({
                "type": "client_change",
                "severity": "medium",
                "title": f"Mail client changed for {addr}",
                "detail": (
                    f"Sender {addr} used multiple mail clients in this thread:\n"
                    f"{details}\n"
                    f"Could indicate different devices, or someone else sending from this account."
                ),
                "email_id": entries[-1][0].id,
            })

    return anomalies


def run_forensic_scan():
    """Scan emails for hidden codes, reply chain tampering, forwarding, and header oddities."""
    db: Session = SessionLocal()

    try:
        # Get all priority threads
        priority_threads = (
            db.query(Email.thread_id)
            .filter(Email.subject_priority == True, Email.thread_id.isnot(None))
            .distinct()
            .all()
        )
        thread_ids = [t[0] for t in priority_threads]

        # Check which threads already have forensic anomalies
        forensic_types = [
            "hidden_code", "capital_pattern", "number_pattern",
            "reverse_mirror", "reply_tampering",
            "forwarded_message", "third_party_recipient", "bcc_detected",
            "header_forward", "auto_forward_rule",
            "timestamp_anomaly", "delivery_delay",
            "missing_reply_parent", "subject_changed",
            "recipient_added", "recipient_removed",
            "header_mismatch", "auth_failure", "client_change",
        ]
        existing = set(
            t[0] for t in db.query(Anomaly.thread_id)
            .filter(Anomaly.anomaly_type.in_(forensic_types))
            .distinct().all()
        )
        remaining = [tid for tid in thread_ids if tid not in existing]
        print(f"Forensic scan: {len(remaining)} threads ({len(existing)} already done)")

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

            raw_ids = [em.raw_id for em in thread_emails]
            raw_rows = db.query(RawMessage.id, RawMessage.raw_content).filter(
                RawMessage.id.in_(raw_ids)
            ).all()
            raw_contents = {r[0]: r[1] for r in raw_rows}

            thread_anomalies = []

            # Scan Cody's emails for hidden codes
            for em in thread_emails:
                if not em.from_addr or em.from_addr.lower() not in CODY_ADDRS:
                    continue
                body = em.body_text or ""
                if not body:
                    continue

                # Capital letter analysis
                cap_results = extract_capital_pattern(body)
                interesting_caps = []
                if cap_results.get("mid_word_capitals"):
                    interesting_caps.append(f"Mid-word caps: {cap_results['mid_word_capitals'][:5]}")
                if cap_results.get("all_caps_words"):
                    interesting_caps.append(f"ALL CAPS words: {cap_results['all_caps_words'][:10]}")
                if cap_results.get("all_caps_acronym"):
                    interesting_caps.append(f"Acronym from caps: {cap_results['all_caps_acronym']}")
                if cap_results.get("sentence_acrostic"):
                    interesting_caps.append(f"Sentence acrostic: {cap_results['sentence_acrostic']}")
                if cap_results.get("line_acrostic"):
                    interesting_caps.append(f"Line acrostic: {cap_results['line_acrostic']}")

                if interesting_caps:
                    thread_anomalies.append({
                        "type": "capital_pattern",
                        "severity": "medium",
                        "title": f"Capital letter patterns in Cody's email",
                        "detail": "\n".join(interesting_caps),
                        "email_id": em.id,
                    })

                # Number 3 patterns
                num_results = detect_number_patterns(body)
                if any(k != "triple_dots" for k in num_results):
                    details = []
                    if num_results.get("three_count"):
                        details.append(f"Digit '3' appears {num_results['three_count']} times")
                    if num_results.get("triple_patterns"):
                        details.append(f"Triple repeats: {num_results['triple_patterns']}")
                    if num_results.get("numbers_with_three"):
                        details.append(f"Numbers with 3: {num_results['numbers_with_three']}")
                    if details:
                        thread_anomalies.append({
                            "type": "number_pattern",
                            "severity": "medium",
                            "title": f"Number/three patterns in Cody's email",
                            "detail": "\n".join(details),
                            "email_id": em.id,
                        })

                # Reverse/mirror words
                rev_results = detect_reverse_mirror(body)
                interesting_rev = []
                if rev_results.get("reverse_word_pairs"):
                    interesting_rev.append(f"Reverse pairs: {rev_results['reverse_word_pairs']}")
                if rev_results.get("unusual_palindromes"):
                    interesting_rev.append(f"Unusual palindromes: {rev_results['unusual_palindromes']}")
                for n in [2, 3, 5]:
                    key = f"every_{n}th_letter"
                    if rev_results.get(key):
                        interesting_rev.append(f"Every {n}th letter: {rev_results[key]}")

                if interesting_rev:
                    thread_anomalies.append({
                        "type": "reverse_mirror",
                        "severity": "medium",
                        "title": f"Reverse/mirror/steganography patterns in Cody's email",
                        "detail": "\n".join(interesting_rev),
                        "email_id": em.id,
                    })

            # Reply chain tampering (both directions)
            thread_anomalies.extend(
                detect_reply_chain_tampering(thread_emails, raw_contents)
            )

            # Forwarding detection (all emails in thread)
            thread_anomalies.extend(
                detect_forwarding(thread_emails, raw_contents)
            )

            # Timestamp anomalies
            thread_anomalies.extend(
                detect_timestamp_anomalies(thread_emails, raw_contents)
            )

            # Missing replies in chain
            thread_anomalies.extend(
                detect_missing_replies(thread_emails)
            )

            # Subject line changes
            thread_anomalies.extend(
                detect_subject_changes(thread_emails)
            )

            # Recipient changes mid-thread
            thread_anomalies.extend(
                detect_recipient_changes(thread_emails)
            )

            # Header oddities (spoofing, auth failures, client changes)
            thread_anomalies.extend(
                detect_header_oddities(thread_emails, raw_contents)
            )

            # Store
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

        print(f"Forensic scan complete: {total_found} findings")
    finally:
        db.close()
