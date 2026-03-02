#!/bin/bash
set -euo pipefail

# Load environment
ENV_FILE="${ENV_FILE:-/opt/email-rag/secrets/email-rag.env}"
if [ -f "$ENV_FILE" ]; then
    set -a; source "$ENV_FILE"; set +a
fi

echo "Applying schema to email_rag database..."
sudo -u postgres psql -d email_rag -f /opt/email-rag/sql/email_rag_schema.sql

echo "Granting permissions..."
sudo -u postgres psql -d email_rag -c "
    GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO email_rag_user;
    GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO email_rag_user;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO email_rag_user;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO email_rag_user;
"

echo "Database setup complete."
