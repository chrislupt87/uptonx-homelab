#!/usr/bin/env bash
set -euo pipefail

# Verify Coral USB TPU, VAAPI acceleration, and camera streams for Frigate
#
# Frigate runs on aux (.18) with:
#   - Google Coral USB Edge TPU
#   - VAAPI hardware acceleration (Intel iGPU)
#   - 5 cameras on VLAN 40
#
# Usage: ./check-coral.sh

FRIGATE_HOST="root@192.168.1.18"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "============================================"
echo " Frigate Hardware & Camera Check"
echo " Host: aux (192.168.1.18)"
echo "============================================"

# --- Coral USB TPU ---
echo ""
echo "=== CORAL USB TPU ==="

CORAL=$(ssh "$FRIGATE_HOST" "lsusb 2>/dev/null | grep -i -E 'google|coral|global unichip'" || true)
if [ -n "$CORAL" ]; then
  echo -e "  ${GREEN}✓ Coral detected:${NC} $CORAL"
else
  echo -e "  ${RED}✗ Coral USB TPU NOT detected!${NC}"
  echo "    - Check USB connection"
  echo "    - Try different USB port"
  echo "    - Check dmesg: ssh root@192.168.1.18 'dmesg | grep -i apex'"
fi

# Check /dev/bus/usb access
DEV_CHECK=$(ssh "$FRIGATE_HOST" "ls /dev/bus/usb/ 2>/dev/null | wc -l")
echo "  USB buses available: $DEV_CHECK"

# --- VAAPI (Intel iGPU) ---
echo ""
echo "=== VAAPI HARDWARE ACCELERATION ==="

RENDERDEV=$(ssh "$FRIGATE_HOST" "ls -la /dev/dri/renderD128 2>/dev/null" || true)
if [ -n "$RENDERDEV" ]; then
  echo -e "  ${GREEN}✓ /dev/dri/renderD128 present${NC}"
else
  echo -e "  ${RED}✗ /dev/dri/renderD128 NOT found — no VAAPI available${NC}"
fi

VAINFO=$(ssh "$FRIGATE_HOST" "vainfo 2>&1 | head -5" || true)
if echo "$VAINFO" | grep -qi "vainfo"; then
  echo "  $VAINFO"
else
  echo -e "  ${YELLOW}vainfo not available (install intel-media-va-driver)${NC}"
fi

# --- Frigate Container ---
echo ""
echo "=== FRIGATE CONTAINER ==="

FRIGATE_STATUS=$(ssh "$FRIGATE_HOST" "docker ps --filter name=frigate --format '{{.Names}}\t{{.Status}}\t{{.Ports}}'" 2>/dev/null || echo "")
if [ -n "$FRIGATE_STATUS" ]; then
  echo -e "  ${GREEN}✓ Running:${NC} $FRIGATE_STATUS"
else
  echo -e "  ${RED}✗ Frigate container not running!${NC}"
fi

# Check Frigate API
echo ""
echo "  API health check ..."
API_RESP=$(curl -s --connect-timeout 5 "http://192.168.1.18:5000/api/version" 2>/dev/null || echo "FAIL")
if [ "$API_RESP" != "FAIL" ]; then
  echo -e "  ${GREEN}✓ Frigate API responding:${NC} $API_RESP"
else
  echo -e "  ${RED}✗ Frigate API not responding on :5000${NC}"
fi

# --- Camera Streams ---
echo ""
echo "=== CAMERA STREAMS (VLAN 40) ==="
printf "%-20s %-18s %-10s\n" "CAMERA" "IP" "STATUS"
printf "%-20s %-18s %-10s\n" "------" "--" "------"

declare -A CAMERAS=(
  ["Reolink Front"]="192.168.40.11"
  ["Reolink Side"]="192.168.40.12"
  ["Reolink Back"]="192.168.40.13"
  ["Tapo Indoor"]="192.168.40.19"
  ["EZVIZ Doorbell"]="192.168.40.50"
)

for cam in "${!CAMERAS[@]}"; do
  ip="${CAMERAS[$cam]}"
  if ssh "$FRIGATE_HOST" "ping -c 1 -W 2 $ip" &>/dev/null; then
    status="${GREEN}✓ UP${NC}"
  else
    status="${RED}✗ DOWN${NC}"
  fi
  printf "%-20s %-18s %-20b\n" "$cam" "$ip" "$status"
done

# --- MQTT ---
echo ""
echo "=== MQTT (MOSQUITTO) ==="
MQTT_STATUS=$(ssh "$FRIGATE_HOST" "docker ps --filter name=mosquitto --format '{{.Status}}'" 2>/dev/null || echo "")
if [ -n "$MQTT_STATUS" ]; then
  echo -e "  ${GREEN}✓ Mosquitto:${NC} $MQTT_STATUS"
else
  echo -e "  ${RED}✗ Mosquitto not running${NC}"
fi

# --- NFS Archive ---
echo ""
echo "=== NFS ARCHIVE ==="
NFS_CHECK=$(ssh "$FRIGATE_HOST" "mountpoint -q /mnt/nfs/frigate && echo 'mounted' || echo 'not mounted'" 2>/dev/null)
if [ "$NFS_CHECK" = "mounted" ]; then
  NFS_USAGE=$(ssh "$FRIGATE_HOST" "df -h /mnt/nfs/frigate | tail -1 | awk '{print \$3\"/\"\$2\" (\"\$5\" used)\"}'" 2>/dev/null)
  echo -e "  ${GREEN}✓ NFS mounted:${NC} $NFS_USAGE"
else
  echo -e "  ${RED}✗ NFS not mounted at /mnt/nfs/frigate${NC}"
  echo "    Run: docs/scripts/network/remount-nfs.sh frigate"
fi

echo ""
echo "============================================"
echo " Frigate check complete"
echo "============================================"
