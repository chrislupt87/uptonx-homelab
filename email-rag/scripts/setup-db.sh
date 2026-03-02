#!/usr/bin/env bash
# setup-db.sh — Install PostgreSQL 16 + pgvector, create email_rag DB, run schema
# Target: LXC 105 (192.168.1.105) on MSI Proxmox (Debian/Ubuntu)
set -euo pipefail

DB_NAME="${EMAIL_RAG_DB_NAME:-email_rag}"
DB_USER="${EMAIL_RAG_DB_USER:-email_rag}"
DB_PASS="${EMAIL_RAG_DB_PASS:-email_rag}"
SCHEMA_FILE="$(dirname "$0")/../sql/email_rag_schema.sql"

echo "=== Email RAG Database Setup ==="

# --- Install PostgreSQL 16 if not present ---
if ! command -v psql &>/dev/null; then
    echo "[1/4] Installing PostgreSQL 16..."
    apt-get update -qq
    apt-get install -y -qq postgresql-16 postgresql-client-16
else
    echo "[1/4] PostgreSQL already installed: $(psql --version)"
fi

# --- Install pgvector extension ---
if ! dpkg -l | grep -q postgresql-16-pgvector; then
    echo "[2/4] Installing pgvector..."
    apt-get install -y -qq postgresql-16-pgvector
else
    echo "[2/4] pgvector already installed"
fi

# Ensure PostgreSQL is running
systemctl enable --now postgresql

# --- Create role and database ---
echo "[3/4] Creating database '$DB_NAME' and role '$DB_USER'..."
sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DB_USER}') THEN
        CREATE ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASS}';
    END IF;
END
\$\$;

SELECT 'CREATE DATABASE ${DB_NAME} OWNER ${DB_USER}'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${DB_NAME}')\gexec

GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};
SQL

# Grant schema privileges
sudo -u postgres psql -d "${DB_NAME}" -v ON_ERROR_STOP=1 <<SQL
GRANT ALL ON SCHEMA public TO ${DB_USER};
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO ${DB_USER};
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO ${DB_USER};
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO ${DB_USER};
SQL

# --- Run schema ---
echo "[4/4] Applying schema from ${SCHEMA_FILE}..."
if [ ! -f "$SCHEMA_FILE" ]; then
    echo "ERROR: Schema file not found: $SCHEMA_FILE"
    exit 1
fi

sudo -u postgres psql -d "${DB_NAME}" -v ON_ERROR_STOP=1 -f "$SCHEMA_FILE"

echo ""
echo "=== Setup complete ==="
echo "Database: $DB_NAME"
echo "User: $DB_USER"
echo "Tables:"
sudo -u postgres psql -d "${DB_NAME}" -c "\dt"
