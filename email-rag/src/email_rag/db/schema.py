"""SQLAlchemy ORM models matching email_rag_schema.sql."""

from sqlalchemy import (
    Column, Integer, Text, Boolean, DateTime, Float, ForeignKey, CheckConstraint,
    UniqueConstraint, Index,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector

Base = declarative_base()


class RawMessage(Base):
    __tablename__ = "raw_messages"

    id = Column(Text, primary_key=True)
    raw_content = Column(Text, nullable=False)
    source_file = Column(Text)
    store = Column(Text, nullable=False)
    imported_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    size_bytes = Column(Integer)

    __table_args__ = (
        CheckConstraint("store IN ('rolling', 'archive')", name="ck_raw_messages_store"),
    )

    emails = relationship("Email", back_populates="raw_message")


class Snapshot(Base):
    __tablename__ = "snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    metadata_ = Column("metadata", JSONB)

    findings = relationship("Finding", back_populates="snapshot")


class Email(Base):
    __tablename__ = "emails"

    id = Column(Integer, primary_key=True, autoincrement=True)
    raw_id = Column(Text, ForeignKey("raw_messages.id"), nullable=False)
    message_id = Column(Text)
    thread_id = Column(Text)
    in_reply_to = Column(Text)
    references_header = Column(Text)
    from_addr = Column(Text)
    to_addrs = Column(ARRAY(Text))
    cc_addrs = Column(ARRAY(Text))
    bcc_addrs = Column(ARRAY(Text))
    subject = Column(Text)
    date_sent = Column(DateTime(timezone=True))
    body_text = Column(Text)
    body_html = Column(Text)
    store = Column(Text, nullable=False)
    corpus = Column(Text, nullable=False)
    subject_priority = Column(Boolean, nullable=False, default=False)
    gmail_labels = Column(ARRAY(Text))
    gmail_read = Column(Boolean)
    gmail_starred = Column(Boolean)
    gmail_importance = Column(Text)

    __table_args__ = (
        UniqueConstraint("raw_id", "store", name="uq_emails_raw_id_store"),
        CheckConstraint("store IN ('rolling', 'archive')", name="ck_emails_store"),
        CheckConstraint("corpus IN ('sent', 'subject', 'other')", name="ck_emails_corpus"),
    )

    raw_message = relationship("RawMessage", back_populates="emails")
    snippets = relationship("Snippet", back_populates="email")
    entities = relationship("Entity", back_populates="email")


class Snippet(Base):
    __tablename__ = "snippets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email_id = Column(Integer, ForeignKey("emails.id", ondelete="CASCADE"), nullable=False)
    raw_id = Column(Text, ForeignKey("raw_messages.id"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(1024))
    store = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("store IN ('rolling', 'archive')", name="ck_snippets_store"),
    )

    email = relationship("Email", back_populates="snippets")


class Entity(Base):
    __tablename__ = "entities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email_id = Column(Integer, ForeignKey("emails.id", ondelete="CASCADE"), nullable=False)
    raw_id = Column(Text, ForeignKey("raw_messages.id"), nullable=False)
    entity_type = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    context = Column(Text)
    confidence = Column(Float)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    email = relationship("Email", back_populates="entities")


class ClaimsLog(Base):
    __tablename__ = "claims_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    claim_text = Column(Text, nullable=False)
    claim_embedding = Column(Vector(1024))
    source = Column(Text, nullable=False)
    source_email_id = Column(Integer, ForeignKey("emails.id", ondelete="SET NULL"))
    date_of_claim = Column(DateTime(timezone=True))
    verified = Column(Boolean)
    contradicts_claim_ids = Column(JSONB)
    metadata_ = Column("metadata", JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Timeline(Base):
    __tablename__ = "timeline"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email_id = Column(Integer, ForeignKey("emails.id", ondelete="SET NULL"))
    event_date = Column(DateTime(timezone=True), nullable=False)
    event_type = Column(Text, nullable=False)
    summary = Column(Text, nullable=False)
    participants = Column(ARRAY(Text))
    source = Column(Text)
    confidence = Column(Float)
    metadata_ = Column("metadata", JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SenderStats(Base):
    __tablename__ = "sender_stats"

    from_addr = Column(Text, primary_key=True)
    total_count = Column(Integer, nullable=False, default=0)
    sent_count = Column(Integer, nullable=False, default=0)
    subject_count = Column(Integer, nullable=False, default=0)
    other_count = Column(Integer, nullable=False, default=0)
    priority_count = Column(Integer, nullable=False, default=0)
    first_seen = Column(DateTime(timezone=True))
    last_seen = Column(DateTime(timezone=True))
    refreshed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ReviewQueue(Base):
    __tablename__ = "review_queue"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email_id = Column(Integer, ForeignKey("emails.id", ondelete="CASCADE"))
    raw_id = Column(Text, ForeignKey("raw_messages.id"))
    reason = Column(Text, nullable=False)
    details = Column(Text)
    resolved = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resolved_at = Column(DateTime(timezone=True))


class Finding(Base):
    __tablename__ = "findings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_id = Column(Integer, ForeignKey("snapshots.id", ondelete="SET NULL"))
    title = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    supporting_email_ids = Column(JSONB, nullable=False)
    grounding = Column(Text, nullable=False)
    contradicts_finding_ids = Column(JSONB)
    inference_score_detail = Column(JSONB)
    tags = Column(ARRAY(Text))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "jsonb_array_length(supporting_email_ids) > 0",
            name="ck_findings_citations",
        ),
        CheckConstraint(
            "grounding IN ('grounded', 'inferred', 'speculative')",
            name="ck_findings_grounding",
        ),
    )

    snapshot = relationship("Snapshot", back_populates="findings")
