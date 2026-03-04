"""Shared metadata extraction for emails — used by gmail.py and eml_import.py."""

import re
from email.message import Message


def detect_attachments(msg: Message) -> tuple[bool, int]:
    """Count attachment parts in a MIME message."""
    count = 0
    if msg.is_multipart():
        for part in msg.walk():
            disposition = part.get("Content-Disposition", "")
            if "attachment" in disposition.lower():
                count += 1
    return (count > 0, count)


def detect_bulk(msg: Message) -> bool:
    """Check if message is bulk/automated mail."""
    if msg.get("List-Unsubscribe"):
        return True
    precedence = (msg.get("Precedence") or "").lower()
    if precedence in ("bulk", "list", "junk"):
        return True
    auto_submitted = (msg.get("Auto-Submitted") or "").lower()
    if auto_submitted and auto_submitted != "no":
        return True
    return False


def extract_importance(msg: Message) -> str | None:
    """Normalize importance from various headers to high/normal/low."""
    importance = (msg.get("Importance") or "").lower()
    if importance in ("high", "low", "normal"):
        return importance

    x_priority = msg.get("X-Priority") or ""
    if x_priority:
        try:
            level = int(x_priority.strip()[0])
            if level <= 2:
                return "high"
            elif level == 3:
                return "normal"
            else:
                return "low"
        except (ValueError, IndexError):
            pass

    ms_priority = (msg.get("X-MSMail-Priority") or "").lower()
    if ms_priority:
        if "high" in ms_priority:
            return "high"
        elif "low" in ms_priority:
            return "low"
        elif "normal" in ms_priority:
            return "normal"

    return None


def extract_mail_client(msg: Message) -> str | None:
    """Extract mail client from X-Mailer or User-Agent header."""
    client = msg.get("X-Mailer") or msg.get("User-Agent")
    if client:
        return client.strip()[:200]
    return None


def parse_gmail_labels_header(msg: Message) -> list[str]:
    """Parse X-Gmail-Labels header from Google Takeout EML exports."""
    labels_header = msg.get("X-Gmail-Labels")
    if not labels_header:
        return []
    return [label.strip() for label in labels_header.split(",") if label.strip()]


def extract_eml_metadata(msg: Message) -> dict:
    """Extract all metadata from a parsed email message.

    Returns dict with: has_attachments, attachment_count, is_bulk,
    importance, mail_client, gmail_labels, is_read, is_flagged.
    """
    has_attachments, attachment_count = detect_attachments(msg)
    gmail_labels = parse_gmail_labels_header(msg)

    # Derive read/flagged from Takeout labels if available
    is_read = None
    is_flagged = False
    if gmail_labels:
        is_read = "Unread" not in gmail_labels
        is_flagged = "Starred" in gmail_labels

    return {
        "has_attachments": has_attachments,
        "attachment_count": attachment_count,
        "is_bulk": detect_bulk(msg),
        "importance": extract_importance(msg),
        "mail_client": extract_mail_client(msg),
        "gmail_labels": gmail_labels,
        "is_read": is_read,
        "is_flagged": is_flagged,
    }


def parse_imap_envelope(envelope_line: bytes) -> dict:
    """Parse FLAGS, X-GM-LABELS, X-GM-THRID, X-GM-MSGID from IMAP response.

    The envelope_line is the first element of the IMAP fetch tuple, e.g.:
    b'123 (FLAGS (\\Seen) X-GM-LABELS ("Label1" "Label2") X-GM-THRID 1234 X-GM-MSGID 5678 RFC822 {size})'
    """
    result = {
        "is_read": False,
        "is_flagged": False,
        "is_replied": False,
        "gmail_labels": [],
        "gmail_thread_id": None,
        "gmail_message_id": None,
    }

    try:
        line = envelope_line.decode("utf-8", errors="replace") if isinstance(envelope_line, bytes) else str(envelope_line)

        # Parse FLAGS
        flags_match = re.search(r"FLAGS\s*\(([^)]*)\)", line)
        if flags_match:
            flags = flags_match.group(1)
            result["is_read"] = "\\Seen" in flags
            result["is_flagged"] = "\\Flagged" in flags
            result["is_replied"] = "\\Answered" in flags

        # Parse X-GM-LABELS — values are space-separated, possibly quoted
        labels_match = re.search(r"X-GM-LABELS\s*\(([^)]*)\)", line)
        if labels_match:
            raw_labels = labels_match.group(1)
            labels = []
            for m in re.finditer(r'"([^"]+)"|(\S+)', raw_labels):
                label = m.group(1) or m.group(2)
                if label:
                    labels.append(label)
            result["gmail_labels"] = labels

        # Parse X-GM-THRID
        thrid_match = re.search(r"X-GM-THRID\s+(\d+)", line)
        if thrid_match:
            result["gmail_thread_id"] = thrid_match.group(1)

        # Parse X-GM-MSGID
        msgid_match = re.search(r"X-GM-MSGID\s+(\d+)", line)
        if msgid_match:
            result["gmail_message_id"] = msgid_match.group(1)

    except Exception:
        pass  # Graceful degradation — return defaults

    return result
