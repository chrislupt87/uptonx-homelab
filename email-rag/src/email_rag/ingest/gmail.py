"""Gmail IMAP sync — fetch from [Gmail]/All Mail via App Password."""

import imaplib
import re
import time
from datetime import datetime, timedelta, timezone

import click
from sqlalchemy.dialects.postgresql import insert as pg_insert

from email_rag.config import (
    GMAIL_IMAP_HOST, GMAIL_IMAP_PORT, MY_GMAIL, GMAIL_APP_PASSWORD,
    GMAIL_SYNC_DAYS, GMAIL_BATCH_SIZE, GMAIL_MAX_RETRIES,
)
from email_rag.db.engine import get_session
from email_rag.db.schema import RawMessage, Email, ReviewQueue
from email_rag.ingest.parse import parse_raw_email
from email_rag.structure.tagging import classify_email


def _imap_date(days_ago: int) -> str:
    """Format date for IMAP SINCE filter: DD-Mon-YYYY."""
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return dt.strftime("%d-%b-%Y")


def _parse_gmail_labels(label_data: bytes | str) -> list[str]:
    """Extract labels from X-GM-LABELS response."""
    if isinstance(label_data, bytes):
        label_data = label_data.decode("utf-8", errors="replace")
    labels = re.findall(r'"([^"]+)"|(\S+)', label_data)
    return [quoted or unquoted for quoted, unquoted in labels if quoted or unquoted]


def _extract_gmail_metadata(fetch_data: dict) -> dict:
    """Extract Gmail-specific metadata from fetch response parts."""
    flags_raw = fetch_data.get(b"FLAGS", b"")
    if isinstance(flags_raw, bytes):
        flags_str = flags_raw.decode("utf-8", errors="replace")
    else:
        flags_str = str(flags_raw)

    labels_raw = fetch_data.get(b"X-GM-LABELS", b"")
    labels = _parse_gmail_labels(labels_raw)

    return {
        "gmail_read": "\\Seen" in flags_str,
        "gmail_starred": "\\Flagged" in flags_str,
        "gmail_labels": labels,
        "gmail_importance": "high" if "\\Important" in flags_str else "normal",
    }


def _connect_imap() -> imaplib.IMAP4_SSL:
    if not GMAIL_APP_PASSWORD:
        raise click.ClickException(
            "GMAIL_APP_PASSWORD not set. Generate an App Password at "
            "https://myaccount.google.com/apppasswords"
        )
    conn = imaplib.IMAP4_SSL(GMAIL_IMAP_HOST, GMAIL_IMAP_PORT)
    conn.login(MY_GMAIL, GMAIL_APP_PASSWORD)
    return conn


def sync_gmail(days: int = GMAIL_SYNC_DAYS) -> dict:
    """Sync emails from Gmail IMAP. Returns stats dict."""
    stats = {"fetched": 0, "new_raw": 0, "new_emails": 0, "errors": 0, "skipped": 0}

    for attempt in range(1, GMAIL_MAX_RETRIES + 1):
        try:
            conn = _connect_imap()
            break
        except (imaplib.IMAP4.error, OSError) as e:
            if attempt == GMAIL_MAX_RETRIES:
                raise click.ClickException(f"IMAP connection failed after {GMAIL_MAX_RETRIES} attempts: {e}")
            click.echo(f"  Connection attempt {attempt} failed, retrying...")
            time.sleep(2 ** attempt)

    try:
        status, _ = conn.select('"[Gmail]/All Mail"', readonly=True)
        if status != "OK":
            raise click.ClickException("Failed to select [Gmail]/All Mail")

        since_date = _imap_date(days)
        status, msg_ids = conn.search(None, f"SINCE {since_date}")
        if status != "OK":
            raise click.ClickException("IMAP search failed")

        id_list = msg_ids[0].split()
        click.echo(f"  Found {len(id_list)} messages since {since_date}")

        session = get_session()
        try:
            for i in range(0, len(id_list), GMAIL_BATCH_SIZE):
                batch = id_list[i:i + GMAIL_BATCH_SIZE]
                batch_str = b",".join(batch)

                status, fetch_response = conn.fetch(
                    batch_str, "(RFC822 FLAGS X-GM-LABELS)"
                )
                if status != "OK":
                    stats["errors"] += len(batch)
                    continue

                for item in fetch_response:
                    if not isinstance(item, tuple) or len(item) < 2:
                        continue

                    raw_bytes = item[1]
                    if not isinstance(raw_bytes, bytes):
                        continue

                    stats["fetched"] += 1

                    try:
                        parsed = parse_raw_email(raw_bytes)
                    except Exception as e:
                        stats["errors"] += 1
                        session.add(ReviewQueue(
                            reason="parse_error",
                            details=f"Gmail parse error: {e}",
                        ))
                        continue

                    # Insert raw_message (dedup on SHA-256)
                    result = session.execute(
                        pg_insert(RawMessage).values(
                            id=parsed.raw_hash,
                            raw_content=parsed.raw_content,
                            source_file=None,
                            store="rolling",
                            size_bytes=parsed.size_bytes,
                        ).on_conflict_do_nothing(index_elements=["id"])
                    )
                    if result.rowcount > 0:
                        stats["new_raw"] += 1

                    # Extract Gmail metadata from fetch response
                    # For simplicity, parse flags from the first element
                    flags_data = item[0] if isinstance(item[0], bytes) else b""
                    gmail_meta = {
                        "gmail_read": b"\\Seen" in flags_data,
                        "gmail_starred": b"\\Flagged" in flags_data,
                        "gmail_labels": [],
                        "gmail_importance": "high" if b"\\Important" in flags_data else "normal",
                    }

                    corpus, subject_priority = classify_email(
                        parsed.from_addr, parsed.to_addrs,
                        parsed.cc_addrs, parsed.bcc_addrs,
                    )

                    result = session.execute(
                        pg_insert(Email).values(
                            raw_id=parsed.raw_hash,
                            message_id=parsed.message_id,
                            in_reply_to=parsed.in_reply_to,
                            references_header=parsed.references_header,
                            from_addr=parsed.from_addr,
                            to_addrs=parsed.to_addrs,
                            cc_addrs=parsed.cc_addrs,
                            bcc_addrs=parsed.bcc_addrs,
                            subject=parsed.subject,
                            date_sent=parsed.date_sent,
                            body_text=parsed.body_text,
                            body_html=parsed.body_html,
                            store="rolling",
                            corpus=corpus,
                            subject_priority=subject_priority,
                            gmail_labels=gmail_meta["gmail_labels"],
                            gmail_read=gmail_meta["gmail_read"],
                            gmail_starred=gmail_meta["gmail_starred"],
                            gmail_importance=gmail_meta["gmail_importance"],
                        ).on_conflict_do_nothing(constraint="uq_emails_raw_id_store")
                    )
                    if result.rowcount > 0:
                        stats["new_emails"] += 1
                    else:
                        stats["skipped"] += 1

                session.commit()
                click.echo(f"  Processed {min(i + GMAIL_BATCH_SIZE, len(id_list))}/{len(id_list)}")

        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    finally:
        try:
            conn.logout()
        except Exception:
            pass

    return stats
