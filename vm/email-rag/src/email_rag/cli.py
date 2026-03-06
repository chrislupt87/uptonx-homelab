"""Email RAG CLI."""

import os
import subprocess
import click
from dotenv import load_dotenv

# Load env from secrets
env_path = os.environ.get("ENV_FILE", "/opt/email-rag/secrets/email-rag.env")
if os.path.exists(env_path):
    load_dotenv(env_path)


@click.group()
def cli():
    """Email RAG command-line interface."""
    pass


@cli.command("setup-db")
def setup_db():
    """Apply database schema."""
    db_url = os.environ.get("DB_URL", "")
    if not db_url:
        click.echo("DB_URL not set")
        return
    # Extract connection params
    import psycopg2
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor()
    schema_path = "/opt/email-rag/sql/email_rag_schema.sql"
    with open(schema_path) as f:
        cur.execute(f.read())
    click.echo("Schema applied successfully")
    cur.close()
    conn.close()


@cli.command("ingest-gmail")
def ingest_gmail():
    """Pull emails from Gmail via IMAP."""
    from email_rag.ingest.gmail import ingest_gmail as _ingest
    _ingest()


@cli.command("import-eml")
@click.argument("path", default="/mnt/nfs/volumes/email-rag/archive/")
def import_eml(path):
    """Import .eml files from a path."""
    from email_rag.ingest.eml_import import import_eml as _import
    _import(path)


@cli.command("load-facts")
@click.argument("path", default="/mnt/nfs/volumes/email-rag/config/known_facts.json")
def load_facts(path):
    """Load known facts from JSON file."""
    from email_rag.ingest.load_known_facts import load_facts as _load
    _load(path)


@cli.command("rebuild-threads")
def rebuild_threads():
    """Rebuild email thread groupings."""
    from email_rag.structure.threads import rebuild_threads as _rebuild
    _rebuild()


@cli.command("triage")
def triage():
    """Run triage: chunk and embed unprocessed emails."""
    from email_rag.analysis.triage import triage_emails
    triage_emails()


@cli.command("analyze")
def analyze():
    """Run deep analysis on priority threads."""
    from email_rag.analysis.deep_analysis import run_deep_analysis
    run_deep_analysis()


@cli.command("detect-anomalies")
def detect_anomalies():
    """Scan emails for header inconsistencies, reply chain gaps, and hidden text."""
    from email_rag.analysis.anomaly_detector import run_anomaly_detection
    run_anomaly_detection()


@cli.command("forensic-scan")
def forensic_scan():
    """Scan for hidden codes, steganography, and reply chain tampering."""
    from email_rag.analysis.forensic_decoder import run_forensic_scan
    run_forensic_scan()


@cli.command("backfill-metadata")
def backfill_metadata():
    """Re-parse raw_messages to populate metadata columns on existing emails."""
    import email as email_mod
    from email_rag.db.schema import SessionLocal, Email, RawMessage
    from email_rag.ingest.metadata import extract_eml_metadata

    db = SessionLocal()
    try:
        # Get all emails joined with their raw content
        rows = (
            db.query(Email, RawMessage.raw_content)
            .join(RawMessage, Email.raw_id == RawMessage.id)
            .all()
        )
        click.echo(f"Backfilling metadata for {len(rows)} emails...")

        updated = 0
        for em, raw_content in rows:
            try:
                msg = email_mod.message_from_string(raw_content)
                meta = extract_eml_metadata(msg)

                # Use COALESCE logic: don't overwrite IMAP-derived values with weaker ones
                # Only set is_read if currently NULL (IMAP value is stronger)
                if em.is_read is None and meta["is_read"] is not None:
                    em.is_read = meta["is_read"]
                # Only set is_flagged if currently default (False)
                if not em.is_flagged and meta["is_flagged"]:
                    em.is_flagged = meta["is_flagged"]
                # Don't touch is_replied — only IMAP can set it

                # Always overwrite these — derived from message content, not IMAP
                em.has_attachments = meta["has_attachments"]
                em.attachment_count = meta["attachment_count"]
                em.is_bulk = meta["is_bulk"]
                em.importance = meta["importance"]
                em.mail_client = meta["mail_client"]

                # Set gmail_labels from Takeout header if not already set from IMAP
                if not em.gmail_labels and meta["gmail_labels"]:
                    em.gmail_labels = meta["gmail_labels"]

                updated += 1
                if updated % 500 == 0:
                    db.commit()
                    click.echo(f"  ...{updated} processed")
            except Exception as e:
                click.echo(f"  Error on email {em.id}: {e}")
                continue

        db.commit()
        click.echo(f"Backfill complete: {updated} emails updated")
    finally:
        db.close()


@cli.command("stats")
def stats():
    """Show database statistics."""
    from email_rag.db.schema import SessionLocal, RawMessage, Email, Snippet, Finding
    from sqlalchemy import func

    db = SessionLocal()
    try:
        raw = db.query(func.count(RawMessage.id)).scalar()
        emails = db.query(func.count(Email.id)).scalar()
        snippets = db.query(func.count(Snippet.id)).scalar()
        findings = db.query(func.count(Finding.id)).scalar()
        processed = db.query(func.count(Email.id)).filter(Email.processed == True).scalar()
        priority = db.query(func.count(Email.id)).filter(Email.subject_priority == True).scalar()

        click.echo(f"Raw messages:  {raw}")
        click.echo(f"Emails:        {emails}")
        click.echo(f"  Processed:   {processed}")
        click.echo(f"  Priority:    {priority}")
        click.echo(f"Snippets:      {snippets}")
        click.echo(f"Findings:      {findings}")
    finally:
        db.close()


if __name__ == "__main__":
    cli()
