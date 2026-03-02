"""Load known facts from a structured file into the claims_log."""

import json
import os
from pathlib import Path

from sqlalchemy.orm import Session

from email_rag.db.schema import SessionLocal, ClaimLog

NFS_BASE = os.environ.get("NFS_BASE", "/mnt/nfs/volumes/email-rag")
FACTS_FILE = os.path.join(NFS_BASE, "config", "known_facts.json")


def load_facts(facts_path: str = None):
    """Load known facts from JSON file into claims_log.

    Expected format:
    [
        {
            "claim_text": "...",
            "claim_type": "factual",
            "speaker": "known",
            "confidence": 1.0,
            "raw_id": "manual-entry"
        }
    ]
    """
    path = facts_path or FACTS_FILE

    if not os.path.exists(path):
        print(f"Facts file not found: {path}")
        print("Create a JSON file with known facts to seed the database.")
        return

    with open(path) as f:
        facts = json.load(f)

    db: Session = SessionLocal()
    count = 0

    try:
        for fact in facts:
            claim = ClaimLog(
                raw_id=fact.get("raw_id", "manual-entry"),
                claim_text=fact["claim_text"],
                claim_type=fact.get("claim_type", "factual"),
                speaker=fact.get("speaker", "known"),
                confidence=fact.get("confidence", 1.0),
            )
            db.add(claim)
            count += 1

        db.commit()
        print(f"Loaded {count} known facts")
    finally:
        db.close()
