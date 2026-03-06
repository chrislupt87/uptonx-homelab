"""Forensic decoder — scans for hidden codes, patterns, and reply chain tampering."""

import email as email_mod
import re
from collections import Counter
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from email_rag.db.schema import SessionLocal, Email, RawMessage, Anomaly


CODY_ADDRS = {"b.yourself1@hotmail.com"}


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
                        changes.append(f"CHANGED: '{orig_chunk}' → '{quoted_chunk}'")
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


def run_forensic_scan():
    """Scan Cody's emails for hidden codes and reply chain tampering."""
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
        existing = set(
            t[0] for t in db.query(Anomaly.thread_id)
            .filter(Anomaly.anomaly_type.in_([
                "hidden_code", "capital_pattern", "number_pattern",
                "reverse_mirror", "reply_tampering"
            ]))
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
