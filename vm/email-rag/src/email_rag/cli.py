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
