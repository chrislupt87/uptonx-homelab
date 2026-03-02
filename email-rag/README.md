# Email RAG — Forensic Email Intelligence Pipeline

Local-first system for ingesting, tagging, and analyzing email from Gmail (IMAP) and iCloud (.eml archive). Stores everything in a 3-layer PostgreSQL schema designed for AI-powered analysis.

## Architecture

**3-Layer Schema:**
1. **Raw** — immutable RFC822 evidence (`raw_messages`)
2. **Structured** — parsed emails, entities, claims, timeline, snippets
3. **Analysis** — snapshots and findings with mandatory citations

**Target Environment:** LXC 105 (192.168.1.105) — PostgreSQL 16 + pgvector

## Quick Start

```bash
# 1. Copy and fill in secrets
cp secrets/email-rag.env.template secrets/email-rag.env
# Edit secrets/email-rag.env with your credentials

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set up database (run on LXC 105 as root)
bash scripts/setup-db.sh

# 4. Import .eml archive
python -m email_rag.cli import-eml /mnt/nfs/volumes/email-rag/archive

# 5. Sync Gmail
python -m email_rag.cli ingest-gmail

# 6. Reconstruct threads
python -m email_rag.cli rebuild-threads

# 7. Load known facts
python -m email_rag.cli load-facts

# 8. Check stats
python -m email_rag.cli stats
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `setup-db` | Install PG + pgvector, create DB, run schema |
| `ingest-gmail` | Gmail IMAP sync (`--days 180`) |
| `import-eml [PATH]` | Bulk .eml file import |
| `load-facts [PATH]` | Seed claims_log from known_facts.json |
| `rebuild-threads` | Thread chain reconstruction |
| `stats` | Counts by store/corpus/priority |

## Corpus Tagging

- **sent** — from your email addresses
- **subject** — involves the primary subject email
- **other** — everything else

Emails can be both `corpus='sent'` and `subject_priority=true` (e.g., you emailing the subject).
