"""Seed claims_log from known_facts.json."""

import json
from datetime import datetime, timezone
from pathlib import Path

import click

from email_rag.db.engine import get_session
from email_rag.db.schema import ClaimsLog


DEFAULT_FACTS_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "known_facts.json"


def load_known_facts(facts_path: str | None = None) -> dict:
    """Load known facts JSON into claims_log with source='known_facts_seed'.

    JSON format: array of objects with keys:
      - claim_text (required)
      - date_of_claim (optional, ISO 8601)
      - verified (optional, bool)
      - metadata (optional, object)

    Returns stats dict.
    """
    path = Path(facts_path) if facts_path else DEFAULT_FACTS_PATH
    if not path.exists():
        raise click.ClickException(f"Facts file not found: {path}")

    with open(path) as f:
        facts = json.load(f)

    if not isinstance(facts, list):
        raise click.ClickException("known_facts.json must be a JSON array")

    stats = {"loaded": 0, "skipped": 0, "errors": 0}

    session = get_session()
    try:
        # Get existing known_facts_seed claims to avoid duplicates
        existing = set()
        for row in session.query(ClaimsLog.claim_text).filter(
            ClaimsLog.source == "known_facts_seed"
        ).all():
            existing.add(row[0])

        for fact in facts:
            claim_text = fact.get("claim_text")
            if not claim_text:
                stats["errors"] += 1
                continue

            if claim_text in existing:
                stats["skipped"] += 1
                continue

            date_str = fact.get("date_of_claim")
            date_of_claim = None
            if date_str:
                try:
                    date_of_claim = datetime.fromisoformat(date_str)
                    if date_of_claim.tzinfo is None:
                        date_of_claim = date_of_claim.replace(tzinfo=timezone.utc)
                except ValueError:
                    pass

            session.add(ClaimsLog(
                claim_text=claim_text,
                source="known_facts_seed",
                date_of_claim=date_of_claim,
                verified=fact.get("verified"),
                metadata_=fact.get("metadata"),
            ))
            stats["loaded"] += 1
            existing.add(claim_text)

        session.commit()

    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return stats
