"""Centralized configuration loaded from email-rag.env via python-dotenv."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from secrets directory
_secrets_dir = Path(__file__).resolve().parent.parent.parent / "secrets"
_env_file = _secrets_dir / "email-rag.env"
load_dotenv(_env_file)


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise RuntimeError(f"Missing required env var: {key} (set in {_env_file})")
    return val


# PostgreSQL
DB_HOST = os.getenv("EMAIL_RAG_DB_HOST", "192.168.1.105")
DB_PORT = os.getenv("EMAIL_RAG_DB_PORT", "5432")
DB_NAME = os.getenv("EMAIL_RAG_DB_NAME", "email_rag")
DB_USER = os.getenv("EMAIL_RAG_DB_USER", "email_rag")
DB_PASS = os.getenv("EMAIL_RAG_DB_PASS", "email_rag")

DATABASE_URL = (
    f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

# Email addresses
MY_GMAIL = os.getenv("GMAIL_ADDRESS", "claurenceu@gmail.com")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
MY_ICLOUD = os.getenv("ICLOUD_ADDRESS", "chrislupt87@icloud.com")
PRIMARY_SUBJECT_EMAIL = os.getenv("PRIMARY_SUBJECT_EMAIL", "b.yourself1@hotmail.com")

MY_ADDRESSES = {MY_GMAIL.lower(), MY_ICLOUD.lower()}

# Paths
EML_ARCHIVE_PATH = os.getenv("EML_ARCHIVE_PATH", "/mnt/nfs/volumes/email-rag/archive")

# Ollama (Phase 2+)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://192.168.1.105:11434")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "snowflake-arctic-embed2")

# Gmail IMAP settings
GMAIL_IMAP_HOST = "imap.gmail.com"
GMAIL_IMAP_PORT = 993
GMAIL_SYNC_DAYS = int(os.getenv("GMAIL_SYNC_DAYS", "180"))
GMAIL_BATCH_SIZE = 50
GMAIL_MAX_RETRIES = 3
