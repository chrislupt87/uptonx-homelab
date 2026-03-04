"""Database connection and ORM models."""

import os
from sqlalchemy import (
    create_engine, Column, Text, BigInteger, Boolean, Integer, Float,
    DateTime, ForeignKey, Index, CheckConstraint, ARRAY
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector

DB_URL = os.environ.get("DB_URL", "postgresql://email_rag_user:password@localhost/email_rag")

engine = create_engine(DB_URL, pool_size=10, max_overflow=5)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class RawMessage(Base):
    __tablename__ = "raw_messages"

    id = Column(Text, primary_key=True)
    source = Column(Text, nullable=False)
    corpus = Column(Text, nullable=False)
    store = Column(Text, nullable=False)
    raw_content = Column(Text, nullable=False)
    raw_headers = Column(JSONB)
    file_path = Column(Text)
    imported_at = Column(DateTime(timezone=True), server_default=func.now())
    subject_priority = Column(Boolean, default=False)


class Email(Base):
    __tablename__ = "emails"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    raw_id = Column(Text, ForeignKey("raw_messages.id"), nullable=False)
    message_id = Column(Text)
    in_reply_to = Column(Text)
    thread_id = Column(Text)
    from_addr = Column(Text, nullable=False)
    to_addrs = Column(ARRAY(Text), default=[])
    cc_addrs = Column(ARRAY(Text), default=[])
    subject = Column(Text)
    body_text = Column(Text)
    sent_at = Column(DateTime(timezone=True))
    corpus = Column(Text, nullable=False)
    store = Column(Text, nullable=False)
    subject_priority = Column(Boolean, default=False)
    processed = Column(Boolean, default=False)
    processed_at = Column(DateTime(timezone=True))
    is_read = Column(Boolean)
    is_flagged = Column(Boolean, default=False)
    is_replied = Column(Boolean, default=False)
    gmail_labels = Column(ARRAY(Text), default=[])
    gmail_thread_id = Column(Text)
    gmail_message_id = Column(Text)
    has_attachments = Column(Boolean, default=False)
    attachment_count = Column(Integer, default=0)
    is_bulk = Column(Boolean, default=False)
    importance = Column(Text)
    mail_client = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Snippet(Base):
    __tablename__ = "snippets"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    raw_id = Column(Text, ForeignKey("raw_messages.id"), nullable=False)
    email_id = Column(BigInteger, ForeignKey("emails.id"))
    content = Column(Text, nullable=False)
    embedding = Column(Vector(1024))
    store = Column(Text, nullable=False)
    chunk_index = Column(Integer, default=0)
    token_count = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Entity(Base):
    __tablename__ = "entities"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    raw_id = Column(Text, ForeignKey("raw_messages.id"), nullable=False)
    email_id = Column(BigInteger, ForeignKey("emails.id"))
    entity_type = Column(Text, nullable=False)
    entity_value = Column(Text, nullable=False)
    confidence = Column(Float)
    context = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ClaimLog(Base):
    __tablename__ = "claims_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    raw_id = Column(Text, ForeignKey("raw_messages.id"), nullable=False)
    email_id = Column(BigInteger, ForeignKey("emails.id"))
    claim_text = Column(Text, nullable=False)
    claim_embedding = Column(Vector(1024))
    claim_type = Column(Text)
    speaker = Column(Text)
    confidence = Column(Float)
    contradicts_claim_ids = Column(ARRAY(BigInteger), default=[])
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Timeline(Base):
    __tablename__ = "timeline"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    raw_id = Column(Text, ForeignKey("raw_messages.id"), nullable=False)
    email_id = Column(BigInteger, ForeignKey("emails.id"))
    event_date = Column(DateTime(timezone=True))
    event_type = Column(Text, nullable=False)
    description = Column(Text, nullable=False)
    participants = Column(ARRAY(Text))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class SenderStats(Base):
    __tablename__ = "sender_stats"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    email_address = Column(Text, nullable=False, unique=True)
    display_name = Column(Text)
    total_messages = Column(Integer, default=0)
    first_seen = Column(DateTime(timezone=True))
    last_seen = Column(DateTime(timezone=True))
    avg_response_time_hours = Column(Float)
    top_topics = Column(JSONB)
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class ReviewQueue(Base):
    __tablename__ = "review_queue"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    raw_id = Column(Text, ForeignKey("raw_messages.id"), nullable=False)
    email_id = Column(BigInteger, ForeignKey("emails.id"))
    reason = Column(Text, nullable=False)
    priority = Column(Integer, default=0)
    status = Column(Text, default="pending")
    reviewed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Finding(Base):
    __tablename__ = "findings"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    title = Column(Text, nullable=False)
    summary = Column(Text, nullable=False)
    detail = Column(Text)
    finding_type = Column(Text, nullable=False)
    grounding = Column(Text, nullable=False)
    supporting_email_ids = Column(JSONB, nullable=False)
    inference_score_detail = Column(JSONB)
    contradicts_finding_ids = Column(JSONB, default=[])
    confidence = Column(Float)
    model_used = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class Snapshot(Base):
    __tablename__ = "snapshots"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_type = Column(Text, nullable=False)
    summary = Column(Text, nullable=False)
    findings_ids = Column(ARRAY(BigInteger), default=[])
    stats = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class UserFact(Base):
    __tablename__ = "user_facts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    category = Column(Text, nullable=False)
    subject = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SuggestedQuestion(Base):
    __tablename__ = "suggested_questions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    question_text = Column(Text, nullable=False)
    context = Column(Text)
    source_type = Column(Text, nullable=False)
    source_email_ids = Column(JSONB)
    status = Column(Text, nullable=False, default="pending")
    answer_text = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    answered_at = Column(DateTime(timezone=True))
