#!/usr/bin/env bash
set -euo pipefail

# Restore Infisical secrets management on ai NUC (.69)
#
# Standalone Docker Compose (NOT in Swarm)
# Location: /opt/infisical/docker-compose.yml
# Port: 8093 → 8080 (internal)
# Postgres needs privileged: true
#
# Usage: ./restore-infisical.sh

AI_HOST="root@192.168.1.69"
INFISICAL_DIR="/opt/infisical"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "============================================"
echo " Infisical Recovery — ai NUC (.69)"
echo "============================================"

# Step 1: Check Docker
echo ""
echo "[1/5] Checking Docker ..."
ssh "$AI_HOST" "docker info --format '{{.ServerVersion}}'" || {
  echo -e "${RED}Docker not running!${NC}"
  exit 1
}

# Step 2: Check for existing compose file
echo "[2/5] Checking Infisical deployment ..."
HAS_COMPOSE=$(ssh "$AI_HOST" "test -f $INFISICAL_DIR/docker-compose.yml && echo yes || echo no")

if [ "$HAS_COMPOSE" = "no" ]; then
  echo -e "${YELLOW}No docker-compose.yml found at $INFISICAL_DIR${NC}"
  echo ""
  echo "Creating from swarm stack template ..."

  ssh "$AI_HOST" "mkdir -p $INFISICAL_DIR/postgres"
  ssh "$AI_HOST" bash -s <<'COMPOSEEOF'
cat > /opt/infisical/docker-compose.yml <<'YML'
version: "3.8"

services:
  infisical:
    image: infisical/infisical:latest
    ports:
      - "8093:8080"
    environment:
      - NODE_ENV=production
      - ENCRYPTION_KEY=${INFISICAL_ENCRYPTION_KEY}
      - AUTH_SECRET=${INFISICAL_AUTH_SECRET}
      - DB_CONNECTION_URI=postgresql://infisical:${INFISICAL_POSTGRES_PASSWORD}@postgres:5432/infisical?sslmode=disable
      - REDIS_URL=redis://redis:6379
      - SITE_URL=https://infisical.uptonx.com
    depends_on:
      - postgres
      - redis
    restart: unless-stopped

  postgres:
    image: postgres:16-alpine
    privileged: true
    environment:
      - POSTGRES_USER=infisical
      - POSTGRES_PASSWORD=${INFISICAL_POSTGRES_PASSWORD}
      - POSTGRES_DB=infisical
    volumes:
      - /opt/infisical/postgres:/var/lib/postgresql/data
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    restart: unless-stopped
YML
COMPOSEEOF
  echo "  Created docker-compose.yml"
fi

# Step 3: Check for .env file
echo "[3/5] Checking environment variables ..."
HAS_ENV=$(ssh "$AI_HOST" "test -f $INFISICAL_DIR/.env && echo yes || echo no")

if [ "$HAS_ENV" = "no" ]; then
  echo -e "${YELLOW}WARNING: No .env file found!${NC}"
  echo ""
  echo "Infisical needs these environment variables:"
  echo "  INFISICAL_ENCRYPTION_KEY=<32-char hex key>"
  echo "  INFISICAL_AUTH_SECRET=<random secret>"
  echo "  INFISICAL_POSTGRES_PASSWORD=<db password>"
  echo ""
  echo "Create .env:"
  echo "  ssh $AI_HOST 'cat > $INFISICAL_DIR/.env'"
  echo ""
  echo "Or generate new values:"
  echo "  INFISICAL_ENCRYPTION_KEY=\$(openssl rand -hex 16)"
  echo "  INFISICAL_AUTH_SECRET=\$(openssl rand -base64 32)"
  echo "  INFISICAL_POSTGRES_PASSWORD=\$(openssl rand -base64 16)"
  echo ""
  read -p "Continue without .env? (y/N) " -n 1 -r
  echo
  [[ $REPLY =~ ^[Yy]$ ]] || exit 1
fi

# Step 4: Restart
echo "[4/5] Restarting Infisical ..."
ssh "$AI_HOST" "cd $INFISICAL_DIR && docker compose down --timeout 30" 2>/dev/null || true
ssh "$AI_HOST" "cd $INFISICAL_DIR && docker compose up -d"

echo "  Waiting for startup (15s) ..."
sleep 15

# Step 5: Verify
echo "[5/5] Verification ..."
echo ""

ssh "$AI_HOST" "cd $INFISICAL_DIR && docker compose ps"
echo ""

RESP=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 10 "http://192.168.1.69:8093" 2>/dev/null || echo "000")
if [ "$RESP" = "200" ] || [ "$RESP" = "302" ]; then
  echo -e "  ${GREEN}✓ Infisical responding on :8093 (HTTP $RESP)${NC}"
else
  echo -e "  ${YELLOW}⚠ Infisical returned HTTP $RESP — may still be starting${NC}"
  echo "  Check logs: ssh $AI_HOST 'cd $INFISICAL_DIR && docker compose logs --tail 30'"
fi

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN} Infisical restored${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "  URL:     https://infisical.uptonx.com"
echo "  Direct:  http://192.168.1.69:8093"
echo ""
echo "Key notes:"
echo "  - Postgres runs with privileged: true (required on Proxmox)"
echo "  - NOT in Docker Swarm (overlay network issues)"
echo "  - Swarm stack in repo is reference only"
echo ""
