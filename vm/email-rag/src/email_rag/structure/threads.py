"""Thread reconstruction — group emails into conversation threads."""

from sqlalchemy import func
from sqlalchemy.orm import Session

from email_rag.db.schema import SessionLocal, Email


def rebuild_threads():
    """Rebuild thread_id for all emails based on In-Reply-To and References."""
    db: Session = SessionLocal()

    try:
        # Reset all thread IDs
        db.query(Email).update({Email.thread_id: None})
        db.commit()

        # Build message_id -> email mapping
        emails = db.query(Email).order_by(Email.sent_at.asc().nullslast()).all()
        msg_id_map = {}
        for em in emails:
            if em.message_id:
                msg_id_map[em.message_id.strip("<>")] = em

        # Assign threads using In-Reply-To chains
        thread_counter = 0
        visited = set()

        for em in emails:
            if em.id in visited:
                continue

            # Walk the reply chain to find the root
            chain = [em]
            current = em
            while current.in_reply_to:
                ref_id = current.in_reply_to.strip("<>")
                parent = msg_id_map.get(ref_id)
                if parent and parent.id not in visited:
                    chain.append(parent)
                    current = parent
                else:
                    break

            # Assign thread_id to all in chain
            thread_counter += 1
            thread_id = f"thread-{thread_counter:06d}"
            for em_in_chain in chain:
                em_in_chain.thread_id = thread_id
                visited.add(em_in_chain.id)

        db.commit()

        total_threads = thread_counter
        total_emails = len(emails)
        print(f"Thread rebuild complete: {total_emails} emails -> {total_threads} threads")

    finally:
        db.close()
