#!/usr/bin/env bash
set -euo pipefail

# Emergency restart of Frigate NVR and all sidecars
#
# Frigate on aux (.18):
#   - Frigate 0.17.0 (host networking, Coral TPU, VAAPI)
#   - Mosquitto MQTT sidecar
#   - Docker Compose at /opt/frigate/
#
# IMPORTANT: Frigate uses docker compose, NOT docker stack deploy
#
# Usage: ./emergency-restart.sh

FRIGATE_HOST="root@192.168.1.18"
FRIGATE_DIR="/opt/frigate"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "============================================"
echo " Frigate Emergency Restart"
echo " Host: aux (192.168.1.18)"
echo "============================================"

# Step 1: Stop all Frigate containers
echo ""
echo "[1/5] Stopping Frigate stack ..."
ssh "$FRIGATE_HOST" "cd $FRIGATE_DIR && docker compose down --timeout 30" 2>/dev/null || {
  echo -e "  ${YELLOW}Compose down failed, force-stopping containers ...${NC}"
  ssh "$FRIGATE_HOST" "docker ps -q --filter name=frigate | xargs -r docker stop -t 10" || true
  ssh "$FRIGATE_HOST" "docker ps -q --filter name=mosquitto | xargs -r docker stop -t 10" || true
}

# Step 2: Clean up any orphaned containers
echo "[2/5] Cleaning up ..."
ssh "$FRIGATE_HOST" "docker ps -aq --filter name=frigate | xargs -r docker rm -f" 2>/dev/null || true
ssh "$FRIGATE_HOST" "docker ps -aq --filter name=mosquitto | xargs -r docker rm -f" 2>/dev/null || true

# Step 3: Verify Coral TPU is accessible
echo "[3/5] Checking Coral TPU ..."
CORAL=$(ssh "$FRIGATE_HOST" "lsusb | grep -i -E 'google|coral|global unichip'" 2>/dev/null || true)
if [ -n "$CORAL" ]; then
  echo -e "  ${GREEN}✓ Coral detected${NC}"
else
  echo -e "  ${YELLOW}⚠ Coral NOT detected — Frigate will fall back to CPU detection${NC}"
fi

# Step 4: Check NFS archive mount
echo "[4/5] Checking NFS archive mount ..."
NFS_OK=$(ssh "$FRIGATE_HOST" "mountpoint -q /mnt/nfs/frigate && timeout 5 ls /mnt/nfs/frigate &>/dev/null && echo ok || echo fail")
if [ "$NFS_OK" = "ok" ]; then
  echo -e "  ${GREEN}✓ NFS archive mounted${NC}"
else
  echo -e "  ${YELLOW}⚠ NFS not mounted, attempting remount ...${NC}"
  ssh "$FRIGATE_HOST" "umount -l /mnt/nfs/frigate 2>/dev/null; mount -t nfs -o vers=3,soft,timeo=30 192.168.1.11:/volume1/UptonX/frigate /mnt/nfs/frigate" || {
    echo -e "  ${RED}NFS remount failed — Frigate will start without NAS archive${NC}"
  }
fi

# Step 5: Start Frigate stack
echo "[5/5] Starting Frigate stack ..."
ssh "$FRIGATE_HOST" "cd $FRIGATE_DIR && docker compose up -d"

# Wait for Frigate to initialize
echo ""
echo "Waiting for Frigate to start (30s) ..."
sleep 30

# Verify
echo ""
echo "=== Verification ==="
echo ""

# Container status
ssh "$FRIGATE_HOST" "docker ps --filter name=frigate --filter name=mosquitto --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"

echo ""

# API check
API_RESP=$(curl -s --connect-timeout 10 "http://192.168.1.18:5000/api/version" 2>/dev/null || echo "FAIL")
if [ "$API_RESP" != "FAIL" ]; then
  echo -e "${GREEN}✓ Frigate API responding:${NC} $API_RESP"
else
  echo -e "${RED}✗ Frigate API not responding — check logs:${NC}"
  echo "  ssh root@192.168.1.18 'cd $FRIGATE_DIR && docker compose logs --tail 50 frigate'"
fi

echo ""
echo "============================================"
echo " Frigate restart complete"
echo "============================================"
echo ""
echo "  Web UI:  http://192.168.1.18:5000"
echo "  Traefik: https://frigate.uptonx.com"
echo "  Logs:    ssh root@192.168.1.18 'cd $FRIGATE_DIR && docker compose logs -f frigate'"
echo ""
