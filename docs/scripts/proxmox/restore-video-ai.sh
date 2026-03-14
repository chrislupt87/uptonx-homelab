#!/usr/bin/env bash
set -euo pipefail

# Restore the Video AI stack on ai NUC (.69)
#
# 8 containers: CompreFace, Double-Take, Qdrant, n8n,
#               CLIP indexer, LLaVA bridge, face trainer, postgres
#
# All containers need privileged: true on Proxmox
# Docker iptables must be enabled (daemon.json = {})
#
# Usage: ./restore-video-ai.sh

AI_HOST="root@192.168.1.69"
STACK_DIR="/opt/video-ai"
REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "============================================"
echo " Video AI Stack Recovery — ai NUC (.69)"
echo "============================================"

# Step 1: Verify Docker is healthy
echo ""
echo "[1/6] Checking Docker on ai NUC ..."
DOCKER_VER=$(ssh "$AI_HOST" "docker info --format '{{.ServerVersion}}'" 2>/dev/null || echo "FAIL")
if [ "$DOCKER_VER" = "FAIL" ]; then
  echo -e "${RED}Docker not running on .69!${NC}"
  echo "  Fix: ssh $AI_HOST 'systemctl start docker'"
  exit 1
fi
echo -e "  ${GREEN}Docker $DOCKER_VER${NC}"

# Check daemon.json is correct (iptables must be enabled)
DAEMON_JSON=$(ssh "$AI_HOST" "cat /etc/docker/daemon.json 2>/dev/null" || echo "{}")
if echo "$DAEMON_JSON" | grep -q '"iptables": false'; then
  echo -e "${RED}WARNING: Docker iptables is DISABLED!${NC}"
  echo "  Fixing daemon.json ..."
  ssh "$AI_HOST" "echo '{}' > /etc/docker/daemon.json && systemctl restart docker"
  sleep 5
fi

# Step 2: Sync compose file from repo
echo "[2/6] Syncing docker-compose.yml from repo ..."
ssh "$AI_HOST" "mkdir -p $STACK_DIR"
scp "$REPO_DIR/proxmox/video-ai/docker-compose.yml" "$AI_HOST:$STACK_DIR/docker-compose.yml"

# Sync config files
for f in double-take-config.yml clip_service.py llava_bridge.py face_trainer.py; do
  if [ -f "$REPO_DIR/proxmox/video-ai/$f" ]; then
    case "$f" in
      double-take-config.yml)
        ssh "$AI_HOST" "mkdir -p $STACK_DIR/double-take"
        scp "$REPO_DIR/proxmox/video-ai/$f" "$AI_HOST:$STACK_DIR/double-take/config.yml"
        ;;
      clip_service.py)
        ssh "$AI_HOST" "mkdir -p $STACK_DIR/clip"
        scp "$REPO_DIR/proxmox/video-ai/$f" "$AI_HOST:$STACK_DIR/clip/"
        ;;
      llava_bridge.py)
        ssh "$AI_HOST" "mkdir -p $STACK_DIR/llava"
        scp "$REPO_DIR/proxmox/video-ai/$f" "$AI_HOST:$STACK_DIR/llava/"
        ;;
      face_trainer.py)
        ssh "$AI_HOST" "mkdir -p $STACK_DIR/face-trainer"
        scp "$REPO_DIR/proxmox/video-ai/$f" "$AI_HOST:$STACK_DIR/face-trainer/"
        ;;
    esac
  fi
done

# Step 3: Create data directories
echo "[3/6] Ensuring data directories ..."
ssh "$AI_HOST" bash -s <<'DIREOF'
mkdir -p /opt/video-ai/{compreface/db,double-take,qdrant,n8n,clip,llava/data,face-trainer/data}
DIREOF

# Step 4: Stop existing containers
echo "[4/6] Stopping existing containers ..."
ssh "$AI_HOST" "cd $STACK_DIR && docker compose down --timeout 30" 2>/dev/null || true

# Step 5: Start stack
echo "[5/6] Starting Video AI stack ..."
ssh "$AI_HOST" "cd $STACK_DIR && docker compose up -d"

echo "  Waiting for containers to start (15s) ..."
sleep 15

# Step 6: Verify
echo "[6/6] Verification ..."
echo ""

ssh "$AI_HOST" "docker ps --filter 'label=com.docker.compose.project=video-ai' --format 'table {{.Names}}\t{{.Status}}'" 2>/dev/null || \
  ssh "$AI_HOST" "cd $STACK_DIR && docker compose ps"

echo ""

# Check key services
for svc_info in "CompreFace:8000" "Double-Take:3000" "Qdrant:6333" "n8n:5678"; do
  svc=$(echo "$svc_info" | cut -d: -f1)
  port=$(echo "$svc_info" | cut -d: -f2)
  if ssh "$AI_HOST" "curl -s --connect-timeout 3 http://localhost:$port" &>/dev/null; then
    echo -e "  ${GREEN}✓${NC} $svc (:$port)"
  else
    echo -e "  ${YELLOW}⚠${NC} $svc (:$port) — may still be starting"
  fi
done

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN} Video AI stack restored${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "  CompreFace: http://192.168.1.69:8000 (faces.uptonx.com)"
echo "  Double-Take: http://192.168.1.69:3000 (dt.uptonx.com)"
echo "  n8n: http://192.168.1.69:5678 (n8n.uptonx.com)"
echo "  Qdrant: http://192.168.1.69:6333"
echo ""
echo "If .env is missing (face_trainer needs COMPREFACE_API_KEY, TELEGRAM_BOT_TOKEN):"
echo "  ssh $AI_HOST 'cat > $STACK_DIR/.env'"
echo ""
