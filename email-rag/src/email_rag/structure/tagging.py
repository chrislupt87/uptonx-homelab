"""Corpus and subject_priority classification logic.

Corpus rules (first match wins):
  1. from_addr IN (MY_GMAIL, MY_ICLOUD) → 'sent'
  2. subject_priority = true             → 'subject'
  3. else                                → 'other'

subject_priority = PRIMARY_SUBJECT_EMAIL in any address field.
"""

from email_rag.config import MY_ADDRESSES, PRIMARY_SUBJECT_EMAIL


def _normalize(addr: str | None) -> str:
    if not addr:
        return ""
    return addr.strip().lower()


def _addrs_lower(addrs: list[str] | None) -> list[str]:
    if not addrs:
        return []
    return [_normalize(a) for a in addrs]


def compute_subject_priority(
    from_addr: str | None,
    to_addrs: list[str] | None,
    cc_addrs: list[str] | None,
    bcc_addrs: list[str] | None,
) -> bool:
    """Check if PRIMARY_SUBJECT_EMAIL appears in any address field."""
    target = _normalize(PRIMARY_SUBJECT_EMAIL)
    all_addrs = (
        [_normalize(from_addr)]
        + _addrs_lower(to_addrs)
        + _addrs_lower(cc_addrs)
        + _addrs_lower(bcc_addrs)
    )
    return target in all_addrs


def compute_corpus(
    from_addr: str | None,
    subject_priority: bool,
) -> str:
    """Determine corpus tag: 'sent', 'subject', or 'other'."""
    if _normalize(from_addr) in MY_ADDRESSES:
        return "sent"
    if subject_priority:
        return "subject"
    return "other"


def classify_email(
    from_addr: str | None,
    to_addrs: list[str] | None,
    cc_addrs: list[str] | None,
    bcc_addrs: list[str] | None,
) -> tuple[str, bool]:
    """Return (corpus, subject_priority) for an email."""
    sp = compute_subject_priority(from_addr, to_addrs, cc_addrs, bcc_addrs)
    corpus = compute_corpus(from_addr, sp)
    return corpus, sp
