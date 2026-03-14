#!/usr/bin/env bash
set -euo pipefail

# Restore a VM or CT from Proxmox Backup Server (PBS at .19)
#
# PBS: 192.168.1.19 (port 8007)
# Datastore: backups on all Proxmox hosts
#
# Backup schedule:
#   02:00 — PBS snapshots: all Proxmox hosts → .19
#   03:00 — Docker volume dumps → NAS
#   05:00 — NAS → Google Drive (Sundays)
#
# Usage:
#   ./restore-from-pbs.sh <host-ip> <vmid|ctid> [snapshot]
#
# Examples:
#   ./restore-from-pbs.sh 192.168.1.69 401         # Restore email-rag VM (latest)
#   ./restore-from-pbs.sh 192.168.1.18 106         # Restore swarm manager CT (latest)
#   ./restore-from-pbs.sh 192.168.1.69 401 2026-03-10  # Specific date

HOST_IP="${1:?Usage: $0 <host-ip> <vmid|ctid> [snapshot-date]}"
VMID="${2:?Usage: $0 <host-ip> <vmid|ctid> [snapshot-date]}"
SNAP_DATE="${3:-}"

PBS_IP="192.168.1.19"
PVE_HOST="root@$HOST_IP"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Map IPs to host names
case "$HOST_IP" in
  192.168.1.18) HOST_NAME="aux" ;;
  192.168.1.77) HOST_NAME="helm" ;;
  192.168.1.80) HOST_NAME="aux2" ;;
  192.168.1.69) HOST_NAME="ai" ;;
  192.168.1.74) HOST_NAME="msi" ;;
  *) HOST_NAME="unknown" ;;
esac

echo "============================================"
echo " PBS Restore: VMID $VMID on $HOST_NAME ($HOST_IP)"
echo "============================================"

# Step 1: Verify PBS is reachable
echo ""
echo "[1/6] Checking PBS ($PBS_IP) ..."
if ! ping -c 2 -W 3 "$PBS_IP" &>/dev/null; then
  echo -e "${RED}ERROR: PBS at $PBS_IP is unreachable!${NC}"
  echo "  Check PBS server power and network"
  exit 1
fi
echo -e "  ${GREEN}PBS is reachable${NC}"

# Step 2: Check Proxmox host is reachable
echo "[2/6] Checking Proxmox host ($HOST_IP) ..."
if ! ping -c 2 -W 3 "$HOST_IP" &>/dev/null; then
  echo -e "${RED}ERROR: Proxmox host at $HOST_IP is unreachable!${NC}"
  exit 1
fi
echo -e "  ${GREEN}Host is reachable${NC}"

# Step 3: List available backups
echo "[3/6] Listing available backups for VMID $VMID ..."
echo ""

BACKUPS=$(ssh "$PVE_HOST" "pvesh get /nodes/\$(hostname)/storage/pbs/content --vmid $VMID --output-format json-pretty 2>/dev/null" || echo "[]")

if [ "$BACKUPS" = "[]" ] || [ -z "$BACKUPS" ]; then
  echo -e "${RED}No backups found for VMID $VMID on this host!${NC}"
  echo ""
  echo "Check PBS directly:"
  echo "  https://$PBS_IP:8007"
  echo ""
  echo "Or list all backups:"
  echo "  ssh $PVE_HOST 'pvesh get /nodes/\$(hostname)/storage/pbs/content'"
  exit 1
fi

echo "$BACKUPS" | python3 -c "
import json, sys
data = json.load(sys.stdin)
print(f'  Found {len(data)} backup(s):')
for b in sorted(data, key=lambda x: x.get('ctime', 0)):
    volid = b.get('volid', 'unknown')
    size = b.get('size', 0) / (1024*1024*1024)
    fmt = b.get('format', '?')
    print(f'    {volid}  ({size:.1f} GB, {fmt})')
" 2>/dev/null || echo "  (Could not parse backup list — check manually)"

# Step 4: Determine which backup to restore
echo ""
if [ -n "$SNAP_DATE" ]; then
  echo "[4/6] Looking for backup from $SNAP_DATE ..."
  VOLID=$(echo "$BACKUPS" | python3 -c "
import json, sys
data = json.load(sys.stdin)
date='$SNAP_DATE'
for b in data:
    if date in b.get('volid', ''):
        print(b['volid'])
        break
" 2>/dev/null)
  if [ -z "$VOLID" ]; then
    echo -e "${RED}No backup found for date $SNAP_DATE${NC}"
    exit 1
  fi
else
  echo "[4/6] Using latest backup ..."
  VOLID=$(echo "$BACKUPS" | python3 -c "
import json, sys
data = json.load(sys.stdin)
latest = sorted(data, key=lambda x: x.get('ctime', 0))[-1]
print(latest['volid'])
" 2>/dev/null)
fi

echo "  Selected: $VOLID"

# Step 5: Check if VM/CT exists and is running
echo ""
echo "[5/6] Checking current state of VMID $VMID ..."

IS_VM=false
IS_CT=false
IS_RUNNING=false

if ssh "$PVE_HOST" "qm status $VMID" &>/dev/null; then
  IS_VM=true
  STATUS=$(ssh "$PVE_HOST" "qm status $VMID" | awk '{print $2}')
  [ "$STATUS" = "running" ] && IS_RUNNING=true
  echo "  Type: VM, Status: $STATUS"
elif ssh "$PVE_HOST" "pct status $VMID" &>/dev/null; then
  IS_CT=true
  STATUS=$(ssh "$PVE_HOST" "pct status $VMID" | awk '{print $2}')
  [ "$STATUS" = "running" ] && IS_RUNNING=true
  echo "  Type: CT, Status: $STATUS"
else
  echo "  VMID $VMID does not exist (will be created by restore)"
fi

if $IS_RUNNING; then
  echo ""
  echo -e "${YELLOW}WARNING: VMID $VMID is currently running!${NC}"
  echo "It must be stopped before restore."
  read -p "Stop it now? (y/N) " -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    if $IS_VM; then
      ssh "$PVE_HOST" "qm stop $VMID"
    else
      ssh "$PVE_HOST" "pct stop $VMID"
    fi
    sleep 5
  else
    echo "Aborted."
    exit 1
  fi
fi

# Step 6: Restore
echo ""
echo "[6/6] Restoring $VOLID ..."
echo -e "${YELLOW}This will overwrite VMID $VMID!${NC}"
read -p "Continue? (y/N) " -n 1 -r
echo

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
  echo "Aborted."
  exit 1
fi

if $IS_VM || echo "$VOLID" | grep -q "qemu"; then
  ssh "$PVE_HOST" "qmrestore '$VOLID' $VMID --force"
  echo "  Starting VM ..."
  ssh "$PVE_HOST" "qm start $VMID"
else
  ssh "$PVE_HOST" "pct restore $VMID '$VOLID' --force"
  echo "  Starting CT ..."
  ssh "$PVE_HOST" "pct start $VMID"
fi

sleep 5

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN} Restore complete!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "Next steps:"
echo "  1. Verify the VM/CT is running and accessible"
echo "  2. Check services inside are healthy"
echo "  3. Remount NFS if needed: ./docs/scripts/network/remount-nfs.sh"
echo ""
