#!/usr/bin/env bash
# Edit placeholder values before running. Run on Aux 2.
# Creates Docker secrets used by various stacks.
set -euo pipefail

# ┌─────────────────────────────────────────────────────┐
# │  EDIT THESE VALUES BEFORE RUNNING                   │
# │  Replace each CHANGEME with a real secret value.    │
# └─────────────────────────────────────────────────────┘

# Traefik dashboard basic-auth password (htpasswd format: user:hash)
# Generate with: echo $(htpasswd -nB admin)
TRAEFIK_DASHBOARD_AUTH="admin:CHANGEME_GENERATE_WITH_HTPASSWD"

# Vaultwarden admin panel token
# Generate with: openssl rand -base64 48
VAULTWARDEN_ADMIN_TOKEN="CHANGEME_GENERATE_WITH_OPENSSL"

# Generic database password placeholder (for future services that need a DB)
# Generate with: openssl rand -base64 32
DB_PASSWORD="CHANGEME_GENERATE_WITH_OPENSSL"

# ─── Create secrets ──────────────────────────────────

echo "==> Creating Docker secrets..."

echo -n "${TRAEFIK_DASHBOARD_AUTH}" | docker secret create traefik_dashboard_auth - 2>/dev/null \
  && echo "    Created: traefik_dashboard_auth" \
  || echo "    Secret traefik_dashboard_auth already exists, skipping."

echo -n "${VAULTWARDEN_ADMIN_TOKEN}" | docker secret create vaultwarden_admin_token - 2>/dev/null \
  && echo "    Created: vaultwarden_admin_token" \
  || echo "    Secret vaultwarden_admin_token already exists, skipping."

echo -n "${DB_PASSWORD}" | docker secret create db_password - 2>/dev/null \
  && echo "    Created: db_password" \
  || echo "    Secret db_password already exists, skipping."

echo ""
echo "==> Secrets created. Verify with: docker secret ls"
