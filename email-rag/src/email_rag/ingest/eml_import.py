"""Bulk .eml file import from NFS archive directory."""

from pathlib import Path

import click
from sqlalchemy.dialects.postgresql import insert as pg_insert
from tqdm import tqdm

from email_rag.config import EML_ARCHIVE_PATH
from email_rag.db.engine import get_session
from email_rag.db.schema import RawMessage, Email, ReviewQueue
from email_rag.ingest.parse import parse_raw_email
from email_rag.structure.tagging import classify_email


def import_eml_files(archive_path: str | None = None) -> dict:
    """Scan archive directory for .eml files and import them.

    Resume-safe via SHA-256 dedup (ON CONFLICT DO NOTHING).
    Returns stats dict.
    """
    base = Path(archive_path or EML_ARCHIVE_PATH)
    if not base.exists():
        raise click.ClickException(f"Archive path does not exist: {base}")

    eml_files = sorted(base.rglob("*.eml"))
    if not eml_files:
        click.echo(f"  No .eml files found in {base}")
        return {"scanned": 0, "new_raw": 0, "new_emails": 0, "errors": 0, "skipped": 0}

    stats = {"scanned": 0, "new_raw": 0, "new_emails": 0, "errors": 0, "skipped": 0}

    session = get_session()
    try:
        for eml_path in tqdm(eml_files, desc="Importing .eml", unit="file"):
            stats["scanned"] += 1
            try:
                raw_bytes = eml_path.read_bytes()
                parsed = parse_raw_email(raw_bytes)
            except Exception as e:
                stats["errors"] += 1
                rel_path = str(eml_path.relative_to(base))
                session.add(ReviewQueue(
                    reason="parse_error",
                    details=f"EML parse error ({rel_path}): {e}",
                ))
                continue

            rel_path = str(eml_path.relative_to(base))

            # Insert raw_message
            result = session.execute(
                pg_insert(RawMessage).values(
                    id=parsed.raw_hash,
                    raw_content=parsed.raw_content,
                    source_file=rel_path,
                    store="archive",
                    size_bytes=parsed.size_bytes,
                ).on_conflict_do_nothing(index_elements=["id"])
            )
            if result.rowcount > 0:
                stats["new_raw"] += 1

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
                    store="archive",
                    corpus=corpus,
                    subject_priority=subject_priority,
                    gmail_labels=None,
                    gmail_read=None,
                    gmail_starred=None,
                    gmail_importance=None,
                ).on_conflict_do_nothing(constraint="uq_emails_raw_id_store")
            )
            if result.rowcount > 0:
                stats["new_emails"] += 1
            else:
                stats["skipped"] += 1

        session.commit()

    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return stats
