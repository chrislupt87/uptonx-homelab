"""Gmail IMAP ingest — pull last 180 days, classify corpus."""

import imaplib
import email
import hashlib
import os
from datetime import datetime, timedelta
from email.utils import parseaddr, parsedate_to_datetime

from sqlalchemy.orm import Session
from tqdm import tqdm

from email_rag.db.schema import SessionLocal, RawMessage, Email
from email_rag.ingest.metadata import extract_eml_metadata, parse_imap_envelope

MY_GMAIL = os.environ.get("MY_GMAIL", "")
MY_ICLOUD = os.environ.get("MY_ICLOUD", "")
PRIMARY_SUBJECT = os.environ.get("PRIMARY_SUBJECT_EMAIL", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")


def connect_gmail():
    imap = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    imap.login(MY_GMAIL, GMAIL_APP_PASSWORD)
    return imap


def sha256_of(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()


def classify_email(from_addr: str, to_addrs: list[str], cc_addrs: list[str]):
    """Determine corpus and subject_priority."""
    all_addrs = [from_addr.lower()] + [a.lower() for a in to_addrs + cc_addrs]
    my_addrs = {MY_GMAIL.lower(), MY_ICLOUD.lower()}
    subject_addr = PRIMARY_SUBJECT.lower()

    corpus = "other"
    if from_addr.lower() in my_addrs:
        corpus = "sent"
    if subject_addr and any(subject_addr in a for a in all_addrs):
        corpus = "subject"

    subject_priority = subject_addr and any(subject_addr in a for a in all_addrs)
    return corpus, bool(subject_priority)


def extract_body(msg):
    """Extract plain text body from email message."""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode("utf-8", errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            return payload.decode("utf-8", errors="replace")
    return ""


def parse_addrs(header_value):
    """Parse a comma-separated address list."""
    if not header_value:
        return []
    return [parseaddr(a)[1] for a in header_value.split(",") if parseaddr(a)[1]]


def ingest_gmail():
    """Pull last 180 days from Gmail via IMAP."""
    if not GMAIL_APP_PASSWORD:
        print("GMAIL_APP_PASSWORD not set, skipping Gmail ingest")
        return

    imap = connect_gmail()
    imap.select('"[Gmail]/All Mail"', readonly=True)

    since_date = (datetime.now() - timedelta(days=180)).strftime("%d-%b-%Y")
    _, msg_ids = imap.search(None, f"SINCE {since_date}")
    msg_id_list = msg_ids[0].split()

    print(f"Found {len(msg_id_list)} messages since {since_date}")

    db: Session = SessionLocal()
    new_count = 0

    try:
        for msg_id in tqdm(msg_id_list, desc="Gmail ingest"):
            _, data = imap.fetch(msg_id, "(RFC822 FLAGS X-GM-LABELS X-GM-THRID X-GM-MSGID)")

            # data[0] is a tuple: (envelope_line, rfc822_bytes)
            envelope_line = data[0][0] if data[0][0] else b""
            raw_bytes = data[0][1]
            raw_content = raw_bytes.decode("utf-8", errors="replace")
            content_hash = sha256_of(raw_content)

            # Dedup by SHA-256 (no_autoflush to avoid FK ordering issues)
            with db.no_autoflush:
                if db.query(RawMessage).filter_by(id=content_hash).first():
                    continue

            # Parse IMAP envelope for flags and Gmail extensions
            imap_meta = parse_imap_envelope(envelope_line)

            msg = email.message_from_bytes(raw_bytes)
            from_addr = parseaddr(msg.get("From", ""))[1]
            to_addrs = parse_addrs(msg.get("To"))
            cc_addrs = parse_addrs(msg.get("Cc"))
            corpus, subject_priority = classify_email(from_addr, to_addrs, cc_addrs)

            # Only keep sent + subject corpus
            if corpus not in ("sent", "subject"):
                continue

            headers = {k: v for k, v in msg.items()}
            sent_at = None
            try:
                sent_at = parsedate_to_datetime(msg.get("Date", ""))
            except Exception:
                pass

            # Extract message-level metadata (attachments, bulk, importance, etc.)
            msg_meta = extract_eml_metadata(msg)

            raw_msg = RawMessage(
                id=content_hash,
                source="gmail",
                corpus=corpus,
                store="rolling",
                raw_content=raw_content,
                raw_headers=headers,
                subject_priority=subject_priority,
            )
            db.add(raw_msg)
            db.flush()  # ensure raw_message exists before email FK

            body_text = extract_body(msg)
            email_record = Email(
                raw_id=content_hash,
                message_id=msg.get("Message-ID"),
                in_reply_to=msg.get("In-Reply-To"),
                from_addr=from_addr,
                to_addrs=to_addrs,
                cc_addrs=cc_addrs,
                subject=msg.get("Subject"),
                body_text=body_text,
                sent_at=sent_at,
                corpus=corpus,
                store="rolling",
                subject_priority=subject_priority,
                # IMAP flags
                is_read=imap_meta["is_read"],
                is_flagged=imap_meta["is_flagged"],
                is_replied=imap_meta["is_replied"],
                # Gmail extensions
                gmail_labels=imap_meta["gmail_labels"],
                gmail_thread_id=imap_meta["gmail_thread_id"],
                gmail_message_id=imap_meta["gmail_message_id"],
                # Message-level metadata
                has_attachments=msg_meta["has_attachments"],
                attachment_count=msg_meta["attachment_count"],
                is_bulk=msg_meta["is_bulk"],
                importance=msg_meta["importance"],
                mail_client=msg_meta["mail_client"],
            )
            db.add(email_record)
            new_count += 1

            if new_count % 50 == 0:
                db.commit()

        db.commit()
        print(f"Gmail ingest complete: {new_count} new messages")
    finally:
        db.close()
        imap.logout()
