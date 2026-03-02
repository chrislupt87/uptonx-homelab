"""Shared RFC822 parsing and SHA-256 hashing.

Used by both gmail.py and eml_import.py to produce consistent
(raw_id, parsed fields) from raw email bytes.
"""

import email
import email.policy
import email.utils
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class ParsedEmail:
    raw_hash: str
    raw_content: str
    size_bytes: int
    message_id: str | None = None
    in_reply_to: str | None = None
    references_header: str | None = None
    from_addr: str | None = None
    to_addrs: list[str] = field(default_factory=list)
    cc_addrs: list[str] = field(default_factory=list)
    bcc_addrs: list[str] = field(default_factory=list)
    subject: str | None = None
    date_sent: datetime | None = None
    body_text: str | None = None
    body_html: str | None = None


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse_address_list(header_value: str | None) -> list[str]:
    """Extract email addresses from a header value."""
    if not header_value:
        return []
    addrs = email.utils.getaddresses([header_value])
    return [addr for _, addr in addrs if addr]


def _parse_date(header_value: str | None) -> datetime | None:
    if not header_value:
        return None
    parsed = email.utils.parsedate_to_datetime(header_value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _get_body(msg: email.message.Message, content_type: str) -> str | None:
    """Extract body text for a given content type."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == content_type:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
    else:
        if msg.get_content_type() == content_type:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
    return None


def parse_raw_email(raw_bytes: bytes) -> ParsedEmail:
    """Parse raw RFC822 bytes into a ParsedEmail dataclass.

    Raises ValueError for completely unparseable content.
    """
    raw_hash = sha256_hex(raw_bytes)
    raw_content = raw_bytes.decode("utf-8", errors="replace")
    size_bytes = len(raw_bytes)

    msg = email.message_from_bytes(raw_bytes, policy=email.policy.compat32)

    date_sent = None
    date_str = msg.get("Date")
    if date_str:
        try:
            date_sent = _parse_date(date_str)
        except (ValueError, TypeError):
            date_sent = None

    return ParsedEmail(
        raw_hash=raw_hash,
        raw_content=raw_content,
        size_bytes=size_bytes,
        message_id=msg.get("Message-ID"),
        in_reply_to=msg.get("In-Reply-To"),
        references_header=msg.get("References"),
        from_addr=_parse_address_list(msg.get("From"))[0] if msg.get("From") else None,
        to_addrs=_parse_address_list(msg.get("To")),
        cc_addrs=_parse_address_list(msg.get("Cc")),
        bcc_addrs=_parse_address_list(msg.get("Bcc")),
        subject=msg.get("Subject"),
        date_sent=date_sent,
        body_text=_get_body(msg, "text/plain"),
        body_html=_get_body(msg, "text/html"),
    )
