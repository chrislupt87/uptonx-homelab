#!/usr/bin/env bash
set -euo pipefail

# Restore the Forensic Audio Pipeline on MSI (.74)
#
# Stack: 2 containers (API + frontend)
# Location: /opt/stacks/audio-pipeline/ on MSI
# Special: apparmor:unconfined + seccomp:unconfined (NOT privileged)
# Frontend: must be built on workstation (Proxmox blocks child_process.spawn)
#
# Usage: ./restore-audio-pipeline.sh

MSI_HOST="root@192.168.1.74"
STACK_DIR="/opt/stacks/audio-pipeline"
REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "============================================"
echo " Audio Pipeline Recovery — MSI (.74)"
echo "============================================"

# Step 1: Check Docker on MSI
echo ""
echo "[1/5] Checking Docker on MSI ..."
DOCKER_VER=$(ssh "$MSI_HOST" "docker info --format '{{.ServerVersion}}'" 2>/dev/null || echo "FAIL")
if [ "$DOCKER_VER" = "FAIL" ]; then
  echo -e "${RED}Docker not running on .74!${NC}"
  echo "  Fix: ssh $MSI_HOST 'systemctl start docker'"
  exit 1
fi
echo -e "  ${GREEN}Docker $DOCKER_VER${NC}"

# Step 2: Sync compose file
echo "[2/5] Syncing docker-compose.yml ..."
ssh "$MSI_HOST" "mkdir -p $STACK_DIR"
scp "$REPO_DIR/vm/audio-pipeline/docker-compose.yml" "$MSI_HOST:$STACK_DIR/docker-compose.yml"

# Step 3: Check if images exist
echo "[3/5] Checking Docker images ..."
API_IMG=$(ssh "$MSI_HOST" "docker images audio-pipeline-api:latest --format '{{.ID}}'" 2>/dev/null || echo "")
FE_IMG=$(ssh "$MSI_HOST" "docker images audio-pipeline-frontend:latest --format '{{.ID}}'" 2>/dev/null || echo "")

if [ -z "$API_IMG" ] || [ -z "$FE_IMG" ]; then
  echo -e "${YELLOW}WARNING: Images not found on MSI.${NC}"
  echo ""
  echo "Images must be built and deployed using the deploy script:"
  echo "  cd $REPO_DIR/vm/audio-pipeline"
  echo "  ./deploy.sh all"
  echo ""
  echo "NOTE: Frontend MUST be built on the workstation (.95), not on MSI."
  echo "The deploy.sh script handles this automatically."
  echo ""
  read -p "Continue with existing images anyway? (y/N) " -n 1 -r
  echo
  [[ $REPLY =~ ^[Yy]$ ]] || exit 1
fi

# Step 4: Stop and restart
echo "[4/5] Restarting Audio Pipeline ..."
ssh "$MSI_HOST" "cd $STACK_DIR && docker compose down --timeout 30" 2>/dev/null || true
ssh "$MSI_HOST" "cd $STACK_DIR && docker compose up -d"

echo "  Waiting for startup (10s) ..."
sleep 10

# Step 5: Verify
echo "[5/5] Verification ..."
echo ""

ssh "$MSI_HOST" "cd $STACK_DIR && docker compose ps"
echo ""

# API check
API_RESP=$(curl -s --connect-timeout 5 "http://192.168.1.74:8000/health" 2>/dev/null || \
           curl -s --connect-timeout 5 "http://192.168.1.74:8000/docs" 2>/dev/null || echo "FAIL")
if [ "$API_RESP" != "FAIL" ]; then
  echo -e "  ${GREEN}✓ API responding on :8000${NC}"
else
  echo -e "  ${YELLOW}⚠ API not responding — check logs:${NC}"
  echo "    ssh $MSI_HOST 'cd $STACK_DIR && docker compose logs --tail 30 audio_api'"
fi

# Frontend check
FE_RESP=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 "http://192.168.1.74:8090" 2>/dev/null || echo "000")
if [ "$FE_RESP" = "200" ]; then
  echo -e "  ${GREEN}✓ Frontend responding on :8090${NC}"
else
  echo -e "  ${YELLOW}⚠ Frontend returned $FE_RESP${NC}"
fi

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN} Audio Pipeline restored${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "  Web UI:  http://192.168.1.74:8090"
echo "  API:     http://192.168.1.74:8000"
echo "  Traefik: https://audio.uptonx.com"
echo ""
echo "Key settings:"
echo "  - security_opt: apparmor:unconfined, seccomp:unconfined"
echo "  - API memory limit: 24GB, CPU limit: 10 cores"
echo "  - Whisper model: large-v3 (CPU int8)"
echo "  - MultipartParser: unlimited file size"
echo ""
