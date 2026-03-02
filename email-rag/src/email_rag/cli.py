"""Click CLI entry point for email-rag."""

import subprocess
import sys
from pathlib import Path

import click

from email_rag.db.engine import get_session
from email_rag.db.schema import Email, RawMessage


@click.group()
def cli():
    """Email RAG — forensic email intelligence pipeline."""
    pass


@cli.command("setup-db")
def setup_db():
    """Run setup-db.sh to install PostgreSQL + pgvector and create schema."""
    script = Path(__file__).resolve().parent.parent.parent / "scripts" / "setup-db.sh"
    if not script.exists():
        raise click.ClickException(f"Script not found: {script}")
    click.echo(f"Running {script}...")
    result = subprocess.run(["bash", str(script)], check=False)
    sys.exit(result.returncode)


@cli.command("ingest-gmail")
@click.option("--days", default=180, help="Number of days to sync (default: 180)")
def ingest_gmail(days: int):
    """Sync emails from Gmail IMAP."""
    from email_rag.ingest.gmail import sync_gmail

    click.echo(f"Syncing Gmail (last {days} days)...")
    stats = sync_gmail(days=days)
    click.echo(f"  Fetched:    {stats['fetched']}")
    click.echo(f"  New raw:    {stats['new_raw']}")
    click.echo(f"  New emails: {stats['new_emails']}")
    click.echo(f"  Skipped:    {stats['skipped']}")
    click.echo(f"  Errors:     {stats['errors']}")


@cli.command("import-eml")
@click.argument("path", required=False)
def import_eml(path: str | None):
    """Import .eml files from archive directory."""
    from email_rag.ingest.eml_import import import_eml_files

    click.echo(f"Importing .eml files from {path or 'default archive path'}...")
    stats = import_eml_files(archive_path=path)
    click.echo(f"  Scanned:    {stats['scanned']}")
    click.echo(f"  New raw:    {stats['new_raw']}")
    click.echo(f"  New emails: {stats['new_emails']}")
    click.echo(f"  Skipped:    {stats['skipped']}")
    click.echo(f"  Errors:     {stats['errors']}")


@cli.command("load-facts")
@click.argument("path", required=False)
def load_facts(path: str | None):
    """Load known_facts.json into claims_log."""
    from email_rag.ingest.load_known_facts import load_known_facts

    click.echo("Loading known facts...")
    stats = load_known_facts(facts_path=path)
    click.echo(f"  Loaded:  {stats['loaded']}")
    click.echo(f"  Skipped: {stats['skipped']}")
    click.echo(f"  Errors:  {stats['errors']}")


@cli.command("rebuild-threads")
def rebuild_threads_cmd():
    """Reconstruct thread chains from email headers."""
    from email_rag.structure.threads import rebuild_threads

    click.echo("Rebuilding threads...")
    stats = rebuild_threads()
    click.echo(f"  Emails processed: {stats['emails']}")
    click.echo(f"  Threads created:  {stats['threads']}")


@cli.command("stats")
def stats():
    """Show counts by store, corpus, and subject_priority."""
    from sqlalchemy import func
    from email_rag.db.schema import ReviewQueue, ClaimsLog

    session = get_session()
    try:
        total = session.query(func.count(Email.id)).scalar()
        raw_total = session.query(func.count(RawMessage.id)).scalar()

        click.echo(f"\nRaw messages: {raw_total}")
        click.echo(f"Parsed emails: {total}")
        click.echo()

        # By store
        click.echo("By store:")
        for store, count in session.query(
            Email.store, func.count(Email.id)
        ).group_by(Email.store).all():
            click.echo(f"  {store}: {count}")

        # By corpus
        click.echo("\nBy corpus:")
        for corpus, count in session.query(
            Email.corpus, func.count(Email.id)
        ).group_by(Email.corpus).all():
            click.echo(f"  {corpus}: {count}")

        # Subject priority
        priority_count = session.query(func.count(Email.id)).filter(
            Email.subject_priority == True
        ).scalar()
        click.echo(f"\nSubject priority: {priority_count}")

        # Threads
        thread_count = session.query(
            func.count(func.distinct(Email.thread_id))
        ).filter(Email.thread_id.isnot(None)).scalar()
        click.echo(f"Threads: {thread_count}")

        # Review queue
        review_count = session.query(func.count(ReviewQueue.id)).filter(
            ReviewQueue.resolved == False
        ).scalar()
        click.echo(f"Review queue (unresolved): {review_count}")

        # Claims
        claims_count = session.query(func.count(ClaimsLog.id)).scalar()
        click.echo(f"Claims: {claims_count}")

    finally:
        session.close()


if __name__ == "__main__":
    cli()
