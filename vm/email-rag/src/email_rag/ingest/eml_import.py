"""Import .eml files from NFS archive — resume-safe via SHA-256 dedup."""

import email
import hashlib
import os
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

from sqlalchemy.orm import Session
from tqdm import tqdm

from email_rag.db.schema import SessionLocal, RawMessage, Email
from email_rag.ingest.gmail import classify_email, extract_body, parse_addrs
from email_rag.ingest.metadata import extract_eml_metadata

NFS_BASE = os.environ.get("NFS_BASE", "/mnt/nfs/volumes/email-rag")
ARCHIVE_DIR = os.path.join(NFS_BASE, "archive")


def sha256_of(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()


def import_eml(path: str = None):
    """Import .eml files from archive directory or specific path."""
    search_path = path or ARCHIVE_DIR

    if os.path.isfile(search_path):
        eml_files = [Path(search_path)]
    else:
        eml_files = sorted(Path(search_path).rglob("*.eml"))

    if not eml_files:
        print(f"No .eml files found in {search_path}")
        return

    print(f"Found {len(eml_files)} .eml files")

    db: Session = SessionLocal()
    new_count = 0
    skip_count = 0

    try:
        for eml_path in tqdm(eml_files, desc="EML import"):
            try:
                raw_content = eml_path.read_text(encoding="utf-8", errors="replace")
                content_hash = sha256_of(raw_content)

                # Resume-safe: skip if already imported (no_autoflush for FK safety)
                with db.no_autoflush:
                    existing = db.query(RawMessage).filter_by(id=content_hash).first()
                if existing:
                    skip_count += 1
                    continue

                msg = email.message_from_string(raw_content)
                from_addr = parseaddr(msg.get("From", ""))[1]
                to_addrs = parse_addrs(msg.get("To"))
                cc_addrs = parse_addrs(msg.get("Cc"))
                corpus, subject_priority = classify_email(from_addr, to_addrs, cc_addrs)

                headers = {k: v for k, v in msg.items()}
                sent_at = None
                try:
                    sent_at = parsedate_to_datetime(msg.get("Date", ""))
                except Exception:
                    pass

                # Extract metadata from message headers
                meta = extract_eml_metadata(msg)

                raw_msg = RawMessage(
                    id=content_hash,
                    source="icloud",
                    corpus=corpus,
                    store="archive",
                    raw_content=raw_content,
                    raw_headers=headers,
                    file_path=str(eml_path),
                    subject_priority=subject_priority,
                )
                db.add(raw_msg)

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
                    store="archive",
                    subject_priority=subject_priority,
                    # Metadata from headers
                    is_read=meta["is_read"],
                    is_flagged=meta["is_flagged"],
                    has_attachments=meta["has_attachments"],
                    attachment_count=meta["attachment_count"],
                    is_bulk=meta["is_bulk"],
                    importance=meta["importance"],
                    mail_client=meta["mail_client"],
                    gmail_labels=meta["gmail_labels"],
                    # Not available from EML files
                    is_replied=False,
                    gmail_thread_id=None,
                    gmail_message_id=None,
                )
                db.add(email_record)
                new_count += 1

                if new_count % 100 == 0:
                    db.commit()

            except Exception as e:
                print(f"Error processing {eml_path}: {e}")
                continue

        db.commit()
        print(f"EML import complete: {new_count} new, {skip_count} skipped (already imported)")
    finally:
        db.close()
