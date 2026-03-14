#!/usr/bin/env bash
set -euo pipefail

# Restore Technitium DNS and flush all caches
#
# Technitium: CT 101 on aux2 (.80), IP: 192.168.1.51
# Web UI: http://192.168.1.51:5380
# Zones: uptonx.local, uptonx.com (wildcard → .15 Traefik)
#
# Usage: ./fix-dns.sh

DNS_IP="192.168.1.51"
PVE_AUX2="root@192.168.1.80"
CT_ID=101

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "============================================"
echo " DNS Recovery — Technitium at $DNS_IP"
echo "============================================"

# Step 1: Check if CT 101 is running
echo ""
echo "[1/5] Checking CT $CT_ID status ..."
CT_STATUS=$(ssh "$PVE_AUX2" "pct status $CT_ID" 2>/dev/null || echo "error")

if echo "$CT_STATUS" | grep -q "running"; then
  echo -e "  ${GREEN}CT $CT_ID is running${NC}"
elif echo "$CT_STATUS" | grep -q "stopped"; then
  echo -e "  ${YELLOW}CT $CT_ID is stopped, starting ...${NC}"
  ssh "$PVE_AUX2" "pct start $CT_ID"
  sleep 5
else
  echo -e "  ${RED}Cannot reach aux2 or CT $CT_ID not found${NC}"
  exit 1
fi

# Step 2: Verify Docker is running inside CT
echo "[2/5] Checking Docker in CT $CT_ID ..."
ssh "$PVE_AUX2" "pct exec $CT_ID -- systemctl is-active docker" || {
  echo "  Starting Docker ..."
  ssh "$PVE_AUX2" "pct exec $CT_ID -- systemctl start docker"
  sleep 3
}

# Step 3: Check Technitium container
echo "[3/5] Checking Technitium container ..."
CONTAINER_STATUS=$(ssh "$PVE_AUX2" "pct exec $CT_ID -- docker ps --filter name=technitium --format '{{.Status}}'" 2>/dev/null || echo "")

if [ -z "$CONTAINER_STATUS" ]; then
  echo "  Technitium container not running, starting ..."
  ssh "$PVE_AUX2" "pct exec $CT_ID -- bash -c 'cd /opt/technitium && docker compose up -d'" || {
    echo -e "  ${RED}Failed to start Technitium${NC}"
    exit 1
  }
  sleep 5
else
  echo "  Container status: $CONTAINER_STATUS"
fi

# Step 4: Flush local DNS cache
echo "[4/5] Flushing DNS caches ..."

# Flush on this machine
if command -v resolvectl &>/dev/null; then
  resolvectl flush-caches 2>/dev/null && echo "  Flushed systemd-resolved cache" || true
fi

# Flush on all Proxmox hosts
for host in 192.168.1.18 192.168.1.77 192.168.1.80 192.168.1.69 192.168.1.74; do
  ssh "root@$host" "resolvectl flush-caches 2>/dev/null || systemd-resolve --flush-caches 2>/dev/null || true" 2>/dev/null && \
    echo "  Flushed cache on $host" || true
done

# Step 5: Verify DNS resolution
echo "[5/5] Testing DNS resolution ..."

TESTS=("uptonx.com" "frigate.uptonx.com" "grafana.uptonx.com" "portainer.uptonx.com")
ALL_OK=true

for domain in "${TESTS[@]}"; do
  result=$(dig +short "$domain" @"$DNS_IP" 2>/dev/null || echo "FAIL")
  if [ "$result" = "192.168.1.15" ] || [ -n "$result" ] && [ "$result" != "FAIL" ]; then
    echo -e "  ${GREEN}✓${NC} $domain → $result"
  else
    echo -e "  ${RED}✗${NC} $domain → FAILED"
    ALL_OK=false
  fi
done

echo ""
if $ALL_OK; then
  echo -e "${GREEN}DNS is healthy!${NC}"
else
  echo -e "${YELLOW}Some lookups failed. Check Technitium UI:${NC}"
  echo "  http://192.168.1.51:5380"
fi

echo ""
echo "============================================"
echo " DNS recovery complete"
echo "============================================"
