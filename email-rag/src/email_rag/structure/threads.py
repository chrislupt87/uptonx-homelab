"""Thread chain reconstruction using Union-Find on Message-ID/In-Reply-To/References."""

import uuid

import click
from sqlalchemy import text

from email_rag.db.engine import get_session
from email_rag.db.schema import Email


class UnionFind:
    """Simple Union-Find (disjoint set) for grouping message IDs into threads."""

    def __init__(self):
        self.parent: dict[str, str] = {}
        self.rank: dict[str, int] = {}

    def find(self, x: str) -> str:
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x: str, y: str) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1


def rebuild_threads() -> dict:
    """Reconstruct thread_id for all emails using Union-Find.

    Links emails by Message-ID, In-Reply-To, and References headers.
    Each connected component gets one UUID4 thread_id.
    Returns stats dict.
    """
    session = get_session()
    try:
        emails = session.query(
            Email.id, Email.message_id, Email.in_reply_to, Email.references_header
        ).all()

        if not emails:
            return {"emails": 0, "threads": 0}

        uf = UnionFind()
        email_to_msgid: dict[int, str] = {}

        for eid, msg_id, in_reply_to, refs_header in emails:
            if not msg_id:
                # Emails without Message-ID get a synthetic node
                msg_id = f"_synthetic_{eid}"

            email_to_msgid[eid] = msg_id
            uf.find(msg_id)  # ensure node exists

            if in_reply_to:
                uf.union(msg_id, in_reply_to.strip())

            if refs_header:
                ref_ids = refs_header.split()
                for ref_id in ref_ids:
                    ref_id = ref_id.strip()
                    if ref_id:
                        uf.union(msg_id, ref_id)

        # Assign UUID4 thread_id per connected component
        root_to_thread: dict[str, str] = {}
        updates: list[dict] = []

        for eid, msg_id in email_to_msgid.items():
            root = uf.find(msg_id)
            if root not in root_to_thread:
                root_to_thread[root] = str(uuid.uuid4())
            updates.append({"eid": eid, "tid": root_to_thread[root]})

        # Batch update
        if updates:
            for batch_start in range(0, len(updates), 500):
                batch = updates[batch_start:batch_start + 500]
                for u in batch:
                    session.execute(
                        text("UPDATE emails SET thread_id = :tid WHERE id = :eid"),
                        {"tid": u["tid"], "eid": u["eid"]},
                    )
            session.commit()

        return {
            "emails": len(email_to_msgid),
            "threads": len(root_to_thread),
        }

    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
